from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.models import Item


def recurrence_facts(items: list[Item], activities: list[dict[str, Any]], timezone: str, now: datetime | None = None) -> list[dict[str, Any]]:
    zone = ZoneInfo(timezone)
    local_now = (now or datetime.now(UTC)).astimezone(zone)
    today = local_now.date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    facts: list[dict[str, Any]] = []

    def local_date(value: Any):
        text = str(value or "")
        try:
            if len(text) == 10:
                return datetime.fromisoformat(text).date()
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(zone).date()
        except ValueError:
            return None

    for item in items:
        recurrence = item.recurrence or {}
        if not recurrence:
            continue
        completed_dates = [
            date for row in activities
            if row.get("item_id") == item.id and row.get("record_type") == "occurrence"
            and row.get("is_completion", 1) and (date := local_date(row.get("period_start"))) is not None
        ]
        frequency = recurrence.get("frequency")
        fact: dict[str, Any] = {"item_id": item.id, "title": item.title, "frequency": frequency, "item_active": item.status == "active"}
        if frequency == "monthly":
            done = any((date.year, date.month) == (today.year, today.month) for date in completed_dates)
            fact.update({"period": f"{today.year}-{today.month:02d}", "current_occurrence_completed": done})
        elif frequency == "weekly":
            dates = sorted(str(date) for date in completed_dates if week_start <= date <= week_end)
            fact.update({"period_start": str(week_start), "period_end": str(week_end), "completed_dates": dates})
            if recurrence.get("days_of_week"):
                scheduled = local_now.strftime("%A").lower() in {str(day).lower() for day in recurrence["days_of_week"]}
                fact.update({"scheduled_today": scheduled, "current_occurrence_completed": str(today) in dates})
            elif recurrence.get("times_per_week"):
                goal = int(recurrence["times_per_week"])
                fact.update({"completed_count": len(dates), "goal": goal, "current_period_completed": len(dates) >= goal})
        facts.append(fact)
    return facts
