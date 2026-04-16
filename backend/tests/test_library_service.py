from __future__ import annotations

import json
from sqlalchemy.dialects import postgresql
import pytest

from app.services import library_service


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, _ttl: int, value: str):
        self.store[key] = value

    async def delete(self, *keys: str):
        for key in keys:
            self.store.pop(key, None)


class _FakeDb:
    def __init__(self):
        self.commit_count = 0

    async def commit(self):
        self.commit_count += 1


class _EmptyResult:
    def all(self):
        return []


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _OneResult:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class _CaptureQueryDb:
    def __init__(self):
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)
        return _EmptyResult()


class _StatsDb:
    def __init__(self, stats_row, quarantined: int):
        self.stats_row = stats_row
        self.quarantined = quarantined
        self.call_count = 0

    async def execute(self, query):
        del query
        self.call_count += 1
        if self.call_count == 1:
            return _OneResult(self.stats_row)
        return _ScalarResult(self.quarantined)


def _raw_product(product_id: int, *, title: str, slug: str, price: float, status: str):
    return {
        "product_views": {
            "core": {
                "id": product_id,
                "title": title,
                "slug": slug,
                "brand": "",
            },
            "stock_availability_summary": {
                "status": status,
            },
            "buybox_summary": {
                "product_id": product_id,
                "prices": [price],
                "listing_price": price,
                "pretty_price": f"R {price:.2f}",
                "saving": "",
                "is_preorder": status.lower().startswith("pre-order"),
            },
            "gallery": {
                "images": [f"https://images.example/{product_id}-{{size}}.jpg"],
            },
            "review_summary": {
                "star_rating": 0,
                "review_count": 0,
                "distribution": {},
            },
        },
    }


@pytest.mark.asyncio
async def test_scrape_to_library_uses_department_slug_but_keeps_display_category(monkeypatch):
    fake_db = _FakeDb()
    fake_redis = _FakeRedis()
    calls: list[dict] = []
    captured_batches: list[list[dict]] = []

    async def _fake_fetch_api(_client, params, retries=library_service.MAX_RETRIES):
        del retries
        calls.append(dict(params))
        return {
            "sections": {
                "products": {
                    "results": [
                        _raw_product(
                            1001,
                            title="Kitchen Storage Box",
                            slug="kitchen-storage-box",
                            price=199,
                            status="Ships in 7 - 10 work days",
                        )
                    ],
                    "paging": {
                        "next_is_after": "",
                    },
                }
            }
        }

    async def _fake_upsert_library_batch(_db, batch):
        captured_batches.append(list(batch))
        return len(batch)

    async def _fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(library_service, "_fetch_api", _fake_fetch_api)
    monkeypatch.setattr(library_service, "_upsert_library_batch", _fake_upsert_library_batch)
    monkeypatch.setattr(library_service, "_async_sleep", _fake_sleep)

    total = await library_service.scrape_to_library(
        db=fake_db,
        redis=fake_redis,
        user_id=7,
        categories=["Home & Kitchen"],
        lead_min=0,
        lead_max=999,
        min_price=0,
        max_price=100000,
        max_per_cat=1,
    )

    assert total == 1
    assert fake_db.commit_count == 1
    assert calls
    assert calls[0]["department_slug"] == "home-kitchen"
    assert "Department:" not in calls[0]["filter"]
    assert len(captured_batches) == 1
    assert len(captured_batches[0]) == 1
    assert captured_batches[0][0]["product_id"] == 1001
    assert captured_batches[0][0]["category_main"] == "Home & Kitchen"


@pytest.mark.asyncio
async def test_scrape_to_library_filters_leadtime_locally(monkeypatch):
    fake_db = _FakeDb()
    fake_redis = _FakeRedis()
    captured_batches: list[list[dict]] = []

    async def _fake_fetch_api(_client, params, retries=library_service.MAX_RETRIES):
        del params, retries
        return {
            "sections": {
                "products": {
                    "results": [
                        _raw_product(
                            2001,
                            title="Children's Book",
                            slug="childrens-book",
                            price=179,
                            status="Ships in 7 - 10 work days",
                        ),
                        _raw_product(
                            2002,
                            title="Future Preorder Book",
                            slug="future-preorder-book",
                            price=245,
                            status="Pre-order: Ships 12 Jan, 2027",
                        ),
                    ],
                    "paging": {
                        "next_is_after": "",
                    },
                }
            }
        }

    async def _fake_upsert_library_batch(_db, batch):
        captured_batches.append(list(batch))
        return len(batch)

    async def _fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(library_service, "_fetch_api", _fake_fetch_api)
    monkeypatch.setattr(library_service, "_upsert_library_batch", _fake_upsert_library_batch)
    monkeypatch.setattr(library_service, "_async_sleep", _fake_sleep)

    total = await library_service.scrape_to_library(
        db=fake_db,
        redis=fake_redis,
        user_id=8,
        categories=["Books"],
        lead_min=7,
        lead_max=21,
        min_price=0,
        max_price=100000,
        max_per_cat=10,
    )

    assert total == 1
    assert len(captured_batches) == 1
    assert [item["product_id"] for item in captured_batches[0]] == [2001]


