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
            recurrence = item.recurrence or {}
            weekly_days = recurrence.get("days_of_week") if recurrence.get("frequency") == "weekly" else None
            weekly_quota = recurrence.get("times_per_week") if recurrence.get("frequency") == "weekly" else None
            if weekly_days:
                candidate = self._weekly_candidate(item, now)
                if not candidate:
                    continue
            elif weekly_quota:
                if item.id in pending_item_ids:
                    continue
                candidate = self._weekly_quota_candidate(item, now)
                if not candidate:
                    continue
            elif item.id in pending_item_ids or not self._eligible(item, now):
                continue
            else:
                candidate = self.evaluate(item, now)
            if candidate and candidate["score"] >= self.THRESHOLD:
                created.append(self.repository.create_checkin(item.id, candidate["message"], candidate["reason"], candidate["score"], candidate.get("target_due_at")))
                self.repository.update_item(item.id, {"last_checked_at": now.isoformat()}, "monitor", None)
        return created

    def _weekly_candidate(self, item: Item, now: datetime) -> dict[str, Any] | None:
        if item.status != "active":
            return None
        recurrence = item.recurrence or {}
        scheduled_days = {str(day).lower() for day in recurrence.get("days_of_week", [])}
        local_now = now.astimezone(self.timezone)
        day_name = local_now.strftime("%A").lower()
        if day_name not in scheduled_days:
            return None
        target = datetime(local_now.year, local_now.month, local_now.day, 23, 59, 59, tzinfo=self.timezone).astimezone(UTC)
        target_iso = target.isoformat()
        if self.repository.has_checkin_for_target(item.id, target_iso) or self._has_activity_on_local_date(item.id, local_now.date()):
            return None
        days_it = {"monday": "lunedì", "tuesday": "martedì", "wednesday": "mercoledì", "thursday": "giovedì", "friday": "venerdì", "saturday": "sabato", "sunday": "domenica"}
        message = f"Oggi è {days_it.get(day_name, day_name)}: è previsto “{item.title}”. È ancora realistico farlo oggi?"
        return {"score": 1.0, "reason": "occorrenza settimanale prevista oggi", "message": message, "target_due_at": target_iso}

    def _weekly_quota_candidate(self, item: Item, now: datetime) -> dict[str, Any] | None:
        if item.status != "active":
            return None
        goal = int((item.recurrence or {}).get("times_per_week") or 0)
        if goal < 1:
            return None
        local_now = now.astimezone(self.timezone)
        week_start = local_now.date() - timedelta(days=local_now.weekday())
        week_end = week_start + timedelta(days=6)
        completed = self._activity_count_between(item.id, week_start, week_end)
        remaining = max(0, goal - completed)
        days_remaining = (week_end - local_now.date()).days + 1
        if remaining == 0 or days_remaining > remaining + 1:
            return None
        target = datetime(week_end.year, week_end.month, week_end.day, 23, 59, 59, tzinfo=self.timezone).astimezone(UTC)
        target_iso = target.isoformat()
        if self.repository.has_checkin_for_target(item.id, target_iso):
            return None
        message = f"Questa settimana risultano {completed} su {goal} per “{item.title}”. Restano {remaining}: vuoi recuperarne una oggi?"
        return {"score": 1.0, "reason": "obiettivo settimanale a rischio", "message": message, "target_due_at": target_iso}

    def _activity_count_between(self, item_id: str, start_date: Any, end_date: Any) -> int:
        total = 0
        for record in self.repository.list_activity_records(item_id):
            if record.get("record_type") != "occurrence":
                continue
            activity_date = self._activity_local_date(record)
            if activity_date and start_date <= activity_date <= end_date:
                total += max(1, int(record.get("count") or 1))
        return total

    def _activity_local_date(self, record: dict[str, Any]) -> Any:
        raw = str(record.get("period_start") or "")
        try:
            if len(raw) == 10:
                return datetime.fromisoformat(raw).date()
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(self.timezone).date()
        except ValueError:
            return None

    def _has_activity_on_local_date(self, item_id: str, target_date: Any) -> bool:
        for record in self.repository.list_activity_records(item_id):
            if self._activity_local_date(record) == target_date:
                return True
        return False

    def evaluate(self, item: Item, now: datetime) -> dict[str, Any] | None:
        if item.status != "active" or item.kind in {"tema", "theme"}:
            return None
        due_score = 0.0
        progress_pressure = 0.0
        workload_pressure = 0.0
        remaining_minutes: float | None = None
        effort_days = 0.0
        margin_days = 0.0
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
        if effective_due and item.estimate_minutes:
            remaining_minutes = float(item.estimate_minutes)
            if item.progress_total and item.progress_value is not None:
                remaining_ratio = max(0.0, item.progress_total - item.progress_value) / item.progress_total
                remaining_minutes *= remaining_ratio
            effort_days = remaining_minutes / 480
            margin_days = max(1.0, effort_days * 0.25)
            days_available = max(0.0, (effective_due - now).total_seconds() / 86400)
            alert_horizon = effort_days + margin_days
            if remaining_minutes > 0 and days_available <= alert_horizon:
                workload_pressure = min(0.95, max(0.65, alert_horizon / max(days_available, 0.5)))
                reason.append("tempo disponibile vicino al lavoro stimato, incluso margine")
        if item.last_checked_at:
            staleness = min(0.45, (now - item.last_checked_at).days / 30)
        elif (now - item.created_at).days >= 10:
            staleness = 0.32
            reason.append("nessuna verifica recente")
        if item.importance:
            importance = 0.45 if any(word in item.importance.lower() for word in ("alta", "urgente", "econom")) else 0.3
        if item.consequences:
            importance = max(importance, 0.45)

        score = min(1.0, due_score * 0.65 + progress_pressure * 0.3 + workload_pressure * 0.5 + importance * 0.15 + staleness * 0.05 + (0.15 if reason else 0))
        if score < self.THRESHOLD:
            return None
        if effective_due:
            due_phrase = self._due_phrase(effective_due, now)
            progress = ""
            if item.progress_value is not None and item.progress_total:
                progress = f" Sei a {item.progress_value:g} su {item.progress_total:g}."
            effort = ""
            if workload_pressure and remaining_minutes is not None:
                if remaining_minutes >= 480:
                    estimate = f"{remaining_minutes / 480:g} giorni di lavoro"
                elif remaining_minutes >= 60:
                    estimate = f"{remaining_minutes / 60:g} ore"
                else:
                    estimate = f"{remaining_minutes:g} minuti"
                effort = f" La stima residua è circa {estimate}, oltre a un margine di {margin_days:g} giorni."
            message = self._due_message(item.title, due_phrase, progress, effort)
        else:
            message = f"È da un po' che non verifichiamo “{item.title}”. È ancora qualcosa che vuoi mantenere attivo?"
        return {"score": round(score, 3), "reason": "; ".join(reason) or "verifica contestuale", "message": message, "target_due_at": effective_due.isoformat() if effective_due else None}

    def pending_checkins(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(UTC)
        rendered: list[dict[str, Any]] = []
        for checkin in self.repository.pending_checkins():
            row = dict(checkin)
            item = self.repository.get_item(row["item_id"]) if row.get("item_id") else None
            if item:
                target_due = self._checkin_due(row, item)
                if target_due:
                    progress = f" Sei a {item.progress_value:g} su {item.progress_total:g}." if item.progress_value is not None and item.progress_total else ""
                    row["message"] = self._due_message(item.title, self._due_phrase(target_due, now), progress, "")
            rendered.append(row)
        return rendered

    def backfill_pending_targets(self) -> None:
        for checkin in self.repository.pending_checkins():
            if checkin.get("target_due_at") or not checkin.get("item_id"):
                continue
            item = self.repository.get_item(checkin["item_id"])
            if item:
                target_due = self._checkin_due(checkin, item)
                if target_due:
                    self.repository.set_checkin_target_due(checkin["id"], target_due.isoformat())

    def _checkin_due(self, checkin: dict[str, Any], item: Item) -> datetime | None:
        if checkin.get("target_due_at"):
            return self._aware(datetime.fromisoformat(str(checkin["target_due_at"]).replace("Z", "+00:00")))
        if item.due_at:
            return self._aware(item.due_at)
        recurrence = item.recurrence or {}
        if recurrence.get("frequency") == "monthly" and recurrence.get("day_of_month"):
            created = self._aware(datetime.fromisoformat(str(checkin["created_at"]).replace("Z", "+00:00")))
            return self._effective_due(item, created)
        return None

    def _due_phrase(self, due: datetime, now: datetime) -> str:
        days_left = (due.astimezone(self.timezone).date() - now.astimezone(self.timezone).date()).days
        if days_left == 0:
            return "oggi"
        if days_left == 1:
            return "domani"
        if days_left > 1:
            return f"tra {days_left} giorni"
        if days_left == -1:
            return "ieri"
        return f"da {-days_left} giorni"

    @staticmethod
    def _due_message(title: str, phrase: str, progress: str, effort: str) -> str:
        if phrase == "ieri" or phrase.startswith("da "):
            opening = f"“{title}” è scaduto {phrase}."
        else:
            opening = f"“{title}” ha una scadenza {phrase}."
        return f"{opening}{progress}{effort} È ancora realistico o c'è qualcosa da rinegoziare?"

    def _effective_due(self, item: Item, now: datetime) -> datetime | None:
        if item.due_at:
            return self._aware(item.due_at)
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

    def _eligible(self, item: Item, now: datetime) -> bool:
        if item.status == "suspended":
            return bool(item.suspended_until and self._aware(item.suspended_until) <= now)
        if item.last_checked_at and now - self._aware(item.last_checked_at) < timedelta(days=item.checkin_cooldown_days):
            return False
        return True

    def _aware(self, value: datetime) -> datetime:
        """Treat provider dates without an offset as local dates, then compare in UTC."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=self.timezone)
        return value.astimezone(UTC)
