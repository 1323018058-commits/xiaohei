from datetime import datetime, timezone
import hashlib
import secrets
from threading import Lock
from time import monotonic
from typing import Any

from fastapi import HTTPException, status

from src.modules.auth.repo import auth_repository
from src.modules.common.dev_state import app_state, new_id
from src.modules.common.tenant_scope import require_tenant_access
from src.modules.subscription.service import subscription_service

from .schemas import (
    AdminActionResponse,
    ActivationCardActionResponse,
    ActivationCardCreateResponse,
    ActivationCardListResponse,
    ActivationCardResponse,
    AdminFeatureFlagResponse,
    AdminUserDetail,
    AdminUserListResponse,
    AdminUserSummary,
    AuditListResponse,
    AuditLogResponse,
    SystemComponentHealth,
    SystemHealthResponse,
    SystemSettingResponse,
    TenantActionResponse,
    TenantListResponse,
    TenantPlanLimits,
    TenantRemaining,
    TenantSummary,
    TenantUsage,
)


class AdminService:
    _HEALTH_CACHE_SECONDS = 60

    def __init__(self) -> None:
        self._health_cache: dict[str, tuple[float, SystemHealthResponse]] = {}
        self._health_cache_lock = Lock()

    def list_users(
        self,
        *,
        actor: dict[str, Any],
        status_filter: str | None = None,
        role_filter: str | None = None,
        keyword: str | None = None,
    ) -> AdminUserListResponse:
        normalized_keyword = keyword.strip().lower() if keyword else None
        raw_users = sorted(
            app_state.list_users(
                None if actor["role"] == "super_admin" else actor["tenant_id"]
            ),
            key=lambda current_user: current_user["updated_at"],
            reverse=True,
        )
        user_ids = [user["id"] for user in raw_users]
        feature_flags_by_user = self._feature_flags_by_user(user_ids)
        session_counts_by_user = auth_repository.count_sessions_for_users(user_ids)
        users = []
        for user in raw_users:
            summary = self._to_user_summary(
                user,
                feature_flags=feature_flags_by_user.get(user["id"], []),
                active_session_count=session_counts_by_user.get(user["id"], 0),
            )
            if status_filter is not None and summary.status != status_filter:
                continue
            if role_filter is not None and summary.role != role_filter:
                continue
            if normalized_keyword is not None and (
                normalized_keyword not in summary.username.lower()
                and normalized_keyword not in (summary.email or "").lower()
            ):
                continue
            users.append(summary)
        return AdminUserListResponse(users=users)

    def get_user(self, user_id: str, actor: dict[str, Any]) -> AdminUserDetail:
        user = self._require_user(user_id, actor)
        feature_flags_by_user = self._feature_flags_by_user([user_id])
        session_counts_by_user = auth_repository.count_sessions_for_users([user_id])
        return self._to_user_detail(
            user,
            feature_flags=feature_flags_by_user.get(user_id, []),
            active_session_count=session_counts_by_user.get(user_id, 0),
        )

    def list_tenants(self, actor: dict[str, Any]) -> TenantListResponse:
        self._ensure_super_admin(actor)
        return TenantListResponse(
            tenants=[
                self._to_tenant_summary(tenant)
                for tenant in app_state.list_tenants()
            ]
        )

    def list_activation_cards(self, actor: dict[str, Any]) -> ActivationCardListResponse:
        self._ensure_admin_enabled()
        self._ensure_super_admin(actor)
        cards = app_state.list_activation_cards()
        return ActivationCardListResponse(
            cards=[self._to_activation_card(card, include_plain_code=False) for card in cards]
        )

    def create_activation_cards(
        self,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_id: str,
    ) -> ActivationCardCreateResponse:
        self._ensure_admin_enabled()
        self._ensure_super_admin(actor)
        quantity = int(payload["quantity"])
        days = int(payload["days"])
        records = []
        for _ in range(quantity):
            code = self._generate_activation_code()
            records.append(
                {
                    "code": code,
                    "code_hash": self._hash_activation_code(code),
                    "code_suffix": code[-4:],
                    "days": days,
                    "note": payload.get("note"),
                    "created_by": actor["id"],
                }
            )
        cards = app_state.create_activation_cards(records)
        app_state.append_audit(
            request_id=request_id,
            tenant_id=actor["tenant_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.activation_cards.create",
            action_label="Create activation cards",
            risk_level="high",
            target_type="activation_card_batch",
            target_id=None,
            target_label=f"{quantity} cards / {days} days",
            before=None,
            after={"quantity": quantity, "days": days, "note": payload.get("note")},
            reason=payload.get("note") or "create activation cards",
            result="success",
            task_id=None,
        )
        return ActivationCardCreateResponse(
            cards=[self._to_activation_card(card, include_plain_code=True) for card in cards]
        )

    def void_activation_card(
        self,
        card_id: str,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> ActivationCardActionResponse:
        self._ensure_admin_enabled()
        self._ensure_super_admin(actor)
        before = app_state.get_activation_card(card_id)
        if before is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activation card not found",
            )
        try:
            card = app_state.void_activation_card(
                card_id=card_id,
                voided_by=actor["id"],
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        app_state.append_audit(
            request_id=request_id,
            tenant_id=actor["tenant_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.activation_cards.void",
            action_label="Void activation card",
            risk_level="high",
            target_type="activation_card",
            target_id=card_id,
            target_label=f"****{card['code_suffix']}",
            before=self._activation_card_audit_snapshot(before),
            after=self._activation_card_audit_snapshot(card),
            reason=reason,
            result="success",
            task_id=None,
        )
        return ActivationCardActionResponse(
            card=self._to_activation_card(card, include_plain_code=False)
        )

    def create_tenant(
        self,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_id: str,
    ) -> TenantActionResponse:
        self._ensure_admin_enabled()
        self._ensure_super_admin(actor)
        if app_state.get_tenant_by_slug(payload["slug"]) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tenant slug already exists",
            )
        if app_state.get_user_by_username(payload["admin_username"]) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Admin username already exists",
            )
        result = app_state.create_tenant_with_admin(payload, actor["id"])
        tenant = result["tenant"]
        admin_user = result["admin_user"]
        app_state.append_audit(
            request_id=request_id,
            tenant_id=tenant["id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.tenant.create",
            action_label="Create tenant",
            risk_level="high",
            target_type="tenant",
            target_id=tenant["id"],
            target_label=tenant["slug"],
            before=None,
            after={
                "tenant": self._tenant_audit_snapshot(tenant),
                "admin_user": self._user_audit_snapshot(admin_user),
                "subscription": {
                    "plan": payload["plan"],
                    "status": payload["subscription_status"],
                },
            },
            reason=payload["reason"],
            result="success",
            task_id=None,
        )
        return TenantActionResponse(
            tenant=self._to_tenant_summary(tenant),
            admin_user=self._to_user_detail(admin_user, feature_flags=[], active_session_count=0),
        )

    def update_tenant_subscription(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_id: str,
    ) -> TenantActionResponse:
        self._ensure_admin_enabled()
        self._ensure_super_admin(actor)
        tenant = app_state.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found",
            )
        before = app_state.get_tenant_entitlement(tenant_id)
        updated = app_state.update_tenant_subscription(
            tenant_id,
            plan=payload.get("plan"),
            status=payload.get("status"),
            trial_ends_at=payload.get("trial_ends_at"),
            current_period_ends_at=payload.get("current_period_ends_at"),
            update_trial_ends_at="trial_ends_at" in payload,
            update_current_period_ends_at="current_period_ends_at" in payload,
            updated_by=actor["id"],
        )
        auth_repository.forget_cached_sessions_for_tenant(tenant_id)
        app_state.append_audit(
            request_id=request_id,
            tenant_id=tenant_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.tenant.subscription.update",
            action_label="Update tenant subscription",
            risk_level="high",
            target_type="tenant_subscription",
            target_id=tenant_id,
            target_label=tenant["slug"],
            before={
                "plan": before["plan"],
                "status": before["subscription_status"],
                "trial_ends_at": before.get("trial_ends_at"),
                "current_period_ends_at": before.get("current_period_ends_at"),
            },
            after={
                "plan": updated["subscription"]["plan"],
                "status": updated["subscription"]["status"],
                "effective_status": self._to_tenant_summary(updated["tenant"]).subscription_status,
                "trial_ends_at": updated["subscription"].get("trial_ends_at"),
                "current_period_ends_at": updated["subscription"].get("current_period_ends_at"),
            },
            reason=payload["reason"],
            result="success",
            task_id=None,
        )
        return TenantActionResponse(tenant=self._to_tenant_summary(updated["tenant"]))

    def update_tenant(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_id: str,
    ) -> TenantActionResponse:
        self._ensure_admin_enabled()
        self._ensure_super_admin(actor)
        if tenant_id == actor["tenant_id"] and payload["status"] != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot suspend or disable the current admin tenant",
            )
        tenant = app_state.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found",
            )
        before = self._tenant_audit_snapshot(tenant)
        updated = app_state.update_tenant_status(tenant_id, status=payload["status"])
        revoked_count = (
            auth_repository.delete_sessions_for_tenant(tenant_id)
            if payload["status"] != "active"
            else 0
        )
        app_state.append_audit(
            request_id=request_id,
            tenant_id=tenant_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.tenant.status.update",
            action_label="Update tenant status",
            risk_level="critical",
            target_type="tenant",
            target_id=tenant_id,
            target_label=tenant["slug"],
            before=before,
            after=self._tenant_audit_snapshot(updated) | {"revoked_sessions": revoked_count},
            reason=payload["reason"],
            result="success",
            task_id=None,
        )
        return TenantActionResponse(
            tenant=self._to_tenant_summary(updated),
            revoked_session_count=revoked_count,
        )

    def reset_tenant_admin_password(
        self,
        tenant_id: str,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> TenantActionResponse:
        self._ensure_admin_enabled()
        self._ensure_super_admin(actor)
        tenant = app_state.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found",
            )
        admin_user = self._primary_tenant_admin_user(tenant_id)
        before = self._user_audit_snapshot(admin_user)
        updated_user = app_state.update_user(
            admin_user["id"],
            password="temp12345",
            force_password_reset=True,
        )
        revoked_count = auth_repository.delete_sessions_for_user(admin_user["id"])
        app_state.append_audit(
            request_id=request_id,
            tenant_id=tenant_id,
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.tenant.admin_password.reset",
            action_label="Reset tenant admin password",
            risk_level="critical",
            target_type="user",
            target_id=updated_user["id"],
            target_label=updated_user["username"],
            before=before,
            after=self._user_audit_snapshot(updated_user) | {"revoked_sessions": revoked_count},
            reason=reason,
            result="success",
            task_id=None,
        )
        return TenantActionResponse(
            tenant=self._to_tenant_summary(tenant),
            admin_user=self._to_user_detail(updated_user),
            revoked_session_count=revoked_count,
        )

    def create_user(
        self,
        payload: dict[str, Any],
        actor: dict[str, Any],
        request_id: str,
    ) -> AdminActionResponse:
        self._ensure_admin_enabled()
        if app_state.get_user_by_username(payload["username"]) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already exists",
            )
        if actor["role"] != "super_admin" and payload["role"] == "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can create super_admin users",
            )
        subscription_service.ensure_can_create_user(actor)

        user = app_state.create_user({**payload, "tenant_id": actor["tenant_id"]})
        app_state.append_audit(
            request_id=request_id,
            tenant_id=user["tenant_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.user.create",
            action_label="Create user",
            risk_level="medium",
            target_type="user",
            target_id=user["id"],
            target_label=user["username"],
            before=None,
            after=self._user_audit_snapshot(user),
            reason="创建控制台用户",
            result="success",
            task_id=None,
        )
        return AdminActionResponse(
            user=self._to_user_detail(user, feature_flags=[], active_session_count=0)
        )

    def reset_password(
        self,
        user_id: str,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> AdminActionResponse:
        self._ensure_admin_enabled()
        user = self._require_user(user_id, actor)
        before = self._user_audit_snapshot(user)
        updated = app_state.update_user(
            user_id,
            password="temp12345",
            force_password_reset=True,
        )
        self._write_user_audit(
            request_id=request_id,
            actor=actor,
            action="admin.user.reset_password",
            action_label="Reset password",
            risk_level="critical",
            target=updated,
            before=before,
            after=self._user_audit_snapshot(updated),
            reason=reason,
        )
        return AdminActionResponse(user=self._to_user_detail(updated))

    def disable_user(
        self,
        user_id: str,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> AdminActionResponse:
        self._ensure_admin_enabled()
        if user_id == actor["id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot disable the current user",
            )
        user = self._require_user(user_id, actor)
        before = self._user_audit_snapshot(user)
        updated = app_state.update_user(user_id, status="disabled")
        revoked_count = auth_repository.delete_sessions_for_user(user_id)
        after = self._user_audit_snapshot(updated) | {"revoked_sessions": revoked_count}
        self._write_user_audit(
            request_id=request_id,
            actor=actor,
            action="admin.user.disable",
            action_label="Disable user",
            risk_level="high",
            target=updated,
            before=before,
            after=after,
            reason=reason,
        )
        return AdminActionResponse(
            user=self._to_user_detail(updated),
            active_session_count=0,
        )

    def enable_user(
        self,
        user_id: str,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> AdminActionResponse:
        self._ensure_admin_enabled()
        user = self._require_user(user_id, actor)
        before = self._user_audit_snapshot(user)
        updated = app_state.update_user(user_id, status="active")
        self._write_user_audit(
            request_id=request_id,
            actor=actor,
            action="admin.user.enable",
            action_label="Enable user",
            risk_level="high",
            target=updated,
            before=before,
            after=self._user_audit_snapshot(updated),
            reason=reason,
        )
        return AdminActionResponse(user=self._to_user_detail(updated))

    def set_expiry(
        self,
        user_id: str,
        expires_at: datetime | None,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> AdminActionResponse:
        self._ensure_admin_enabled()
        if expires_at is not None:
            normalized_expiry = (
                expires_at
                if expires_at.tzinfo is not None
                else expires_at.replace(tzinfo=timezone.utc)
            )
            if normalized_expiry <= datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Expiry must be later than now",
                )
        user = self._require_user(user_id, actor)
        before = self._user_audit_snapshot(user)
        updated = app_state.update_user(user_id, expires_at=expires_at)
        self._write_user_audit(
            request_id=request_id,
            actor=actor,
            action="admin.user.set_expiry",
            action_label="Set expiry",
            risk_level="high",
            target=updated,
            before=before,
            after=self._user_audit_snapshot(updated),
            reason=reason,
        )
        return AdminActionResponse(user=self._to_user_detail(updated))

    def update_feature_flag(
        self,
        user_id: str,
        feature_key: str,
        enabled: bool,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> AdminActionResponse:
        self._ensure_admin_enabled()
        user = self._require_user(user_id, actor)
        before_flag = next(
            (
                flag
                for flag in app_state.list_user_feature_flags(user_id)
                if flag["feature_key"] == feature_key
            ),
            None,
        )
        flag = app_state.upsert_user_feature_flag(
            user_id=user_id,
            feature_key=feature_key,
            enabled=enabled,
            source="manual",
            updated_by=actor["id"],
        )
        app_state.append_audit(
            request_id=request_id,
            tenant_id=user["tenant_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.user.feature_flags.update",
            action_label="Update feature flags",
            risk_level="critical",
            target_type="user",
            target_id=user_id,
            target_label=user["username"],
            before=self._flag_audit_snapshot(before_flag),
            after=self._flag_audit_snapshot(flag),
            reason=reason,
            result="success",
            task_id=None,
        )
        return AdminActionResponse(
            user=self._to_user_detail(app_state.get_user(user_id)),
            feature_flag=self._to_feature_flag(flag),
        )

    def force_logout(
        self,
        user_id: str,
        reason: str,
        actor: dict[str, Any],
        request_id: str,
    ) -> AdminActionResponse:
        self._ensure_admin_enabled()
        user = self._require_user(user_id, actor)
        active_session_count = auth_repository.count_sessions_for_user(user_id)
        revoked_count = auth_repository.delete_sessions_for_user(user_id)
        app_state.append_audit(
            request_id=request_id,
            tenant_id=user["tenant_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="admin.user.force_logout",
            action_label="Force logout",
            risk_level="high",
            target_type="user",
            target_id=user_id,
            target_label=user["username"],
            before={"active_session_count": active_session_count},
            after={"active_session_count": 0, "revoked_sessions": revoked_count},
            reason=reason,
            result="success",
            task_id=None,
        )
        return AdminActionResponse(
            user=self._to_user_detail(user),
            active_session_count=0,
        )

    def list_audits(self, actor: dict[str, Any]) -> AuditListResponse:
        return AuditListResponse(
            audits=[
                self._to_audit(audit)
                for audit in app_state.list_audits(
                    None if actor["role"] == "super_admin" else actor["tenant_id"]
                )
            ]
        )

    def system_health(self, actor: dict[str, Any]) -> SystemHealthResponse:
        tenant_id = None if actor["role"] == "super_admin" else actor["tenant_id"]
        cache_key = tenant_id or "__all__"
        now = monotonic()
        with self._health_cache_lock:
            cached = self._health_cache.get(cache_key)
            if cached is not None:
                expires_at, response = cached
                if expires_at > now:
                    return response

            response = self._build_system_health(tenant_id)
            self._health_cache[cache_key] = (
                now + self._HEALTH_CACHE_SECONDS,
                response,
            )
            return response

    def _build_system_health(self, tenant_id: str | None) -> SystemHealthResponse:
        if hasattr(app_state, "health_counters"):
            counters = app_state.health_counters(tenant_id)
            active_tasks = counters["active_task_count"]
            audit_log_count = counters["audit_log_count"]
        else:
            active_tasks = app_state.count_active_tasks(tenant_id)
            audit_log_count = len(app_state.list_audits(tenant_id))
        components = [
            SystemComponentHealth(
                component="api",
                status="ok",
                detail="FastAPI application responding",
            ),
            SystemComponentHealth(
                component="db",
                status=getattr(app_state, "backend_status", "stub"),
                detail=getattr(app_state, "backend_detail", "Using in-memory dev state"),
            ),
            SystemComponentHealth(
                component="tasking",
                status="ok" if active_tasks < 10 else "warning",
                detail=f"active_tasks={active_tasks}",
            ),
            SystemComponentHealth(
                component="external_connectors",
                status="stub",
                detail="external connectors are still stubbed in dev mode",
            ),
        ]
        status_value = "ok" if all(item.status in {"ok", "stub"} for item in components) else "warning"
        return SystemHealthResponse(
            status=status_value,
            components=components,
            release_switches=[
                self._to_system_setting(setting)
                for setting in app_state.list_system_settings()
            ],
            active_task_count=active_tasks,
            audit_log_count=audit_log_count,
        )

    def _ensure_admin_enabled(self) -> None:
        if not app_state.is_setting_enabled("admin_enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin switch is disabled",
            )

    @staticmethod
    def _ensure_super_admin(actor: dict[str, Any]) -> None:
        if actor["role"] != "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin can manage tenants",
            )

    @staticmethod
    def _require_user(user_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        user = app_state.get_user(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在",
            )
        require_tenant_access(actor, user["tenant_id"], detail="User not found")
        return user

    @staticmethod
    def _primary_tenant_admin_user(tenant_id: str) -> dict[str, Any]:
        tenant_admins = [
            user
            for user in app_state.list_users(tenant_id)
            if user["role"] == "tenant_admin" and user["status"] != "disabled"
        ]
        if not tenant_admins:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant admin user not found",
            )
        return sorted(tenant_admins, key=lambda user: user["created_at"])[0]

    def _to_user_summary(
        self,
        user: dict[str, Any],
        *,
        feature_flags: list[dict[str, Any]] | None = None,
        active_session_count: int | None = None,
    ) -> AdminUserSummary:
        resolved_feature_flags = (
            feature_flags
            if feature_flags is not None
            else app_state.list_user_feature_flags(user["id"])
        )
        resolved_active_session_count = (
            active_session_count
            if active_session_count is not None
            else auth_repository.count_sessions_for_user(user["id"])
        )
        return AdminUserSummary(
            user_id=user["id"],
            username=user["username"],
            email=user["email"],
            role=user["role"],
            status=self._effective_user_status(user),
            expires_at=user["expires_at"],
            subscription_status=user["subscription_status"],
            feature_flags=[
                self._to_feature_flag(flag)
                for flag in resolved_feature_flags
            ],
            active_session_count=resolved_active_session_count,
        )

    def _to_user_detail(
        self,
        user: dict[str, Any] | None,
        *,
        feature_flags: list[dict[str, Any]] | None = None,
        active_session_count: int | None = None,
    ) -> AdminUserDetail:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在",
            )
        summary = self._to_user_summary(
            user,
            feature_flags=feature_flags,
            active_session_count=active_session_count,
        )
        return AdminUserDetail(
            **summary.model_dump(),
            force_password_reset=user["force_password_reset"],
            last_login_at=user["last_login_at"],
            created_at=user["created_at"],
            updated_at=user["updated_at"],
            version=user["version"],
        )

    def _to_tenant_summary(self, tenant: dict[str, Any]) -> TenantSummary:
        entitlement = app_state.get_tenant_entitlement(tenant["id"])
        usage = app_state.get_tenant_usage(tenant["id"])
        limits = entitlement["limits"]
        return TenantSummary(
            tenant_id=tenant["id"],
            slug=tenant["slug"],
            name=tenant["name"],
            status=tenant["status"],
            plan=entitlement["plan"],
            plan_name=entitlement["plan_name"],
            subscription_status=entitlement["subscription_status"],
            trial_ends_at=entitlement.get("trial_ends_at"),
            current_period_ends_at=entitlement.get("current_period_ends_at"),
            limits=TenantPlanLimits(**limits),
            usage=TenantUsage(**usage),
            remaining=TenantRemaining(
                users=max(0, int(limits["max_users"]) - int(usage["active_users"])),
                stores=max(0, int(limits["max_stores"]) - int(usage["active_stores"])),
                active_sync_tasks=max(
                    0,
                    int(limits["max_active_sync_tasks"]) - int(usage["active_sync_tasks"]),
                ),
                listings=max(0, int(limits["max_listings"]) - int(usage["listings"])),
            ),
            created_at=tenant["created_at"],
            updated_at=tenant["updated_at"],
        )

    @staticmethod
    def _to_feature_flag(flag: dict[str, Any]) -> AdminFeatureFlagResponse:
        return AdminFeatureFlagResponse(
            feature_key=flag["feature_key"],
            enabled=flag["enabled"],
            source=flag["source"],
            updated_at=flag["updated_at"],
        )

    @staticmethod
    def _to_activation_card(
        card: dict[str, Any],
        *,
        include_plain_code: bool,
    ) -> ActivationCardResponse:
        return ActivationCardResponse(
            card_id=card["id"],
            code=card.get("code") if include_plain_code else None,
            code_suffix=card["code_suffix"],
            days=card["days"],
            status=card["status"],
            note=card.get("note"),
            created_by=card.get("created_by"),
            redeemed_by=card.get("redeemed_by"),
            redeemed_tenant_id=card.get("redeemed_tenant_id"),
            redeemed_at=card.get("redeemed_at"),
            voided_by=card.get("voided_by"),
            voided_at=card.get("voided_at"),
            created_at=card["created_at"],
            updated_at=card["updated_at"],
        )

    @staticmethod
    def _activation_card_audit_snapshot(card: dict[str, Any] | None) -> dict[str, Any] | None:
        if card is None:
            return None
        return {
            "id": card["id"],
            "code_suffix": card["code_suffix"],
            "days": card["days"],
            "status": card["status"],
            "redeemed_tenant_id": card.get("redeemed_tenant_id"),
            "redeemed_by": card.get("redeemed_by"),
            "redeemed_at": card.get("redeemed_at"),
            "voided_at": card.get("voided_at"),
        }

    @staticmethod
    def _generate_activation_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        chunks = [
            "".join(secrets.choice(alphabet) for _ in range(4))
            for _ in range(4)
        ]
        return "XH-" + "-".join(chunks)

    @staticmethod
    def _hash_activation_code(code: str) -> str:
        normalized = "".join(ch for ch in code.upper() if ch.isalnum())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_system_setting(setting: dict[str, Any]) -> SystemSettingResponse:
        return SystemSettingResponse(
            setting_key=setting["setting_key"],
            value=setting["value"],
            value_type=setting["value_type"],
            description=setting["description"],
            updated_at=setting["updated_at"],
        )

    @staticmethod
    def _to_audit(audit: dict[str, Any]) -> AuditLogResponse:
        return AuditLogResponse(
            audit_id=audit["id"],
            request_id=audit["request_id"],
            tenant_id=audit["tenant_id"],
            store_id=audit["store_id"],
            actor_user_id=audit["actor_user_id"],
            actor_role=audit["actor_role"],
            actor_display_name=audit["actor_display_name"],
            action=audit["action"],
            action_label=audit["action_label"],
            risk_level=audit["risk_level"],
            target_type=audit["target_type"],
            target_id=audit["target_id"],
            target_label=audit["target_label"],
            before=audit["before"],
            after=audit["after"],
            reason=audit["reason"],
            result=audit["result"],
            error_code=audit["error_code"],
            task_id=audit["task_id"],
            created_at=audit["created_at"],
        )

    @staticmethod
    def _user_audit_snapshot(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "status": AdminService._effective_user_status(user),
            "expires_at": user["expires_at"],
            "force_password_reset": user["force_password_reset"],
        }

    @staticmethod
    def _tenant_audit_snapshot(tenant: dict[str, Any]) -> dict[str, Any]:
        return {
            "tenant_id": tenant["id"],
            "slug": tenant["slug"],
            "name": tenant["name"],
            "status": tenant["status"],
            "plan": tenant["plan"],
        }

    @staticmethod
    def _flag_audit_snapshot(flag: dict[str, Any] | None) -> dict[str, Any] | None:
        if flag is None:
            return None
        return {
            "feature_key": flag["feature_key"],
            "enabled": flag["enabled"],
            "source": flag["source"],
        }

    @staticmethod
    def _feature_flags_by_user(user_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if hasattr(app_state, "list_user_feature_flags_map"):
            return app_state.list_user_feature_flags_map(user_ids)
        return {
            user_id: app_state.list_user_feature_flags(user_id)
            for user_id in user_ids
        }

    @staticmethod
    def _effective_user_status(user: dict[str, Any]) -> str:
        current_status = user["status"]
        if current_status != "active":
            return current_status
        expires_at = user.get("expires_at")
        if expires_at is None:
            return current_status
        normalized_expiry = (
            expires_at
            if expires_at.tzinfo is not None
            else expires_at.replace(tzinfo=timezone.utc)
        )
        return "expired" if normalized_expiry <= datetime.now(timezone.utc) else current_status

    def _write_user_audit(
        self,
        *,
        request_id: str,
        actor: dict[str, Any],
        action: str,
        action_label: str,
        risk_level: str,
        target: dict[str, Any],
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str,
    ) -> None:
        app_state.append_audit(
            request_id=request_id,
            tenant_id=target["tenant_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action=action,
            action_label=action_label,
            risk_level=risk_level,
            target_type="user",
            target_id=target["id"],
            target_label=target["username"],
            before=before,
            after=after,
            reason=reason,
            result="success",
            task_id=None,
        )


def get_request_id(headers: dict[str, str]) -> str:
    return headers.get("x-request-id") or new_id()
