from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.db import Database, json_dump, new_id, now_iso, row_to_item
from app.models import Item, ItemKind, ItemStatus


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def list_items(self, statuses: list[str] | None = None) -> list[Item]:
        sql = "SELECT * FROM items"
        params: list[Any] = []
        if statuses:
            sql += f" WHERE status IN ({','.join('?' for _ in statuses)})"
            params.extend(statuses)
        sql += " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'waiting' THEN 1 WHEN 'unplanned' THEN 2 ELSE 3 END, due_at IS NULL, due_at, updated_at DESC"
        with self.db.connect() as conn:
            return [row_to_item(row) for row in conn.execute(sql, params).fetchall()]

    def get_item(self, item_id: str) -> Item | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return row_to_item(row) if row else None

    def find_item(self, reference: str) -> Item | None:
        normalized = reference.strip().lower()
        items = self.list_items()
        exact = next((item for item in items if item.title.lower() == normalized), None)
        if exact:
            return exact
        candidates = [item for item in items if normalized in item.title.lower() or item.title.lower() in normalized]
        return candidates[0] if len(candidates) == 1 else None

    def create_item(self, data: dict[str, Any], origin: str, source_message_id: str | None) -> Item:
        timestamp = now_iso()
        item_id = data.get("id") or new_id("item")
        fields = {
            "id": item_id,
            "title": data["title"].strip(),
            "description": data.get("description"),
            "category": data.get("category"),
            "kind": data.get("kind", ItemKind.POSSIBILITY.value),
            "status": data.get("status", ItemStatus.ACTIVE.value),
            "due_at": data.get("due_at"),
            "recurrence_json": json_dump(data["recurrence"]) if data.get("recurrence") else None,
            "target_quantity": data.get("target_quantity"),
            "target_unit": data.get("target_unit"),
            "estimate_minutes": data.get("estimate_minutes"),
            "progress_value": data.get("progress_value"),
            "progress_total": data.get("progress_total"),
            "importance": data.get("importance"),
            "consequences": data.get("consequences"),
            "flexibility": data.get("flexibility"),
            "motivation": data.get("motivation"),
            "context": data.get("context"),
            "user_assessment": data.get("user_assessment"),
            "confidence": data.get("confidence", 1.0),
            "checkin_cooldown_days": data.get("checkin_cooldown_days", 3),
            "last_checked_at": data.get("last_checked_at"),
            "suspended_until": data.get("suspended_until"),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        with self.db.connect() as conn:
            conn.execute(f"INSERT INTO items ({columns}) VALUES ({placeholders})", tuple(fields.values()))
            self._audit(conn, "item", item_id, "create", origin, source_message_id, None, fields)
        return self.get_item(item_id)  # type: ignore[return-value]

    def update_item(self, item_id: str, changes: dict[str, Any], origin: str, source_message_id: str | None) -> Item:
        before = self.get_item(item_id)
        if not before:
            raise KeyError(item_id)
        allowed = set(Item.model_fields) - {"id", "created_at", "updated_at"}
        clean = {key: value for key, value in changes.items() if key in allowed}
        if "recurrence" in clean:
            recurrence = clean.pop("recurrence")
            clean["recurrence_json"] = json_dump(recurrence) if recurrence else None
        clean["updated_at"] = now_iso()
        assignments = ", ".join(f"{key}=?" for key in clean)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE items SET {assignments} WHERE id=?", (*clean.values(), item_id))
            after_row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            after = row_to_item(after_row).model_dump(mode="json")
            self._audit(conn, "item", item_id, "update", origin, source_message_id, before.model_dump(mode="json"), after)
        return self.get_item(item_id)  # type: ignore[return-value]

    def delete_item(self, item_id: str, origin: str = "manual") -> None:
        before = self.get_item(item_id)
        if not before:
            raise KeyError(item_id)
        with self.db.connect() as conn:
            self._audit(conn, "item", item_id, "delete", origin, None, before.model_dump(mode="json"), None)
            conn.execute("DELETE FROM items WHERE id=?", (item_id,))

    def add_relation(self, source_id: str, target_id: str, relation_type: str, origin: str, source_message_id: str | None) -> None:
        relation_id = new_id("rel")
        data = {"source_item_id": source_id, "target_item_id": target_id, "relation_type": relation_type}
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO relations(id, source_item_id, target_item_id, relation_type, created_at) VALUES(?,?,?,?,?)",
                (relation_id, source_id, target_id, relation_type, now_iso()),
            )
            self._audit(conn, "relation", relation_id, "create", origin, source_message_id, None, data)

    def list_relations(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM relations ORDER BY created_at").fetchall()]

    def record_progress(self, item_id: str, value: float | None, total: float | None, unit: str | None, note: str | None, source_message_id: str | None) -> Item:
        event_id = new_id("progress")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO progress_events(id,item_id,value,total,unit,note,happened_at,source_message_id) VALUES(?,?,?,?,?,?,?,?)",
                (event_id, item_id, value, total, unit, note, now_iso(), source_message_id),
            )
        changes = {key: val for key, val in {"progress_value": value, "progress_total": total}.items() if val is not None}
        return self.update_item(item_id, changes, "conversation", source_message_id)

    def record_activity(self, item_id: str, data: dict[str, Any], source_message_id: str | None) -> dict[str, Any]:
        if not self.get_item(item_id):
            raise KeyError(item_id)
        record_type = data.get("record_type", "occurrence")
        if record_type not in {"occurrence", "summary"}:
            record_type = "occurrence"
        source_type = data.get("source_type", "explicit")
        if source_type not in {"explicit", "evidence", "inference"}:
            source_type = "explicit"
        period_start = data.get("period_start") or now_iso()
        period_end = data.get("period_end") or period_start
        record_id = new_id("activity")
        values = {
            "id": record_id, "item_id": item_id, "record_type": record_type,
            "period_start": period_start, "period_end": period_end,
            "count": data.get("count", 1 if record_type == "occurrence" else None),
            "quantity": data.get("quantity"), "unit": data.get("unit"),
            "source_type": source_type, "confidence": float(data.get("confidence", 1.0)),
            "note": data.get("note"), "source_message_id": source_message_id,
            "recorded_at": now_iso(), "voided_at": None,
        }
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO activity_records(id,item_id,record_type,period_start,period_end,count,quantity,unit,source_type,confidence,note,source_message_id,recorded_at,voided_at)
                VALUES(:id,:item_id,:record_type,:period_start,:period_end,:count,:quantity,:unit,:source_type,:confidence,:note,:source_message_id,:recorded_at,:voided_at)""",
                values,
            )
            self._audit(conn, "activity_record", record_id, "create", "conversation", source_message_id, None, values)
        return values

    def list_activity_records(self, item_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM activity_records WHERE voided_at IS NULL"
        params: list[Any] = []
        if item_id:
            sql += " AND item_id=?"
            params.append(item_id)
        sql += " ORDER BY period_start, recorded_at"
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def add_message(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> str:
        message_id = new_id("msg")
        with self.db.connect() as conn:
            conn.execute("INSERT INTO messages(id,role,content,created_at,metadata_json) VALUES(?,?,?,?,?)", (message_id, role, content, now_iso(), json_dump(metadata) if metadata else None))
        return message_id

    def recent_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def create_checkin(self, item_id: str | None, message: str, reason: str, score: float) -> dict[str, Any]:
        checkin_id = new_id("checkin")
        timestamp = now_iso()
        with self.db.connect() as conn:
            conn.execute("INSERT INTO checkins(id,item_id,message,reason,score,status,created_at) VALUES(?,?,?,?,?,'pending',?)", (checkin_id, item_id, message, reason, score, timestamp))
        return {"id": checkin_id, "item_id": item_id, "message": message, "reason": reason, "score": score, "status": "pending", "created_at": timestamp}

    def pending_checkins(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM checkins WHERE status='pending' ORDER BY score DESC, created_at").fetchall()]

    def deliver_checkin(self, checkin_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE checkins SET status='delivered', delivered_at=? WHERE id=?", (now_iso(), checkin_id))

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]

    def record_ai_usage(self, usage: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO ai_usage(
                    id,response_id,provider,model,input_tokens,cached_input_tokens,
                    output_tokens,total_tokens,estimated_cost_usd,response_status,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id("usage"), usage.get("response_id"), usage.get("provider", "unknown"),
                    usage.get("model", "unknown"), int(usage.get("input_tokens", 0)),
                    int(usage.get("cached_input_tokens", 0)), int(usage.get("output_tokens", 0)),
                    int(usage.get("total_tokens", 0)), float(usage.get("estimated_cost_usd", 0)),
                    usage.get("response_status"), now_iso(),
                ),
            )

    def ai_usage_summary(self, monthly_budget_usd: float) -> dict[str, Any]:
        month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS request_count, COALESCE(SUM(input_tokens),0) AS input_tokens,
                    COALESCE(SUM(cached_input_tokens),0) AS cached_input_tokens,
                    COALESCE(SUM(output_tokens),0) AS output_tokens,
                    COALESCE(SUM(total_tokens),0) AS total_tokens,
                    COALESCE(SUM(estimated_cost_usd),0) AS estimated_cost_usd
                    FROM ai_usage WHERE created_at >= ?""",
                (month_start,),
            ).fetchone()
        result = dict(row)
        result["estimated_cost_usd"] = round(float(result["estimated_cost_usd"]), 8)
        result["monthly_budget_usd"] = monthly_budget_usd
        result["remaining_usd"] = round(max(0, monthly_budget_usd - result["estimated_cost_usd"]), 8)
        result["blocked"] = result["estimated_cost_usd"] >= monthly_budget_usd
        result["month_start"] = month_start
        return result

    def raw_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Developer inspection view. Table names are deliberately hard-coded."""
        tables = {
            "items": "created_at, id",
            "relations": "created_at, id",
            "progress_events": "happened_at, id",
            "activity_records": "period_start, recorded_at, id",
            "messages": "created_at, id",
            "checkins": "created_at, id",
            "audit_log": "created_at, id",
            "ai_usage": "created_at, id",
        }
        snapshot: dict[str, list[dict[str, Any]]] = {}
        with self.db.connect() as conn:
            for table, order_by in tables.items():
                snapshot[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()]
        return snapshot

    @staticmethod
    def _audit(conn: Any, entity_type: str, entity_id: str, action: str, origin: str, source_message_id: str | None, before: Any, after: Any) -> None:
        conn.execute(
            "INSERT INTO audit_log(id,entity_type,entity_id,action,origin,source_message_id,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (new_id("audit"), entity_type, entity_id, action, origin, source_message_id, json_dump(before) if before is not None else None, json_dump(after) if after is not None else None, now_iso()),
        )
