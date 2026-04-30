from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    pass


class BiddingRule(Base):
    __tablename__ = "bidding_rules"
    __table_args__ = (
        UniqueConstraint("store_id", "sku", name="uq_bidding_rules_store_sku"),
        CheckConstraint("floor_price > 0", name="ck_bidding_rules_floor_price_positive"),
        CheckConstraint(
            "ceiling_price is null or ceiling_price >= floor_price",
            name="ck_bidding_rules_ceiling_gte_floor",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("stores.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    listing_id: Mapped[str | None] = mapped_column(String(128))
    floor_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    ceiling_price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    strategy_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
