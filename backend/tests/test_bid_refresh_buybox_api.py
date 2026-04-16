from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from app.api import bids as bids_api
from app.api import deps


class _FakeDb:
    async def flush(self) -> None:
        return None


def test_refresh_buybox_endpoint_returns_latest_buybox(monkeypatch):
    app = create_app()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db():
        yield _FakeDb()

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db

    store = SimpleNamespace(
        id=2,
        store_name="King store",
        store_alias="",
        takealot_store_id="29897844",
        is_active=1,
    )
    product = SimpleNamespace(
        id=40,
        offer_id="231968285",
        sku="9902319682858",
        plid="PLID101180179",
        title="Sparkling Angel Eye Zircon Bracelet",
        floor_price_zar=500,
        target_price_zar=None,
        current_price_zar=528.0,
        buybox_price_zar=505.0,
        auto_bid_enabled=1,
        last_action="raised",
        brand="",
        image_url="",
        takealot_url="",
        api_status="",
        offer_status="Buyable",
        buybox_store="King store",
        last_checked_at=None,
    )

    async def _fake_require_store(db, store_id: int, user_id: int):
        return store

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return product

    async def _fake_fetch_product_detail(plid: str):
        return {
            "ok": True,
            "buybox_price": 528.0,
            "buybox_seller": "King store",
            "buybox_seller_id": "29897844",
            "buybox_offer_id": "231968285",
            "next_offer_price": 529.0,
            "takealot_url": "https://www.takealot.com/sparkling-angel-eye-zircon-bracelet-luxury-silver-fashion-jewelr/PLID101180179",
        }

    monkeypatch.setattr(bids_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(bids_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr("app.services.buybox_service.fetch_product_detail", _fake_fetch_product_detail)

    client = TestClient(app)
    response = client.post("/api/bids/2/products/231968285/refresh-buybox")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["product"]["buybox_price_zar"] == 528.0
    assert payload["product"]["buybox_store"] == "King store"
    assert payload["product"]["takealot_url"].endswith("/PLID101180179")


def test_refresh_all_buybox_endpoint_returns_summary(monkeypatch):
    app = create_app()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db():
        yield _FakeDb()

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db

    store = SimpleNamespace(
        id=2,
        store_name="King store",
        store_alias="",
        takealot_store_id="29897844",
        is_active=1,
    )

    async def _fake_require_store(db, store_id: int, user_id: int):
        return store

    async def _fake_refresh_store_buybox(db, store_arg):
        assert store_arg is store
        return {
            "total": 42,
            "refreshed": 40,
            "failed": 1,
            "skipped": 1,
        }

    monkeypatch.setattr(bids_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(bids_api.bid_service, "refresh_store_buybox", _fake_refresh_store_buybox)

    client = TestClient(app)
    response = client.post("/api/bids/2/products/refresh-buybox-all")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "ok": True,
        "total": 42,
        "refreshed": 40,
        "failed": 1,
        "skipped": 1,
    }
