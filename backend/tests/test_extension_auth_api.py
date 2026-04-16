from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from app.api import deps
from app.api import extension as extension_api


class _FakeDb:
    pass


class _FakeRedis:
    pass


def _install_authorize_auth(app, user_id: int = 2, username: str = "alice"):
    async def _fake_user():
        return SimpleNamespace(id=user_id, role="user", username=username)

    async def _fake_db():
        yield _FakeDb()

    async def _fake_redis():
        yield _FakeRedis()

    app.dependency_overrides[deps.get_current_active_user] = _fake_user
    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_redis] = _fake_redis


def test_authorize_api_returns_auth_code_instead_of_token(monkeypatch):
    app = create_app()
    _install_authorize_auth(app)

    async def _fake_issue_authorization_code(redis, user_id: int):
        assert isinstance(redis, _FakeRedis)
        assert user_id == 2
        return ("auth-code-123", "2026-04-16T12:00:00+00:00")

    monkeypatch.setattr(
        extension_api.extension_service,
        "issue_authorization_code",
        _fake_issue_authorization_code,
    )

    client = TestClient(app)
    response = client.post("/api/extension/authorize-api")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["auth_code"] == "auth-code-123"
    assert payload["expires_at"] == "2026-04-16T12:00:00+00:00"
    assert "token" not in payload


def test_redeem_code_returns_token(monkeypatch):
    app = create_app()
    _install_authorize_auth(app)

    async def _fake_redeem_authorization_code(db, redis, auth_code: str):
        assert isinstance(db, _FakeDb)
        assert isinstance(redis, _FakeRedis)
        assert auth_code == "auth-code-123"
        return {
            "token": "extension-token-123",
            "expires_at": "2026-07-15T00:00:00+00:00",
        }

    monkeypatch.setattr(
        extension_api.extension_service,
        "redeem_authorization_code",
        _fake_redeem_authorization_code,
    )

    client = TestClient(app)
    response = client.post(
        "/api/extension/redeem-code",
        json={"auth_code": "auth-code-123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["token"] == "extension-token-123"
    assert payload["expires_at"] == "2026-07-15T00:00:00+00:00"


def test_authorize_html_route_is_gone(monkeypatch):
    app = create_app()
    _install_authorize_auth(app)

    client = TestClient(app)
    response = client.get("/api/extension/authorize")

    assert response.status_code == 410
    assert "已下线" in response.json()["detail"]
