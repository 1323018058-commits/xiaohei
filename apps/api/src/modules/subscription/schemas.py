from datetime import datetime

from pydantic import BaseModel, Field


class TenantPlanLimits(BaseModel):
    max_users: int
    max_stores: int
    max_active_sync_tasks: int
    max_listings: int
    autobid_enabled: bool
    sync_enabled: bool
    extension_enabled: bool = False
    listing_enabled: bool = False


class TenantUsage(BaseModel):
    active_users: int
    active_stores: int
    listings: int
    active_tasks: int
    active_sync_tasks: int


class TenantRemaining(BaseModel):
    users: int
    stores: int
    active_sync_tasks: int
    listings: int


class TenantUsageResponse(BaseModel):
    tenant_id: str
    plan: str
    plan_name: str
    subscription_status: str
    trial_ends_at: datetime | None = None
    current_period_ends_at: datetime | None = None
    limits: TenantPlanLimits
    usage: TenantUsage
    remaining: TenantRemaining
    features: dict[str, bool]
    is_writable: bool
    warnings: list[str]


class RedeemActivationCardRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class RedeemActivationCardResponse(BaseModel):
    success: bool = True
    tenant_id: str
    plan: str
    subscription_status: str
    current_period_ends_at: datetime
    added_days: int
