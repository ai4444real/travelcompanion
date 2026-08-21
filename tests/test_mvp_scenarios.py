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


def test_weekly_frequency_without_fixed_days_is_preserved(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Correre", "recurrence": {"frequency": "weekly", "times_per_week": 3}}, "test", None)
    updated = repo.update_item(item.id, {"recurrence": {"frequency": "weekly", "times_per_week": 4}}, "manual", None)
    assert updated.recurrence == {"frequency": "weekly", "times_per_week": 4}


def test_raw_snapshot_exposes_app_tables_without_configuration(tmp_path):
    repo, _, _ = setup(tmp_path)
    repo.create_item({"title": "Fatture"}, "test", None)
    snapshot = repo.raw_snapshot()
    assert set(snapshot) == {"items", "relations", "progress_events", "activity_records", "messages", "checkins", "audit_log", "ai_usage"}
    assert snapshot["items"][0]["title"] == "Fatture"
    assert "OPENAI_API_KEY" not in str(snapshot)


def test_free_form_category_is_persisted_and_editable(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Fatture", "category": "Amministrazione scuola"}, "test", None)
    assert item.category == "Amministrazione scuola"
    updated = repo.update_item(item.id, {"category": "Amministrazione associazione"}, "manual", None)
    assert updated.category == "Amministrazione associazione"


def test_individual_activity_keeps_optional_distance(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Correre", "kind": "routine"}, "test", None)
    message_id = repo.add_message("user", "Ho corso 6 km oggi")
    executor.execute([Action(type=ActionType.RECORD_ACTIVITY, item_id=item.id, data={
        "record_type": "occurrence", "period_start": "2026-08-20T07:00:00+02:00",
        "period_end": "2026-08-20T07:00:00+02:00", "count": 1, "quantity": 6,
        "unit": "km", "source_type": "explicit", "note": "Ho corso 6 km oggi",
    })], message_id)
    records = repo.list_activity_records(item.id)
    assert records[0]["count"] == 1
    assert records[0]["quantity"] == 6
    assert records[0]["unit"] == "km"


def test_approximate_activity_summary_does_not_invent_dates_or_distance(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Correre", "kind": "routine"}, "test", None)
    message_id = repo.add_message("user", "Questa settimana ho corso due volte")
    executor.execute([Action(type=ActionType.RECORD_ACTIVITY, item_id=item.id, data={
        "record_type": "summary", "period_start": "2026-08-17T00:00:00+02:00",
        "period_end": "2026-08-23T23:59:59+02:00", "count": 2,
        "source_type": "explicit", "note": "Questa settimana ho corso due volte",
    })], message_id)
    record = repo.list_activity_records(item.id)[0]
    assert record["record_type"] == "summary"
    assert record["count"] == 2
    assert record["quantity"] is None
    assert record["period_start"].startswith("2026-08-17")


def test_activity_resolves_an_existing_checkin(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Palestra", "kind": "routine"}, "test", None)
    repo.create_checkin(item.id, "Vai ancora in palestra?", "test", 0.8)
    message_id = repo.add_message("user", "Stamattina ho fatto palestra")
    executor.execute([Action(type="record_activity", item_id=item.id, data={"record_type": "occurrence"}, confidence=1)], message_id)
    assert repo.pending_checkins() == []


def test_due_today_is_enough_for_a_checkin_without_explicit_importance(tmp_path):
    repo, _, _ = setup(tmp_path)
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    item = repo.create_item({"title": "Chiamare Monica", "due_at": "2026-08-21T14:00:00Z"}, "test", None)
    candidate = Monitor(repo, "Europe/Zurich").evaluate(item, now)
    assert candidate is not None
    assert candidate["score"] >= Monitor.THRESHOLD


def test_monitor_accepts_due_dates_without_timezone(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Scadenza locale", "due_at": "2026-09-01T00:00:00"}, "test", None)
    monitor = Monitor(repo, "Europe/Zurich")
    due = monitor._effective_due(item, datetime(2026, 8, 21, 10, 0, tzinfo=UTC))
    assert due is not None and due.tzinfo is not None


def test_monitor_warns_when_estimated_work_plus_margin_fills_available_time(tmp_path):
    repo, _, _ = setup(tmp_path)
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    due = now + timedelta(days=10)
    item = repo.create_item({
        "title": "Lavoro lungo", "due_at": due.isoformat(), "estimate_minutes": 8 * 480,
    }, "test", None)
    candidate = Monitor(repo, "Europe/Zurich").evaluate(item, now)
    assert candidate is not None
    assert candidate["score"] >= Monitor.THRESHOLD
    assert "8 giorni di lavoro" in candidate["message"]
    assert "margine di 2 giorni" in candidate["message"]


def test_monitor_stays_silent_when_estimated_work_has_plenty_of_margin(tmp_path):
    repo, _, _ = setup(tmp_path)
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    item = repo.create_item({
        "title": "Lavoro breve", "due_at": (now + timedelta(days=30)).isoformat(), "estimate_minutes": 480,
    }, "test", None)
    assert Monitor(repo, "Europe/Zurich").evaluate(item, now) is None


def test_theme_is_a_real_kind_and_never_generates_checkins(tmp_path):
    repo, executor, _ = setup(tmp_path)
    message_id = repo.add_message("user", "Mentore aziendale è un tema")
    changed = executor.execute([Action(
        type=ActionType.CREATE_ITEM,
        data={"title": "Mentore aziendale", "kind": "tema", "description": "Portarlo sul mercato"},
        confidence=1,
    )], message_id)
    assert changed[0].kind == "tema"
    assert changed[0].description == "Portarlo sul mercato"
    assert Monitor(repo).run() == []


def test_task_can_belong_to_an_existing_theme(tmp_path):
    repo, executor, _ = setup(tmp_path)
    theme = repo.create_item({"title": "Mentore aziendale", "kind": "tema"}, "test", None)
    task = repo.create_item({"title": "Chiamare Monica", "kind": "commitment"}, "test", None)
    executor.execute([Action(type=ActionType.ADD_RELATION, item_id=task.id, data={
        "target_item_id": theme.id, "relation_type": "belongs_to",
    }, confidence=1)], repo.add_message("user", "Collegalo al tema"))
    relation = repo.list_relations()[0]
    assert relation["source_item_id"] == task.id
    assert relation["target_item_id"] == theme.id
    assert relation["relation_type"] == "belongs_to"
