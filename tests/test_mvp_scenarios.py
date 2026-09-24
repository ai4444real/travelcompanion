from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.ai import LocalInterpreter
from app.db import Database
from app.domain import ActionExecutor
from app.models import Action, ActionType, ItemStatus
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
    assert set(snapshot) == {"items", "relations", "progress_events", "activity_records", "messages", "checkins", "audit_log", "ai_usage", "calendar_events"}
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


def test_focus_is_an_ordered_optional_selection(tmp_path):
    repo, _, _ = setup(tmp_path)
    first = repo.create_item({"title": "Primo"}, "test", None)
    second = repo.create_item({"title": "Secondo"}, "test", None)
    repo.set_focus_order([second.id, first.id])
    assert repo.get_item(second.id).focus_position == 1
    assert repo.get_item(first.id).focus_position == 2
    repo.set_focus_order([first.id])
    assert repo.get_item(first.id).focus_position == 1
    assert repo.get_item(second.id).focus_position is None


def test_theme_can_be_added_to_focus(tmp_path):
    repo, _, _ = setup(tmp_path)
    theme = repo.create_item({"title": "Un tema", "kind": "tema"}, "test", None)
    repo.set_focus_order([theme.id])
    assert repo.get_item(theme.id).focus_position == 1


def test_pending_checkin_recalculates_relative_deadline_when_read(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Chiamare consulente", "due_at": "2026-08-25T17:00:00Z"}, "test", None)
    repo.create_checkin(item.id, "Scadenza tra due giorni", "test", 0.8, "2026-08-25T17:00:00+00:00")
    monitor = Monitor(repo, "Europe/Zurich")
    upcoming = monitor.pending_checkins(datetime(2026, 8, 24, 9, 0, tzinfo=UTC))[0]
    today = monitor.pending_checkins(datetime(2026, 8, 25, 9, 0, tzinfo=UTC))[0]
    overdue = monitor.pending_checkins(datetime(2026, 8, 27, 9, 0, tzinfo=UTC))[0]
    assert upcoming["timing"] == "upcoming"
    assert "scadenza oggi" in today["message"]
    assert today["timing"] == "due"
    assert "scaduto da 2 giorni" in overdue["message"]
    assert overdue["timing"] == "due"


def test_legacy_monthly_checkin_uses_occurrence_near_creation(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Fatture", "recurrence": {"frequency": "monthly", "day_of_month": 25}}, "test", None)
    checkin = repo.create_checkin(item.id, "Scadenza domani", "test", 0.8)
    with repo.db.connect() as conn:
        conn.execute("UPDATE checkins SET created_at=? WHERE id=?", ("2026-08-23T22:00:00+00:00", checkin["id"]))
    rendered = Monitor(repo, "Europe/Zurich").pending_checkins(datetime(2026, 8, 25, 9, 0, tzinfo=UTC))[0]
    assert "scadenza oggi" in rendered["message"]


def test_due_dates_are_stored_as_canonical_utc(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Scadenza locale", "due_at": "2026-09-01"}, "test", None)
    assert item.due_at is not None
    assert item.due_at.isoformat() == "2026-09-01T21:59:59+00:00"


def test_completing_recurring_item_records_occurrence_and_keeps_it_active(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Fatture", "kind": "commitment", "recurrence": {"frequency": "monthly", "day_of_month": 25}}, "test", None)
    repo.create_checkin(item.id, "Scade oggi", "test", 0.8)
    executor.execute([Action(type=ActionType.COMPLETE_ITEM, item_id=item.id, confidence=1)], repo.add_message("user", "Fatto"))
    assert repo.get_item(item.id).status == "active"
    assert len(repo.list_activity_records(item.id)) == 1
    assert repo.pending_checkins() == []


def test_conversation_update_cannot_mark_recurring_item_completed(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Stipendi", "recurrence": {"frequency": "monthly", "day_of_month": 26}}, "test", None)
    executor.execute([Action(type=ActionType.UPDATE_ITEM, item_id=item.id, data={"status": "completed"}, confidence=1)], repo.add_message("user", "Fatto"))
    assert repo.get_item(item.id).status == "active"
    assert len(repo.list_activity_records(item.id)) == 1


def test_rescheduling_closes_old_checkin_without_abandoning_item(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Chiamare consulente", "due_at": "2026-08-25T17:00:00Z"}, "test", None)
    repo.create_checkin(item.id, "Scade oggi", "test", 0.8, "2026-08-25T17:00:00Z")
    executor.execute([Action(type=ActionType.UPDATE_ITEM, item_id=item.id, data={
        "due_at": "2026-08-28T15:00:00Z", "estimate_minutes": 30, "status": "abandoned",
    }, confidence=1)], repo.add_message("user", "Sposta la scadenza e cancella il box"))
    updated = repo.get_item(item.id)
    assert updated.status == "active"
    assert updated.estimate_minutes == 30
    assert updated.due_at.isoformat() == "2026-08-28T15:00:00+00:00"
    assert repo.pending_checkins() == []


def test_dismiss_checkin_does_not_change_item_status(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Un impegno"}, "test", None)
    repo.create_checkin(item.id, "Ne parliamo?", "test", 0.8)
    executor.execute([Action(type=ActionType.DISMISS_CHECKIN, item_id=item.id, confidence=1)], repo.add_message("user", "Togli il box"))
    assert repo.get_item(item.id).status == "active"
    assert repo.pending_checkins() == []


def test_dismiss_checkin_accepts_checkin_id_from_ai(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Palestra", "kind": "routine"}, "test", None)
    checkin = repo.create_checkin(item.id, "Ne parliamo?", "test", 1)
    executor.execute([Action(type=ActionType.DISMISS_CHECKIN, item_id=checkin["id"], confidence=1)], repo.add_message("user", "Togli il box"))
    assert repo.pending_checkins() == []
    assert repo.get_item(item.id).status == "active"


def test_send_checkin_creates_a_real_box_for_the_item(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Chiamare Michi", "due_at": "2026-09-24T18:00:00Z"}, "test", None)
    executor.execute([Action(type=ActionType.SEND_CHECKIN, item_id=item.id, data={
        "message": "Chiamare Michi entro le 20:00.",
        "reason": "richiesto dall'utente",
        "target_due_at": "2026-09-24T20:00:00+02:00",
    }, confidence=1)], repo.add_message("user", "Crea il box"))

    checkin = repo.pending_checkins()[0]
    assert checkin["item_id"] == item.id
    assert checkin["message"] == "Chiamare Michi entro le 20:00."
    assert checkin["target_due_at"] == "2026-09-24T20:00:00+02:00"


def test_send_checkin_rejects_a_missing_target_before_writes(tmp_path):
    repo, executor, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="Oggetto del richiamo inesistente"):
        executor.execute([Action(type=ActionType.SEND_CHECKIN, data={"target_item_id": "missing"}, confidence=1)], "message")
    assert repo.pending_checkins() == []


def test_dismiss_checkin_is_idempotent_when_already_closed(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Palestra"}, "test", None)
    checkin = repo.create_checkin(item.id, "Ne parliamo?", "test", 1)
    action = Action(type=ActionType.DISMISS_CHECKIN, item_id=checkin["id"], confidence=1)
    executor.execute([action], repo.add_message("user", "Chiudi"))
    executor.execute([action], repo.add_message("user", "Chiudi ancora"))
    assert repo.get_checkin(checkin["id"])["status"] == "resolved"


def test_old_checkin_id_does_not_hide_a_new_pending_box(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Palestra"}, "test", None)
    old = repo.create_checkin(item.id, "Vecchio", "test", 1)
    repo.resolve_checkin(old["id"])
    new = repo.create_checkin(item.id, "Nuovo", "test", 1)
    action = Action(type=ActionType.DISMISS_CHECKIN, item_id=old["id"], confidence=1)
    with pytest.raises(ValueError, match="più recente"):
        executor.execute([action], repo.add_message("user", "Chiudi il box"))
    assert repo.get_checkin(new["id"])["status"] == "pending"


def test_invalid_second_action_cannot_partially_create_item(tmp_path):
    repo, executor, _ = setup(tmp_path)
    actions = [
        Action(type=ActionType.CREATE_ITEM, data={"title": "Contattare Simona"}, confidence=1),
        Action(type=ActionType.UPDATE_ITEM, item_id=None, data={"due_at": "2026-09-25T17:00:00+02:00"}, confidence=1),
    ]
    with pytest.raises(ValueError, match="ID mancante"):
        executor.execute(actions, repo.add_message("user", "Aggiungi Contattare Simona"))
    assert repo.list_items() == []


def test_fixed_weekly_recurrence_creates_checkin_on_each_scheduled_day(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Controllo richiami", "kind": "routine", "recurrence": {
        "frequency": "weekly", "days_of_week": ["tuesday", "thursday"],
    }}, "test", None)
    monitor = Monitor(repo, "Europe/Zurich")
    tuesday = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
    created = monitor.run(tuesday)
    assert len(created) == 1
    assert "martedì" in created[0]["message"]
    assert "Settimana 24–30 agosto" in created[0]["message"]
    assert monitor.run(tuesday + timedelta(hours=1)) == []
    repo.record_activity(item.id, {"record_type": "occurrence", "period_start": "2026-08-25"}, "test")
    thursday = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
    created = monitor.run(thursday)
    assert len(created) == 1
    assert "giovedì" in created[0]["message"]


def test_fixed_weekly_recurrence_does_not_remind_if_already_done_that_day(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Controllo richiami", "kind": "routine", "recurrence": {
        "frequency": "weekly", "days_of_week": ["thursday"],
    }}, "test", None)
    repo.record_activity(item.id, {"record_type": "occurrence", "period_start": "2026-08-27"}, "test")
    assert Monitor(repo, "Europe/Zurich").run(datetime(2026, 8, 27, 8, 0, tzinfo=UTC)) == []


def test_weekly_quota_warns_once_when_remaining_days_get_tight(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Correre", "kind": "routine", "recurrence": {
        "frequency": "weekly", "times_per_week": 3,
    }}, "test", None)
    monitor = Monitor(repo, "Europe/Zurich")
    assert monitor.run(datetime(2026, 8, 26, 8, 0, tzinfo=UTC)) == []
    created = monitor.run(datetime(2026, 8, 27, 8, 0, tzinfo=UTC))
    assert len(created) == 1
    assert "0 su 3" in created[0]["message"]
    assert "Settimana 24–30 agosto" in created[0]["message"]
    repo.record_activity(item.id, {"record_type": "occurrence", "period_start": "2026-08-28"}, "test")
    assert monitor.run(datetime(2026, 8, 29, 8, 0, tzinfo=UTC)) == []


def test_weekly_quota_counts_current_week_activities(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Palestra", "kind": "routine", "recurrence": {
        "frequency": "weekly", "times_per_week": 2,
    }}, "test", None)
    repo.record_activity(item.id, {"record_type": "occurrence", "period_start": "2026-08-25"}, "test")
    monitor = Monitor(repo, "Europe/Zurich")
    created = monitor.run(datetime(2026, 8, 29, 8, 0, tzinfo=UTC))
    assert len(created) == 1
    assert "1 su 2" in created[0]["message"]
    assert "Restano 1" in created[0]["message"]


def test_weekly_checkin_keeps_explicit_period_when_rendered(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Richiami", "kind": "routine", "recurrence": {
        "frequency": "weekly", "days_of_week": ["thursday"],
    }}, "test", None)
    monitor = Monitor(repo, "Europe/Zurich")
    monitor.run(datetime(2026, 8, 27, 8, 0, tzinfo=UTC))
    rendered = monitor.pending_checkins(datetime(2026, 8, 27, 9, 0, tzinfo=UTC))
    assert len(rendered) == 1
    assert "Settimana 24–30 agosto" in rendered[0]["message"]
    assert "oggi è giovedì" in rendered[0]["message"]


