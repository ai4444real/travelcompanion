from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.db import Database, now_iso


class GoogleCalendar:
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

    def __init__(self, db: Database, client_id: str | None, client_secret: str | None, redirect_uri: str):
        self.db = db
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._lock = asyncio.Lock()

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def connected(self) -> bool:
        return bool(self._get("refresh_token"))

    def authorization_url(self) -> str:
        if not self.configured():
            raise RuntimeError("Credenziali Google non configurate")
        state = secrets.token_urlsafe(32)
        self._set("oauth_state", state)
        return f"{self.AUTH_URL}?{urlencode({'client_id': self.client_id, 'redirect_uri': self.redirect_uri, 'response_type': 'code', 'scope': self.SCOPE, 'access_type': 'offline', 'prompt': 'consent', 'state': state})}"

    async def exchange_code(self, code: str, state: str) -> None:
        if not state or not secrets.compare_digest(state, self._get("oauth_state") or ""):
            raise ValueError("Stato OAuth non valido")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.TOKEN_URL, data={
                "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri, "grant_type": "authorization_code",
            })
            response.raise_for_status()
        tokens = response.json()
        if tokens.get("refresh_token"):
            self._set("refresh_token", tokens["refresh_token"])
        self._set_access_token(tokens)
        self._delete("oauth_state")

    async def sync(self) -> dict[str, Any]:
        if not self.connected():
            return self.status()
        async with self._lock:
            try:
                access_token = await self._access_token()
                changed = await self._sync_events(access_token)
                self._set("last_sync_at", now_iso())
                self._delete("last_error")
                self._prune()
                self._reclassify_cached_events()
                result = self.status()
                result["changed"] = changed
                return result
            except Exception as exc:
                self._set("last_error", str(exc)[:500])
                result = self.status()
                result["ok"] = False
                return result

    def status(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        upcoming = self.events_between(now - timedelta(days=1), now + timedelta(days=14)) if self.connected() else []
        return {
            "configured": self.configured(), "connected": self.connected(),
            "last_sync_at": self._get("last_sync_at"), "last_error": self._get("last_error"),
            "event_count": len(upcoming), "window_end": (now + timedelta(days=14)).isoformat(),
            "ok": self.connected() and not self._get("last_error"),
        }

    def events_between(self, start: datetime, end: datetime, include_transparent: bool = False) -> list[dict[str, Any]]:
        transparency_filter = "" if include_transparent else "AND COALESCE(transparency,'opaque')!='transparent'"
        with self.db.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                f"""SELECT * FROM calendar_events
                   WHERE event_status!='cancelled' {transparency_filter}
                     AND ends_at>? AND starts_at<? ORDER BY starts_at""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()]
        for row in rows:
            row["blocks_time"] = row.get("transparency") != "transparent"
            row["protected_time"] = row.get("category") == "protected_personal"
        return rows

    async def _access_token(self) -> str:
        token = self._get("access_token")
        expires = self._get("access_token_expires_at")
        if token and expires and datetime.fromisoformat(expires) > datetime.now(UTC) + timedelta(minutes=1):
            return token
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.TOKEN_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self._get("refresh_token"), "grant_type": "refresh_token",
            })
            response.raise_for_status()
        tokens = response.json()
        self._set_access_token(tokens)
        return tokens["access_token"]

    def _set_access_token(self, tokens: dict[str, Any]) -> None:
        self._set("access_token", tokens["access_token"])
        expires = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
        self._set("access_token_expires_at", expires.isoformat())

    async def _sync_events(self, access_token: str) -> int:
        sync_token = self._get("sync_token")
        window_created_at = self._get("sync_window_created_at")
        window_expired = not window_created_at or datetime.fromisoformat(window_created_at) < datetime.now(UTC) - timedelta(days=30)
        # Older versions created an unbounded sync token, which expanded recurring
        # events decades into the future. Reset it once, and periodically roll the window.
        if sync_token and (not self._get("sync_time_max") or window_expired):
            self._delete("sync_token")
            sync_token = None
        params: dict[str, Any] = {"singleEvents": "true", "showDeleted": "true", "maxResults": 2500}
        if sync_token:
            params["syncToken"] = sync_token
        else:
            time_min = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            time_max = (datetime.now(UTC) + timedelta(days=90)).isoformat()
            self._set("sync_time_min", time_min)
            self._set("sync_time_max", time_max)
            self._set("sync_window_created_at", now_iso())
            params["timeMin"] = time_min
            params["timeMax"] = time_max
        changed = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                response = await client.get(self.EVENTS_URL, params=params, headers={"Authorization": f"Bearer {access_token}"})
                if response.status_code == 410 and sync_token:
                    self._delete("sync_token")
                    return await self._sync_events(access_token)
                response.raise_for_status()
                payload = response.json()
                for event in payload.get("items", []):
                    self._store_event(event)
                    changed += 1
                if payload.get("nextPageToken"):
                    params["pageToken"] = payload["nextPageToken"]
                else:
                    if payload.get("nextSyncToken"):
                        self._set("sync_token", payload["nextSyncToken"])
                    break
        return changed

    def _store_event(self, event: dict[str, Any]) -> None:
        event_id = event.get("id")
        if not event_id:
            return
        if event.get("status") == "cancelled":
            with self.db.connect() as conn:
                conn.execute("DELETE FROM calendar_events WHERE event_id=?", (event_id,))
            return
        start_data, end_data = event.get("start", {}), event.get("end", {})
        starts_at = self._canonical_event_time(start_data.get("dateTime") or start_data.get("date"))
        ends_at = self._canonical_event_time(end_data.get("dateTime") or end_data.get("date"))
        if not starts_at or not ends_at:
            return
        summary = event.get("summary") or "(senza titolo)"
        category, category_code = self._classify(summary)
        coaching = category == "coaching"
        category_code = summary.split("-", 1)[1].strip() if coaching and "-" in summary else None
        values = (event_id, "primary", summary, starts_at, ends_at, int("date" in start_data),
                  event.get("transparency"), event.get("status", "confirmed"), event.get("eventType"),
                  category, category_code, event.get("updated"), event.get("etag"), now_iso())
        with self.db.connect() as conn:
            conn.execute("""INSERT INTO calendar_events(event_id,calendar_id,summary,starts_at,ends_at,all_day,transparency,event_status,event_type,category,category_code,google_updated_at,etag,cached_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET
                summary=excluded.summary,starts_at=excluded.starts_at,ends_at=excluded.ends_at,all_day=excluded.all_day,
                transparency=excluded.transparency,event_status=excluded.event_status,event_type=excluded.event_type,
                category=excluded.category,category_code=excluded.category_code,google_updated_at=excluded.google_updated_at,
                etag=excluded.etag,cached_at=excluded.cached_at""", values)

    def _prune(self) -> None:
        cutoff = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        ceiling = self._get("sync_time_max") or (datetime.now(UTC) + timedelta(days=90)).isoformat()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM calendar_events WHERE ends_at<?", (cutoff,))
            conn.execute("DELETE FROM calendar_events WHERE starts_at>?", (ceiling,))

    @staticmethod
    def _classify(summary: str) -> tuple[str | None, str | None]:
        normalized = summary.strip().casefold()
        if normalized.startswith("coaching - "):
            return "coaching", summary.split("-", 1)[1].strip()
        if normalized in {"simo - libero", "palestra"}:
            return "protected_personal", None
        return None, None

    def _reclassify_cached_events(self) -> None:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT event_id,summary FROM calendar_events").fetchall()
            for row in rows:
                category, code = self._classify(row["summary"] or "")
                conn.execute("UPDATE calendar_events SET category=?,category_code=? WHERE event_id=?", (category, code, row["event_id"]))

    @staticmethod
    def _canonical_event_time(value: str | None) -> str | None:
        if not value or len(value) == 10:
            return value
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()

    def _get(self, key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM calendar_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set(self, key: str, value: str) -> None:
        with self.db.connect() as conn:
            conn.execute("""INSERT INTO calendar_settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""", (key, value, now_iso()))

    def _delete(self, key: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM calendar_settings WHERE key=?", (key,))
