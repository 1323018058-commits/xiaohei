"""Product library Pydantic schemas — matches actual ORM models and API responses."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ScrapeStartRequest(BaseModel):
    """Request body for POST /api/library/scrape/start."""
    lead_min: int = Field(7, ge=0, le=365, description="Minimum lead time (work days)")
    lead_max: int = Field(21, ge=0, le=365, description="Maximum lead time (work days)")
    price_min: float = Field(0, ge=0, description="Minimum price in ZAR")
    price_max: float = Field(100000, ge=0, description="Maximum price in ZAR")
    max_per_cat: int = Field(500, ge=0, description="Max products per category (0=unlimited)")
    categories: list[str] = Field(default_factory=list, description="Category names to scrape (empty=all)")

    @model_validator(mode="after")
    def validate_ranges(self):
        """Ensure min values don't exceed max values."""
        if self.lead_min > self.lead_max:
            raise ValueError(f"lead_min ({self.lead_min}) cannot exceed lead_max ({self.lead_max})")
        if self.price_min > self.price_max:
            raise ValueError(f"price_min ({self.price_min}) cannot exceed price_max ({self.price_max})")
        return self


class ScrapeProgress(BaseModel):
    """Response for GET /api/library/scrape/progress."""
    running: bool = False
    total_scraped: int = 0
    round: int = 0
    current_cat: str = ""
    total_cats: int = 1
    done_cats: int = 0
    mode: str = "idle"
    error: str | None = None
    elapsed_sec: float = 0
    last_event: str = ""


class LibraryProductItem(BaseModel):
    """Single library product in list response."""
    product_id: int
    tsin: int | None = None
    title: str = ""
    brand: str = ""
    slug: str = ""
    url: str = ""
    image: str = ""
    category_main: str = ""
    category_l1: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    pretty_price: str = ""
    saving: str = ""
    star_rating: float | None = None
    reviews_total: int = 0
    reviews_5: int = 0
    reviews_4: int = 0
    reviews_3: int = 0
    reviews_2: int = 0
    reviews_1: int = 0
    latest_review_at: str | None = None
    in_stock: str = ""
    is_preorder: int = 0
    offer_count: int = 0
    updated_at: str | None = None

    class Config:
        from_attributes = True


class LibraryAutoScrapeStatus(BaseModel):
    running: bool = False
    status: str = "idle"
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_task_id: str | None = None
    last_total_scraped: int = 0
    last_new_products: int = 0
    last_error: str | None = None


class LibraryStats(BaseModel):
    """Response for GET /api/library/stats."""
    total_products: int = 0
    quarantined: int = 0
    categories: int = 0
    brands: int = 0
    last_updated: str | None = None
    auto_scrape: LibraryAutoScrapeStatus = Field(default_factory=LibraryAutoScrapeStatus)


class QuarantineRequest(BaseModel):
    """Request body for POST /api/library/quarantine."""
    product_ids: list[int] = Field(..., max_length=5000)
    reason: str = "manual"


class ImportRequest(BaseModel):
    """Request body for POST /api/library/import."""
    products: list[dict] = Field(..., min_length=1, max_length=1000)
