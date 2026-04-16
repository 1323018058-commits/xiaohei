"""Store binding model — Takealot seller API credentials per user."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Float, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StoreBinding(Base):
    __tablename__ = "store_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    store_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1, server_default="1", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Migration columns from original system
    store_alias: Mapped[str] = mapped_column(String(200), default="", server_default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    offer_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    takealot_store_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    unique_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    auto_push_price: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    min_price_90pct: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    direct_ship: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    api_key_status: Mapped[str] = mapped_column(String(50), default="有效", server_default="有效")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Relationships
    user = relationship("User", back_populates="store_bindings")
    bid_products = relationship("BidProduct", back_populates="store_binding", lazy="select")
    webhook_config = relationship("TakealotWebhookConfig", back_populates="store_binding", uselist=False, lazy="select")
    fulfillment_drafts = relationship("FulfillmentDraft", back_populates="store_binding", lazy="select")
