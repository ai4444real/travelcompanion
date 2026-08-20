from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.ai import LocalInterpreter
from app.db import Database
from app.domain import ActionExecutor
from app.models import ActionType
from app.models import Action
from app.monitor import Monitor
from app.repository import Repository


def setup(tmp_path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    repo = Repository(db)
    return repo, ActionExecutor(repo), LocalInterpreter()


def converse(repo, executor, interpreter, text):
    message_id = repo.add_message("user", text)
    result = asyncio.run(interpreter.interpret(text, repo.list_items(), repo.recent_messages()))
    changed = executor.execute(result.actions, message_id)
    repo.add_message("assistant", result.reply)
    return result, changed


def test_case_1_add_routine(tmp_path):
    repo, executor, interpreter = setup(tmp_path)
    _, changed = converse(repo, executor, interpreter, "Voglio correre tre volte alla settimana.")
    assert len(changed) == 1
    assert changed[0].kind == "routine"
    assert changed[0].recurrence == {"period": "week", "frequency": 3}


def test_case_2_new_commitment_surfaces_conflict(tmp_path):
    repo, executor, interpreter = setup(tmp_path)
    due = (datetime.now(UTC) + timedelta(days=4)).isoformat()
    repo.create_item({"title": "finire il libro", "kind": "commitment", "due_at": due, "estimate_minutes": 960}, "test", None)
    result, changed = converse(repo, executor, interpreter, "Voglio preparare la lezione entro venerdì. Mi serve un giorno.")
    assert changed
    assert any(action.type == ActionType.REQUEST_CLARIFICATION for action in result.actions)
    assert "attrito" in result.reply


def test_case_3_relative_priority(tmp_path):
    repo, executor, interpreter = setup(tmp_path)
    book = repo.create_item({"title": "libro", "kind": "possibility"}, "test", None)
    target = repo.create_item({"title": "B", "kind": "commitment"}, "test", None)
    result, _ = converse(repo, executor, interpreter, "Il libro mettilo dopo B.")
    assert result.actions[0].type == ActionType.REORDER_ITEM
    relations = repo.list_relations()
    assert relations[0]["source_item_id"] == book.id
    assert relations[0]["target_item_id"] == target.id
    assert relations[0]["relation_type"] == "after"


def test_case_4_progress(tmp_path):
    repo, executor, interpreter = setup(tmp_path)
    book = repo.create_item({"title": "libro"}, "test", None)
    converse(repo, executor, interpreter, "Del libro ho fatto tre delle cinque giornate previste.")
    updated = repo.get_item(book.id)
    assert updated.progress_value == 3
    assert updated.progress_total == 5


def test_case_5_monitor_intercepts_pressure(tmp_path):
    repo, _, _ = setup(tmp_path)
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    repo.create_item({"title": "preparare la lezione", "kind": "commitment", "due_at": due, "progress_value": 1, "progress_total": 4, "importance": "alta"}, "test", None)
    created = Monitor(repo).run()
    assert len(created) == 1
    assert "realistico" in created[0]["message"]


def test_case_6_renegotiation_does_not_abandon(tmp_path):
    repo, executor, interpreter = setup(tmp_path)
    book = repo.create_item({"title": "libro"}, "test", None)
    result, _ = converse(repo, executor, interpreter, "Il libro non ce la farò mai.")
    assert repo.get_item(book.id).status == "active"
    assert any(action.type == ActionType.REQUEST_CLARIFICATION for action in result.actions)


def test_case_7_suspension_stops_checkins(tmp_path):
    repo, executor, interpreter = setup(tmp_path)
    bass = repo.create_item({"title": "basso", "created_at": (datetime.now(UTC)-timedelta(days=20)).isoformat()}, "test", None)
    converse(repo, executor, interpreter, "Per questo mese lasciamo perdere il basso.")
    assert repo.get_item(bass.id).status == "suspended"
    assert Monitor(repo).run() == []


def test_case_8_intelligent_silence(tmp_path):
    repo, _, _ = setup(tmp_path)
    repo.create_item({"title": "leggere un romanzo", "kind": "possibility"}, "test", None)
    assert Monitor(repo).run() == []


def test_audit_records_before_and_after(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "fatture"}, "test", None)
    repo.update_item(item.id, {"importance": "alta"}, "manual", None)
    log = repo.audit_log()
    assert len(log) == 2
    assert log[0]["before_json"] and log[0]["after_json"]


