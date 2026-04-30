from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExtensionStoreSummary(BaseModel):
    store_id: str
    name: str
    platform: str
    bidding_enabled: bool
    listing_enabled: bool
    sync_enabled: bool


class ExtensionProfileUser(BaseModel):
    user_id: str
    username: str
    role: str
    tenant_id: str


class ExtensionProfileResponse(BaseModel):
    user: ExtensionProfileUser
    stores: list[ExtensionStoreSummary]


class ExtensionAuthRequest(BaseModel):
    store_id: str | None = Field(default=None, min_length=1)

    @field_validator("store_id", mode="before")
    @classmethod
    def strip_store_id(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class ExtensionAuthResponse(BaseModel):
    token: str
    expires_at: datetime
    store_id: str | None


class ExtensionLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    store_id: str | None = Field(default=None, min_length=1)

    @field_validator("username", "password", "store_id", mode="before")
    @classmethod
    def strip_login_fields(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class ExtensionLoginResponse(BaseModel):
    token: str
    expires_at: datetime
    store_id: str | None
    user: ExtensionProfileUser
    stores: list[ExtensionStoreSummary]


class ProfitPreviewRequest(BaseModel):
    store_id: str = Field(min_length=1)
    plid: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=512)
    category_path: list[str] | None = None
    air_freight_unit_cny_per_kg: float | None = None
    purchase_price_cny: float | None = None
    sale_price_zar: float | None = None
    actual_weight_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    force_refresh_facts: bool = False

    @field_validator("store_id", "plid", "title", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("category_path", mode="before")
    @classmethod
    def normalize_category_path(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            values = [part.strip() for part in value.split(">")]
        elif isinstance(value, list):
            values = [str(part).strip() for part in value]
        else:
            return None
        return [part for part in values if part]

    @field_validator(
        "air_freight_unit_cny_per_kg",
        "purchase_price_cny",
        "sale_price_zar",
        "actual_weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
    )
    @classmethod
    def non_negative_numbers(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("pricing inputs must be non-negative")
        return value


class ProfitPreviewProduct(BaseModel):
    product_id: str
    platform: str
    plid: str
    title: str
    fact_status: str
    merchant_packaged_weight_raw: str | None
    merchant_packaged_dimensions_raw: str | None
    cbs_package_weight_raw: str | None
    cbs_package_dimensions_raw: str | None
    consolidated_packaged_dimensions_raw: str | None
    actual_weight_kg: float | None
    length_cm: float | None
    width_cm: float | None
    height_cm: float | None
    category_path: list[str]
    category_label: str | None
    last_refreshed_at: datetime | None


class ProfitPreviewGuardrail(BaseModel):
    guardrail_id: str | None
    protected_floor_price: float | None
    status: str
    linked_bidding_rule_id: str | None
    linked_listing_id: str | None
    autobid_sync_status: str | None


class ProfitPreviewResponse(BaseModel):
    store_id: str
    product: ProfitPreviewProduct
    guardrail: ProfitPreviewGuardrail
    pricing: "ProfitPreviewPricing"


class ProfitPreviewPricing(BaseModel):
    formula_version: str
    best_price_zar: float | None
    air_freight_unit_cny_per_kg: float | None
    purchase_price_cny: float | None
    sale_price_zar: float | None
    actual_weight_kg: float | None
    length_cm: float | None
    width_cm: float | None
    height_cm: float | None
    volume_m3: float | None
    volumetric_weight_kg: float | None
    chargeable_weight_kg: float | None
    cny_to_zar_rate: float
    payout_rate: float
    withdraw_fx_rate: float
    purchase_vat_rate: float
    po_fee_cny: float
    po_fee_zar: float | None
    success_fee_category: str | None
    success_fee_rate: float
    success_fee_vat_rate: float
    success_fee_amount_zar: float | None
    tail_shipping_fee_zar: float | None
    tail_vat_fee_zar: float | None
    fulfillment_size_tier: str | None
    fulfillment_weight_tier: str | None
    purchase_converted_cost_zar: float | None
    payout_amount_zar: float | None
    withdraw_fx_loss_zar: float | None
    airfreight_cost_zar: float | None
    purchase_tax_cost_zar: float | None
    total_main_cost_zar: float | None
    profit_zar: float | None
    profit_cny: float | None
    margin_rate: float | None
    recommended_price_10_zar: float | None
    recommended_price_30_zar: float | None
    recommended_protected_floor_price_zar: float | None
    break_even_price_zar: float | None
    note: str


class ProtectedFloorRequest(BaseModel):
    store_id: str = Field(min_length=1)
    plid: str = Field(min_length=1, max_length=128)
    protected_floor_price: float
    title: str | None = Field(default=None, max_length=512)

    @field_validator("store_id", "plid", "title", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class ProtectedFloorResponse(BaseModel):
    guardrail_id: str
    store_id: str
    product_id: str
    plid: str
    protected_floor_price: float
    status: str
    autobid_sync_status: str
    linked_bidding_rule_id: str | None
    linked_listing_id: str | None
    updated_at: datetime


class ExtensionListNowRequest(BaseModel):
    store_id: str = Field(min_length=1)
    plid: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=512)
    sale_price_zar: float | None = None
    quantity: int | None = None

    @field_validator("store_id", "plid", "title", mode="before")
    @classmethod
    def strip_list_now_fields(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("sale_price_zar")
    @classmethod
    def sale_price_non_negative(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("sale_price_zar must be non-negative")
        return value

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("quantity must be greater than 0")
        return value


class ExtensionListNowResponse(BaseModel):
    task_id: str
    status: str
    stage: str
    store_id: str
    plid: str


class ExtensionListNowTaskStatusResponse(BaseModel):
    task_id: str
    task_status: str
    task_stage: str
    request_id: str
    store_id: str | None
    plid: str | None
    listing_job_id: str | None
    listing_status: str | None
    listing_stage: str | None
    note: str | None
    offer_id: int | None
    offer_status: str | None
    barcode: str | None
    sku: str | None
    protected_floor_price: float | None
    leadtime_merchant_warehouse_id: int | None
    default_leadtime_days: int
    can_auto_make_buyable: bool
    needs_buyable_patch: bool
