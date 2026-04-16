"""Fulfillment draft models — shipment workflow, items, audit log."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FulfillmentDraft(Base):
    """履约草稿主表 — 每个 Shipment 一条记录，存储完整工作流状态。"""
    __tablename__ = "fulfillment_drafts"
    __table_args__ = (
        UniqueConstraint("store_binding_id", "shipment_id", name="uq_fulfillment_store_shipment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_binding_id: Mapped[int] = mapped_column(Integer, ForeignKey("store_bindings.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    shipment_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # --- Shipment 元信息 ---
    shipment_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    po_number: Mapped[str] = mapped_column(String(100), default="", server_default="")
    due_date: Mapped[str] = mapped_column(String(50), default="", server_default="")
    facility_code: Mapped[str] = mapped_column(String(100), default="", server_default="")
    facility_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warehouse_name: Mapped[str] = mapped_column(String(255), default="", server_default="")

    # --- 包裹信息 ---
    package_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    total_weight_kg: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    length_cm: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    width_cm: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    height_cm: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")

    # --- 申报信息 ---
    decl_currency: Mapped[str] = mapped_column(String(10), default="USD", server_default="USD")
    sender_country: Mapped[str] = mapped_column(String(100), default="中国", server_default="中国")
    bill_files: Mapped[str] = mapped_column(Text, default="", server_default="")
    delivery_address: Mapped[str] = mapped_column(Text, default="", server_default="")

    # --- 嘉鸿配置 ---
    selected_cnx_warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_cnx_line_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cnx_order_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    cnx_forecasted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- 工作流状态 ---
    workflow_status: Mapped[str] = mapped_column(String(30), default="待用户预报快递", server_default="待用户预报快递", index=True)
    warehouse_received_complete: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    labels_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    labels_done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_to_cnx: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sent_to_cnx_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notify_user_cnx_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    warehouse_note: Mapped[str] = mapped_column(Text, default="", server_default="")

    # --- 审计 ---
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_username: Mapped[str] = mapped_column(String(255), default="", server_default="")
    updated_by_role: Mapped[str] = mapped_column(String(50), default="", server_default="")

    # --- 乐观锁 ---
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # --- 时间戳 ---
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    store_binding = relationship("StoreBinding", back_populates="fulfillment_drafts")
    items = relationship("FulfillmentDraftItem", back_populates="draft", cascade="all, delete-orphan", lazy="selectin")
    owner = relationship("User", foreign_keys=[user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])
    audit_logs = relationship("FulfillmentAuditLog", back_populates="draft", cascade="all, delete-orphan", lazy="select")


class FulfillmentDraftItem(Base):
    """履约草稿行项目 — 每个 SKU 一条记录。"""
    __tablename__ = "fulfillment_draft_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(Integer, ForeignKey("fulfillment_drafts.id", ondelete="CASCADE"), nullable=False, index=True)

    # --- 商品标识 ---
    shipment_item_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    line_no: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sku: Mapped[str] = mapped_column(String(100), default="", server_default="", index=True)
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    takealot_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    tsin_id: Mapped[str] = mapped_column(String(100), default="", server_default="")

    # --- 数量 ---
    qty_required: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qty_sending: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    arrived_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # --- 快递 ---
    domestic_tracking_no: Mapped[str] = mapped_column(String(255), default="", server_default="")
    domestic_carrier: Mapped[str] = mapped_column(String(100), default="", server_default="")

    # --- 报关 ---
    declared_en_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    declared_cn_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    hs_code: Mapped[str] = mapped_column(String(50), default="", server_default="")
    origin_country: Mapped[str] = mapped_column(String(100), default="CN-China/中国", server_default="CN-China/中国")
    unit_price_usd: Mapped[float] = mapped_column(Float, default=0.1, server_default="0.1")
    unit_weight_kg: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")

    # --- 备注 ---
    note: Mapped[str] = mapped_column(Text, default="", server_default="")

    # --- 时间戳 ---
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    draft = relationship("FulfillmentDraft", back_populates="items")


class FulfillmentAuditLog(Base):
    """履约审计日志 — 记录每次草稿修改的详细信息。"""
    __tablename__ = "fulfillment_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(Integer, ForeignKey("fulfillment_drafts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(255), default="", server_default="")
    role: Mapped[str] = mapped_column(String(50), default="", server_default="")

    action: Mapped[str] = mapped_column(String(50), nullable=False)  # create / update / status_change / cnx_submit / timeout_rollback
    old_status: Mapped[str] = mapped_column(String(30), default="", server_default="")
    new_status: Mapped[str] = mapped_column(String(30), default="", server_default="")
    changes_json: Mapped[str] = mapped_column(Text, default="", server_default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    # --- Relationships ---
    draft = relationship("FulfillmentDraft", back_populates="audit_logs")
    user = relationship("User", foreign_keys=[user_id])
