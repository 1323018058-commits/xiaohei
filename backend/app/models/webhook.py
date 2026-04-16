"""Takealot webhook configuration and delivery log models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TakealotWebhookConfig(Base):
    __tablename__ = "takealot_webhook_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_binding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("store_bindings.id"), unique=True, index=True
    )
    secret: Mapped[str] = mapped_column(Text, default="", server_default="")  # encrypted
    active: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_event_type: Mapped[str] = mapped_column(String(100), default="", server_default="")
    last_delivery_id: Mapped[str] = mapped_column(String(200), default="", server_default="")
    last_delivery_status: Mapped[str] = mapped_column(String(50), default="", server_default="")

    # Relationships
    store_binding = relationship("StoreBinding", back_populates="webhook_config")


class TakealotWebhookDelivery(Base):
    __tablename__ = "takealot_webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_binding_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("store_bindings.id"), nullable=True,
                                                          index=True)
    delivery_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(30), default="received", server_default="received")
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
