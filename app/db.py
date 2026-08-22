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
    category TEXT,
    focus_position INTEGER,
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

CREATE TABLE IF NOT EXISTS activity_records (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    record_type TEXT NOT NULL CHECK(record_type IN ('occurrence', 'summary')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    count REAL,
    quantity REAL,
    unit TEXT,
    source_type TEXT NOT NULL DEFAULT 'explicit' CHECK(source_type IN ('explicit', 'evidence', 'inference')),
    confidence REAL NOT NULL DEFAULT 1,
    note TEXT,
    source_message_id TEXT,
    recorded_at TEXT NOT NULL,
    voided_at TEXT
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

CREATE TABLE IF NOT EXISTS ai_usage (
    id TEXT PRIMARY KEY,
    response_id TEXT UNIQUE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    response_status TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_status_due ON items(status, due_at);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_checkins_status ON checkins(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_activity_item_period ON activity_records(item_id, period_start, period_end);
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
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(items)").fetchall()}
            if "category" not in columns:
                connection.execute("ALTER TABLE items ADD COLUMN category TEXT")
            if "focus_position" not in columns:
                connection.execute("ALTER TABLE items ADD COLUMN focus_position INTEGER")

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
