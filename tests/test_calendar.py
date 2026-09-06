from datetime import UTC, datetime, timedelta

from app.calendar import GoogleCalendar
from app.db import Database


def calendar(tmp_path):
    db = Database(tmp_path / "calendar.db")
    db.initialize()
    return GoogleCalendar(db, "client-id", "client-secret", "https://example.test/callback")


def test_oauth_url_is_read_only_and_keeps_state(tmp_path):
    service = calendar(tmp_path)
    url = service.authorization_url()
    assert "calendar.readonly" in url
    assert "access_type=offline" in url
    assert service._get("oauth_state")


def test_calendar_cache_recognizes_coaching_and_busy_events(tmp_path):
    service = calendar(tmp_path)
    service._store_event({
        "id": "coaching-1", "summary": "coaching - MiPu", "status": "confirmed",
        "start": {"dateTime": "2026-09-07T09:00:00+02:00"},
        "end": {"dateTime": "2026-09-07T10:00:00+02:00"},
        "updated": "2026-09-06T10:00:00Z", "etag": "one",
    })
    events = service.events_between(datetime(2026, 9, 7, tzinfo=UTC), datetime(2026, 9, 8, tzinfo=UTC))
    assert len(events) == 1
    assert events[0]["category"] == "coaching"
    assert events[0]["category_code"] == "MiPu"


def test_transparent_and_cancelled_events_do_not_block_time(tmp_path):
    service = calendar(tmp_path)
    base = {"start": {"dateTime": "2026-09-07T09:00:00+02:00"}, "end": {"dateTime": "2026-09-07T10:00:00+02:00"}}
    service._store_event({**base, "id": "free", "summary": "Promemoria", "status": "confirmed", "transparency": "transparent"})
    service._store_event({**base, "id": "gone", "summary": "Annullato", "status": "cancelled"})
    events = service.events_between(datetime.now(UTC) - timedelta(days=30), datetime.now(UTC) + timedelta(days=30))
    assert events == []
    informational = service.events_between(datetime.now(UTC) - timedelta(days=30), datetime.now(UTC) + timedelta(days=30), include_transparent=True)
    assert len(informational) == 1
    assert informational[0]["blocks_time"] is False


def test_personal_free_time_and_gym_are_protected(tmp_path):
    service = calendar(tmp_path)
    assert service._classify("Simo - libero") == ("protected_personal", None)
    assert service._classify("palestra") == ("protected_personal", None)
    assert service._classify("PALESTRA") == ("protected_personal", None)


def test_planning_context_converts_utc_to_local_timezone(tmp_path):
    service = calendar(tmp_path)
    service._store_event({
        "id": "local-time", "summary": "coaching - MiPu", "status": "confirmed",
        "start": {"dateTime": "2026-09-07T07:00:00Z"},
        "end": {"dateTime": "2026-09-07T08:00:00Z"},
    })
    events = service.planning_context(datetime(2026, 9, 7, tzinfo=UTC), datetime(2026, 9, 8, tzinfo=UTC), "Europe/Zurich")
    assert events[0]["starts_at"] == "2026-09-07T09:00:00+02:00"
    assert events[0]["ends_at"] == "2026-09-07T10:00:00+02:00"


def test_prune_removes_calendar_events_beyond_operational_window(tmp_path):
    service = calendar(tmp_path)
    service._set("sync_time_max", "2026-12-05T00:00:00+00:00")
    service._store_event({
        "id": "too-far", "summary": "Ricorrenza lontana", "status": "confirmed",
        "start": {"dateTime": "2056-01-01T09:00:00+01:00"},
        "end": {"dateTime": "2056-01-01T10:00:00+01:00"},
    })
    service._prune()
    with service.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == 0
