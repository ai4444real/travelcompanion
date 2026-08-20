from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.models import Item
from app.repository import Repository


class Monitor:
    """Deterministic candidate scoring. Silence is the default below threshold."""

    THRESHOLD = 0.60

    def __init__(self, repository: Repository, timezone: str = "Europe/Zurich"):
        self.repository = repository
        self.timezone = ZoneInfo(timezone)

    def run(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(UTC)
        created: list[dict[str, Any]] = []
        pending_item_ids = {row["item_id"] for row in self.repository.pending_checkins()}
        for item in self.repository.list_items(["active", "waiting", "unplanned", "suspended"]):
            if item.id in pending_item_ids or not self._eligible(item, now):
                continue
            candidate = self.evaluate(item, now)
            if candidate and candidate["score"] >= self.THRESHOLD:
                created.append(self.repository.create_checkin(item.id, candidate["message"], candidate["reason"], candidate["score"]))
                self.repository.update_item(item.id, {"last_checked_at": now.isoformat()}, "monitor", None)
        return created

    def evaluate(self, item: Item, now: datetime) -> dict[str, Any] | None:
        if item.status != "active":
            return None
        due_score = 0.0
        progress_pressure = 0.0
        staleness = 0.0
        importance = 0.2
        reason: list[str] = []

        effective_due = self._effective_due(item, now)
        if effective_due:
            days = (effective_due - now).total_seconds() / 86400
            if days < 0:
                due_score = 0.9
                reason.append("scadenza superata")
            elif days <= 2:
                due_score = 0.8
                reason.append("scadenza entro due giorni")
            elif days <= 7:
                due_score = 0.58
                reason.append("scadenza vicina")
            elif days <= 14:
                due_score = 0.3
        if item.progress_total and item.progress_value is not None:
            remaining_ratio = max(0, item.progress_total - item.progress_value) / item.progress_total
            if effective_due:
                days = max(0.5, (effective_due - now).total_seconds() / 86400)
                progress_pressure = min(0.85, remaining_ratio * (7 / days))
                if progress_pressure >= 0.45:
                    reason.append("margine in riduzione rispetto all'avanzamento")
        if item.last_checked_at:
            staleness = min(0.45, (now - item.last_checked_at).days / 30)
        elif (now - item.created_at).days >= 10:
            staleness = 0.32
            reason.append("nessuna verifica recente")
        if item.importance:
            importance = 0.45 if any(word in item.importance.lower() for word in ("alta", "urgente", "econom")) else 0.3
        if item.consequences:
            importance = max(importance, 0.45)

        score = min(1.0, due_score * 0.5 + progress_pressure * 0.3 + importance * 0.15 + staleness * 0.05 + (0.15 if reason else 0))
        if score < self.THRESHOLD:
            return None
        if effective_due:
            days_left = max(0, (effective_due.astimezone(self.timezone).date() - now.astimezone(self.timezone).date()).days)
            due_phrase = "oggi" if days_left == 0 else "domani" if days_left == 1 else f"tra {days_left} giorni"
            progress = ""
            if item.progress_value is not None and item.progress_total:
                progress = f" Sei a {item.progress_value:g} su {item.progress_total:g}."
            message = f"“{item.title}” ha una scadenza {due_phrase}.{progress} È ancora realistico o c'è qualcosa da rinegoziare?"
        else:
            message = f"È da un po' che non verifichiamo “{item.title}”. È ancora qualcosa che vuoi mantenere attivo?"
        return {"score": round(score, 3), "reason": "; ".join(reason) or "verifica contestuale", "message": message}

    def _effective_due(self, item: Item, now: datetime) -> datetime | None:
        if item.due_at:
            return item.due_at
        recurrence = item.recurrence or {}
        if recurrence.get("frequency") != "monthly" or not recurrence.get("day_of_month"):
            return None
        local_now = now.astimezone(self.timezone)
        year, month = local_now.year, local_now.month
        requested_day = int(recurrence["day_of_month"])

        def occurrence(target_year: int, target_month: int) -> datetime:
            day = min(requested_day, calendar.monthrange(target_year, target_month)[1])
            return datetime(target_year, target_month, day, 23, 59, 59, tzinfo=self.timezone)

        due = occurrence(year, month)
        if local_now > due:
            month = month + 1
            if month == 13:
                year, month = year + 1, 1
            due = occurrence(year, month)
        return due.astimezone(UTC)

    @staticmethod
    def _eligible(item: Item, now: datetime) -> bool:
        if item.status == "suspended":
            return bool(item.suspended_until and item.suspended_until <= now)
        if item.last_checked_at and now - item.last_checked_at < timedelta(days=item.checkin_cooldown_days):
            return False
        return True
