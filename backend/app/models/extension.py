"""Chrome extension auth token and action log models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExtensionAuthToken(Base):
    __tablename__ = "extension_auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    token_name: Mapped[str] = mapped_column(String(100), default="takealot_extension",
                                             server_default="takealot_extension")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="extension_tokens")


class ExtensionAction(Base):
    __tablename__ = "extension_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store_bindings.id"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_source: Mapped[str] = mapped_column(String(50), default="takealot_extension",
                                                server_default="takealot_extension")
    plid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    page_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    barcode: Mapped[str] = mapped_column(String(100), default="", server_default="")
    brand_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    buybox_price_zar: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    page_price_zar: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    target_price_zar: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    offer_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    task_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    action_status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", index=True)
    error_code: Mapped[str] = mapped_column(String(100), default="", server_default="")
    error_msg: Mapped[str] = mapped_column(Text, default="", server_default="")
    pricing_snapshot_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    raw_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
