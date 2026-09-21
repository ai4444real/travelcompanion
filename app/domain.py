from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.models import Action, ActionType, Item, ItemKind, ItemStatus
from app.repository import Repository


class ActionExecutor:
    """Validates and applies model proposals; the model never writes directly."""

    def __init__(self, repository: Repository, timezone: str = "Europe/Zurich"):
        self.repository = repository
        self.timezone = ZoneInfo(timezone)

    def execute(self, actions: list[Action], source_message_id: str) -> list[Item]:
        self.validate_actions(actions)
        changed: dict[str, Item] = {}
        for action in actions:
            if action.confidence < 0.65 and action.type not in {ActionType.REQUEST_CLARIFICATION, ActionType.NO_ACTION}:
                continue
            item = self._execute_one(action, source_message_id)
            if item:
                changed[item.id] = item
        return list(changed.values())

    def validate_actions(self, actions: list[Action]) -> None:
        """Reject an invalid batch before the first write can occur."""
        for action in actions:
            if action.confidence < 0.65 or action.type in {ActionType.NO_ACTION, ActionType.REQUEST_CLARIFICATION, ActionType.SEND_CHECKIN}:
                continue
            if action.type == ActionType.CREATE_ITEM:
                if not action.data.get("title"):
                    raise ValueError("Creazione senza titolo")
                continue
            if action.type == ActionType.DISMISS_CHECKIN:
                checkin = self.repository.get_checkin(action.item_id) if action.item_id else None
                if checkin and checkin["status"] != "pending":
                    if any(row["item_id"] == checkin["item_id"] for row in self.repository.pending_checkins()):
                        raise ValueError("Richiamo superato: esiste un box più recente per lo stesso oggetto")
                if not action.item_id or not (checkin or self.repository.get_item(action.item_id)):
                    raise ValueError("Richiamo inesistente")
                continue
            if not action.item_id or not self.repository.get_item(action.item_id):
                raise ValueError("Oggetto inesistente o ID mancante")

    def _execute_one(self, action: Action, source_message_id: str) -> Item | None:
        if action.type in {ActionType.NO_ACTION, ActionType.REQUEST_CLARIFICATION, ActionType.SEND_CHECKIN}:
            return None
        if action.type == ActionType.CREATE_ITEM:
            if not action.data.get("title"):
                raise ValueError("Creazione ignorata: titolo mancante")
            return self.repository.create_item(self._normalize_item_data(action.data), "conversation", source_message_id)
        if action.type == ActionType.DISMISS_CHECKIN:
            if not action.item_id:
                return None
            if self.repository.resolve_checkin(action.item_id):
                return None
            if self.repository.get_checkin(action.item_id):
                return None  # Chiusura ripetuta: già risolto o scaduto.
            if self.repository.get_item(action.item_id):
                self.repository.resolve_pending_checkins(action.item_id)
                return None
            raise ValueError(f"Richiamo o oggetto non trovato: {action.item_id}")
        if not action.item_id or not self.repository.get_item(action.item_id):
            raise ValueError(f"Oggetto non trovato: {action.item_id or 'ID mancante'}")
        if action.type == ActionType.UPDATE_ITEM:
            changes = dict(action.data)
            current = self.repository.get_item(action.item_id)
            if changes.get("status") == ItemStatus.ABANDONED.value:
                changes.pop("status")
            if current and current.recurrence and changes.get("status") == ItemStatus.COMPLETED.value:
                changes.pop("status")
                self._record_recurring_once(current, {
                    "record_type": "occurrence", "source_type": "explicit",
                    "is_completion": True,
                    "note": "Occorrenza ricorrente completata.",
                }, source_message_id)
                if not changes:
                    return self.repository.get_item(action.item_id)
            if not changes:
                return current
            updated = self.repository.update_item(action.item_id, changes, "conversation", source_message_id)
            if "due_at" in changes or "recurrence" in changes:
                self.repository.resolve_pending_checkins(action.item_id)
            return updated
        if action.type == ActionType.COMPLETE_ITEM:
            current = self.repository.get_item(action.item_id)
            if current and current.recurrence:
                self._record_recurring_once(current, {
                    "record_type": "occurrence", "source_type": "explicit",
                    "is_completion": True,
                    "note": "Occorrenza ricorrente completata.",
                }, source_message_id)
                return self.repository.get_item(action.item_id)
            item = self.repository.update_item(action.item_id, {"status": ItemStatus.COMPLETED.value}, "conversation", source_message_id)
            self.repository.resolve_pending_checkins(action.item_id)
            return item
        if action.type == ActionType.SUSPEND_ITEM:
            changes = {"status": ItemStatus.SUSPENDED.value}
            if action.data.get("suspended_until"):
                changes["suspended_until"] = action.data["suspended_until"]
            return self.repository.update_item(action.item_id, changes, "conversation", source_message_id)
        if action.type == ActionType.ABANDON_ITEM:
            return self.repository.update_item(action.item_id, {"status": ItemStatus.ABANDONED.value}, "conversation", source_message_id)
        if action.type == ActionType.UPDATE_ESTIMATE:
            return self.repository.update_item(action.item_id, {"estimate_minutes": action.data.get("estimate_minutes")}, "conversation", source_message_id)
        if action.type == ActionType.RECORD_PROGRESS:
            return self.repository.record_progress(action.item_id, action.data.get("value"), action.data.get("total"), action.data.get("unit"), action.data.get("note"), source_message_id)
        if action.type == ActionType.RECORD_USER_ASSESSMENT:
            return self.repository.update_item(action.item_id, {"user_assessment": action.data.get("assessment")}, "conversation", source_message_id)
        if action.type == ActionType.RECORD_ACTIVITY:
            current = self.repository.get_item(action.item_id)
            if current and current.recurrence and action.data.get("record_type", "occurrence") == "occurrence":
                self._record_recurring_once(current, action.data, source_message_id)
            else:
                self.repository.record_activity(action.item_id, action.data, source_message_id)
            return self.repository.get_item(action.item_id)
        if action.type == ActionType.REORDER_ITEM:
            target_id = action.data.get("target_item_id")
            relation = action.data.get("relation", "after")
            if target_id and self.repository.get_item(target_id):
                self.repository.add_relation(action.item_id, target_id, relation, "conversation", source_message_id)
            return self.repository.get_item(action.item_id)
        if action.type == ActionType.ADD_RELATION:
            target_id = action.data.get("target_item_id")
            if target_id and self.repository.get_item(target_id):
                self.repository.add_relation(action.item_id, target_id, action.data.get("relation_type", "related"), "conversation", source_message_id)
            return self.repository.get_item(action.item_id)
        return None

    def _record_recurring_once(self, item: Item, data: dict, source_message_id: str) -> None:
        recurrence = item.recurrence or {}
        frequency = recurrence.get("frequency")
        value = data.get("period_start") or datetime.now(UTC).isoformat()
        occurrence = self._local_datetime(value)
        for existing in self.repository.list_activity_records(item.id):
            if existing.get("record_type") != "occurrence" or not existing.get("is_completion", 1):
                continue
            previous = self._local_datetime(existing.get("period_start"))
            duplicate = (
                frequency == "monthly" and (previous.year, previous.month) == (occurrence.year, occurrence.month)
                or frequency == "weekly" and recurrence.get("days_of_week") and previous.date() == occurrence.date()
            )
            if duplicate:
                self.repository.resolve_pending_checkins(item.id)
                return
        self.repository.record_activity(item.id, data, source_message_id)

    def _local_datetime(self, value: object) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.timezone)
        return parsed.astimezone(self.timezone)

    @staticmethod
    def _normalize_item_data(data: dict) -> dict:
        """Keep provider vocabulary outside the canonical domain model."""
        normalized = dict(data)
        status_aliases = {
            "open": ItemStatus.ACTIVE.value,
            "paused": ItemStatus.SUSPENDED.value,
            "done": ItemStatus.COMPLETED.value,
            "pending": ItemStatus.WAITING.value,
            "backlog": ItemStatus.UNPLANNED.value,
        }
        kind_aliases = {
            "theme": ItemKind.TEMA.value,
            "tema": ItemKind.TEMA.value,
            "topic": ItemKind.TEMA.value,
            "project": ItemKind.TEMA.value,
            "task": ItemKind.COMMITMENT.value,
            "goal": ItemKind.COMMITMENT.value,
            "habit": ItemKind.ROUTINE.value,
            "change": ItemKind.INTRODUCTION.value,
            "backlog": ItemKind.POSSIBILITY.value,
            "book": ItemKind.POSSIBILITY.value,
            "libro": ItemKind.POSSIBILITY.value,
        }
        if "due_at" not in normalized and normalized.get("due_date"):
            normalized["due_at"] = f"{normalized.pop('due_date')}T23:59:00+00:00"
        if "context" not in normalized and normalized.get("note"):
            normalized["context"] = normalized.pop("note")
        status = str(normalized.get("status", ItemStatus.ACTIVE.value)).lower()
        kind = str(normalized.get("kind", ItemKind.POSSIBILITY.value)).lower()
        valid_statuses = {entry.value for entry in ItemStatus}
        valid_kinds = {entry.value for entry in ItemKind}
        normalized["status"] = status_aliases.get(status, status if status in valid_statuses else ItemStatus.ACTIVE.value)
        normalized["kind"] = kind_aliases.get(kind, kind if kind in valid_kinds else ItemKind.POSSIBILITY.value)
        return normalized
