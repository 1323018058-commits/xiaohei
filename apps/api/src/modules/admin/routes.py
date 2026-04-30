from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from src.modules.auth.dependencies import require_roles

from .schemas import (
    AdminActionResponse,
    TenantActionResponse,
    TenantListResponse,
    AdminUserDetail,
    AdminUserListResponse,
    AuditListResponse,
    CreateUserRequest,
    CreateTenantRequest,
    ReasonRequest,
    SetExpiryRequest,
    SystemHealthResponse,
    UpdateTenantRequest,
    UpdateTenantSubscriptionRequest,
    UpdateFeatureFlagRequest,
)
from .service import AdminService, get_request_id

router = APIRouter(prefix="/admin/api", tags=["admin"])
service = AdminService()
AdminUser = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin")),
]


@router.get("/tenants", response_model=TenantListResponse)
def list_tenants(current_user: AdminUser):
    return service.list_tenants(current_user)


@router.post("/tenants", response_model=TenantActionResponse)
def create_tenant(
    payload: CreateTenantRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.create_tenant(
        payload.model_dump(),
        current_user,
        get_request_id(request.headers),
    )


@router.patch("/tenants/{tenant_id}/subscription", response_model=TenantActionResponse)
def update_tenant_subscription(
    tenant_id: str,
    payload: UpdateTenantSubscriptionRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.update_tenant_subscription(
        tenant_id,
        payload.model_dump(exclude_unset=True),
        current_user,
        get_request_id(request.headers),
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantActionResponse)
def update_tenant(
    tenant_id: str,
    payload: UpdateTenantRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.update_tenant(
        tenant_id,
        payload.model_dump(),
        current_user,
        get_request_id(request.headers),
    )


@router.post("/tenants/{tenant_id}/reset-admin-password", response_model=TenantActionResponse)
def reset_tenant_admin_password(
    tenant_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.reset_tenant_admin_password(
        tenant_id,
        payload.reason,
        current_user,
        get_request_id(request.headers),
    )


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    current_user: AdminUser,
    status: str | None = None,
    role: str | None = None,
    keyword: str | None = None,
):
    return service.list_users(
        actor=current_user,
        status_filter=status,
        role_filter=role,
        keyword=keyword,
    )


@router.post("/users", response_model=AdminActionResponse)
def create_user(payload: CreateUserRequest, request: Request, current_user: AdminUser):
    return service.create_user(
        payload.model_dump(),
        current_user,
        get_request_id(request.headers),
    )


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user(user_id: str, current_user: AdminUser):
    return service.get_user(user_id, current_user)


@router.post("/users/{user_id}/reset-password", response_model=AdminActionResponse)
def reset_password(
    user_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.reset_password(
        user_id,
        payload.reason,
        current_user,
        get_request_id(request.headers),
    )


@router.post("/users/{user_id}/disable", response_model=AdminActionResponse)
def disable_user(
    user_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.disable_user(
        user_id,
        payload.reason,
        current_user,
        get_request_id(request.headers),
    )


@router.post("/users/{user_id}/enable", response_model=AdminActionResponse)
def enable_user(
    user_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.enable_user(
        user_id,
        payload.reason,
        current_user,
        get_request_id(request.headers),
    )


@router.post("/users/{user_id}/set-expiry", response_model=AdminActionResponse)
def set_expiry(
    user_id: str,
    payload: SetExpiryRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.set_expiry(
        user_id,
        payload.expires_at,
        payload.reason,
        current_user,
        get_request_id(request.headers),
    )


@router.post("/users/{user_id}/feature-flags", response_model=AdminActionResponse)
def update_feature_flags(
    user_id: str,
    payload: UpdateFeatureFlagRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.update_feature_flag(
        user_id,
        payload.feature_key,
        payload.enabled,
        payload.reason,
        current_user,
        get_request_id(request.headers),
    )


@router.post("/users/{user_id}/force-logout", response_model=AdminActionResponse)
def force_logout(
    user_id: str,
    payload: ReasonRequest,
    request: Request,
    current_user: AdminUser,
):
    return service.force_logout(
        user_id,
        payload.reason,
        current_user,
        get_request_id(request.headers),
    )


@router.get("/audits", response_model=AuditListResponse)
def list_audits(current_user: AdminUser):
    return service.list_audits(current_user)


@router.get("/system/health", response_model=SystemHealthResponse)
def system_health(current_user: AdminUser):
    return service.system_health(current_user)
