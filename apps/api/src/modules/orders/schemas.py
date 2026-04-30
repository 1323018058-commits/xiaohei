from datetime import datetime

from pydantic import BaseModel, Field

from src.modules.store.schemas import TaskCreatedResponse


class OrderItemResponse(BaseModel):
    item_id: str
    order_id: str
    external_order_item_id: str
    sku: str
    title: str | None
    quantity: int
    unit_price: float | None
    status: str | None
    raw_payload: dict | None
    created_at: datetime
    updated_at: datetime


class OrderEventResponse(BaseModel):
    event_id: str
    order_id: str
    event_type: str
    status: str | None
    message: str | None
    payload: dict | None
    occurred_at: datetime
    created_at: datetime


class OrderSummary(BaseModel):
    order_id: str
    tenant_id: str
    store_id: str
    external_order_id: str
    order_number: str | None
    status: str
    fulfillment_status: str | None
    total_amount: float | None
    currency: str
    item_count: int
    placed_at: datetime | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrderDetail(OrderSummary):
    raw_payload: dict | None
    items: list[OrderItemResponse]
    events: list[OrderEventResponse]


class OrderListResponse(BaseModel):
    orders: list[OrderSummary]


class OrderSyncRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
