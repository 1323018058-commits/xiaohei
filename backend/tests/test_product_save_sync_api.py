from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from app.api import deps
from app.api import products as products_api


class _FakeDb:
    def __init__(self):
        self.flush_count = 0

    async def flush(self):
        self.flush_count += 1


def _fake_product() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        offer_id="232783053",
        sku="SKU-232783053",
        plid="PLID-232783053",
        title="Product 232783053",
        brand="Brand",
        current_price_zar=1212.0,
        rrp_zar=1212.0,
        dropship_stock=0,
        offer_status="Not Buyable",
        api_status="",
        buybox_price_zar=1212.0,
        buybox_store="",
        floor_price_zar=0.0,
        target_price_zar=1212.0,
        image_url="",
        takealot_url="https://www.takealot.com/x/PLID232783053",
        procurement_price_cny=None,
        procurement_url="",
        product_weight_g=None,
    )


def test_product_save_sync_updates_price_rrp_status_and_stock(monkeypatch):
    app = create_app()
    fake_db = _FakeDb()
    product = _fake_product()
    captured = {}

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    async def _fake_require_store(db, store_id: int, user_id: int):
        return SimpleNamespace(id=store_id, store_name="King store", store_alias="")

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        assert store_id == 2
        assert offer_id == "232783053"
        return product

    class _FakeApi:
        async def get_merchant_warehouses(self, validated: bool = True):
            assert validated is True
            return {
                "merchant_warehouses": [
                    {"merchant_warehouse_id": 58790},
                ]
            }

        async def update_offer_fields(self, offer_id: str, fields: dict):
            captured["offer_id"] = offer_id
            captured["fields"] = fields
            return True, {
                "offer": {
                    "offer_id": offer_id,
                    "status": "Buyable",
                    "selling_price": 1299,
                    "rrp": 1499,
                    "leadtime_days": 14,
                    "leadtime_stock": [
                        {
                            "merchant_warehouse": {"warehouse_id": 58790, "name": None},
                            "quantity_available": 12,
                        },
                    ],
                },
                "validation_errors": [],
            }

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.post(
        "/api/products/2/232783053/save-sync",
        json={
            "selling_price_zar": 1299,
            "rrp_zar": 1499,
            "offer_status": "Buyable",
            "dropship_stock": 12,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["sync_result"] == "ok"
    assert captured == {
        "offer_id": "232783053",
        "fields": {
            "selling_price": 1299,
            "rrp": 1499,
            "leadtime_days": 14,
            "leadtime_stock": [
                {"merchant_warehouse_id": 58790, "quantity": 12},
            ],
        },
    }
    assert product.current_price_zar == 1299
    assert product.rrp_zar == 1499
    assert product.offer_status == "Buyable"
    assert product.dropship_stock == 12
    assert fake_db.flush_count == 1


def test_product_save_sync_rejects_when_takealot_keeps_old_stock(monkeypatch):
    app = create_app()
    fake_db = _FakeDb()
    product = _fake_product()
    product.offer_status = "Buyable"
    product.dropship_stock = 1

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    async def _fake_require_store(db, store_id: int, user_id: int):
        return SimpleNamespace(id=store_id, store_name="King store", store_alias="")

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return product

    class _FakeApi:
        async def get_merchant_warehouses(self, validated: bool = True):
            return {"merchant_warehouses": [{"merchant_warehouse_id": 58790}]}

        async def get_offer_detail(self, offer_id: str):
            return {
                "offer_id": offer_id,
                "status": "Buyable",
                "leadtime_days": 14,
                "leadtime_stock": [
                    {
                        "merchant_warehouse": {"warehouse_id": 58790, "name": None},
                        "quantity_available": 1,
                    },
                ],
            }

        async def update_offer_fields(self, offer_id: str, fields: dict):
            return True, {
                "offer": {
                    "offer_id": offer_id,
                    "status": "Buyable",
                    "leadtime_days": 14,
                    "leadtime_stock": [
                        {
                            "merchant_warehouse": {"warehouse_id": 58790, "name": None},
                            "quantity_available": 1,
                        },
                    ],
                },
                "validation_errors": [],
            }

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.post(
        "/api/products/2/232783053/save-sync",
        json={"dropship_stock": 10},
    )

    assert response.status_code == 502
    assert "库存同步未生效" in response.json()["detail"]
    assert product.dropship_stock == 1
    assert fake_db.flush_count == 0


def test_product_save_sync_updates_only_leadtime_stock(monkeypatch):
    app = create_app()
    fake_db = _FakeDb()
    product = _fake_product()
    product.offer_status = "Buyable"
    product.dropship_stock = 1
    captured = {}

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    async def _fake_require_store(db, store_id: int, user_id: int):
        return SimpleNamespace(id=store_id, store_name="King store", store_alias="")

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return product

    class _FakeApi:
        async def get_merchant_warehouses(self, validated: bool = True):
            return {"merchant_warehouses": [{"merchant_warehouse_id": 58790}]}

        async def update_offer_fields(self, offer_id: str, fields: dict):
            captured["offer_id"] = offer_id
            captured["fields"] = fields
            return True, {
                "offer": {
                    "offer_id": offer_id,
                    "status": "Buyable",
                    "leadtime_days": 14,
                    "leadtime_stock": [
                        {
                            "merchant_warehouse": {"warehouse_id": 58790, "name": None},
                            "quantity_available": 10,
                        },
                    ],
                },
                "validation_errors": [],
            }

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.post(
        "/api/products/2/232783053/save-sync",
        json={"dropship_stock": 10},
    )

    assert response.status_code == 200
    assert captured == {
        "offer_id": "232783053",
        "fields": {
            "leadtime_stock": [
                {"merchant_warehouse_id": 58790, "quantity": 10},
            ],
        },
    }
    assert product.offer_status == "Buyable"
    assert product.dropship_stock == 10
    assert response.json()["product"]["dropship_stock"] == 10
    assert fake_db.flush_count == 1


def test_product_save_sync_can_clear_leadtime_to_none(monkeypatch):
    app = create_app()
    fake_db = _FakeDb()
    product = _fake_product()
    product.offer_status = "Buyable"
    product.dropship_stock = 10
    captured = {}

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    async def _fake_require_store(db, store_id: int, user_id: int):
        return SimpleNamespace(id=store_id, store_name="King store", store_alias="")

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return product

    class _FakeApi:
        async def get_offer_detail(self, offer_id: str):
            return {
                "offer_id": offer_id,
                "leadtime_days": 14,
                "leadtime_stock": [
                    {
                        "merchant_warehouse": {"warehouse_id": 58790, "name": None},
                        "quantity_available": 10,
                    },
                ],
            }

        async def get_merchant_warehouses(self, validated: bool = True):
            return {"merchant_warehouses": [{"merchant_warehouse_id": 58790}]}

        async def update_offer_fields(self, offer_id: str, fields: dict):
            captured["offer_id"] = offer_id
            captured["fields"] = fields
            return True, {
                "offer": {
                    "offer_id": offer_id,
                    "status": "Not Buyable",
                    "leadtime_days": None,
                    "leadtime_stock": [],
                },
                "validation_errors": [],
            }

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.post(
        "/api/products/2/232783053/save-sync",
        json={"leadtime_days": None, "dropship_stock": 0},
    )

    assert response.status_code == 200
    assert captured == {
        "offer_id": "232783053",
        "fields": {
            "leadtime_days": -1,
            "leadtime_stock": [
                {"merchant_warehouse_id": 58790, "quantity": 0},
            ],
        },
    }
    payload = response.json()
    assert payload["product"]["leadtime_days"] is None
    assert payload["product"]["offer_status"] == "Not Buyable"
    assert payload["product"]["status_group"] == "Not Buyable"
    assert product.offer_status == "Not Buyable"
    assert fake_db.flush_count == 1


def test_product_save_sync_rejects_stock_when_no_merchant_warehouse(monkeypatch):
    app = create_app()
    fake_db = _FakeDb()
    product = _fake_product()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    async def _fake_require_store(db, store_id: int, user_id: int):
        return SimpleNamespace(id=store_id, store_name="King store", store_alias="")

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return product

    class _FakeApi:
        async def get_merchant_warehouses(self, validated: bool = True):
            return {"merchant_warehouses": []}

        async def update_offer_fields(self, offer_id: str, fields: dict):
            raise AssertionError("should not call update_offer_fields without warehouse")

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.post(
        "/api/products/2/232783053/save-sync",
        json={"dropship_stock": 12},
    )

    assert response.status_code == 409
    assert "仓库" in response.json()["detail"]


def test_product_save_sync_rejects_buyable_when_stock_is_not_positive(monkeypatch):
    app = create_app()
    fake_db = _FakeDb()
    product = _fake_product()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    async def _fake_require_store(db, store_id: int, user_id: int):
        return SimpleNamespace(id=store_id, store_name="King store", store_alias="")

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return product

    class _FakeApi:
        async def get_merchant_warehouses(self, validated: bool = True):
            return {"merchant_warehouses": [{"merchant_warehouse_id": 58790}]}

        async def update_offer_fields(self, offer_id: str, fields: dict):
            raise AssertionError("stock <= 0 should be rejected before remote sync")

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.post(
        "/api/products/2/232783053/save-sync",
        json={"offer_status": "Buyable"},
    )

    assert response.status_code == 400
    assert "库存" in response.json()["detail"]


def test_product_save_sync_can_disable_by_seller(monkeypatch):
    app = create_app()
    fake_db = _FakeDb()
    product = _fake_product()
    captured = {}

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db_dep():
        yield fake_db

    async def _fake_require_store(db, store_id: int, user_id: int):
        return SimpleNamespace(id=store_id, store_name="King store", store_alias="")

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return product

    class _FakeApi:
        async def get_merchant_warehouses(self, validated: bool = True):
            return {"merchant_warehouses": [{"merchant_warehouse_id": 58790}]}

        async def update_offer_fields(self, offer_id: str, fields: dict):
            captured["offer_id"] = offer_id
            captured["fields"] = fields
            return True, {
                "offer": {
                    "offer_id": offer_id,
                    "status": "Disabled by Seller",
                },
                "validation_errors": [],
            }

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db_dep

    monkeypatch.setattr(products_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(products_api.bid_service, "get_bid_product", _fake_get_bid_product)
    monkeypatch.setattr(products_api.store_service, "get_takealot_api", lambda _store: _FakeApi())

    client = TestClient(app)
    response = client.post(
        "/api/products/2/232783053/save-sync",
        json={"offer_status": "Disabled by Seller"},
    )

    assert response.status_code == 200
    assert captured == {
        "offer_id": "232783053",
        "fields": {
            "status": "Disabled by Seller",
        },
    }
