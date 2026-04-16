"""Store-related Pydantic schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StoreCreate(BaseModel):
    store_name: str = Field(..., min_length=1, max_length=200)
    api_key: str = Field(..., min_length=1)
    api_secret: str = ""
    takealot_store_id: str = Field(..., min_length=1)


class StoreUpdate(BaseModel):
    store_name: str | None = None
    store_alias: str | None = None
    auto_push_price: int | None = None
    min_price_90pct: int | None = None
    direct_ship: int | None = None
    notes: str | None = None


class StoreInfo(BaseModel):
    id: int
    store_name: str | None
    store_alias: str
    is_active: int
    offer_count: int
    takealot_store_id: str
    api_key_status: str
    api_key_display: str = ""
    auto_push_price: int
    min_price_90pct: int
    direct_ship: int
    notes: str
    last_synced_at: str | None
    created_at: str | None

    class Config:
        from_attributes = True


class StoreListResponse(BaseModel):
    ok: bool = True
    stores: list[StoreInfo]
