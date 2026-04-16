"""User and license key models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    license_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    activated_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    store_bindings = relationship("StoreBinding", back_populates="user", lazy="select")
    extension_tokens = relationship("ExtensionAuthToken", back_populates="user", lazy="select")
    notifications = relationship("SiteNotification", back_populates="user", lazy="select")


class LicenseKey(Base):
    __tablename__ = "license_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    used_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
