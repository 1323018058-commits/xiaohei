"""Listing and dropship job models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ListingJob(Base):
    __tablename__ = "listing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    amazon_url: Mapped[str] = mapped_column(Text, nullable=False)
    asin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    store_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("store_bindings.id"), nullable=True)
    parent_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    category_retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", index=True)

    # Original scraped data
    orig_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    orig_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    orig_bullets: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI-rewritten fields
    listing_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    listing_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    listing_bullets: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_contents: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Listing parameters
    price_zar: Mapped[float | None] = mapped_column(Float, nullable=True)
    rrp_zar: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    cost_cny: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    package_dimensions_cm: Mapped[str] = mapped_column(String(100), default="", server_default="")
    barcode: Mapped[str] = mapped_column(String(100), default="", server_default="")

    # Category
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    top_category: Mapped[str] = mapped_column(String(200), default="", server_default="")
    lowest_category: Mapped[str] = mapped_column(String(200), default="", server_default="")
    brand: Mapped[str] = mapped_column(String(200), default="", server_default="")
    model_number: Mapped[str] = mapped_column(String(200), default="", server_default="")
    color_main: Mapped[str] = mapped_column(String(100), default="", server_default="")
    ai_attributes: Mapped[str] = mapped_column(Text, default="", server_default="")
    category_confidence_score: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    category_confidence_label: Mapped[str] = mapped_column(String(50), default="", server_default="")
    retry_hint_top_category: Mapped[str] = mapped_column(String(200), default="", server_default="")
    retry_hint_lowest_category: Mapped[str] = mapped_column(String(200), default="", server_default="")

    # Takealot response
    takealot_offer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    submission_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    submission_status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    review_status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    review_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    review_reason_code: Mapped[str] = mapped_column(String(100), default="", server_default="")
    review_result_at: Mapped[str] = mapped_column(String(50), default="", server_default="")
    takealot_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DropshipJob(Base):
    __tablename__ = "dropship_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    store_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("store_bindings.id"), nullable=True, index=True)
    amazon_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_keyword: Mapped[str] = mapped_column(String(300), default="", server_default="")
    asin: Mapped[str] = mapped_column(String(20), default="", server_default="")
    parent_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    category_retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending", index=True)
    similarity_threshold: Mapped[int] = mapped_column(Integer, default=65, server_default="65")
    price_zar: Mapped[float] = mapped_column(Float, default=0, server_default="0")

    # Amazon side
    orig_title: Mapped[str] = mapped_column(Text, default="", server_default="")
    orig_brand: Mapped[str] = mapped_column(String(200), default="", server_default="")
    orig_description: Mapped[str] = mapped_column(Text, default="", server_default="")
    orig_bullets: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_urls_json: Mapped[str] = mapped_column(Text, default="", server_default="")
    barcode: Mapped[str] = mapped_column(String(100), default="", server_default="")

    # 1688 match side
    matched_similarity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    matched_image_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    matched_1688_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    matched_1688_title: Mapped[str] = mapped_column(Text, default="", server_default="")
    purchase_price_cny: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    weight_kg: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    package_dimensions_cm: Mapped[str] = mapped_column(String(100), default="", server_default="")

    # Category
    category_confidence_score: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    category_confidence_label: Mapped[str] = mapped_column(String(50), default="", server_default="")
    retry_hint_top_category: Mapped[str] = mapped_column(String(200), default="", server_default="")
    retry_hint_lowest_category: Mapped[str] = mapped_column(String(200), default="", server_default="")
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    top_category: Mapped[str] = mapped_column(String(200), default="", server_default="")
    lowest_category: Mapped[str] = mapped_column(String(200), default="", server_default="")

    # AI / listing side
    listing_title: Mapped[str] = mapped_column(Text, default="", server_default="")
    listing_description: Mapped[str] = mapped_column(Text, default="", server_default="")
    package_contents: Mapped[str] = mapped_column(Text, default="", server_default="")
    ai_attributes: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Submission / review side
    loadsheet_path: Mapped[str] = mapped_column(Text, default="", server_default="")
    submission_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    submission_status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    review_status: Mapped[str] = mapped_column(String(50), default="", server_default="")
    review_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    review_reason_code: Mapped[str] = mapped_column(String(100), default="", server_default="")
    review_result_at: Mapped[str] = mapped_column(String(50), default="", server_default="")
    approved_offer_id: Mapped[str] = mapped_column(String(100), default="", server_default="")
    approved_listing_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    error_code: Mapped[str] = mapped_column(String(100), default="", server_default="")
    error_msg: Mapped[str] = mapped_column(Text, default="", server_default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
