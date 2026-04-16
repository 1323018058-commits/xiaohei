from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from app.api import deps
from app.api import extension as extension_api


class _FakeDb:
    def __init__(self):
        self.flush_count = 0
        self.commit_count = 0

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


def _install_extension_auth(app, monkeypatch, user_id: int = 2):
    async def _fake_user():
        return SimpleNamespace(id=user_id, role="user")

    async def _fake_db():
        yield _fake_db.session

    _fake_db.session = _FakeDb()  # type: ignore[attr-defined]
    app.dependency_overrides[extension_api._get_extension_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db
    return _fake_db.session


def _install_owned_store(monkeypatch, store_id: int = 2):
    async def _fake_build_status(db, user_id: int):
        return {"stores": [{"id": store_id}]}

    monkeypatch.setattr(extension_api.extension_service, "build_status", _fake_build_status)


def test_list_now_validation_requires_plid(monkeypatch):
    app = create_app()
    _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    client = TestClient(app)
    response = client.post("/api/extension/list-now", json={"store_id": 2})

    assert response.status_code == 422


def test_list_now_rejects_already_pending(monkeypatch):
    app = create_app()
    _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    async def _fake_pending_action(db, user_id: int, store_id: int, plid: str):
        return SimpleNamespace(id=41)

    async def _fake_listed_product(db, store_id: int, plid: str, barcode: str):
        return None

    monkeypatch.setattr(extension_api, "_find_inflight_list_now_action", _fake_pending_action)
    monkeypatch.setattr(extension_api, "_find_listed_bid_product", _fake_listed_product)

    client = TestClient(app)
    response = client.post("/api/extension/list-now", json={"store_id": 2, "plid": "PLID-1"})

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "ALREADY_PENDING"


def test_list_now_rejects_already_listed(monkeypatch):
    app = create_app()
    _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    async def _fake_pending_action(db, user_id: int, store_id: int, plid: str):
        return None

    async def _fake_listed_product(db, store_id: int, plid: str, barcode: str):
        return SimpleNamespace(id=77, plid=plid, barcode=barcode)

    monkeypatch.setattr(extension_api, "_find_inflight_list_now_action", _fake_pending_action)
    monkeypatch.setattr(extension_api, "_find_listed_bid_product", _fake_listed_product)

    client = TestClient(app)
    response = client.post("/api/extension/list-now", json={"store_id": 2, "plid": "PLID-1"})

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "ALREADY_LISTED"


def test_list_now_requires_profit_snapshot(monkeypatch):
    app = create_app()
    _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    async def _fake_pending_action(db, user_id: int, store_id: int, plid: str):
        return None

    async def _fake_listed_product(db, store_id: int, plid: str, barcode: str):
        return None

    async def _fake_log_action(db, **kwargs):
        raise AssertionError("log_action should not be called when profit snapshot is missing")

    monkeypatch.setattr(extension_api, "_find_inflight_list_now_action", _fake_pending_action)
    monkeypatch.setattr(extension_api, "_find_listed_bid_product", _fake_listed_product)
    monkeypatch.setattr(extension_api.extension_service, "log_action", _fake_log_action)

    client = TestClient(app)
    response = client.post(
        "/api/extension/list-now",
        json={"store_id": 2, "plid": "PLID-1", "barcode": "6001234567890"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "PROFIT_CALC_REQUIRED"


def test_list_now_rejects_negative_profit_without_override(monkeypatch):
    app = create_app()
    _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    async def _fake_pending_action(db, user_id: int, store_id: int, plid: str):
        return None

    async def _fake_listed_product(db, store_id: int, plid: str, barcode: str):
        return None

    async def _fake_log_action(db, **kwargs):
        raise AssertionError("log_action should not be called when profit is negative")

    monkeypatch.setattr(extension_api, "_find_inflight_list_now_action", _fake_pending_action)
    monkeypatch.setattr(extension_api, "_find_listed_bid_product", _fake_listed_product)
    monkeypatch.setattr(extension_api.extension_service, "log_action", _fake_log_action)

    client = TestClient(app)
    response = client.post(
        "/api/extension/list-now",
        json={
            "store_id": 2,
            "plid": "PLID-NEG",
            "barcode": "6001234567890",
            "pricing_snapshot": {
                "air_profit_cny": -12.8,
                "air_profit_rate_pct": -6.4,
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "NEGATIVE_PROFIT"


def test_list_now_rejects_low_margin_without_override(monkeypatch):
    app = create_app()
    _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    async def _fake_pending_action(db, user_id: int, store_id: int, plid: str):
        return None

    async def _fake_listed_product(db, store_id: int, plid: str, barcode: str):
        return None

    async def _fake_log_action(db, **kwargs):
        raise AssertionError("log_action should not be called when margin is below target")

    monkeypatch.setattr(extension_api, "_find_inflight_list_now_action", _fake_pending_action)
    monkeypatch.setattr(extension_api, "_find_listed_bid_product", _fake_listed_product)
    monkeypatch.setattr(extension_api.extension_service, "log_action", _fake_log_action)

    client = TestClient(app)
    response = client.post(
        "/api/extension/list-now",
        json={
            "store_id": 2,
            "plid": "PLID-MARGIN",
            "barcode": "6001234567890",
            "pricing_snapshot": {
                "air_profit_cny": 8.5,
                "air_profit_rate_pct": 12.0,
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "MARGIN_BELOW_TARGET"


def test_list_now_queues_action_and_dispatches_task(monkeypatch):
    app = create_app()
    fake_db = _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    async def _fake_pending_action(db, user_id: int, store_id: int, plid: str):
        return None

    async def _fake_listed_product(db, store_id: int, plid: str, barcode: str):
        return None

    action = SimpleNamespace(
        id=123,
        action_status="pending",
        error_code="",
        error_msg="",
        task_id="",
    )
    captured = {}

    async def _fake_log_action(db, **kwargs):
        captured["kwargs"] = kwargs
        return action

    task_module = ModuleType("app.tasks.extension_tasks")

    class _FakeTask:
        id = "celery-task-123"

    def _fake_delay(action_id: int):
        captured["task_action_id"] = action_id
        return _FakeTask()

    task_module.process_extension_list_now = SimpleNamespace(delay=_fake_delay)
    monkeypatch.setitem(sys.modules, "app.tasks.extension_tasks", task_module)
    monkeypatch.setattr(extension_api, "_find_inflight_list_now_action", _fake_pending_action)
    monkeypatch.setattr(extension_api, "_find_listed_bid_product", _fake_listed_product)
    monkeypatch.setattr(extension_api.extension_service, "log_action", _fake_log_action)

    client = TestClient(app)
    response = client.post(
        "/api/extension/list-now",
        json={
            "store_id": 2,
            "plid": "PLID-1",
            "barcode": "BC-1",
            "title": "Example",
            "allow_low_margin": True,
            "pricing_snapshot": {
                "air_profit_cny": 21.5,
                "air_profit_rate_pct": 35.0,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["action_id"] == 123
    assert payload["status"] == "queued"
    assert payload["task_id"] == "celery-task-123"
    assert captured["task_action_id"] == 123
    assert action.action_status == "queued"
    assert action.task_id == "celery-task-123"
    assert captured["kwargs"]["pricing_snapshot_json"] == '{"air_profit_cny": 21.5, "air_profit_rate_pct": 35.0}'
    assert fake_db.commit_count >= 2


def test_list_now_commits_before_dispatching_task(monkeypatch):
    app = create_app()
    fake_db = _install_extension_auth(app, monkeypatch)
    _install_owned_store(monkeypatch)

    async def _fake_pending_action(db, user_id: int, store_id: int, plid: str):
        return None

    async def _fake_listed_product(db, store_id: int, plid: str, barcode: str):
        return None

    action = SimpleNamespace(
        id=124,
        action_status="pending",
        error_code="",
        error_msg="",
        task_id="",
    )
    captured = {}

    async def _fake_log_action(db, **kwargs):
        return action

    task_module = ModuleType("app.tasks.extension_tasks")

    class _FakeTask:
        id = "celery-task-124"

    def _fake_delay(action_id: int):
        captured["commit_count_at_delay"] = fake_db.commit_count
        captured["action_status_at_delay"] = action.action_status
        captured["task_action_id"] = action_id
        return _FakeTask()

    task_module.process_extension_list_now = SimpleNamespace(delay=_fake_delay)
    monkeypatch.setitem(sys.modules, "app.tasks.extension_tasks", task_module)
    monkeypatch.setattr(extension_api, "_find_inflight_list_now_action", _fake_pending_action)
    monkeypatch.setattr(extension_api, "_find_listed_bid_product", _fake_listed_product)
    monkeypatch.setattr(extension_api.extension_service, "log_action", _fake_log_action)

    client = TestClient(app)
    response = client.post(
        "/api/extension/list-now",
        json={
            "store_id": 2,
            "plid": "PLID-2",
            "barcode": "6001234567890",
            "allow_low_margin": True,
            "pricing_snapshot": {
                "air_profit_cny": 12.0,
                "air_profit_rate_pct": 30.0,
            },
        },
    )

    assert response.status_code == 200
    assert captured["task_action_id"] == 124
    assert captured["commit_count_at_delay"] >= 1
    assert captured["action_status_at_delay"] == "queued"
    assert fake_db.commit_count >= 2


def test_list_history_exposes_queue_and_error_fields(monkeypatch):
    app = create_app()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db():
        yield _FakeDb()

    app.dependency_overrides[extension_api._get_extension_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db

    async def _fake_list_actions(db, user_id: int, limit: int = 50):
        return [
            SimpleNamespace(
                id=9,
                action_type="list_now",
                plid="PLID-9",
                title="History Item",
                image_url="",
                buybox_price_zar=12.5,
                offer_id="OFF-9",
                action_status="queued",
                error_code="",
                error_msg="",
                task_id="task-9",
                created_at=None,
            )
        ]

    monkeypatch.setattr(extension_api.extension_service, "list_actions", _fake_list_actions)

    client = TestClient(app)
    response = client.get("/api/extension/list-history")

    assert response.status_code == 200
    item = response.json()["actions"][0]
    assert item["status"] == "queued"
    assert item["error_code"] == ""
    assert item["error_msg"] == ""
    assert item["task_id"] == "task-9"
    assert item["offer_id"] == "OFF-9"


def test_list_history_redacts_internal_error_details(monkeypatch):
    app = create_app()

    async def _fake_user():
        return SimpleNamespace(id=2, role="user")

    async def _fake_db():
        yield _FakeDb()

    app.dependency_overrides[extension_api._get_extension_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db

    async def _fake_list_actions(db, user_id: int, limit: int = 50):
        return [
            SimpleNamespace(
                id=10,
                action_type="list_now",
                plid="PLID-10",
                title="History Failure",
                image_url="",
                buybox_price_zar=12.5,
                offer_id="",
                action_status="failed",
                error_code="OFFER_CREATE_FAILED",
                error_msg="network down: seller-api.takealot.com timeout stacktrace",
                task_id="task-10",
                created_at=None,
            )
        ]

    monkeypatch.setattr(extension_api.extension_service, "list_actions", _fake_list_actions)

    client = TestClient(app)
    response = client.get("/api/extension/list-history")

    assert response.status_code == 200
    item = response.json()["actions"][0]
    assert item["error_code"] == "OFFER_CREATE_FAILED"
    assert item["error_msg"] == "创建 Takealot 商品失败，请稍后重试。"
    assert "stacktrace" not in item["error_msg"]