def test_provider_vocabulary_is_normalized_before_persistence(tmp_path):
    repo, executor, _ = setup(tmp_path)
    message_id = repo.add_message("user", "Voglio leggere un libro")
    changed = executor.execute(
        [Action(type=ActionType.CREATE_ITEM, data={"title": "leggere un libro", "status": "open", "kind": "goal"})],
        message_id,
    )
    assert changed[0].status == "active"
    assert changed[0].kind == "commitment"


def test_provider_date_alias_is_normalized(tmp_path):
    repo, executor, _ = setup(tmp_path)
    message_id = repo.add_message("user", "Voglio leggere il libro entro dieci giorni")
    changed = executor.execute(
        [Action(type=ActionType.CREATE_ITEM, data={"title": "Il libro", "kind": "libro", "due_date": "2026-08-30", "note": "Terminarlo entro dieci giorni"})],
        message_id,
    )
    assert changed[0].due_at.isoformat() == "2026-08-30T23:59:00+00:00"
    assert changed[0].kind == "possibility"
    assert changed[0].context == "Terminarlo entro dieci giorni"


def test_ai_usage_is_tracked_and_budget_enforced_in_summary(tmp_path):
    repo, _, _ = setup(tmp_path)
    repo.record_ai_usage({
        "response_id": "resp_test",
        "provider": "openai",
        "model": "gpt-5-mini",
        "input_tokens": 1000,
        "cached_input_tokens": 200,
        "output_tokens": 500,
        "total_tokens": 1500,
        "estimated_cost_usd": 0.25,
        "response_status": "completed",
    })
    summary = repo.ai_usage_summary(0.20)
    assert summary["request_count"] == 1
    assert summary["total_tokens"] == 1500
    assert summary["estimated_cost_usd"] == 0.25
    assert summary["blocked"] is True


def test_monthly_commitment_is_checked_on_its_due_day(tmp_path):
    repo, _, _ = setup(tmp_path)
    repo.create_item({
        "title": "Inviare fatture della scuola",
        "kind": "commitment",
        "recurrence": {"frequency": "monthly", "day_of_month": 20},
        "importance": "high",
        "consequences": "Possibili problemi di incasso",
    }, "test", None)
    now = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    created = Monitor(repo, "Europe/Zurich").run(now)
    assert len(created) == 1
    assert "scadenza" in created[0]["reason"]
    assert "fatture" in created[0]["message"]


def test_monthly_commitment_rolls_to_next_month_after_due_day(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({
        "title": "Inviare fatture",
        "kind": "commitment",
        "recurrence": {"frequency": "monthly", "day_of_month": 20},
    }, "test", None)
    monitor = Monitor(repo, "Europe/Zurich")
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    due = monitor._effective_due(item, now)
    assert due.astimezone(ZoneInfo("Europe/Zurich")).date().isoformat() == "2026-09-20"


def test_manual_correction_can_change_monthly_day(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({
        "title": "Inviare fatture",
        "recurrence": {"frequency": "monthly", "day_of_month": 20},
    }, "test", None)
    updated = repo.update_item(item.id, {"due_at": None, "recurrence": {"frequency": "monthly", "day_of_month": 18}}, "manual", None)
    assert updated.due_at is None
    assert updated.recurrence == {"frequency": "monthly", "day_of_month": 18}


def test_manual_correction_can_clear_or_update_weekly_recurrence(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Richiami", "recurrence": {"frequency": "weekly", "days_of_week": ["tuesday", "thursday"]}}, "test", None)
    updated = repo.update_item(item.id, {"recurrence": {"frequency": "weekly", "days_of_week": ["monday"]}}, "manual", None)
    assert updated.recurrence == {"frequency": "weekly", "days_of_week": ["monday"]}
    cleared = repo.update_item(item.id, {"recurrence": None}, "manual", None)
    assert cleared.recurrence is None


def test_raw_snapshot_exposes_app_tables_without_configuration(tmp_path):
    repo, _, _ = setup(tmp_path)
    repo.create_item({"title": "Fatture"}, "test", None)
    snapshot = repo.raw_snapshot()
    assert set(snapshot) == {"items", "relations", "progress_events", "messages", "checkins", "audit_log", "ai_usage"}
    assert snapshot["items"][0]["title"] == "Fatture"
    assert "OPENAI_API_KEY" not in str(snapshot)


def test_free_form_category_is_persisted_and_editable(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Fatture", "category": "Amministrazione scuola"}, "test", None)
    assert item.category == "Amministrazione scuola"
    updated = repo.update_item(item.id, {"category": "Amministrazione associazione"}, "manual", None)
    assert updated.category == "Amministrazione associazione"
