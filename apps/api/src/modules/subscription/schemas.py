from datetime import datetime

from pydantic import BaseModel


class TenantPlanLimits(BaseModel):
    max_users: int
    max_stores: int
    max_active_sync_tasks: int
    max_listings: int
    autobid_enabled: bool
    sync_enabled: bool


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
    warnings: list[str]
