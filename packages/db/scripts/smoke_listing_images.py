from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.listing.image_service import ListingImageService  # noqa: E402
from src.modules.listing.repository import ListingCatalogRepository, ListingCatalogUnavailable  # noqa: E402
from src.platform.db.session import get_db_session  # noqa: E402


def run_pure_checks() -> dict:
    image_service = ListingImageService(public_base_url="")
    png_bytes = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 64)
    valid_image = image_service.validate_image_bytes(
        png_bytes,
        filename="smoke.png",
        content_type="image/png",
    )
    invalid_image = image_service.validate_image_bytes(
        b"not-an-image",
        filename="smoke.txt",
        content_type="text/plain",
    )
    url_check = image_service.validate_image_url(
        "https://example.com/smoke.png",
        check_remote=False,
    )
    return {
        "valid_png": valid_image.valid,
        "invalid_txt_rejected": not invalid_image.valid,
        "http_url_valid": bool(url_check["valid"]),
        "public_url_warning_without_base": bool(image_service.public_url_for("listing-assets/smoke.png")[1]),
    }


def main() -> None:
    pure_checks = run_pure_checks()
    repository = ListingCatalogRepository()

    try:
        categories, _, catalog_ready = repository.search_categories(
            query=None,
            page=1,
            page_size=1,
        )
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                store = cursor.execute(
                    "select id::text as id, tenant_id::text as tenant_id from stores order by created_at asc limit 1"
                ).fetchone()
    except Exception as exc:
        detail = exc.message if isinstance(exc, ListingCatalogUnavailable) else str(exc)
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "PostgreSQL unavailable",
                    "detail": detail,
                    "pure_checks": pure_checks,
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
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)
    if store is None:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "No store found for listing_assets DB write smoke.",
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)

    asset = repository.insert_listing_asset(
        tenant_id=store["tenant_id"],
        store_id=store["id"],
        submission_id=None,
        asset={
            "asset_type": "image",
            "source": "url",
            "original_file_name": "smoke.png",
            "file_name": "smoke.png",
            "storage_path": None,
            "public_url": "https://example.com/smoke.png",
            "external_url": "https://example.com/smoke.png",
            "content_type": "image/png",
            "size_bytes": 128,
            "checksum_sha256": "0" * 64,
            "width": None,
            "height": None,
            "validation_status": "warning",
            "validation_errors": [],
            "raw_payload": {"smoke": "listing_images"},
        },
    )
    category = categories[0]
    required_count = int(category.get("min_required_images") or 0)
    current_count = 1
    missing_count = max(0, required_count - current_count)
    passed = all(pure_checks.values()) and bool(asset.get("id"))

    print(
        json.dumps(
            {
                "passed": passed,
                "pure_checks": pure_checks,
                "db_write_checked": True,
                "asset_id": asset.get("id"),
                "category_id": category.get("category_id"),
                "required_count": required_count,
                "current_count": current_count,
                "missing_count": missing_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
