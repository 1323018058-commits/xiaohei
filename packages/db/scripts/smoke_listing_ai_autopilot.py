from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.listing.repository import ListingCatalogRepository, ListingCatalogUnavailable  # noqa: E402


def main() -> None:
    repository = ListingCatalogRepository()
    try:
        categories, _, catalog_ready = repository.search_categories(
            query=None,
            page=1,
            page_size=1,
        )
    except ListingCatalogUnavailable as exc:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "PostgreSQL unavailable",
                    "detail": exc.message,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from exc

    if not catalog_ready or not categories:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "需要导入 Takealot 类目库",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)

    from src.modules.listing.schemas import ListingAiAutopilotRequest  # noqa: E402
    from src.modules.listing.service import ListingService  # noqa: E402

    category_id = int(categories[0]["category_id"])
    request = ListingAiAutopilotRequest(
        product_description="Durable everyday product for marketplace listing smoke test",
        category_id=category_id,
        brand_name="Test Brand",
        required_attributes=[
            {"key": "Waterproof", "type": "boolean"},
            {"key": "Colour", "type": "select", "options": ["Black", "Blue"]},
        ],
        optional_attributes=[
            {"key": "Model", "type": "text"},
            {"key": "Pack Size", "type": "number"},
        ],
        use_ai=False,
    )
    actor = {
        "id": "00000000-0000-0000-0000-000000000000",
        "role": "super_admin",
        "tenant_id": None,
    }
    try:
        response = ListingService().generate_listing_content(actor, request)
    except Exception as exc:
        detail = getattr(exc, "detail", str(exc))
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "PostgreSQL unavailable" if "PostgreSQL" in str(detail) else "autopilot smoke failed",
                    "detail": detail,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2 if "PostgreSQL" in str(detail) else 1) from exc

    payload = response.model_dump()
    required_fields = [
        "category_id",
        "category_path_en",
        "category_path_zh",
        "title",
        "subtitle",
        "description",
        "whats_in_the_box",
        "length_cm",
        "width_cm",
        "height_cm",
        "weight_g",
        "dynamic_attributes",
        "ai_used",
        "fallback_used",
        "warnings",
    ]
    missing = [field for field in required_fields if field not in payload]
    dimensions_ok = all(float(payload[field]) > 0 for field in ("length_cm", "width_cm", "height_cm", "weight_g"))
    box_ok = bool(re.match(r"^[1-9][0-9]*\s+x\s+.{2,}$", payload["whats_in_the_box"]))
    fallback_ok = payload["fallback_used"] is True and payload["ai_used"] is False
    passed = not missing and dimensions_ok and box_ok and fallback_ok and payload["category_id"] == category_id

    print(
        json.dumps(
            {
                "passed": passed,
                "category_id": category_id,
                "forced_local_fallback": True,
                "missing_fields": missing,
                "dimensions_ok": dimensions_ok,
                "whats_in_the_box_ok": box_ok,
                "fallback_ok": fallback_ok,
                "payload": payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
