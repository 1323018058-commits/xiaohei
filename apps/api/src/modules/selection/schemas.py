from datetime import date, datetime

from pydantic import BaseModel, Field


class SelectionProductResponse(BaseModel):
    product_id: str
    platform: str
    platform_product_id: str
    image_url: str | None
    title: str
    main_category: str | None
    category_level1: str | None
    category_level2: str | None
    category_level3: str | None
    brand: str | None
    currency: str
    current_price: float | None
    rating: float | None
    total_review_count: int | None
    rating_5_count: int | None
    rating_4_count: int | None
    rating_3_count: int | None
    rating_2_count: int | None
    rating_1_count: int | None
    latest_review_at: datetime | None
    stock_status: str | None
    offer_count: int | None
    current_snapshot_week: date | None
    status: str
    first_seen_at: datetime
    last_seen_at: datetime | None
    updated_at: datetime


class SelectionProductListResponse(BaseModel):
    products: list[SelectionProductResponse]
    total: int
    limit: int
    offset: int


class SelectionFilterOptionsResponse(BaseModel):
    main_categories: list[str]
    category_level1: list[str]
    category_level2: list[str]
    category_level3: list[str]
    brands: list[str]
    stock_statuses: list[str]
    category_tree: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
