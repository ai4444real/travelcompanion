from datetime import UTC, datetime

from app.db import Database
from app.operational_state import recurrence_facts
from app.repository import Repository


def test_monthly_fact_distinguishes_partial_work_from_completion(tmp_path):
    db = Database(tmp_path / "facts.db")
    db.initialize()
    repo = Repository(db)
    item = repo.create_item({"title": "Fatturare", "kind": "routine", "recurrence": {"frequency": "monthly", "day_of_month": 15}}, "test", None)
    repo.record_activity(item.id, {"period_start": "2026-09-14", "is_completion": False}, "test")
    facts = recurrence_facts(repo.list_items(), repo.list_activity_records(), "Europe/Zurich", datetime(2026, 9, 15, 12, tzinfo=UTC))
    assert facts[0]["item_active"] is True
    assert facts[0]["current_occurrence_completed"] is False
    repo.record_activity(item.id, {"period_start": "2026-09-15", "is_completion": True}, "test")
    facts = recurrence_facts(repo.list_items(), repo.list_activity_records(), "Europe/Zurich", datetime(2026, 9, 15, 12, tzinfo=UTC))
    assert facts[0]["current_occurrence_completed"] is True


def test_fixed_weekly_fact_reports_today_completion_while_item_stays_active(tmp_path):
    db = Database(tmp_path / "facts.db")
    db.initialize()
    repo = Repository(db)
    item = repo.create_item({"title": "Richiami", "kind": "routine", "recurrence": {"frequency": "weekly", "days_of_week": ["tuesday", "thursday"]}}, "test", None)
    repo.record_activity(item.id, {"period_start": "2026-09-15", "is_completion": True}, "test")
    fact = recurrence_facts(repo.list_items(), repo.list_activity_records(), "Europe/Zurich", datetime(2026, 9, 15, 12, tzinfo=UTC))[0]
    assert fact["item_active"] is True
    assert fact["scheduled_today"] is True
    assert fact["current_occurrence_completed"] is True
