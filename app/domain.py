from __future__ import annotations

from app.models import Action, ActionType, Item, ItemStatus
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
            return self.repository.create_item(action.data, "conversation", source_message_id)
        if not action.item_id or not self.repository.get_item(action.item_id):
            return None
        if action.type == ActionType.UPDATE_ITEM:
            return self.repository.update_item(action.item_id, action.data, "conversation", source_message_id)
        if action.type == ActionType.COMPLETE_ITEM:
            return self.repository.update_item(action.item_id, {"status": ItemStatus.COMPLETED.value}, "conversation", source_message_id)
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
