from __future__ import annotations

from app.models import Action, ActionType, Item, ItemKind, ItemStatus
from app.repository import Repository


class ActionExecutor:
    """Validates and applies model proposals; the model never writes directly."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def execute(self, actions: list[Action], source_message_id: str) -> list[Item]:
        changed: dict[str, Item] = {}
        for action in actions:
            if action.confidence < 0.65 and action.type not in {ActionType.REQUEST_CLARIFICATION, ActionType.NO_ACTION}:
                continue
            item = self._execute_one(action, source_message_id)
            if item:
                changed[item.id] = item
        return list(changed.values())

    def _execute_one(self, action: Action, source_message_id: str) -> Item | None:
        if action.type in {ActionType.NO_ACTION, ActionType.REQUEST_CLARIFICATION, ActionType.SEND_CHECKIN}:
            return None
        if action.type == ActionType.CREATE_ITEM:
            if not action.data.get("title"):
                return None
            return self.repository.create_item(self._normalize_item_data(action.data), "conversation", source_message_id)
        if not action.item_id or not self.repository.get_item(action.item_id):
            return None
        if action.type == ActionType.UPDATE_ITEM:
            return self.repository.update_item(action.item_id, action.data, "conversation", source_message_id)
        if action.type == ActionType.COMPLETE_ITEM:
            item = self.repository.update_item(action.item_id, {"status": ItemStatus.COMPLETED.value}, "conversation", source_message_id)
            self.repository.resolve_pending_checkins(action.item_id)
            return item
        if action.type == ActionType.SUSPEND_ITEM:
            changes = {"status": ItemStatus.SUSPENDED.value}
            if action.data.get("suspended_until"):
                changes["suspended_until"] = action.data["suspended_until"]
            return self.repository.update_item(action.item_id, changes, "conversation", source_message_id)
        if action.type == ActionType.ABANDON_ITEM:
            return self.repository.update_item(action.item_id, {"status": ItemStatus.ABANDONED.value}, "conversation", source_message_id)
        if action.type == ActionType.UPDATE_ESTIMATE:
            return self.repository.update_item(action.item_id, {"estimate_minutes": action.data.get("estimate_minutes")}, "conversation", source_message_id)
        if action.type == ActionType.RECORD_PROGRESS:
            return self.repository.record_progress(action.item_id, action.data.get("value"), action.data.get("total"), action.data.get("unit"), action.data.get("note"), source_message_id)
        if action.type == ActionType.RECORD_USER_ASSESSMENT:
            return self.repository.update_item(action.item_id, {"user_assessment": action.data.get("assessment")}, "conversation", source_message_id)
        if action.type == ActionType.RECORD_ACTIVITY:
            self.repository.record_activity(action.item_id, action.data, source_message_id)
            return self.repository.get_item(action.item_id)
        if action.type == ActionType.REORDER_ITEM:
            target_id = action.data.get("target_item_id")
            relation = action.data.get("relation", "after")
            if target_id and self.repository.get_item(target_id):
                self.repository.add_relation(action.item_id, target_id, relation, "conversation", source_message_id)
            return self.repository.get_item(action.item_id)
        if action.type == ActionType.ADD_RELATION:
            target_id = action.data.get("target_item_id")
            if target_id and self.repository.get_item(target_id):
                self.repository.add_relation(action.item_id, target_id, action.data.get("relation_type", "related"), "conversation", source_message_id)
            return self.repository.get_item(action.item_id)
        return None

    @staticmethod
    def _normalize_item_data(data: dict) -> dict:
        """Keep provider vocabulary outside the canonical domain model."""
        normalized = dict(data)
        status_aliases = {
            "open": ItemStatus.ACTIVE.value,
            "paused": ItemStatus.SUSPENDED.value,
            "done": ItemStatus.COMPLETED.value,
            "pending": ItemStatus.WAITING.value,
            "backlog": ItemStatus.UNPLANNED.value,
        }
        kind_aliases = {
            "theme": ItemKind.TEMA.value,
            "tema": ItemKind.TEMA.value,
            "topic": ItemKind.TEMA.value,
            "project": ItemKind.TEMA.value,
            "task": ItemKind.COMMITMENT.value,
            "goal": ItemKind.COMMITMENT.value,
            "habit": ItemKind.ROUTINE.value,
            "change": ItemKind.INTRODUCTION.value,
            "backlog": ItemKind.POSSIBILITY.value,
            "book": ItemKind.POSSIBILITY.value,
            "libro": ItemKind.POSSIBILITY.value,
        }
        if "due_at" not in normalized and normalized.get("due_date"):
            normalized["due_at"] = f"{normalized.pop('due_date')}T23:59:00+00:00"
        if "context" not in normalized and normalized.get("note"):
            normalized["context"] = normalized.pop("note")
        status = str(normalized.get("status", ItemStatus.ACTIVE.value)).lower()
        kind = str(normalized.get("kind", ItemKind.POSSIBILITY.value)).lower()
        valid_statuses = {entry.value for entry in ItemStatus}
        valid_kinds = {entry.value for entry in ItemKind}
        normalized["status"] = status_aliases.get(status, status if status in valid_statuses else ItemStatus.ACTIVE.value)
        normalized["kind"] = kind_aliases.get(kind, kind if kind in valid_kinds else ItemKind.POSSIBILITY.value)
        return normalized
