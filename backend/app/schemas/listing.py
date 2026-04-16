"""Listing and dropship job Pydantic schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ListingJobCreate(BaseModel):
    amazon_url: str = Field(..., min_length=1)
    store_id: int
    price_zar: float | None = None
    notes: str = ""


class ListingJobInfo(BaseModel):
    id: int
    user_id: int | None = None
    store_binding_id: int | None = None
    amazon_url: str = ""
    asin: str = ""
    status: str = ""
    error_code: str = ""
    error_message: str = ""
    submission_id: str = ""
    review_status: str = ""
    title: str = ""
    takealot_title: str = ""
    template_id: int | None = None
    image_url: str = ""
    similarity_score: float | None = None
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


class DropshipJobCreate(BaseModel):
    store_id: int
    keyword: str = Field(..., min_length=1)
    pages: int = Field(5, ge=1, le=10)
    threshold: int = Field(65, ge=0, le=100)
    price_zar: float = 0
    max_items: int = Field(10, ge=1, le=100)


class DropshipJobInfo(BaseModel):
    id: int
    user_id: int | None = None
    store_binding_id: int | None = None
    amazon_url: str = ""
    asin: str = ""
    source_keyword: str = ""
    status: str = ""
    error_code: str = ""
    error_message: str = ""
    submission_id: str = ""
    review_status: str = ""
    title: str = ""
    takealot_title: str = ""
    similarity_score: float | None = None
    similarity_threshold: int = 65
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


class KeywordProgress(BaseModel):
    running: bool = False
    keyword: str = ""
    pages: int = 0
    step: str = ""
    scraped: int = 0
    created_jobs: int = 0
    skipped_existing: int = 0
    skipped_duplicate: int = 0
    error: str = ""
    source: str = ""