def test_weekly_checkin_expires_when_new_week_starts(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Palestra", "kind": "routine", "recurrence": {
        "frequency": "weekly", "times_per_week": 2,
    }}, "test", None)
    monitor = Monitor(repo, "Europe/Zurich")
    monitor.run(datetime(2026, 9, 12, 8, 0, tzinfo=UTC))
    assert len(repo.pending_checkins()) == 1
    assert monitor.pending_checkins(datetime(2026, 9, 14, 8, 0, tzinfo=UTC)) == []
    assert repo.list_checkins()[0]["status"] == "expired"


def test_monthly_checkin_remains_until_month_end_then_expires(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Fatturare", "kind": "commitment", "importance": "alta", "recurrence": {
        "frequency": "monthly", "day_of_month": 15,
    }}, "test", None)
    monitor = Monitor(repo, "Europe/Zurich")
    monitor.run(datetime(2026, 9, 14, 8, 0, tzinfo=UTC))
    assert len(monitor.pending_checkins(datetime(2026, 9, 30, 8, 0, tzinfo=UTC))) == 1
    assert monitor.pending_checkins(datetime(2026, 10, 1, 8, 0, tzinfo=UTC)) == []


def test_manual_date_only_deadline_ends_on_same_zurich_day(tmp_path):
    repo, _, _ = setup(tmp_path)
    item = repo.create_item({"title": "Lezione"}, "test", None)
    updated = repo.update_item(item.id, {"due_at": "2026-09-21T23:59:59"}, "manual", None)
    assert updated.due_at.isoformat() == "2026-09-21T21:59:59+00:00"


