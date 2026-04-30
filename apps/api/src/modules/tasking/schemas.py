from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TaskRunSummary(BaseModel):
    task_id: str
    task_type: str
    domain: str
    status: str
    stage: str
    progress_percent: float | None
    tenant_id: str | None
    store_id: str | None
    target_type: str | None
    target_id: str | None
    request_id: str
    error_code: str | None
    error_msg: str | None
    attempt_count: int
    max_retries: int
    retryable: bool
    next_retry_at: datetime | None
    ui_meta: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class TaskRunDetail(TaskRunSummary):
    progress_current: int | None
    progress_total: int | None
    priority: str
    queue_name: str
    actor_user_id: str | None
    actor_role: str | None
    source_type: str
    lease_owner: str | None
    lease_expires_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    last_heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
    cancel_reason: str | None
    error_details: dict[str, Any] | None
    recent_events: list["TaskEventResponse"]


class TaskEventResponse(BaseModel):
    event_id: str
    task_id: str
    event_type: str
    from_status: str | None
    to_status: str | None
    stage: str | None
    message: str
    details: dict[str, Any] | None
    source: str
    source_id: str | None
    created_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[TaskRunSummary]


class TaskEventListResponse(BaseModel):
    events: list[TaskEventResponse]


class TaskActionRequest(BaseModel):
    reason: str | None = None
