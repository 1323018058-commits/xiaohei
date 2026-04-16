"""Warehouse fulfillment schemas — Pydantic input / output models."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class DraftItemUpdate(BaseModel):
    """单个 SKU 行项目的更新数据。"""
    shipment_item_id: str = ""
    line_no: int = 0
    sku: str = Field("", max_length=100)
    title: str = Field("", max_length=500)
    takealot_url: str = ""
    tsin_id: str = Field("", max_length=100)
    qty_required: int = 0
    qty_sending: int = 1
    arrived_qty: int = 0
    domestic_tracking_no: str = Field("", max_length=255)
    domestic_carrier: str = Field("", max_length=100)
    declared_en_name: str = Field("", max_length=255)
    declared_cn_name: str = Field("", max_length=255)
    hs_code: str = Field("", max_length=50)
    origin_country: str = Field("CN-China/中国", max_length=100)
    unit_price_usd: float = 0.1
    unit_weight_kg: float = 0.5
    note: str = ""

    @field_validator("qty_sending")
    @classmethod
    def qty_sending_positive(cls, v: int) -> int:
        return max(1, v)

    @field_validator("arrived_qty")
    @classmethod
    def arrived_qty_non_negative(cls, v: int) -> int:
        return max(0, v)

    @field_validator("unit_price_usd")
    @classmethod
    def price_non_negative(cls, v: float) -> float:
        return max(0.0, v)

    @field_validator("unit_weight_kg")
    @classmethod
    def weight_non_negative(cls, v: float) -> float:
        return max(0.0, v)


class DraftSave(BaseModel):
    """保存草稿的请求体。"""
    version: int = Field(..., ge=1, description="乐观锁版本号，必须与服务端一致")

    # Shipment 元信息
    shipment_name: str = Field("", max_length=255)
    po_number: str = Field("", max_length=100)
    due_date: str = Field("", max_length=50)
    facility_code: str = Field("", max_length=100)
    facility_id: int | None = None
    warehouse_name: str = Field("", max_length=255)

    # 包裹信息
    package_count: int = Field(1, ge=1)
    total_weight_kg: float = 0.0
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0

    # 申报信息
    decl_currency: str = Field("USD", max_length=10)
    sender_country: str = Field("中国", max_length=100)
    bill_files: str = ""
    delivery_address: str = ""

    # 嘉鸿配置
    selected_cnx_warehouse_id: int | None = None
    selected_cnx_line_id: int | None = None

    # 仓库作业状态
    warehouse_received_complete: bool = False
    labels_done: bool = False
    sent_to_cnx: bool = False
    warehouse_note: str = ""

    # SKU 行项目
    items: list[DraftItemUpdate] = Field(default_factory=list)


class CnxSubmitRequest(BaseModel):
    """提交嘉鸿预报的请求体。"""
    selected_cnx_warehouse_id: int
    selected_cnx_line_id: int
    package_count: int = Field(1, ge=1)
    total_weight_kg: float = Field(..., gt=0)
    length_cm: float = Field(0.0, ge=0)
    width_cm: float = Field(0.0, ge=0)
    height_cm: float = Field(0.0, ge=0)


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------

class DraftItemResponse(BaseModel):
    id: int
    shipment_item_id: str
    line_no: int
    sku: str
    title: str
    takealot_url: str
    tsin_id: str
    qty_required: int
    qty_sending: int
    arrived_qty: int
    domestic_tracking_no: str
    domestic_carrier: str
    declared_en_name: str
    declared_cn_name: str
    hs_code: str
    origin_country: str
    unit_price_usd: float
    unit_weight_kg: float
    note: str

    class Config:
        from_attributes = True


class DraftResponse(BaseModel):
    id: int
    store_binding_id: int
    user_id: int
    shipment_id: int
    shipment_name: str
    po_number: str
    due_date: str
    facility_code: str
    warehouse_name: str
    package_count: int
    total_weight_kg: float
    decl_currency: str
    sender_country: str
    delivery_address: str
    selected_cnx_warehouse_id: int | None
    selected_cnx_line_id: int | None
    cnx_order_no: str
    cnx_forecasted_at: str | None
    workflow_status: str
    warehouse_received_complete: int
    labels_done: int
    labels_done_at: str | None
    sent_to_cnx: int
    sent_to_cnx_at: str | None
    notify_user_cnx_at: str | None
    warehouse_note: str
    updated_by_username: str
    updated_by_role: str
    version: int
    created_at: str | None
    updated_at: str | None
    items: list[DraftItemResponse] = []

    class Config:
        from_attributes = True


class JobSummary(BaseModel):
    """作业列表中的摘要信息。"""
    store_id: int
    store_alias: str
    shipment_id: int
    shipment_name: str
    po_number: str
    due_date: str
    workflow_status: str
    ready_count: int
    total_items: int
    updated_at: str | None
    updated_by_username: str


class AuditLogEntry(BaseModel):
    id: int
    action: str
    old_status: str
    new_status: str
    changes_json: str
    username: str
    role: str
    created_at: str | None

    class Config:
        from_attributes = True
