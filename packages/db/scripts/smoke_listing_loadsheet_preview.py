from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.listing.loadsheet_service import ListingLoadsheetService  # noqa: E402
from src.modules.listing.repository import ListingCatalogRepository, ListingCatalogUnavailable  # noqa: E402
from src.modules.listing.schemas import ListingLoadsheetPreviewRequest  # noqa: E402
from src.platform.db.session import get_db_session  # noqa: E402


def run_pure_checks() -> dict[str, Any]:
    loadsheet_service = ListingLoadsheetService(
        storage_root=Path(tempfile.gettempdir()) / "xiaohei-listing-smoke-loadsheets"
    )
    category = {
        "category_id": 123,
        "path_en": "Electronics > Accessories > Mobile Phone Cases",
        "path_zh": "电子产品 > 配件 > 手机壳",
        "min_required_images": 1,
        "loadsheet_template_id": "smoke-template",
        "loadsheet_template_name": "Smoke Template",
        "compliance_certificates": [],
    }
    allowed_attributes = [
        {
            "key": "Colour",
            "label": "Colour",
            "value_type": "select",
            "options": ["Black", "White"],
            "required": True,
        }
    ]
    request = ListingLoadsheetPreviewRequest(
        store_id="00000000-0000-0000-0000-000000000000",
        category_id=123,
        brand_name="Smoke Brand",
        sku="SMOKE-SKU",
        barcode="1234567890123",
        title="Smoke Product",
        subtitle="Smoke subtitle",
        description="A conservative smoke product description.",
        whats_in_the_box="1 x Smoke Product",
        selling_price=100,
        rrp=120,
        stock_quantity=5,
        minimum_leadtime_days=2,
        seller_warehouse_id="WH1",
        length_cm=10,
        width_cm=8,
        height_cm=4,
        weight_g=250,
        image_urls=["https://example.com/smoke.jpg"],
        dynamic_attributes={"Colour": "Black"},
    )
    valid_result = loadsheet_service.validate_payload(
        request=request,
        category=category,
        allowed_attributes=allowed_attributes,
        assets=[],
        brand={"brand_id": "smoke", "brand_name": "Smoke Brand"},
        brand_catalog_ready=True,
    )
    invalid_result = loadsheet_service.validate_payload(
        request=request.model_copy(update={"dynamic_attributes": {"BadKey": "Value"}}),
        category=category,
        allowed_attributes=allowed_attributes,
        assets=[],
        brand={"brand_id": "smoke", "brand_name": "Smoke Brand"},
        brand_catalog_ready=True,
    )
    preview_result = loadsheet_service.build_preview(
        request=request,
        category=category,
        allowed_attributes=allowed_attributes,
        assets=[],
        brand={"brand_id": "smoke", "brand_name": "Smoke Brand"},
        brand_catalog_ready=True,
    )
    preview_asset = preview_result["loadsheet_asset"] or {}
    preview_path = Path(preview_asset.get("storage_path") or "")
    return {
        "valid_payload_passed": bool(valid_result["valid"]),
        "invalid_dynamic_attribute_rejected": any(
            issue["field"] == "dynamic_attributes.BadKey" for issue in invalid_result["issues"]
        ),
        "missing_required_attribute_rejected": any(
            issue["field"] == "dynamic_attributes.Colour" for issue in invalid_result["issues"]
        ),
        "xlsx_generated": preview_path.exists() and preview_asset.get("size_bytes", 0) > 0,
    }


