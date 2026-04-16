from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services import product_sync_progress_service


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def setex(self, key: str, _ttl: int, value: str):
        self.store[key] = value

    async def delete(self, key: str):
        self.store.pop(key, None)


class _FakeTask:
    def delay(self, _store_id: int):
        return SimpleNamespace(id="task-1")


def test_progress_scopes_are_isolated_but_share_store_lock(monkeypatch):
    async def _run():
        redis = _FakeRedis()

        monkeypatch.setattr(
            product_sync_progress_service,
            "get_settings",
            lambda: SimpleNamespace(product_sync_progress_ttl_seconds=7200),
        )

        first = await product_sync_progress_service.enqueue_sync(
            redis,
            2,
            task_importer=lambda: _FakeTask(),
            progress_scope="products",
            lock_scope="store_products",
            conflict_message="另一同步任务正在运行，请稍后再试",
        )
        second = await product_sync_progress_service.enqueue_sync(
            redis,
            2,
            task_importer=lambda: _FakeTask(),
            progress_scope="bids",
            lock_scope="store_products",
            conflict_message="另一同步任务正在运行，请稍后再试",
        )

        product_progress = await product_sync_progress_service.get_progress(
            redis,
            2,
            scope="products",
        )
        bid_progress = await product_sync_progress_service.get_progress(
            redis,
            2,
            scope="bids",
        )

        assert first["ok"] is True
        assert first["stage"] == "queued"
        assert second["ok"] is False
        assert second["running"] is False
        assert second["stage"] == "blocked"
        assert second["message"] == "另一同步任务正在运行，请稍后再试"
        assert product_progress["stage"] == "queued"
        assert product_progress["running"] is True
        assert bid_progress["stage"] == "idle"
        assert bid_progress["running"] is False

    asyncio.run(_run())