@pytest.mark.asyncio
async def test_scrape_to_library_breaks_cursor_cycles(monkeypatch):
    fake_db = _FakeDb()
    fake_redis = _FakeRedis()
    captured_batches: list[list[dict]] = []
    cursors_seen: list[str] = []

    async def _fake_fetch_api(_client, params, retries=library_service.MAX_RETRIES):
        del retries
        cursor = params.get("is_after", "")
        cursors_seen.append(cursor)
        payloads = {
            "": {
                "sections": {
                    "products": {
                        "results": [
                            _raw_product(
                                3001,
                                title="Cycle A",
                                slug="cycle-a",
                                price=100,
                                status="Ships in 7 - 10 work days",
                            )
                        ],
                        "paging": {"next_is_after": "cursor-a"},
                    }
                }
            },
            "cursor-a": {
                "sections": {
                    "products": {
                        "results": [
                            _raw_product(
                                3002,
                                title="Cycle B",
                                slug="cycle-b",
                                price=110,
                                status="Ships in 7 - 10 work days",
                            )
                        ],
                        "paging": {"next_is_after": "cursor-b"},
                    }
                }
            },
            "cursor-b": {
                "sections": {
                    "products": {
                        "results": [
                            _raw_product(
                                3003,
                                title="Cycle C",
                                slug="cycle-c",
                                price=120,
                                status="Ships in 7 - 10 work days",
                            )
                        ],
                        "paging": {"next_is_after": "cursor-a"},
                    }
                }
            },
        }
        return payloads[cursor]

    async def _fake_upsert_library_batch(_db, batch):
        captured_batches.append(list(batch))
        return len(batch)

    async def _fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(library_service, "_fetch_api", _fake_fetch_api)
    monkeypatch.setattr(library_service, "_upsert_library_batch", _fake_upsert_library_batch)
    monkeypatch.setattr(library_service, "_async_sleep", _fake_sleep)

    total = await library_service.scrape_to_library(
        db=fake_db,
        redis=fake_redis,
        user_id=9,
        categories=["Books"],
        lead_min=0,
        lead_max=999,
        min_price=0,
        max_price=100000,
        max_per_cat=10,
    )

    assert total == 3
    assert fake_db.commit_count == 1
    assert cursors_seen == ["", "cursor-a", "cursor-b"]
    assert len(captured_batches) == 1
    assert [item["product_id"] for item in captured_batches[0]] == [3001, 3002, 3003]


@pytest.mark.asyncio
async def test_cleanup_invalid_categories_uses_display_labels_not_department_slugs():
    fake_db = _CaptureQueryDb()

    result = await library_service.cleanup_invalid_categories(fake_db)

    assert result == {"removed": 0}
    assert len(fake_db.queries) == 1
    sql = str(
        fake_db.queries[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "Home & Kitchen" in sql
    assert "home-kitchen" not in sql


@pytest.mark.asyncio
async def test_get_library_stats_includes_auto_scrape_status_from_redis():
    fake_db = _StatsDb((69, 5, 11, "2026-04-16T10:00:00+08:00"), quarantined=3)
    fake_redis = _FakeRedis()
    fake_redis.store["library:auto_scrape:status"] = json.dumps({
        "running": True,
        "status": "running",
        "last_started_at": "2026-04-16T10:30:00+08:00",
        "last_finished_at": "2026-04-16T10:00:00+08:00",
        "last_task_id": "task-123",
        "last_total_scraped": 20,
        "last_new_products": 4,
        "last_error": "",
    })

    stats = await library_service.get_library_stats(fake_db, redis=fake_redis)

    assert stats["total_products"] == 69
    assert stats["quarantined"] == 3
    assert stats["auto_scrape"] == {
        "running": True,
        "status": "running",
        "last_started_at": "2026-04-16T10:30:00+08:00",
        "last_finished_at": "2026-04-16T10:00:00+08:00",
        "last_task_id": "task-123",
        "last_total_scraped": 20,
        "last_new_products": 4,
        "last_error": "",
    }


@pytest.mark.asyncio
async def test_get_library_stats_defaults_auto_scrape_to_idle():
    fake_db = _StatsDb((102, 6, 18, None), quarantined=0)
    fake_redis = _FakeRedis()

    stats = await library_service.get_library_stats(fake_db, redis=fake_redis)

    assert stats["auto_scrape"] == {
        "running": False,
        "status": "idle",
        "last_started_at": None,
        "last_finished_at": None,
        "last_task_id": None,
        "last_total_scraped": 0,
        "last_new_products": 0,
        "last_error": None,
    }
