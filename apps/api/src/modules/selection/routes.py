from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from src.modules.auth.dependencies import require_roles

from .schemas import SelectionFilterOptionsResponse, SelectionProductListResponse
from .service import SelectionService

router = APIRouter(prefix="/api/v1/selection", tags=["selection"])
service = SelectionService()
SelectionReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator")),
]


@router.get("/products", response_model=SelectionProductListResponse)
def list_products(
    current_user: SelectionReader,
    q: str | None = Query(default=None, max_length=256),
    query: str | None = Query(default=None, max_length=256, include_in_schema=False),
    main_category: str | None = Query(default=None, max_length=255),
    category_level1: str | None = Query(default=None, max_length=255),
    category_level2: str | None = Query(default=None, max_length=255),
    category_level3: str | None = Query(default=None, max_length=255),
    brand: str | None = Query(default=None, max_length=255),
    stock_status: str | None = Query(default=None, max_length=64),
    latest_review_window: str | None = Query(default=None, max_length=32),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    min_reviews: int | None = Query(default=None, ge=0),
    min_offer_count: int | None = Query(default=None, ge=0),
    max_offer_count: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return service.list_products(
        query=q or query,
        main_category=main_category,
        category_level1=category_level1,
        category_level2=category_level2,
        category_level3=category_level3,
        brand=brand,
        stock_status=stock_status,
        latest_review_window=latest_review_window,
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        min_reviews=min_reviews,
        min_offer_count=min_offer_count,
        max_offer_count=max_offer_count,
        limit=limit,
        offset=offset,
    )


@router.get("/filters", response_model=SelectionFilterOptionsResponse)
def get_filters(
    current_user: SelectionReader,
    main_category: str | None = Query(default=None, max_length=255),
    category_level1: str | None = Query(default=None, max_length=255),
    category_level2: str | None = Query(default=None, max_length=255),
    category_level3: str | None = Query(default=None, max_length=255),
    brand: str | None = Query(default=None, max_length=255),
    stock_status: str | None = Query(default=None, max_length=64),
):
    return service.filter_options(
        main_category=main_category,
        category_level1=category_level1,
        category_level2=category_level2,
        category_level3=category_level3,
        brand=brand,
        stock_status=stock_status,
    )
