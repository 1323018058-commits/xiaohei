from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.modules.subscription.schemas import (
    TenantPlanLimits,
    TenantRemaining,
    TenantUsage,
)


TenantPlan = Literal["starter", "growth", "scale", "war-room"]
TenantSubscriptionStatus = Literal["trialing", "active", "past_due", "paused", "cancelled"]
TenantStatus = Literal["active", "suspended", "disabled"]


class AdminFeatureFlagResponse(BaseModel):
    feature_key: str
    enabled: bool
    source: str
    updated_at: datetime


class AdminUserSummary(BaseModel):
    user_id: str
    username: str
    email: str | None
    role: str
    status: str
    expires_at: datetime | None
    subscription_status: str
    feature_flags: list[AdminFeatureFlagResponse]
    active_session_count: int


class AdminUserDetail(AdminUserSummary):
    force_password_reset: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class AdminUserListResponse(BaseModel):
    users: list[AdminUserSummary]


class TenantSummary(BaseModel):
    tenant_id: str
    slug: str
    name: str
    status: str
    plan: str
    plan_name: str
    subscription_status: str
    trial_ends_at: datetime | None = None
    current_period_ends_at: datetime | None = None
    limits: TenantPlanLimits
    usage: TenantUsage
    remaining: TenantRemaining
    created_at: datetime
    updated_at: datetime


class TenantListResponse(BaseModel):
    tenants: list[TenantSummary]


class CreateTenantRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=64, pattern="^[a-z0-9](?:[a-z0-9-]*[a-z0-9])$")
    name: str = Field(min_length=2, max_length=128)
    plan: TenantPlan = "starter"
    subscription_status: TenantSubscriptionStatus = "active"
    admin_username: str = Field(min_length=3, max_length=32, pattern="^[A-Za-z0-9_-]+$")
    admin_email: str | None = Field(default=None, max_length=255)
    admin_password: str = Field(min_length=8, max_length=128)
    reason: str = Field(default="tenant onboarding", min_length=1, max_length=500)

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("name", "admin_username", "admin_email", "admin_password", "reason", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class UpdateTenantSubscriptionRequest(BaseModel):
    plan: TenantPlan | None = None
    status: TenantSubscriptionStatus | None = None
    trial_ends_at: datetime | None = None
    current_period_ends_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class UpdateTenantRequest(BaseModel):
    status: TenantStatus
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class AuditLogResponse(BaseModel):
    audit_id: str
    request_id: str
    tenant_id: str | None
    store_id: str | None
    actor_user_id: str | None
    actor_role: str | None
    actor_display_name: str | None
    action: str
    action_label: str
    risk_level: str
    target_type: str
    target_id: str | None
    target_label: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    result: str
    error_code: str | None
    task_id: str | None
    created_at: datetime


class AuditListResponse(BaseModel):
    audits: list[AuditLogResponse]


class SystemSettingResponse(BaseModel):
    setting_key: str
    value: Any
    value_type: str
    description: str
    updated_at: datetime


class SystemComponentHealth(BaseModel):
    component: str
    status: str
    detail: str


class SystemHealthResponse(BaseModel):
    status: str
    components: list[SystemComponentHealth]
    release_switches: list[SystemSettingResponse]
    active_task_count: int
    audit_log_count: int


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern="^[A-Za-z0-9_-]+$")
    email: str | None = None
    role: str = Field(pattern="^(super_admin|tenant_admin|operator|warehouse)$")
    password: str = Field(default="temp12345", min_length=8, max_length=128)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SetExpiryRequest(BaseModel):
    expires_at: datetime | None
    reason: str = Field(min_length=1, max_length=500)


class UpdateFeatureFlagRequest(BaseModel):
    feature_key: str = Field(min_length=1, max_length=64)
    enabled: bool
    reason: str = Field(min_length=1, max_length=500)


class AdminActionResponse(BaseModel):
    success: bool = True
    user: AdminUserDetail | None = None
    active_session_count: int | None = None
    feature_flag: AdminFeatureFlagResponse | None = None


class TenantActionResponse(BaseModel):
    success: bool = True
    tenant: TenantSummary
    admin_user: AdminUserDetail | None = None
    revoked_session_count: int | None = None
