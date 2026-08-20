from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.models import Action, ActionType, Interpretation, Item, ItemKind
from app.repository import Repository


SYSTEM_PROMPT = """Sei un compagno di viaggio competente, pragmatico e non giudicante.
Interpreta il messaggio usando lo stato fornito. Produci testo conversazionale e azioni separate.
Non inventare decisioni: dubbio o pessimismo non equivalgono ad abbandono. Chiedi chiarimenti solo
se evitano una modifica sbagliata. Usa ID esistenti. Le date sono ISO 8601. Rispondi in italiano.
Per modifiche importanti e ambigue usa request_clarification. La categoria è un'etichetta libera
definita dall'utente: riusala quando il contesto la rende chiara, senza inventare tassonomie.
Non trasformarti in un task manager."""


INTERPRETATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "needs_confirmation": {"type": "boolean"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": [value.value for value in ActionType]},
                    "item_id": {"type": ["string", "null"]},
                    "data": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "category": {"type": "string"},
                            "kind": {"type": "string", "enum": [value.value for value in ItemKind]},
                            "status": {"type": "string", "enum": ["active", "completed", "suspended", "abandoned", "waiting", "unplanned"]},
                            "due_at": {"type": "string"},
                            "recurrence": {"type": "object"},
                            "target_quantity": {"type": "number"},
                            "target_unit": {"type": "string"},
                            "estimate_minutes": {"type": "integer"},
                            "progress_value": {"type": "number"},
                            "progress_total": {"type": "number"},
                            "importance": {"type": "string"},
                            "consequences": {"type": "string"},
                            "flexibility": {"type": "string"},
                            "motivation": {"type": "string"},
                            "context": {"type": "string"},
                            "user_assessment": {"type": "string"},
                            "suspended_until": {"type": "string"},
                            "checkin_cooldown_days": {"type": "integer"},
                            "value": {"type": "number"},
                            "total": {"type": "number"},
                            "unit": {"type": "string"},
                            "note": {"type": "string"},
                            "assessment": {"type": "string"},
                            "target_item_id": {"type": "string"},
                            "relation": {"type": "string"},
                            "relation_type": {"type": "string"}
                        }
                    },
                    "confidence": {"type": "number"},
                    "rationale": {"type": ["string", "null"]},
                },
                "required": ["type", "item_id", "data", "confidence", "rationale"],
            },
        },
    },
    "required": ["reply", "actions", "needs_confirmation"],
}


class Interpreter(ABC):
    @abstractmethod
    async def interpret(self, message: str, items: list[Item], recent_messages: list[dict[str, Any]]) -> Interpretation: ...


class OpenAIInterpreter(Interpreter):
    def __init__(self, api_key: str, model: str, input_price: float, cached_input_price: float, output_price: float):
        self.api_key = api_key
        self.model = model
        self.input_price = input_price
        self.cached_input_price = cached_input_price
        self.output_price = output_price

    async def interpret(self, message: str, items: list[Item], recent_messages: list[dict[str, Any]]) -> Interpretation:
        state = [item.model_dump(mode="json", exclude_none=True) for item in items]
        context = [{"role": msg["role"], "content": msg["content"]} for msg in recent_messages[-12:]]
        payload = {
            "model": self.model,
            "store": False,
            "instructions": SYSTEM_PROMPT,
            "input": context + [{"role": "user", "content": f"STATO:\n{json.dumps(state, ensure_ascii=False)}\n\nMESSAGGIO:\n{message}"}],
            "text": {"format": {"type": "json_schema", "name": "travel_companion_interpretation", "strict": False, "schema": INTERPRETATION_SCHEMA}},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, json=payload)
            response.raise_for_status()
            body = response.json()
        output_text = body.get("output_text")
        if not output_text:
            for output in body.get("output", []):
                for content in output.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
        if not output_text:
            raise RuntimeError("Il provider AI non ha restituito testo strutturato")
        interpretation = Interpretation.model_validate_json(output_text)
        usage = body.get("usage") or {}
        details = usage.get("input_tokens_details") or {}
        cached_tokens = int(details.get("cached_tokens") or 0)
        input_tokens = int(usage.get("input_tokens") or 0)
        uncached_tokens = max(0, input_tokens - cached_tokens)
        output_tokens = int(usage.get("output_tokens") or 0)
        estimated_cost = (
            uncached_tokens * self.input_price
            + cached_tokens * self.cached_input_price
            + output_tokens * self.output_price
        ) / 1_000_000
        interpretation.provider_usage = {
            "response_id": body.get("id"),
            "provider": "openai",
            "model": body.get("model") or self.model,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
            "estimated_cost_usd": estimated_cost,
            "response_status": body.get("status"),
        }
        return interpretation


