from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.modules.auth.dependencies import CurrentUser

from .dependencies import ExtensionUser

from .schemas import (
    ExtensionAuthRequest,
    ExtensionAuthResponse,
    ExtensionListNowRequest,
    ExtensionListNowResponse,
    ExtensionListNowTaskStatusResponse,
    ExtensionLoginRequest,
    ExtensionLoginResponse,
    ExtensionProfileResponse,
    ProfitPreviewRequest,
    ProfitPreviewResponse,
    ProtectedFloorRequest,
    ProtectedFloorResponse,
)
from .service import ExtensionService

router = APIRouter(prefix="/api/extension", tags=["extension"])
service = ExtensionService()


@router.post("/login", response_model=ExtensionLoginResponse)
def extension_login(payload: ExtensionLoginRequest):
    return service.login_with_credentials(
        username=payload.username,
        password=payload.password,
        store_id=payload.store_id,
    )


@router.post("/auth", response_model=ExtensionAuthResponse)
def extension_auth(
    payload: ExtensionAuthRequest,
    current_user: CurrentUser,
):
    if current_user["role"] not in {"super_admin", "tenant_admin", "operator"}:
        raise HTTPException(status_code=403, detail="权限不足")
    return service.issue_auth_token(
        actor=current_user,
        store_id=payload.store_id,
    )


@router.get("/profile", response_model=ExtensionProfileResponse)
def extension_profile(current_user: ExtensionUser):
    return service.profile(current_user)


@router.post("/profit-preview", response_model=ProfitPreviewResponse)
def profit_preview(
    payload: ProfitPreviewRequest,
    current_user: ExtensionUser,
):
    return service.profit_preview(payload=payload, actor=current_user)


@router.post("/protected-floor", response_model=ProtectedFloorResponse)
def protected_floor(
    payload: ProtectedFloorRequest,
    request: Request,
    current_user: ExtensionUser,
):
    return service.save_protected_floor(
        payload=payload,
        actor=current_user,
        request_headers=request.headers,
    )


@router.post("/list-now", response_model=ExtensionListNowResponse)
def list_now(
    payload: ExtensionListNowRequest,
    request: Request,
    current_user: ExtensionUser,
):
    return service.create_list_now_task(
        payload=payload,
        actor=current_user,
        request_headers=request.headers,
    )


@router.get("/list-now/{task_id}", response_model=ExtensionListNowTaskStatusResponse)
def list_now_status(task_id: str, current_user: ExtensionUser):
    return service.get_list_now_status(
        task_id=task_id,
        actor=current_user,
    )


@router.post("/list-now/{task_id}/refresh-status", response_model=ExtensionListNowTaskStatusResponse)
def refresh_list_now_status(task_id: str, current_user: ExtensionUser):
    return service.refresh_list_now_status(
        task_id=task_id,
        actor=current_user,
    )
