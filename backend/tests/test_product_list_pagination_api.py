from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from app.api import deps
from app.api import products as products_api


def _fake_product(*, offer_id: str, offer_status: str, api_status: str = ""):
    return SimpleNamespace(
        id=int(offer_id),
        offer_id=offer_id,
        sku=f"SKU-{offer_id}",
        plid=f"PLID-{offer_id}",
        title=f"Product {offer_id}",
        current_price_zar=99.0,
        rrp_zar=129.0,
        dropship_stock=8,
        offer_status=offer_status,
        api_status=api_status,
        buybox_price_zar=99.0,
        buybox_store="",
        brand="Brand",
        image_url="",
        takealot_url="",
        floor_price_zar=0.0,
        auto_bid_enabled=1,
        procurement_price_cny=None,
        procurement_url="",
        last_checked_at=None,
    )


def test_product_list_supports_server_pagination_and_status_counts(monkeypatch):
    app = create_app()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db

    store = SimpleNamespace(
        id=2,
        store_name="King store",
        store_alias="",
    )

    async def _fake_require_store(db, store_id: int, user_id: int):
        return store

    async def _fake_list_store_products(db, store_id: int, **kwargs):
        assert store_id == 2
        assert kwargs["page"] == 2
        assert kwargs["page_size"] == 1
        assert kwargs["sku"] == "bracelet"
        assert kwargs["status"] == "OffShelf"
        return [
            _fake_product(offer_id="103", offer_status="Disabled by Seller"),
        ], 18

    async def _fake_count_store_products_by_status(db, store_id: int, **kwargs):
        assert store_id == 2
        assert kwargs["sku"] == "bracelet"
        return {
            "all": 42,
            "buyable": 1,
            "not_buyable": 23,
            "off_shelf": 18,
        }

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "list_store_products", _fake_list_store_products)
    monkeypatch.setattr(products_api.bid_service, "count_store_products_by_status", _fake_count_store_products_by_status)

    client = TestClient(app)
    response = client.get("/api/products/2?page=2&page_size=1&q=bracelet&status=OffShelf")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["page"] == 2
    assert payload["page_size"] == 1
    assert payload["total"] == 18
    assert payload["counts"] == {
        "all": 42,
        "buyable": 1,
        "not_buyable": 23,
        "off_shelf": 18,
    }
    assert len(payload["products"]) == 1
    assert payload["products"][0]["status_group"] == "OffShelf"
