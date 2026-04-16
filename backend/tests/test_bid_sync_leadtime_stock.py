from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import bid_service


class _FakeDb:
    def __init__(self):
        self.added = []
        self.flush_count = 0

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flush_count += 1


@pytest.mark.asyncio
async def test_sync_bid_products_persists_leadtime_stock_as_dropship_stock(monkeypatch):
    fake_db = _FakeDb()
    store = SimpleNamespace(id=2, api_key="encrypted-key", offer_count=0, last_synced_at=None)

    class _FakeApi:
        def __init__(self, api_key):
            assert api_key == "plain-key"

        async def get_all_offers(self):
            return [
                {
                    "offer_id": "231968285",
                    "sku": "9902319682858",
                    "product_title": "Sparkling Angel Eye Zircon Bracelet",
                    "status": "Buyable",
                    "leadtime_days": 14,
                    "leadtime_stock": [{"quantity_available": 1}],
                    "selling_price": 528,
                    "rrp": 2000,
                    "stock_at_takealot_total": 0,
                    "total_stock_on_way": 0,
                },
            ]

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return None

    monkeypatch.setattr("app.utils.encryption.decrypt", lambda value: "plain-key")
    monkeypatch.setattr(bid_service, "TakealotSellerAPI", _FakeApi)
    monkeypatch.setattr(bid_service, "get_bid_product", _fake_get_bid_product)

    result = await bid_service.sync_bid_products(fake_db, store)

    assert result["synced"] == 1
    assert fake_db.added
    product = fake_db.added[0]
    assert product.offer_id == "231968285"
    assert product.offer_status == "Buyable"
    assert product.dropship_stock == 1
    assert product.buybox_store_stock == "Ships in 14 work days"
    assert store.offer_count == 1


@pytest.mark.asyncio
async def test_sync_bid_products_treats_buyable_without_leadtime_stock_as_not_buyable(monkeypatch):
    fake_db = _FakeDb()
    store = SimpleNamespace(id=2, api_key="encrypted-key", offer_count=0, last_synced_at=None)

    class _FakeApi:
        def __init__(self, api_key):
            pass

        async def get_all_offers(self):
            return [
                {
                    "offer_id": "231968286",
                    "sku": "9902319682865",
                    "product_title": "Bracelet without leadtime stock",
                    "status": "Buyable",
                    "leadtime_days": None,
                    "leadtime_stock": [],
                    "selling_price": 528,
                    "rrp": 2000,
                    "stock_at_takealot_total": 0,
                    "total_stock_on_way": 0,
                },
            ]

    async def _fake_get_bid_product(db, store_id: int, offer_id: str):
        return None

    monkeypatch.setattr("app.utils.encryption.decrypt", lambda value: "plain-key")
    monkeypatch.setattr(bid_service, "TakealotSellerAPI", _FakeApi)
    monkeypatch.setattr(bid_service, "get_bid_product", _fake_get_bid_product)

    result = await bid_service.sync_bid_products(fake_db, store, sync_mode=bid_service.PRODUCT_SYNC_MODE_CATALOG)

    assert result["synced"] == 1
    product = fake_db.added[0]
    assert product.offer_status == "Not Buyable"
    assert product.dropship_stock == 0
