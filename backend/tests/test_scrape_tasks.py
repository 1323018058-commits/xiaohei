from __future__ import annotations

import json

import pytest

from app.tasks import scrape_tasks


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        del ex
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, *keys: str):
        removed = 0
        for key in keys:
            if key in self.store:
                removed += 1
                self.store.pop(key, None)
        return removed


@pytest.mark.asyncio
async def test_reserve_library_scrape_clears_stale_stop_signal():
    redis = _FakeRedis()
    redis.store["scrape_stop:5"] = "1"

    ok = await scrape_tasks.reserve_library_scrape(
        redis,
        user_id=5,
        owner="pending-1",
        ttl=60,
    )

    assert ok is True
    assert "scrape_stop:5" not in redis.store
    assert redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] == "pending-1"


@pytest.mark.asyncio
async def test_claim_library_scrape_lock_replaces_pending_owner():
    redis = _FakeRedis()
    redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] = "pending-1"

    ok = await scrape_tasks.claim_library_scrape_lock(
        redis,
        owner="task-1",
        ttl=7200,
        pending_owner="pending-1",
    )

    assert ok is True
    assert redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] == "task-1"


@pytest.mark.asyncio
async def test_claim_library_scrape_lock_rejects_existing_execution_owner():
    redis = _FakeRedis()
    redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] = "task-1:run-a"

    ok = await scrape_tasks.claim_library_scrape_lock(
        redis,
        owner="task-1:run-b",
        ttl=7200,
        pending_owner="pending-1",
    )

    assert ok is False
    assert redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] == "task-1:run-a"


@pytest.mark.asyncio
async def test_release_library_scrape_lock_does_not_delete_other_owner():
    redis = _FakeRedis()
    redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] = "task-2"

    released = await scrape_tasks.release_library_scrape_lock(redis, owner="task-1")

    assert released is False
    assert redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] == "task-2"


@pytest.mark.asyncio
async def test_refresh_library_scrape_lock_extends_current_owner():
    redis = _FakeRedis()
    redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] = "task-1"

    refreshed = await scrape_tasks.refresh_library_scrape_lock(redis, owner="task-1", ttl=7200)

    assert refreshed is True
    assert redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] == "task-1"


@pytest.mark.asyncio
async def test_refresh_library_scrape_lock_rejects_other_owner():
    redis = _FakeRedis()
    redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] = "task-2"

    refreshed = await scrape_tasks.refresh_library_scrape_lock(redis, owner="task-1", ttl=7200)

    assert refreshed is False
    assert redis.store[scrape_tasks.LIBRARY_SCRAPE_LOCK_KEY] == "task-2"


@pytest.mark.asyncio
async def test_update_auto_scrape_status_writes_defaults():
    redis = _FakeRedis()

    await scrape_tasks.update_auto_scrape_status(
        redis,
        status="queued",
        running=False,
        last_task_id="task-1",
    )

    assert json.loads(redis.store[scrape_tasks.AUTO_LIBRARY_SCRAPE_STATUS_KEY]) == {
        "running": False,
        "status": "queued",
        "last_started_at": None,
        "last_finished_at": None,
        "last_task_id": "task-1",
        "last_total_scraped": 0,
        "last_new_products": 0,
        "last_error": None,
    }


@pytest.mark.asyncio
async def test_update_auto_scrape_status_preserves_existing_fields():
    redis = _FakeRedis()
    redis.store[scrape_tasks.AUTO_LIBRARY_SCRAPE_STATUS_KEY] = json.dumps({
        "running": False,
        "status": "success",
        "last_started_at": "2026-04-16T10:00:00+08:00",
        "last_finished_at": "2026-04-16T10:05:00+08:00",
        "last_task_id": "task-old",
        "last_total_scraped": 25,
        "last_new_products": 6,
        "last_error": None,
    })

    await scrape_tasks.update_auto_scrape_status(
        redis,
        status="running",
        running=True,
        last_started_at="2026-04-16T10:30:00+08:00",
        last_task_id="task-new",
    )

    assert json.loads(redis.store[scrape_tasks.AUTO_LIBRARY_SCRAPE_STATUS_KEY]) == {
        "running": True,
        "status": "running",
        "last_started_at": "2026-04-16T10:30:00+08:00",
        "last_finished_at": "2026-04-16T10:05:00+08:00",
        "last_task_id": "task-new",
        "last_total_scraped": 25,
        "last_new_products": 6,
        "last_error": None,
    }
