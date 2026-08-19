from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from app.models import Item


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    due_at TEXT,
    recurrence_json TEXT,
    target_quantity REAL,
    target_unit TEXT,
    estimate_minutes INTEGER,
    progress_value REAL,
    progress_total REAL,
    importance TEXT,
    consequences TEXT,
    flexibility TEXT,
    motivation TEXT,
    context TEXT,
    user_assessment TEXT,
    confidence REAL NOT NULL DEFAULT 1,
    checkin_cooldown_days INTEGER NOT NULL DEFAULT 3,
    last_checked_at TEXT,
    suspended_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    target_item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_item_id, target_item_id, relation_type)
);

CREATE TABLE IF NOT EXISTS progress_events (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    value REAL,
    total REAL,
    unit TEXT,
    note TEXT,
    happened_at TEXT NOT NULL,
    source_message_id TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS checkins (
    id TEXT PRIMARY KEY,
    item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
    message TEXT NOT NULL,
    reason TEXT NOT NULL,
    score REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    origin TEXT NOT NULL,
    source_message_id TEXT,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_status_due ON items(status, due_at);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_checkins_status ON checkins(status, created_at);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


JSON_FIELDS = {"recurrence": "recurrence_json"}


def row_to_item(row: sqlite3.Row | dict[str, Any]) -> Item:
    data = dict(row)
    data["recurrence"] = json.loads(data.pop("recurrence_json")) if data.get("recurrence_json") else None
    return Item.model_validate(data)


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