def test_monthly_recurring_completion_is_idempotent_within_month(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Fatturare", "kind": "routine", "recurrence": {
        "frequency": "monthly", "day_of_month": 15,
    }}, "test", None)
    action = Action(type=ActionType.RECORD_ACTIVITY, item_id=item.id, data={
        "record_type": "occurrence", "period_start": "2026-09-15T18:00:00+02:00",
    }, confidence=1)
    executor.execute([action], repo.add_message("user", "Fatto"))
    executor.execute([action], repo.add_message("user", "Te l'ho già detto"))
    assert len(repo.list_activity_records(item.id)) == 1


def test_partial_monthly_activity_does_not_block_later_completion(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Fatturare", "kind": "routine", "recurrence": {
        "frequency": "monthly", "day_of_month": 15,
    }}, "test", None)
    repo.record_activity(item.id, {"record_type": "occurrence", "period_start": "2026-09-14", "is_completion": False, "note": "Preparata, manca un dato"}, "test")
    executor.execute([Action(type=ActionType.RECORD_ACTIVITY, item_id=item.id, data={
        "record_type": "occurrence", "period_start": "2026-09-15", "is_completion": True,
    }, confidence=1)], repo.add_message("user", "Ora è fatta"))
    records = repo.list_activity_records(item.id)
    assert len(records) == 2
    assert [row["is_completion"] for row in records] == [0, 1]