class LocalInterpreter(Interpreter):
    """Useful offline baseline covering the acceptance scenarios; not a general NLU system."""

    async def interpret(self, message: str, items: list[Item], recent_messages: list[dict[str, Any]]) -> Interpretation:
        text = message.strip()
        lower = self._normalize_numbers(text.lower())
        item = self._resolve_item(lower, items)

        if self._looks_like_summary(lower):
            return Interpretation(reply=self._summary(items), actions=[Action(type=ActionType.NO_ACTION)])

        if item and re.search(r"\b(ho finito|completat[oa]|è finit[oa])\b", lower):
            return Interpretation(reply=f"Bene, segno “{item.title}” come completato.", actions=[Action(type=ActionType.COMPLETE_ITEM, item_id=item.id)])

        if item and re.search(r"\b(sospend|metti in pausa|lasciamo perdere)\b", lower):
            until = self._parse_suspend_until(lower)
            suffix = f" fino al {until[:10]}" if until else ""
            return Interpretation(reply=f"Ok, metto in pausa “{item.title}”{suffix}.", actions=[Action(type=ActionType.SUSPEND_ITEM, item_id=item.id, data={"suspended_until": until} if until else {})])

        if item and re.search(r"\b(non voglio più|abbandon|rinuncio)\b", lower):
            return Interpretation(reply=f"Va bene, considero abbandonato “{item.title}”.", actions=[Action(type=ActionType.ABANDON_ITEM, item_id=item.id)])

        if item and re.search(r"\b(non ce la far[oò]|non riuscir[oò]|non penso di riuscire)\b", lower):
            return Interpretation(
                reply=f"Capito. Per “{item.title}” vuoi cambiare la scadenza, ridurre l’obiettivo, liberare spazio oppure lasciarlo andare?",
                actions=[Action(type=ActionType.RECORD_USER_ASSESSMENT, item_id=item.id, data={"assessment": "L'utente ritiene l'obiettivo non fattibile"}), Action(type=ActionType.REQUEST_CLARIFICATION, item_id=item.id)],
            )

        progress = re.search(r"(?:ho fatto|sono a|fatto)\s+(\d+(?:[,.]\d+)?)\s+(?:delle|dei|su)\s+(\d+(?:[,.]\d+)?)", lower)
        if item and progress:
            value, total = (float(part.replace(",", ".")) for part in progress.groups())
            return Interpretation(reply=f"Registrato: per “{item.title}” sei a {value:g} su {total:g}.", actions=[Action(type=ActionType.RECORD_PROGRESS, item_id=item.id, data={"value": value, "total": total, "note": text})])

        estimate = re.search(r"(?:richieder[aà]|servono|serviranno|ci metto)\s+(\d+(?:[,.]\d+)?)\s+(giorn|or|minut)", lower)
        if item and estimate:
            amount = float(estimate.group(1).replace(",", "."))
            minutes = int(amount * (480 if estimate.group(2).startswith("giorn") else 60 if estimate.group(2).startswith("or") else 1))
            return Interpretation(reply=f"Aggiorno la stima per “{item.title}” a {self._human_minutes(minutes)}.", actions=[Action(type=ActionType.UPDATE_ESTIMATE, item_id=item.id, data={"estimate_minutes": minutes})])

        reorder = re.search(r"(.+?)\s+(?:mettil[oa]?\s+)?(dopo|prima di)\s+(.+)", lower)
        if reorder:
            source = self._resolve_item(reorder.group(1), items)
            target = self._resolve_item(reorder.group(3), items)
            if source and target and source.id != target.id:
                relation = "after" if reorder.group(2) == "dopo" else "before"
                return Interpretation(reply=f"Ok, metto “{source.title}” {reorder.group(2)} “{target.title}”.", actions=[Action(type=ActionType.REORDER_ITEM, item_id=source.id, data={"target_item_id": target.id, "relation": relation})])

        update_actions = self._updates_for_existing(text, lower, item)
        if update_actions:
            return update_actions

        creation = self._creation(text, lower, items)
        if creation:
            return creation

        if item:
            return Interpretation(reply=f"Ti seguo. Non cambio ancora “{item.title}”: dimmi che decisione vuoi prendere, se ce n’è una.", actions=[Action(type=ActionType.NO_ACTION, item_id=item.id)])
        return Interpretation(reply="Ti seguo. Non vedo ancora una modifica sicura da registrare: vuoi che questa cosa diventi un impegno, oppure ne stiamo solo parlando?", actions=[Action(type=ActionType.REQUEST_CLARIFICATION)])

    def _creation(self, text: str, lower: str, items: list[Item]) -> Interpretation | None:
        if not re.search(r"\b(voglio|vorrei|devo|mi piacerebbe|ricominciare|riprendere)\b", lower):
            return None
        title = re.sub(r"^(io\s+)?(vorrei ricominciare a|voglio ricominciare a|mi piacerebbe|ricominciare a|riprendere|voglio|vorrei|devo)\s+", "", text, flags=re.I).strip(" .")
        title = re.split(r"\s+(?:entro|perché|perche|almeno|mi serve|ci metto)\b", title, maxsplit=1, flags=re.I)[0].strip()
        title = re.sub(r"\s+(?:\d+|un[oa]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci)\s+volt[ea]\s+(?:alla|a)\s+settimana\.?$", "", title, flags=re.I).strip()
        title = re.sub(r"\s+(?:ogni giorno|tutti i giorni|quotidianamente)\.?$", "", title, flags=re.I).strip()
        if not title:
            return None
        weekly = re.search(r"(\d+)\s+volt[ea]\s+(?:alla|a)\s+settimana", lower)
        daily = bool(re.search(r"\b(ogni giorno|tutti i giorni|quotidianamente)\b", lower))
        due_at = self._parse_due(lower)
        estimate_match = re.search(r"(?:mi serve|ci metto|richiede)\s+(?:almeno\s+)?(\d+(?:[,.]\d+)?)\s+(giorn|or|minut)", lower)
        estimate_minutes = None
        if estimate_match:
            amount = float(estimate_match.group(1).replace(",", "."))
            estimate_minutes = int(amount * (480 if estimate_match.group(2).startswith("giorn") else 60 if estimate_match.group(2).startswith("or") else 1))
        if weekly or daily:
            kind = ItemKind.ROUTINE.value
            recurrence = {"period": "week", "frequency": int(weekly.group(1))} if weekly else {"period": "day", "frequency": 1}
        elif re.search(r"\b(ricominciare|riprendere|reinserire)\b", lower):
            kind, recurrence = ItemKind.INTRODUCTION.value, None
        elif re.search(r"\b(devo|assolutamente)\b", lower) or due_at:
            kind, recurrence = ItemKind.COMMITMENT.value, None
        else:
            kind, recurrence = ItemKind.POSSIBILITY.value, None
        data: dict[str, Any] = {"title": title, "kind": kind, "due_at": due_at, "recurrence": recurrence, "estimate_minutes": estimate_minutes}
        data = {key: value for key, value in data.items() if value is not None}
        action = Action(type=ActionType.CREATE_ITEM, data=data)
        conflict = self._potential_conflict(data, items)
        if conflict:
            return Interpretation(reply=f"Registro “{title}”. Vedo però un possibile attrito con “{conflict.title}”: vuoi dare precedenza alla nuova cosa?", actions=[action, Action(type=ActionType.REQUEST_CLARIFICATION)], needs_confirmation=False)
        return Interpretation(reply=f"Ok, tengo a mente “{title}”." + (" Ti seguirò sul ritmo senza chiedertelo ogni giorno." if recurrence else ""), actions=[action])

    def _updates_for_existing(self, text: str, lower: str, item: Item | None) -> Interpretation | None:
        if not item:
            return None
        changes: dict[str, Any] = {}
        if "urgente" in lower or "molto più importante" in lower:
            changes["importance"] = "alta: l'utente ha indicato urgenza/importanza esplicita"
        due = self._parse_due(lower)
        if due:
            changes["due_at"] = due
        cooldown = re.search(r"ricordam[ei].*meno spesso", lower)
        if cooldown:
            changes["checkin_cooldown_days"] = max(7, item.checkin_cooldown_days * 2)
        if changes:
            return Interpretation(reply=f"Aggiorno “{item.title}” con questa nuova informazione.", actions=[Action(type=ActionType.UPDATE_ITEM, item_id=item.id, data=changes)])
        return None

    @staticmethod
    def _resolve_item(text: str, items: list[Item]) -> Item | None:
        clean = re.sub(r"[^\wàèéìòù ]", " ", text.lower())
        active = [item for item in items if item.status not in {"completed", "abandoned"}]
        scored: list[tuple[int, Item]] = []
        for item in active:
            title = item.title.lower().strip()
            if re.search(rf"\b{re.escape(title)}\b", clean):
                scored.append((100 + len(title), item))
                continue
            overlap = sum(1 for token in title.split() if len(token) >= 4 and token in clean.split())
            if overlap:
                scored.append((overlap * 10 + len(title), item))
        return max(scored, key=lambda pair: pair[0])[1] if scored else None

    @staticmethod
    def _parse_due(lower: str) -> str | None:
        now = datetime.now(UTC)
        iso = re.search(r"entro (?:il\s+)?(\d{4}-\d{2}-\d{2})", lower)
        if iso:
            return f"{iso.group(1)}T23:59:00+00:00"
        if "entro venerdì" in lower or "entro venerdi" in lower:
            days = (4 - now.weekday()) % 7
            days = days or 7
            return (now + timedelta(days=days)).replace(hour=23, minute=59, second=0, microsecond=0).isoformat()
        days_match = re.search(r"entro\s+(\d+)\s+giorni", lower)
        if days_match:
            return (now + timedelta(days=int(days_match.group(1)))).replace(hour=23, minute=59, second=0, microsecond=0).isoformat()
        return None

    @staticmethod
    def _parse_suspend_until(lower: str) -> str | None:
        now = datetime.now(UTC)
        if "questo mese" in lower:
            next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return next_month.isoformat()
        return None

    @staticmethod
    def _potential_conflict(data: dict[str, Any], items: list[Item]) -> Item | None:
        if not data.get("due_at") or not data.get("estimate_minutes"):
            return None
        due = datetime.fromisoformat(data["due_at"])
        nearby = [item for item in items if item.status == "active" and item.due_at and abs((item.due_at - due).days) <= 7]
        return nearby[0] if nearby else None

    @staticmethod
    def _looks_like_summary(lower: str) -> bool:
        return any(phrase in lower for phrase in ("come stanno andando", "fammi il punto", "situazione generale", "a che punto siamo"))

    @staticmethod
    def _normalize_numbers(text: str) -> str:
        numbers = {"un": "1", "uno": "1", "una": "1", "due": "2", "tre": "3", "quattro": "4", "cinque": "5", "sei": "6", "sette": "7", "otto": "8", "nove": "9", "dieci": "10"}
        for word, value in numbers.items():
            text = re.sub(rf"\b{word}\b", value, text)
        return text

    @staticmethod
    def _summary(items: list[Item]) -> str:
        if not items:
            return "Non abbiamo ancora accordi o intenzioni registrate."
        lines = []
        for item in items:
            detail = item.status.value
            if item.due_at:
                detail += f", scadenza {item.due_at.strftime('%d/%m/%Y')}"
            if item.progress_value is not None:
                detail += f", avanzamento {item.progress_value:g}" + (f"/{item.progress_total:g}" if item.progress_total else "")
            lines.append(f"• {item.title}: {detail}")
        return "Ecco il quadro che ho:\n" + "\n".join(lines)

    @staticmethod
    def _human_minutes(minutes: int) -> str:
        if minutes >= 480 and minutes % 480 == 0:
            return f"{minutes // 480} giornate"
        if minutes >= 60 and minutes % 60 == 0:
            return f"{minutes // 60} ore"
        return f"{minutes} minuti"


def build_interpreter(
    provider: str,
    api_key: str | None,
    model: str,
    input_price: float = 0.25,
    cached_input_price: float = 0.025,
    output_price: float = 2.0,
) -> Interpreter:
    if provider == "openai":
        if not api_key:
            raise RuntimeError("AI_PROVIDER=openai richiede OPENAI_API_KEY")
        return OpenAIInterpreter(api_key, model, input_price, cached_input_price, output_price)
    return LocalInterpreter()
