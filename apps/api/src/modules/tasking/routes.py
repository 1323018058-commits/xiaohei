from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from src.modules.auth.dependencies import require_roles

from .schemas import TaskActionRequest, TaskEventListResponse, TaskListResponse, TaskRunDetail
from .service import TaskService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
service = TaskService()
TaskReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin")),
]
TaskOperator = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin")),
]


@router.get("", response_model=TaskListResponse)
def list_tasks(
    current_user: TaskReader,
    status: str | None = None,
    store_id: str | None = None,
):
    return service.list_tasks(current_user, status_filter=status, store_id=store_id)


@router.get("/{task_id}", response_model=TaskRunDetail)
def get_task(task_id: str, current_user: TaskReader):
    return service.get_task(task_id, current_user)


@router.get("/{task_id}/events", response_model=TaskEventListResponse)
def list_events(task_id: str, current_user: TaskReader):
    return service.list_events(task_id, current_user)


@router.post("/{task_id}/retry-now", response_model=TaskRunDetail)
def retry_task_now(
    task_id: str,
    request: Request,
    current_user: TaskOperator,
    payload: TaskActionRequest | None = None,
):
    return service.retry_now(
        task_id,
        current_user,
        dict(request.headers),
        reason=payload.reason if payload else None,
    )


@router.post("/{task_id}/cancel", response_model=TaskRunDetail)
def cancel_task(
    task_id: str,
    request: Request,
    current_user: TaskOperator,
    payload: TaskActionRequest | None = None,
):
    return service.cancel_task(
        task_id,
        current_user,
        dict(request.headers),
        reason=payload.reason if payload else None,
    )
