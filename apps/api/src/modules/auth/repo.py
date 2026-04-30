from threading import Lock
from time import monotonic
from typing import Any

from src.modules.common.dev_state import app_state
from src.platform.settings.base import settings


class AuthRepository:
    _SESSION_CACHE_SECONDS = min(60, settings.session_max_age_seconds)

    def __init__(self) -> None:
        self._session_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._session_cache_lock = Lock()

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        return app_state.verify_credentials(username, password)

    def authenticate_and_create_session(
        self,
        username: str,
        password: str,
        *,
        profile: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        if hasattr(app_state, "authenticate_and_create_session"):
            result = app_state.authenticate_and_create_session(
                username,
                password,
                profile=profile,
            )
            if result is not None:
                session_token, user = result
                self._remember_session(session_token, user)
            return result
        user = self.authenticate(username, password)
        if user is None:
            return None
        return self.create_session(user), user

    def create_session(self, user: dict[str, Any]) -> str:
        session_token = app_state.create_session(user)
        self._remember_session(session_token, user)
        return session_token

    def get_session_user(self, session_token: str | None) -> dict[str, Any] | None:
        cached_user = self._cached_session_user(session_token)
        if cached_user is not None:
            return cached_user
        user = app_state.get_session_user(session_token)
        if session_token and user is not None:
            self._remember_session(session_token, user)
        return user

    def delete_session(self, session_token: str | None) -> None:
        self._forget_session(session_token)
        app_state.delete_session(session_token)

    def delete_sessions_for_user(self, user_id: str) -> int:
        revoked_count = app_state.delete_sessions_for_user(user_id)
        self._forget_user_sessions(user_id)
        return revoked_count

    def delete_sessions_for_tenant(self, tenant_id: str) -> int:
        if not hasattr(app_state, "delete_sessions_for_tenant"):
            return 0
        revoked_count = app_state.delete_sessions_for_tenant(tenant_id)
        self._forget_tenant_sessions(tenant_id)
        return revoked_count

    def forget_cached_sessions_for_tenant(self, tenant_id: str) -> None:
        self._forget_tenant_sessions(tenant_id)

    def count_sessions_for_user(self, user_id: str) -> int:
        return app_state.count_sessions_for_user(user_id)

    def count_sessions_for_users(self, user_ids: list[str]) -> dict[str, int]:
        if hasattr(app_state, "count_sessions_for_users"):
            return app_state.count_sessions_for_users(user_ids)
        return {user_id: self.count_sessions_for_user(user_id) for user_id in user_ids}

    def _remember_session(self, session_token: str, user: dict[str, Any]) -> None:
        expires_at = monotonic() + self._SESSION_CACHE_SECONDS
        with self._session_cache_lock:
            self._session_cache[session_token] = (expires_at, dict(user))

    def _cached_session_user(self, session_token: str | None) -> dict[str, Any] | None:
        if not session_token:
            return None
        now = monotonic()
        with self._session_cache_lock:
            entry = self._session_cache.get(session_token)
            if entry is None:
                return None
            expires_at, user = entry
            if expires_at <= now:
                self._session_cache.pop(session_token, None)
                return None
            return dict(user)

    def _forget_session(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self._session_cache_lock:
            self._session_cache.pop(session_token, None)

    def _forget_user_sessions(self, user_id: str) -> None:
        with self._session_cache_lock:
            stale_tokens = [
                session_token
                for session_token, (_, user) in self._session_cache.items()
                if user.get("id") == user_id
            ]
            for session_token in stale_tokens:
                self._session_cache.pop(session_token, None)

    def _forget_tenant_sessions(self, tenant_id: str) -> None:
        with self._session_cache_lock:
            stale_tokens = [
                session_token
                for session_token, (_, user) in self._session_cache.items()
                if user.get("tenant_id") == tenant_id
            ]
            for session_token in stale_tokens:
                self._session_cache.pop(session_token, None)


auth_repository = AuthRepository()
