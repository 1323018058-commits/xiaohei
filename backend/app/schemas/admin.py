"""Admin-related Pydantic schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AdminStats(BaseModel):
    total_users: int
    active_users: int
    total_keys: int
    unused_keys: int


class LicenseGenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=500)
    days: int = Field(30, ge=1)
    batch_name: str = ""


class LicenseGenerateResponse(BaseModel):
    ok: bool = True
    count: int
    keys: list[str]


class UserListItem(BaseModel):
    id: int
    username: str
    role: str
    activated: bool
    activated_until: str | None = None
    store_count: int = 0
    created_at: str | None = None


class LicenseListItem(BaseModel):
    id: int
    key: str
    days: int
    batch_name: str | None = None
    is_used: int
    used_by: int | None = None
    used_at: str | None = None
    created_at: str | None = None


class SystemHealthComponent(BaseModel):
    name: str
    level: str  # healthy, warning, critical
    detail: str = ""


class SystemHealthResponse(BaseModel):
    ok: bool = True
    metrics: dict
    components: list[SystemHealthComponent]
