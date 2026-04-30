from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


StrategyType = Literal["manual", "guarded", "aggressive"]


class BiddingRuleResponse(BaseModel):
    rule_id: str
    store_id: str
    sku: str
    listing_id: str | None
    floor_price: float | None
    strategy_type: str
    is_active: bool
    next_check_at: datetime | None = None
    buybox_fetch_fail_count: int = 0
    buybox_last_error: str = ""
    buybox_last_success_at: datetime | None = None
    buybox_next_retry_at: datetime | None = None
    buybox_status: str = "idle"
    repricing_blocked_reason: str = ""
    last_action: str = ""
    last_reprice_at: datetime | None = None
    last_suggested_price: float | None = None
    last_applied_price: float | None = None
    last_buybox_price: float | None = None
    last_next_offer_price: float | None = None
    last_cycle_dry_run: bool = True
    last_cycle_error: str = ""
    last_decision: dict | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class BiddingRuleListResponse(BaseModel):
    rules: list[BiddingRuleResponse]


class UpdateBiddingRuleRequest(BaseModel):
    listing_id: str | None = Field(default=None, max_length=128)
    floor_price: float | None = None
    strategy_type: StrategyType | None = None
    is_active: bool | None = None

    @field_validator("listing_id", mode="before")
    @classmethod
    def strip_listing_id(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class BulkImportBiddingRuleItem(BaseModel):
    sku: str = Field(min_length=1, max_length=128)
    floor_price: float | None = None

    @field_validator("sku", mode="before")
    @classmethod
    def strip_sku(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class BulkImportBiddingRuleResponse(BaseModel):
    imported_count: int
    created_count: int
    updated_count: int
    rules: list[BiddingRuleResponse]


class BiddingCycleRequest(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=50, ge=1, le=500)
    force: bool = False


class BiddingCycleItemResponse(BaseModel):
    rule_id: str
    sku: str
    offer_id: str | None
    plid: str | None
    action: str
    current_price: float | None = None
    floor_price: float | None = None
    buybox_price: float | None = None
    next_offer_price: float | None = None
    suggested_price: float | None = None
    applied_price: float | None = None
    owns_buybox: bool | None = None
    dry_run: bool
    status: str
    reason: str = ""


class BiddingCycleResponse(BaseModel):
    store_id: str
    dry_run: bool
    real_write_enabled: bool
    processed_count: int
    suggested_count: int
    applied_count: int
    skipped_count: int
    failed_count: int
    items: list[BiddingCycleItemResponse]


class BiddingStoreStatusResponse(BaseModel):
    store_id: str
    is_running: bool
    active_rule_count: int
    due_rule_count: int
    blocked_count: int
    retrying_count: int
    fresh_count: int
    won_buybox_count: int = 0
    lost_buybox_count: int = 0
    alert_count: int = 0
    dry_run_default: bool
    real_write_enabled: bool
    worker_enabled: bool
    worker_cycle_limit: int
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None
    last_manual_cycle_at: datetime | None = None
    last_worker_cycle_at: datetime | None = None
    last_cycle_summary: dict | None = None


class BiddingRuleLogListResponse(BaseModel):
    rules: list[BiddingRuleResponse]
