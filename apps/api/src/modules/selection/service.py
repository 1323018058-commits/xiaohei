from typing import Any

from src.modules.common.dev_state import app_state

from .schemas import (
    SelectionFilterOptionsResponse,
    SelectionProductListResponse,
    SelectionProductResponse,
)


class SelectionService:
    def list_products(
        self,
        *,
        query: str | None = None,
        main_category: str | None = None,
        category_level1: str | None = None,
        category_level2: str | None = None,
        category_level3: str | None = None,
        brand: str | None = None,
        stock_status: str | None = None,
        latest_review_window: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        min_rating: float | None = None,
        min_reviews: int | None = None,
        min_offer_count: int | None = None,
        max_offer_count: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SelectionProductListResponse:
        result = app_state.list_selection_products(
            query=query,
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
        return SelectionProductListResponse(
            products=[
                self._to_product_response(product)
                for product in result["products"]
            ],
            total=result["total"],
            limit=result["limit"],
            offset=result["offset"],
        )

    def filter_options(
        self,
        *,
        main_category: str | None = None,
        category_level1: str | None = None,
        category_level2: str | None = None,
        category_level3: str | None = None,
        brand: str | None = None,
        stock_status: str | None = None,
    ) -> SelectionFilterOptionsResponse:
        options = app_state.get_selection_filter_options(
            main_category=main_category,
            category_level1=category_level1,
            category_level2=category_level2,
            category_level3=category_level3,
            brand=brand,
            stock_status=stock_status,
        )
        return SelectionFilterOptionsResponse(**options)

    @staticmethod
    def _to_product_response(product: dict[str, Any]) -> SelectionProductResponse:
        return SelectionProductResponse(
            product_id=product["id"],
            platform=product["platform"],
            platform_product_id=product["platform_product_id"],
            image_url=product.get("image_url"),
            title=product["title"],
            main_category=product.get("main_category"),
            category_level1=product.get("category_level1"),
            category_level2=product.get("category_level2"),
            category_level3=product.get("category_level3"),
            brand=product.get("brand"),
            currency=product.get("currency") or "ZAR",
            current_price=product.get("current_price"),
            rating=product.get("rating"),
            total_review_count=product.get("total_review_count"),
            rating_5_count=product.get("rating_5_count"),
            rating_4_count=product.get("rating_4_count"),
            rating_3_count=product.get("rating_3_count"),
            rating_2_count=product.get("rating_2_count"),
            rating_1_count=product.get("rating_1_count"),
            latest_review_at=product.get("latest_review_at"),
            stock_status=product.get("stock_status"),
            offer_count=product.get("offer_count"),
            current_snapshot_week=product.get("current_snapshot_week"),
            status=product["status"],
            first_seen_at=product["first_seen_at"],
            last_seen_at=product.get("last_seen_at"),
            updated_at=product["updated_at"],
        )
