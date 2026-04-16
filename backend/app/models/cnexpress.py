"""CN Express logistics integration models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CnexpressAccount(Base):
    __tablename__ = "cnexpress_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_cnexpress_accounts_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="CN Express", server_default="CN Express")
    base_url: Mapped[str] = mapped_column(Text, default="https://portal.cnexpressintl.com/api",
                                           server_default="https://portal.cnexpressintl.com/api")
    token_header: Mapped[str] = mapped_column(String(50), default="Token", server_default="Token")
    token: Mapped[str] = mapped_column(Text, default="", server_default="")  # encrypted
    account_username: Mapped[str] = mapped_column(String(200), default="", server_default="")
    account_password: Mapped[str] = mapped_column(Text, default="", server_default="")  # encrypted
    customer_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    login_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    is_active: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CnexpressFbaOrder(Base):
    __tablename__ = "cnexpress_fba_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "order_no", name="uq_cnexpress_fba_orders_user_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cnexpress_accounts.id"), nullable=True)
    order_no: Mapped[str] = mapped_column(String(100), nullable=False)
    sn: Mapped[str] = mapped_column(String(100), default="", server_default="")
    transfer_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    order_ref: Mapped[str] = mapped_column(String(200), default="", server_default="")
    status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    status_text: Mapped[str] = mapped_column(String(200), default="", server_default="")
    line_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    warehouse_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    front_warehouse_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    take_dest: Mapped[str] = mapped_column(String(200), default="", server_default="")
    number: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    yu_weight: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    weight: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    yu_long: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    yu_width: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    yu_height: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    take_time: Mapped[str] = mapped_column(String(50), default="", server_default="")
    detail_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    raw_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CnexpressWalletEntry(Base):
    __tablename__ = "cnexpress_wallet_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "entry_key", name="uq_cnexpress_wallet_user_entry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cnexpress_accounts.id"), nullable=True)
    entry_key: Mapped[str] = mapped_column(String(200), nullable=False)
    order_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    transaction_type: Mapped[str] = mapped_column(String(100), default="", server_default="")
    amount: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    balance: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    occurred_at: Mapped[str] = mapped_column(String(50), default="", server_default="")
    raw_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