def normalize_attribute_definitions(category: dict[str, Any]) -> list[dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for required, values in (
        (True, category.get("required_attributes") or []),
        (False, category.get("optional_attributes") or []),
    ):
        for item in values:
            definition = normalize_attribute_definition(item, required=required)
            if definition is not None:
                definitions[definition["key"]] = definition
    return list(definitions.values())


def normalize_attribute_definition(item: Any, *, required: bool) -> dict[str, Any] | None:
    if isinstance(item, str):
        key = item.strip()
        if not key:
            return None
        return {"key": key, "label": key, "value_type": "text", "options": [], "required": required}
    if not isinstance(item, dict):
        return None
    key = (
        item.get("key")
        or item.get("name")
        or item.get("attribute_key")
        or item.get("attribute_name")
        or item.get("field_name")
        or item.get("display_name")
        or item.get("id")
    )
    key = str(key or "").strip()
    if not key:
        return None
    raw_type = str(
        item.get("value_type") or item.get("type") or item.get("data_type") or item.get("input_type") or "text"
    ).strip().lower()
    if raw_type in {"bool", "boolean", "checkbox"}:
        value_type = "boolean"
    elif raw_type in {"int", "integer", "number", "numeric", "decimal", "float"}:
        value_type = "number"
    elif raw_type in {"select", "enum", "dropdown", "option"}:
        value_type = "select"
    else:
        value_type = "text"
    options = normalize_attribute_options(
        item.get("options") or item.get("values") or item.get("allowed_values") or item.get("enum") or []
    )
    if options and value_type == "text":
        value_type = "select"
    return {
        "key": key,
        "label": str(item.get("label") or item.get("display_name") or key),
        "value_type": value_type,
        "options": options,
        "required": bool(item.get("required", required)),
    }


def normalize_attribute_options(values: Any) -> list[Any]:
    if isinstance(values, str):
        values = [part.strip() for part in values.replace("|", ",").replace(";", ",").split(",") if part.strip()]
    if not isinstance(values, list):
        return []
    options: list[Any] = []
    for value in values:
        option = value.get("value") or value.get("name") or value.get("label") if isinstance(value, dict) else value
        if option not in (None, "") and option not in options:
            options.append(option)
    return options


def sample_dynamic_attributes(allowed_attributes: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for attribute in allowed_attributes:
        if not attribute.get("required"):
            continue
        key = attribute["key"]
        options = attribute.get("options") or []
        value_type = attribute.get("value_type") or "text"
        if options:
            payload[key] = options[0]
        elif value_type == "boolean":
            payload[key] = "No"
        elif value_type == "number":
            payload[key] = 1
        else:
            payload[key] = "Smoke value"
    return payload


def main() -> None:
    pure_checks = run_pure_checks()
    repository = ListingCatalogRepository()

    try:
        categories, _, catalog_ready = repository.search_categories(query=None, page=1, page_size=1)
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
                    "message": "Takealot category catalog import required",
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
                    "message": "No store found for loadsheet preview smoke.",
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)

    category = categories[0]
    required_images = max(1, int(category.get("min_required_images") or 0))
    allowed_attributes = normalize_attribute_definitions(category)
    request = ListingLoadsheetPreviewRequest(
        store_id=store["id"],
        category_id=int(category["category_id"]),
        sku="SMOKE-LOADSHEET",
        barcode="1234567890123",
        title="Smoke Loadsheet Product",
        subtitle="Smoke subtitle",
        description="A conservative smoke product description for Takealot review.",
        whats_in_the_box="1 x Smoke Loadsheet Product",
        selling_price=100,
        rrp=120,
        stock_quantity=5,
        minimum_leadtime_days=2,
        seller_warehouse_id="WH1",
        length_cm=10,
        width_cm=8,
        height_cm=4,
        weight_g=250,
        image_urls=[f"https://example.com/smoke-{index}.jpg" for index in range(required_images)],
        dynamic_attributes=sample_dynamic_attributes(allowed_attributes),
    )
    result = ListingLoadsheetService().build_preview(
        request=request,
        category=category,
        allowed_attributes=allowed_attributes,
        assets=[],
        brand=None,
        brand_catalog_ready=True,
    )
    passed = all(pure_checks.values()) and bool(result["loadsheet_asset"]) and bool(result["generated_fields"])
    print(
        json.dumps(
            {
                "passed": passed,
                "pure_checks": pure_checks,
                "db_category_checked": True,
                "category_id": category["category_id"],
                "valid": result["valid"],
                "issue_count": len(result["issues"]),
                "loadsheet_asset": result["loadsheet_asset"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
