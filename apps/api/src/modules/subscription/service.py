from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from src.modules.auth.repo import auth_repository
from src.modules.common.dev_state import app_state
from src.modules.common.tenant_scope import require_tenant_access

from .schemas import RedeemActivationCardResponse, TenantPlanLimits, TenantRemaining, TenantUsage, TenantUsageResponse


WRITABLE_SUBSCRIPTION_STATUSES = {"trialing", "active"}
FEATURE_TO_LIMIT_KEY = {
    "sync": "sync_enabled",
    "autobid": "autobid_enabled",
    "extension": "extension_enabled",
    "listing": "listing_enabled",
}


class SubscriptionService:
    def get_tenant_usage(
        self,
        actor: dict[str, Any],
        tenant_id: str | None = None,
    ) -> TenantUsageResponse:
        resolved_tenant_id = tenant_id or actor["tenant_id"]
        require_tenant_access(actor, resolved_tenant_id, detail="Tenant not found")
        return self._build_response(resolved_tenant_id)

    def ensure_can_create_user(self, actor: dict[str, Any]) -> None:
        self._ensure_write_allowed(actor["tenant_id"])
        entitlement = app_state.get_tenant_entitlement(actor["tenant_id"])
        usage = app_state.get_tenant_usage(actor["tenant_id"])
        self._ensure_limit(
            used=int(usage["active_users"]),
            limit=int(entitlement["limits"]["max_users"]),
            label="user",
        )

    def ensure_can_create_store(self, actor: dict[str, Any]) -> None:
        self._ensure_write_allowed(actor["tenant_id"])
        entitlement = app_state.get_tenant_entitlement(actor["tenant_id"])
        usage = app_state.get_tenant_usage(actor["tenant_id"])
        self._ensure_limit(
            used=int(usage["active_stores"]),
            limit=int(entitlement["limits"]["max_stores"]),
            label="store",
        )

    def ensure_can_enqueue_sync(self, actor: dict[str, Any]) -> None:
        self._ensure_write_allowed(actor["tenant_id"])
        if not self._feature_enabled(actor["tenant_id"], "sync"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Store sync is not included in the current plan",
            )
        entitlement = app_state.get_tenant_entitlement(actor["tenant_id"])
        usage = app_state.get_tenant_usage(actor["tenant_id"])
        self._ensure_limit(
            used=int(usage["active_sync_tasks"]),
            limit=int(entitlement["limits"]["max_active_sync_tasks"]),
            label="active sync task",
        )

    def ensure_subscription_writable(self, actor: dict[str, Any]) -> None:
        self._ensure_write_allowed(actor["tenant_id"])

    def ensure_feature_enabled(self, actor: dict[str, Any], feature_key: str) -> None:
        if not self._feature_enabled(actor["tenant_id"], feature_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{feature_key} is not included in the current plan",
            )

    def ensure_writable_feature_enabled(self, actor: dict[str, Any], feature_key: str) -> None:
        self.ensure_subscription_writable(actor)
        self.ensure_feature_enabled(actor, feature_key)

    def redeem_activation_card(
        self,
        actor: dict[str, Any],
        code: str,
    ) -> RedeemActivationCardResponse:
        normalized_code = self._normalize_activation_code(code)
        try:
            result = app_state.redeem_activation_card(
                code_hash=self._hash_activation_code(normalized_code),
                tenant_id=actor["tenant_id"],
                user_id=actor["id"],
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activation card not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        auth_repository.forget_cached_sessions_for_tenant(actor["tenant_id"])
        subscription = result["subscription"]
        return RedeemActivationCardResponse(
            tenant_id=actor["tenant_id"],
            plan=subscription["plan"],
            subscription_status="active",
            current_period_ends_at=subscription["current_period_ends_at"],
            added_days=int(result["card"]["days"]),
        )

    def _build_response(self, tenant_id: str) -> TenantUsageResponse:
        entitlement = app_state.get_tenant_entitlement(tenant_id)
        usage = app_state.get_tenant_usage(tenant_id)
        limits = entitlement["limits"]
        features = self._features_from_limits(limits)
        warnings = self._warnings(entitlement, usage)
        return TenantUsageResponse(
            tenant_id=tenant_id,
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
            features=features,
            is_writable=entitlement["subscription_status"] in WRITABLE_SUBSCRIPTION_STATUSES,
            warnings=warnings,
        )

    def _ensure_write_allowed(self, tenant_id: str) -> None:
        entitlement = app_state.get_tenant_entitlement(tenant_id)
        if entitlement["subscription_status"] not in WRITABLE_SUBSCRIPTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Tenant subscription is not writable",
            )

    def _feature_enabled(self, tenant_id: str, feature_key: str) -> bool:
        entitlement = app_state.get_tenant_entitlement(tenant_id)
        limit_key = FEATURE_TO_LIMIT_KEY.get(feature_key)
        if limit_key is None:
            return False
        return bool(entitlement["limits"].get(limit_key, False))

    @staticmethod
    def _ensure_limit(*, used: int, limit: int, label: str) -> None:
        if used >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Tenant {label} quota exceeded ({used}/{limit})",
            )

    @staticmethod
    def _warnings(entitlement: dict[str, Any], usage: dict[str, Any]) -> list[str]:
        limits = entitlement["limits"]
        warnings: list[str] = []
        ratios = [
            ("users", int(usage["active_users"]), int(limits["max_users"])),
            ("stores", int(usage["active_stores"]), int(limits["max_stores"])),
            ("sync tasks", int(usage["active_sync_tasks"]), int(limits["max_active_sync_tasks"])),
            ("listings", int(usage["listings"]), int(limits["max_listings"])),
        ]
        for label, used, limit in ratios:
            if limit > 0 and used / limit >= 0.8:
                warnings.append(f"{label} usage is above 80% ({used}/{limit})")
        if entitlement["subscription_status"] not in WRITABLE_SUBSCRIPTION_STATUSES:
            warnings.append("subscription is not writable")
        return warnings

    @staticmethod
    def _features_from_limits(limits: dict[str, Any]) -> dict[str, bool]:
        return {
            "sync": bool(limits.get("sync_enabled")),
            "autobid": bool(limits.get("autobid_enabled")),
            "extension": bool(limits.get("extension_enabled")),
            "listing": bool(limits.get("listing_enabled")),
        }

    @staticmethod
    def _normalize_activation_code(code: str) -> str:
        return "".join(ch for ch in code.upper() if ch.isalnum())

    @staticmethod
    def _hash_activation_code(code: str) -> str:
        import hashlib

        return hashlib.sha256(code.encode("utf-8")).hexdigest()


subscription_service = SubscriptionService()
