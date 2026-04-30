import logging
from typing import Any
from threading import Lock
from time import monotonic

from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool

from src.modules.common.dev_state import app_state

from .repo import auth_repository
from .schemas import (
    AuthUser,
    FeatureFlagResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    SessionInfoResponse,
)

logger = logging.getLogger(__name__)


class AuthService:
    _SWITCH_CACHE_SECONDS = 5
    _FEATURE_FLAG_CACHE_SECONDS = 10

    def __init__(self) -> None:
        self._switch_cache_until = 0.0
        self._switch_cache = (True, False)
        self._switch_cache_lock = Lock()
        self._feature_flags_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._feature_flags_cache_lock = Lock()

    async def login(self, payload: LoginRequest) -> tuple[str, LoginResponse]:
        login_profile: dict[str, Any] = {}
        session_token, user = await run_in_threadpool(
            self._login_hot_path,
            payload.username,
            payload.password,
            login_profile,
        )
        bcrypt_elapsed_ms = float(login_profile.get("verify_ms", 0.0))
        db_read_ms = float(login_profile.get("db_read_ms", 0.0))
        db_write_ms = float(login_profile.get("db_write_ms", 0.0))
        logger.warning(
            "[PROFILE-LOGIN] User: %s | PasswordVerify: %.0fms | DB_Read: %.0fms | DB_Write: %.0fms (%s)",
            payload.username,
            bcrypt_elapsed_ms,
            db_read_ms,
            db_write_ms,
            "Reused" if login_profile.get("reused", False) else "New",
        )
        return session_token, LoginResponse(
            session=self._to_session_info(user, include_feature_flags=False)
        )

    def _login_hot_path(
        self,
        username: str,
        password: str,
        login_profile: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        auth_enabled, maintenance_mode = self._login_switches()
        if not auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="登录主开关已关闭",
            )
        if maintenance_mode:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="系统维护中",
            )

        session = auth_repository.authenticate_and_create_session(
            username,
            password,
            profile=login_profile,
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )

        return session

    def _login_switches(self) -> tuple[bool, bool]:
        now = monotonic()
        with self._switch_cache_lock:
            if now < self._switch_cache_until:
                return self._switch_cache
            self._switch_cache = (
                app_state.is_setting_enabled("auth_enabled", True),
                app_state.is_setting_enabled("maintenance_mode", False),
            )
            self._switch_cache_until = now + self._SWITCH_CACHE_SECONDS
            return self._switch_cache

    def me(self, session_token: str | None) -> SessionInfoResponse:
        user = auth_repository.get_session_user(session_token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未登录或会话已过期",
            )
        return self._to_session_info(user)

    def logout(self, session_token: str | None) -> LogoutResponse:
        auth_repository.delete_session(session_token)
        return LogoutResponse()

    @staticmethod
    def _to_auth_user(user: dict[str, Any]) -> AuthUser:
        return AuthUser(
            user_id=user["id"],
            username=user["username"],
            role=user["role"],
            status=user["status"],
            subscription_status=user["subscription_status"],
        )

    def _to_session_info(
        self,
        user: dict[str, Any],
        *,
        include_feature_flags: bool = True,
    ) -> SessionInfoResponse:
        flags: list[FeatureFlagResponse] = []
        if include_feature_flags:
            raw_flags = user.get("feature_flags")
            if raw_flags is None:
                resolved_flags = self._list_user_feature_flags(user["id"])
            else:
                resolved_flags = [dict(flag) for flag in raw_flags]
                self._remember_feature_flags(user["id"], resolved_flags)
            flags = [
                FeatureFlagResponse(
                    feature_key=flag["feature_key"],
                    enabled=flag["enabled"],
                    source=flag["source"],
                )
                for flag in resolved_flags
            ]
        return SessionInfoResponse(
            user=self._to_auth_user(user),
            roles=[user["role"]],
            feature_flags=flags,
            subscription_status=user["subscription_status"],
        )

    def _list_user_feature_flags(self, user_id: str) -> list[dict[str, Any]]:
        now = monotonic()
        with self._feature_flags_cache_lock:
            entry = self._feature_flags_cache.get(user_id)
            if entry is not None:
                expires_at, flags = entry
                if expires_at > now:
                    return [dict(flag) for flag in flags]
        flags = app_state.list_user_feature_flags(user_id)
        self._remember_feature_flags(user_id, flags, now=now)
        return flags

    def _remember_feature_flags(
        self,
        user_id: str,
        flags: list[dict[str, Any]],
        *,
        now: float | None = None,
    ) -> None:
        expires_at = (now if now is not None else monotonic()) + self._FEATURE_FLAG_CACHE_SECONDS
        with self._feature_flags_cache_lock:
            self._feature_flags_cache[user_id] = (
                expires_at,
                [dict(flag) for flag in flags],
            )
