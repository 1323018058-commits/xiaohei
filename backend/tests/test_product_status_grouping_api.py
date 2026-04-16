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
        target_price_zar=99.0,
        auto_bid_enabled=1,
        procurement_price_cny=None,
        procurement_url="",
        product_weight_g=None,
        last_checked_at=None,
    )


def test_product_list_groups_buyable_not_buyable_and_off_shelf(monkeypatch):
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

    async def _fake_list_store_products(db, store_id: int, **_kwargs):
        return [
            _fake_product(offer_id="101", offer_status="Buyable"),
            _fake_product(offer_id="102", offer_status="Not Buyable"),
            _fake_product(offer_id="103", offer_status="Disabled by Seller"),
            _fake_product(offer_id="104", offer_status="Disabled by Takealot"),
        ], 4

    async def _fake_count_store_products_by_status(db, store_id: int, **_kwargs):
        return {
            "all": 4,
            "buyable": 1,
            "not_buyable": 1,
            "off_shelf": 2,
        }

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "list_store_products", _fake_list_store_products)
    monkeypatch.setattr(products_api.bid_service, "count_store_products_by_status", _fake_count_store_products_by_status)

    client = TestClient(app)
    response = client.get("/api/products/2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True

    by_offer_id = {item["offer_id"]: item for item in payload["products"]}

    assert by_offer_id["101"]["status_group"] == "Buyable"
    assert by_offer_id["101"]["status_label"] == "在售"
    assert by_offer_id["102"]["status_group"] == "Not Buyable"
    assert by_offer_id["102"]["status_label"] == "不可购买"
    assert by_offer_id["103"]["status_group"] == "OffShelf"
    assert by_offer_id["103"]["status_label"] == "已下架"
    assert by_offer_id["104"]["status_group"] == "OffShelf"
    assert by_offer_id["104"]["status_label"] == "已下架"


def test_product_list_does_not_show_buyable_when_local_stock_is_zero(monkeypatch):
    app = create_app()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db

    store = SimpleNamespace(id=2, store_name="King store", store_alias="")

    async def _fake_require_store(db, store_id: int, user_id: int):
        return store

    item = _fake_product(offer_id="201", offer_status="Buyable")
    item.dropship_stock = 0

    async def _fake_list_store_products(db, store_id: int, **_kwargs):
        return [item], 1

    async def _fake_count_store_products_by_status(db, store_id: int, **_kwargs):
        return {
            "all": 1,
            "buyable": 0,
            "not_buyable": 1,
            "off_shelf": 0,
        }

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "list_store_products", _fake_list_store_products)
    monkeypatch.setattr(products_api.bid_service, "count_store_products_by_status", _fake_count_store_products_by_status)

    client = TestClient(app)
    response = client.get("/api/products/2")

    assert response.status_code == 200
    product = response.json()["products"][0]
    assert product["status_group"] == "Not Buyable"
    assert product["status_label"] == "不可购买"
    assert product["offer_status"] == "Not Buyable"


def test_product_detail_refreshes_local_status_from_remote_leadtime_stock(monkeypatch):
    app = create_app()

    class _FakeDb:
        def __init__(self):
            self.flush_count = 0

        async def flush(self):
            self.flush_count += 1

    fake_db = _FakeDb()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    store = SimpleNamespace(id=2, store_name="King store", store_alias="")

    async def _fake_require_store(db, store_id: int, user_id: int):
        return store

    product = _fake_product(offer_id="231968285", offer_status="Buyable")
    product.dropship_stock = 0

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        assert offer_id == "231968285"
        return product

    async def _fake_list_bid_log_for_offer(db, store_id: int, offer_id: str, limit: int = 5):
        return []

    class _FakeApi:
        async def get_offer_detail(self, offer_id: str):
            assert offer_id == "231968285"
            return {
                "offer_id": "231968285",
                "status": "Buyable",
                "leadtime_days": 14,
                "leadtime_stock": [{"quantity_available": 1}],
                "selling_price": 528,
                "rrp": 2000,
            }

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.bid_service, "list_bid_log_for_offer", _fake_list_bid_log_for_offer)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.get("/api/products/2/231968285")

    assert response.status_code == 200
    payload = response.json()["product"]
    assert payload["status_group"] == "Buyable"
    assert payload["status_label"] == "在售"
    assert payload["offer_status"] == "Buyable"
    assert payload["dropship_stock"] == 1
    assert payload["leadtime_days"] == 14
    assert product.dropship_stock == 1
    assert product.offer_status == "Buyable"
    assert product.current_price_zar == 528
    assert product.rrp_zar == 2000
    assert fake_db.flush_count == 1
