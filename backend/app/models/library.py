"""Product library, auto-selection, and category learning models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LibraryProduct(Base):
    __tablename__ = "library_products"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tsin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_main: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    category_l1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l3: Mapped[str | None] = mapped_column(String(200), nullable=True)
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    pretty_price: Mapped[str | None] = mapped_column(String(50), nullable=True)
    saving: Mapped[str | None] = mapped_column(String(50), nullable=True)
    star_rating: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    reviews_total: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reviews_5: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_4: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_3: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_2: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_1: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latest_review_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    in_stock: Mapped[str | None] = mapped_column(String(50), nullable=True)
    stock_dist: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_preorder: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    best_store: Mapped[str | None] = mapped_column(String(200), nullable=True)
    offer_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Pre-computed completeness score for efficient sorting (avoids runtime CASE expressions)
    completeness_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)


class LibraryProductQuarantine(Base):
    __tablename__ = "library_products_quarantine"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    removed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    removed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AutoSelectionProduct(Base):
    __tablename__ = "auto_selection_products"
    __table_args__ = (
        {"comment": "Auto-selected products per user"},
    )

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tsin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_main: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    star_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviews_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_stock: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_image_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    source_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    source_weight_kg: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    source_similarity_pct: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    fail_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    profit_zar: Mapped[float] = mapped_column(Float, default=0, server_default="0", index=True)
    margin_rate: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(50), nullable=True)


class TempScrapeProduct(Base):
    __tablename__ = "temp_scrape_products"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tsin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_main: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l3: Mapped[str | None] = mapped_column(String(200), nullable=True)
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    pretty_price: Mapped[str | None] = mapped_column(String(50), nullable=True)
    saving: Mapped[str | None] = mapped_column(String(50), nullable=True)
    star_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviews_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviews_5: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_4: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_3: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_2: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviews_1: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latest_review_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    in_stock: Mapped[str | None] = mapped_column(String(50), nullable=True)
    stock_dist: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_preorder: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    best_store: Mapped[str | None] = mapped_column(String(200), nullable=True)
    offer_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[str | None] = mapped_column(String(50), nullable=True)


class SelectionMemory(Base):
    __tablename__ = "selection_memory"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_selection_memory_user_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    plid: Mapped[str] = mapped_column(String(100), default="", server_default="")
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    category_main: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CategoryLearningRule(Base):
    __tablename__ = "category_learning_rules"
    __table_args__ = (
        UniqueConstraint("source_fingerprint", "top_category", "lowest_category",
                         name="uq_category_learning_fingerprint_cats"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_fingerprint: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_category: Mapped[str] = mapped_column(String(200), nullable=False)
    lowest_category: Mapped[str] = mapped_column(String(200), nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    approved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    category_reject_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    other_reject_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    learning_level: Mapped[str] = mapped_column(String(30), default="candidate", server_default="candidate")
    last_review_status: Mapped[str] = mapped_column(String(30), default="", server_default="")
    last_review_reason_code: Mapped[str] = mapped_column(String(100), default="", server_default="")
    example_title: Mapped[str] = mapped_column(Text, default="", server_default="")
    example_hint: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
