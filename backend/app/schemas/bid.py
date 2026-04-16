"""Bid-related Pydantic schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class BidProductItem(BaseModel):
    id: int
    offer_id: str
    store_binding_id: int | None = None
    sku: str | None = None
    plid: str | None = None
    title: str | None = None
    floor_price_zar: float = 0
    target_price_zar: float | None = None
    current_price_zar: float | None = None
    buybox_price_zar: float | None = None
    auto_bid_enabled: int = 1
    last_action: str | None = None
    last_checked_at: str | None = None
    last_updated_at: str | None = None
    notes: str | None = None
    brand: str = ""
    image_url: str = ""
    discount_rate: float = 0
    buybox_store: str = ""
    api_status: str = ""
    offer_status: str = ""

    class Config:
        from_attributes = True


class BidProductUpsert(BaseModel):
    offer_id: str = Field(..., min_length=1)
    floor_price_zar: float = 0
    sku: str = ""
    plid: str = ""
    title: str = ""
    target_price_zar: float | None = None
    current_price_zar: float | None = None
    auto_bid_enabled: int = 1
    notes: str = ""


class BidProductPatch(BaseModel):
    floor_price_zar: float | None = None
    target_price_zar: float | None = None
    auto_bid_enabled: int | None = None
    notes: str | None = None


class BidLogItem(BaseModel):
    id: int
    store_binding_id: int | None = None
    offer_id: str | None = None
    sku: str | None = None
    old_price: float | None = None
    new_price: float | None = None
    buybox_price: float | None = None
    action: str | None = None
    reason: str | None = None
    created_at: str | None = None


class BidEngineStatus(BaseModel):
    running: bool = False
    last_run: str | None = None
    next_run: str | None = None
    last_raised: int = 0
    last_lowered: int = 0
    last_floored: int = 0
    last_unchanged: int = 0
    last_errors: int = 0
    total_checked: int = 0
    total_updated: int = 0
    consecutive_error_cycles: int = 0
    total_products: int = 0
    active_products: int = 0
    paused_products: int = 0


class BidInsights(BaseModel):
    total_products: int = 0
    active_bid_products: int = 0
    paused_bid_products: int = 0
    floor_coverage_rate: float = 0
    at_floor_products: int = 0
    api_health_rate: float = 0
    avg_price_gap: float = 0
    recent_24h_adjustments: int = 0
    recent_24h_failures: int = 0
