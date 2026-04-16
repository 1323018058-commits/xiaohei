"""Site notification model."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SiteNotification(Base):
    __tablename__ = "site_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    store_binding_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("store_bindings.id"), nullable=True)
    notif_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    module: Mapped[str] = mapped_column(String(50), default="", server_default="")
    level: Mapped[str] = mapped_column(String(20), default="info", server_default="info")
    title: Mapped[str] = mapped_column(String(500), default="", server_default="")
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    entity_type: Mapped[str] = mapped_column(String(50), default="", server_default="")
    entity_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    link_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_read: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="notifications")
