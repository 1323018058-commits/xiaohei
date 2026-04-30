from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.store.adapters.base import (  # noqa: E402
    AdapterAuthError,
    AdapterCredentials,
    AdapterTemporaryError,
)
from src.modules.store.adapters.takealot import TakealotAdapter  # noqa: E402


def assert_takealot_success() -> int:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/offers"
        assert request.headers["X-API-Key"] == "takealot-key"
        continuation_token = request.url.params.get("continuation_token")
        if not continuation_token:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "offer_id": 101,
                            "sku": "TL-SKU-101",
                            "selling_price": 199,
                            "seller_warehouse_stock": [{"quantity_available": 3}],
                            "takealot_warehouse_stock": [{"quantity_available": 5}],
                            "title": "Takealot Mock Product",
                        }
                    ],
                    "continuation_token": "next-page",
                },
            )
        return httpx.Response(200, json={"items": []})

    adapter = TakealotAdapter(
        AdapterCredentials(
            platform="takealot",
            api_key="takealot-key",
            api_secret="unused-secret",
        ),
        base_url="https://marketplace-api.takealot.com/v1",
        transport=httpx.MockTransport(handler),
    )
    listings = adapter.fetch_listings()
    assert len(listings) == 1, listings
    assert listings[0].external_listing_id == "101", listings[0]
    assert listings[0].sku == "TL-SKU-101", listings[0]
    assert listings[0].title == "Takealot Mock Product", listings[0]
    assert listings[0].platform_price == 199.0, listings[0]
    assert listings[0].stock_quantity == 5, listings[0]
    return len(listings)


def assert_failure_mapping() -> dict[str, str]:
    failures: dict[str, str] = {}

    takealot_auth = TakealotAdapter(
        AdapterCredentials("takealot", "bad", "unused"),
        transport=httpx.MockTransport(lambda _: httpx.Response(403, json={"message": "forbidden"})),
    )
    try:
        takealot_auth.fetch_listings()
    except AdapterAuthError as exc:
        failures["takealot_403"] = exc.__class__.__name__

    takealot_503 = TakealotAdapter(
        AdapterCredentials("takealot", "key", "unused"),
        transport=httpx.MockTransport(lambda _: httpx.Response(503, json={"message": "down"})),
    )
    try:
        takealot_503.fetch_listings()
    except AdapterTemporaryError as exc:
        failures["takealot_503"] = exc.__class__.__name__

    assert failures == {
        "takealot_403": "AdapterAuthError",
        "takealot_503": "AdapterTemporaryError",
    }, failures
    return failures


def assert_offer_create_update() -> dict[str, object]:
    requests_seen: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        requests_seen.append((request.method, request.url.path, body))

        if request.method == "GET" and request.url.path == "/v1/offers/by_barcode/6001234567890":
            return httpx.Response(404, json={"message": "not found"})
        if request.method == "GET" and request.url.path == "/v1/seller":
            return httpx.Response(
                200,
                json={
                    "warehouses": [
                        {"seller_warehouse_id": 4321, "name": "Main Warehouse"}
                    ]
                },
            )
        if request.method == "POST" and request.url.path == "/v1/offers":
            return httpx.Response(
                201,
                json={
                    "offer_id": 555001,
                    "sku": body.get("sku"),
                    "selling_price": body.get("selling_price"),
                    "title": "Created Offer",
                },
            )
        if request.method == "GET" and request.url.path == "/v1/offers/by_barcode/6000000000001":
            return httpx.Response(
                200,
                json={
                    "offer_id": 888002,
                    "sku": "EXISTING-SKU",
                    "selling_price": 199,
                    "title": "Existing Offer",
                },
            )
        if request.method == "PATCH" and request.url.path == "/v1/offers/by_barcode/6000000000001":
            return httpx.Response(
                200,
                json={
                    "offer_id": 888002,
                    "sku": body.get("sku"),
                    "selling_price": body.get("selling_price"),
                    "title": "Updated Offer",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    adapter = TakealotAdapter(
        AdapterCredentials(
            platform="takealot",
            api_key="takealot-key",
            api_secret="unused-secret",
        ),
        base_url="https://marketplace-api.takealot.com/v1",
        transport=httpx.MockTransport(handler),
    )
    created = adapter.create_or_update_offer(
        barcode="6001234567890",
        sku="NEW-SKU-001",
        selling_price=299.0,
        quantity=3,
        minimum_leadtime_days=3,
    )
    updated = adapter.create_or_update_offer(
        barcode="6000000000001",
        sku="UPDATED-SKU-001",
        selling_price=279.0,
        quantity=5,
        minimum_leadtime_days=3,
    )

    create_request = next(
        request
        for request in requests_seen
        if request[0] == "POST" and request[1] == "/v1/offers"
    )
    patch_request = next(
        request
        for request in requests_seen
        if request[0] == "PATCH" and request[1] == "/v1/offers/by_barcode/6000000000001"
    )

    assert create_request[2]["barcode"] == "6001234567890"
    assert create_request[2]["seller_warehouse_stock"][0]["seller_warehouse_id"] == 4321
    assert patch_request[2]["sku"] == "UPDATED-SKU-001"

    return {
        "created_offer_id": created["offer_id"],
        "updated_offer_id": updated["offer_id"],
        "request_count": len(requests_seen),
    }


def main() -> None:
    result = {
        "takealot_listing_count": assert_takealot_success(),
        "failures": assert_failure_mapping(),
        "offer_create_update": assert_offer_create_update(),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
