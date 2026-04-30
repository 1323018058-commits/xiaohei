import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Any

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
    PhoneVerificationCodeRequest,
    PhoneVerificationCodeResponse,
    RegisterRequest,
    SessionInfoResponse,
)

logger = logging.getLogger(__name__)


class AuthService:
    _SWITCH_CACHE_SECONDS = 5
    _FEATURE_FLAG_CACHE_SECONDS = 10
    _PHONE_CODE_TTL_SECONDS = 10 * 60

    def __init__(self) -> None:
        self._switch_cache_until = 0.0
        self._switch_cache = (True, False)
        self._switch_cache_lock = Lock()
        self._feature_flags_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._feature_flags_cache_lock = Lock()

    async def login(self, payload: LoginRequest) -> tuple[str, LoginResponse]:
        login_profile: dict[str, Any] = {}
        username = self._normalize_phone_if_possible(payload.username)
        session_token, user = await run_in_threadpool(
            self._login_hot_path,
            username,
            payload.password,
            login_profile,
        )
        bcrypt_elapsed_ms = float(login_profile.get("verify_ms", 0.0))
        db_read_ms = float(login_profile.get("db_read_ms", 0.0))
        db_write_ms = float(login_profile.get("db_write_ms", 0.0))
        logger.warning(
            "[PROFILE-LOGIN] User: %s | PasswordVerify: %.0fms | DB_Read: %.0fms | DB_Write: %.0fms (%s)",
            username,
            bcrypt_elapsed_ms,
            db_read_ms,
            db_write_ms,
            "Reused" if login_profile.get("reused", False) else "New",
        )
        return session_token, LoginResponse(
            session=self._to_session_info(user, include_feature_flags=False)
        )

    async def send_registration_code(
        self,
        payload: PhoneVerificationCodeRequest,
    ) -> PhoneVerificationCodeResponse:
        return await run_in_threadpool(self._send_registration_code_hot_path, payload)

    def _send_registration_code_hot_path(
        self,
        payload: PhoneVerificationCodeRequest,
    ) -> PhoneVerificationCodeResponse:
        auth_enabled, maintenance_mode = self._login_switches()
        if not auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            )
        if maintenance_mode:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="系统维护中，请稍后再试",
            )

        phone = self._normalize_phone(payload.phone)
        if app_state.get_user_by_username(phone) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该手机号已经注册，请直接登录",
            )

        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.now(UTC) + timedelta(seconds=self._PHONE_CODE_TTL_SECONDS)
        app_state.create_phone_verification_code(
            phone=phone,
            purpose="register",
            code_hash=self._hash_phone_code(phone, "register", code),
            expires_at=expires_at,
        )
        logger.warning("[DEV-SMS] register phone=%s code=%s", phone, code)
        return PhoneVerificationCodeResponse(
            phone=phone,
            expires_at=expires_at.isoformat(),
            debug_code=code,
        )

    async def register(self, payload: RegisterRequest) -> tuple[str, LoginResponse]:
        return await run_in_threadpool(self._register_hot_path, payload)

    def _register_hot_path(self, payload: RegisterRequest) -> tuple[str, LoginResponse]:
        auth_enabled, maintenance_mode = self._login_switches()
        if not auth_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            )
        if maintenance_mode:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="系统维护中，请稍后再试",
            )

        phone = self._normalize_phone(payload.phone)
        if app_state.get_user_by_username(phone) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该手机号已经注册，请直接登录",
            )
        try:
            app_state.consume_phone_verification_code(
                phone=phone,
                purpose="register",
                code_hash=self._hash_phone_code(
                    phone,
                    "register",
                    payload.verification_code,
                ),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="验证码不存在或已过期，请重新发送",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        slug = self._build_unique_tenant_slug(payload.company_name, phone)
        result = app_state.create_tenant_with_admin(
            {
                "slug": slug,
                "name": payload.company_name.strip(),
                "plan": "growth",
                "subscription_status": "unactivated",
                "admin_username": phone,
                "admin_email": None,
                "admin_password": payload.password,
                "reason": "self registration",
            },
            None,
        )
        admin_user = result["admin_user"]
        if hasattr(app_state, "append_audit"):
            app_state.append_audit(
                request_id=f"register-{secrets.token_hex(8)}",
                tenant_id=result["tenant"]["id"],
                actor_user_id=admin_user["id"],
                actor_role=admin_user["role"],
                action="auth.register",
                action_label="Register tenant",
                risk_level="medium",
                target_type="tenant",
                target_id=result["tenant"]["id"],
                target_label=result["tenant"]["slug"],
                before=None,
                after={
                    "tenant": {
                        "slug": result["tenant"]["slug"],
                        "name": result["tenant"]["name"],
                    },
                    "subscription": {
                        "plan": "growth",
                        "status": "unactivated",
                    },
                },
                reason="self registration",
                result="success",
                task_id=None,
            )
        session_token = auth_repository.create_session(admin_user)
        return session_token, LoginResponse(session=self._to_session_info(admin_user))

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
                detail="账号或密码错误",
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

    def _build_unique_tenant_slug(self, company_name: str, username: str) -> str:
        base_text = f"{company_name}-{username}".strip().lower()
        base = re.sub(r"[^a-z0-9]+", "-", base_text).strip("-")
        if len(base) < 3:
            base = f"xh-{re.sub(r'[^a-z0-9]+', '-', username.lower()).strip('-')}"
        base = base[:48].strip("-") or "xh-tenant"
        for _ in range(12):
            suffix = secrets.token_hex(3)
            slug = f"{base}-{suffix}"[:64].strip("-")
            if len(slug) >= 3 and app_state.get_tenant_by_slug(slug) is None:
                return slug
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="无法创建租户标识，请稍后重试",
        )

    @staticmethod
    def _normalize_phone_if_possible(value: str) -> str:
        stripped = value.strip()
        compact = re.sub(r"[\s\-().]", "", stripped)
        if re.fullmatch(r"\+?[0-9]{8,16}", compact):
            return compact
        return stripped

    @staticmethod
    def _normalize_phone(value: str) -> str:
        compact = re.sub(r"[\s\-().]", "", value.strip())
        if compact.startswith("00"):
            compact = "+" + compact[2:]
        if not re.fullmatch(r"\+?[0-9]{8,16}", compact):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="手机号格式不正确",
            )
        return compact

    @staticmethod
    def _hash_phone_code(phone: str, purpose: str, code: str) -> str:
        normalized_code = re.sub(r"\D", "", code)
        return hashlib.sha256(f"{purpose}:{phone}:{normalized_code}".encode("utf-8")).hexdigest()

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
