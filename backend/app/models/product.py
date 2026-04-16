"""Bid, auto-price, and product annotation models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BidProduct(Base):
    __tablename__ = "bid_products"
    __table_args__ = (
        UniqueConstraint("offer_id", "store_binding_id", name="uq_bid_products_offer_store"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offer_id: Mapped[str] = mapped_column(String(100), nullable=False)
    store_binding_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("store_bindings.id"), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    floor_price_zar: Mapped[float] = mapped_column(Float, nullable=False, default=0, server_default="0")
    target_price_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    buybox_price_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    rrp_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_bid_enabled: Mapped[int] = mapped_column(Integer, default=1, server_default="1", index=True)
    last_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Migration columns
    brand: Mapped[str] = mapped_column(String(200), default="", server_default="")
    image_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    takealot_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    discount_rate: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    buybox_store: Mapped[str] = mapped_column(String(200), default="", server_default="")
    buybox_store_stock: Mapped[str] = mapped_column(Text, default="", server_default="")
    api_status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    offer_status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    stock_detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    last_price_change: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    tsin_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    barcode: Mapped[str] = mapped_column(String(100), default="", server_default="")
    product_label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    official_stock_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stock_on_way_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    dropship_stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    marketplace_status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    marketplace_updated_at: Mapped[str] = mapped_column(String(50), default="", server_default="")

    # Metrics
    last_metrics_synced_at: Mapped[str] = mapped_column(String(50), default="", server_default="")
    page_views_30_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversion_percentage_30_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    conversion_percentage_previous_30_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_returned_30_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_sold_30_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_wishlist: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wishlist_30_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_metrics_json: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Dimensions & procurement
    product_length_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    product_width_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    product_height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    product_weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    procurement_length_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    procurement_width_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    procurement_height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    procurement_weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    procurement_price_cny: Mapped[float | None] = mapped_column(Float, nullable=True)
    procurement_url: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Relationships
    store_binding = relationship("StoreBinding", back_populates="bid_products")


class BidEngineState(Base):
    __tablename__ = "bid_engine_state"

    store_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    running: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_success_run: Mapped[str | None] = mapped_column(String(50), nullable=True)
    next_run: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_result: Mapped[str] = mapped_column(Text, default="", server_default="")
    last_raised: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_lowered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_floored: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_unchanged: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_no_floor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_checked: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_updated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    consecutive_error_cycles: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_api_error_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_successful_update_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_buybox_refresh_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class BidLog(Base):
    __tablename__ = "bid_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_binding_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    offer_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    buybox_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AutoPriceProduct(Base):
    __tablename__ = "auto_price_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    offer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_price_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_allowed_price_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_floor_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_price_enabled: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    last_adjusted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    margin_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProductAnnotation(Base):
    __tablename__ = "product_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    takealot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    margin_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