def test_completed_activity_closes_one_off_item_and_its_checkin(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({
        "title": "Registrare presenze",
        "kind": "commitment",
        "due_at": "2026-09-16T15:00:00+00:00",
    }, "test", None)
    repo.create_checkin(item.id, "Scaduto", "test", 1)
    assert len(repo.pending_checkins()) == 1

    executor.execute([Action(type=ActionType.RECORD_ACTIVITY, item_id=item.id, data={
        "record_type": "occurrence", "is_completion": True,
        "note": "Utente: registrato come completato.",
    }, confidence=1)], repo.add_message("user", "Fatto"))

    assert repo.get_item(item.id).status == ItemStatus.COMPLETED
    assert repo.pending_checkins() == []
    Monitor(repo).run(datetime(2026, 9, 23, 8, 0, tzinfo=UTC))
    assert repo.pending_checkins() == []


def test_partial_activity_keeps_one_off_item_active(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Preparare lezione", "kind": "commitment"}, "test", None)
    executor.execute([Action(type=ActionType.RECORD_ACTIVITY, item_id=item.id, data={
        "record_type": "occurrence", "is_completion": False, "note": "Iniziata",
    }, confidence=1)], repo.add_message("user", "Ho iniziato"))
    assert repo.get_item(item.id).status == ItemStatus.ACTIVE


def test_fixed_weekly_completion_deduplicates_day_not_week(tmp_path):
    repo, executor, _ = setup(tmp_path)
    item = repo.create_item({"title": "Richiami", "kind": "routine", "recurrence": {
        "frequency": "weekly", "days_of_week": ["tuesday", "thursday"],
    }}, "test", None)
    for when in ["2026-09-15T08:00:00+02:00", "2026-09-15T18:00:00+02:00", "2026-09-17T08:00:00+02:00"]:
        executor.execute([Action(type=ActionType.RECORD_ACTIVITY, item_id=item.id, data={
            "record_type": "occurrence", "period_start": when,
        }, confidence=1)], repo.add_message("user", "Fatto"))
    assert len(repo.list_activity_records(item.id)) == 2
