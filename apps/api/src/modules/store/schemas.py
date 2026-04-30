from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.modules.tasking.schemas import TaskRunSummary

StorePlatform = Literal["takealot"]
StoreStatus = Literal["active", "disabled"]


class StoreFeaturePolicies(BaseModel):
    bidding_enabled: bool
    listing_enabled: bool
    sync_enabled: bool


class StorePlatformProfile(BaseModel):
    seller_id: str | None = None
    display_name: str | None = None
    business_status: str | None = None
    on_vacation: bool | None = None
    leadtime_label: str | None = None
    tenure_label: str | None = None
    validated_at: datetime | None = None


class StoreSummary(BaseModel):
    store_id: str
    tenant_id: str
    name: str
    platform: str
    status: str
    api_key_status: str | None
    credential_status: str | None
    last_synced_at: datetime | None
    feature_policies: StoreFeaturePolicies
    created_at: datetime
    updated_at: datetime
    version: int


class StoreDetail(StoreSummary):
    masked_api_key: str | None
    platform_profile: StorePlatformProfile | None = None
    sync_tasks: list[TaskRunSummary]


class StoreListResponse(BaseModel):
    stores: list[StoreSummary]


class StoreSyncTaskListResponse(BaseModel):
    tasks: list[TaskRunSummary]


class StoreListingResponse(BaseModel):
    listing_id: str
    store_id: str
    external_listing_id: str
    platform_product_id: str | None
    sku: str
    title: str
    platform_price: float | None
    buybox_price: float | None = None
    stock_quantity: int | None
    currency: str
    sync_status: str
    raw_payload: dict | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StoreListingListResponse(BaseModel):
    listings: list[StoreListingResponse]
    total: int
    limit: int
    offset: int
    status_counts: dict[str, int] = Field(default_factory=dict)


class UpdateStoreListingRequest(BaseModel):
    selling_price: float | None = Field(default=None, ge=0)
    seller_stock: int | None = Field(default=None, ge=0)
    seller_stock_enabled: bool | None = None


class StoreListingMetricResponse(BaseModel):
    store_id: str
    sku: str
    sales_30d: int


class StoreListingMetricListResponse(BaseModel):
    metrics: list[StoreListingMetricResponse]


class CreateStoreRequest(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    platform: StorePlatform = "takealot"
    api_key: str = Field(min_length=8, max_length=1024)
    api_secret: str = Field(min_length=8, max_length=2048)
    status: StoreStatus = "active"

    @field_validator("name", "api_key", "api_secret", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("api_key", "api_secret")
    @classmethod
    def reject_whitespace(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("Credential values must not contain whitespace")
        return value


class UpdateStoreRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: StoreStatus | None = None
    bidding_enabled: bool | None = None
    listing_enabled: bool | None = None
    sync_enabled: bool | None = None


class UpdateStoreCredentialsRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)
    api_secret: str = Field(min_length=8, max_length=2048)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("api_key", "api_secret", "reason", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("api_key", "api_secret")
    @classmethod
    def reject_whitespace(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("Credential values must not contain whitespace")
        return value


class StoreSyncRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    sync_scope: Literal["full", "bidding"] = "full"


class TaskCreatedResponse(BaseModel):
    task_id: str
    status: str
    stage: str


class StoreCredentialValidationResponse(BaseModel):
    store_id: str
    status: str
    message: str
    platform_profile: StorePlatformProfile | None = None
    store: StoreDetail


class StoreDeleteResponse(BaseModel):
    store_id: str
    deleted: bool
