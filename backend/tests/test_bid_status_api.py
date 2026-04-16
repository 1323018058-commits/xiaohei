from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from app.api import bids as bids_api
from app.api import deps


class _FakeStatusResult:
    def one(self):
        return SimpleNamespace(total=8, active=3)


class _FakeDb:
    async def execute(self, *_args, **_kwargs):
        return _FakeStatusResult()


class _FakeRedis:
    async def get(self, _key: str):
        return None

    async def setex(self, _key: str, _ttl: int, _value: str):
        return None

    async def delete(self, _key: str):
        return None


def test_bid_status_includes_last_product_sync_at(monkeypatch):
    app = create_app()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db():
        yield _FakeDb()

    async def _fake_redis():
        yield _FakeRedis()

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_redis] = _fake_redis

    store = SimpleNamespace(
        id=2,
        store_name="King store",
        store_alias="",
        takealot_store_id="29897844",
        is_active=1,
        last_synced_at=datetime(2026, 4, 15, 10, 30, 0),
    )

    async def _fake_require_store(db, store_id: int, user_id: int):
        return store

    async def _fake_get_engine_state(db, store_id: int):
        return {
            "running": True,
            "last_run": "2026-04-15 09:12:25",
            "next_run": None,
            "last_raised": 0,
            "last_lowered": 0,
            "last_floored": 0,
            "last_unchanged": 0,
            "last_errors": 0,
            "total_checked": 0,
            "total_updated": 0,
            "consecutive_error_cycles": 0,
        }

    monkeypatch.setattr(bids_api, "_require_store", _fake_require_store)
    monkeypatch.setattr(bids_api.bid_service, "get_engine_state", _fake_get_engine_state)

    client = TestClient(app)
    response = client.get("/api/bids/2/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["state"]["last_product_sync_at"] == "2026-04-15 18:30:00"
    assert payload["state"]["next_product_sync_at"] == "2026-04-15 19:00:00"
    assert payload["state"]["last_run"] == "2026-04-15 17:12:25"
