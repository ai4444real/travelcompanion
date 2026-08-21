from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ItemStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    SUSPENDED = "suspended"
    ABANDONED = "abandoned"
    WAITING = "waiting"
    UNPLANNED = "unplanned"


class ItemKind(StrEnum):
    TEMA = "tema"
    LEGACY_THEME = "theme"
    COMMITMENT = "commitment"
    ROUTINE = "routine"
    INTRODUCTION = "introduction"
    POSSIBILITY = "possibility"


class ActionType(StrEnum):
    CREATE_ITEM = "create_item"
    UPDATE_ITEM = "update_item"
    COMPLETE_ITEM = "complete_item"
    SUSPEND_ITEM = "suspend_item"
    ABANDON_ITEM = "abandon_item"
    REORDER_ITEM = "reorder_item"
    ADD_RELATION = "add_relation"
    UPDATE_ESTIMATE = "update_estimate"
    RECORD_PROGRESS = "record_progress"
    RECORD_USER_ASSESSMENT = "record_user_assessment"
    RECORD_ACTIVITY = "record_activity"
    REQUEST_CLARIFICATION = "request_clarification"
    SEND_CHECKIN = "send_checkin"
    NO_ACTION = "no_action"


class Item(BaseModel):
    id: str
    title: str
    description: str | None = None
    category: str | None = None
    kind: ItemKind = ItemKind.POSSIBILITY
    status: ItemStatus = ItemStatus.ACTIVE
    due_at: datetime | None = None
    recurrence: dict[str, Any] | None = None
    target_quantity: float | None = None
    target_unit: str | None = None
    estimate_minutes: int | None = None
    progress_value: float | None = None
    progress_total: float | None = None
    importance: str | None = None
    consequences: str | None = None
    flexibility: str | None = None
    motivation: str | None = None
    context: str | None = None
    user_assessment: str | None = None
    confidence: float = 1.0
    checkin_cooldown_days: int = 3
    last_checked_at: datetime | None = None
    suspended_until: datetime | None = None
    created_at: datetime
    updated_at: datetime


class Action(BaseModel):
    type: ActionType
    item_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    rationale: str | None = None


class Interpretation(BaseModel):
    reply: str
    actions: list[Action] = Field(default_factory=list)
    needs_confirmation: bool = False
    provider_usage: dict[str, Any] | None = Field(default=None, exclude=True)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    reply: str
    actions: list[Action]
    changed_items: list[Item] = Field(default_factory=list)


class ItemPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    kind: ItemKind | None = None
    status: ItemStatus | None = None
    due_at: datetime | None = None
    recurrence: dict[str, Any] | None = None
    target_quantity: float | None = None
    target_unit: str | None = None
    estimate_minutes: int | None = None
    progress_value: float | None = None
    progress_total: float | None = None
    importance: str | None = None
    consequences: str | None = None
    flexibility: str | None = None
    motivation: str | None = None
    user_assessment: str | None = None
    checkin_cooldown_days: int | None = None
    suspended_until: datetime | None = None


class ActivityRecord(BaseModel):
    id: str
    item_id: str
    record_type: str
    period_start: datetime
    period_end: datetime
    count: float | None = None
    quantity: float | None = None
    unit: str | None = None
    source_type: str = "explicit"
    confidence: float = 1.0
    note: str | None = None
    source_message_id: str | None = None
    recorded_at: datetime
    voided_at: datetime | None = None
