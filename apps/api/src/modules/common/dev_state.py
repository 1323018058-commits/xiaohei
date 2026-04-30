from __future__ import annotations

import logging
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.platform.settings.base import settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


BUYABLE_STATUS_RE = re.compile(
    r"(^|[^a-z])(active|buyable|enabled|live|listed|published|available|synced|webhook_synced)([^a-z]|$)"
)
DISABLED_STATUS_RE = re.compile(
    r"(^|[^a-z])(disabled|inactive|unavailable|out_of_stock|not_buyable|rejected|blocked)([^a-z]|$)"
)
PLATFORM_DISABLED_TOKENS = (
    "disabled_by_takealot",
    "takealot_disabled",
    "platform_disabled",
    "disabled by takealot",
    "disabled_by_platform",
)
SELLER_DISABLED_TOKENS = (
    "disabled_by_seller",
    "seller_disabled",
    "merchant_disabled",
    "disabled_by_merchant",
    "disabled by seller",
)


def _listing_status_text(listing: dict[str, Any]) -> str:
    values: list[Any] = []

    def append_payload_status(payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        for key in ("status", "offer_status", "availability", "state"):
            values.append(payload.get(key))

    payload = listing.get("raw_payload")
    append_payload_status(payload)
    if isinstance(payload, dict):
        append_payload_status(payload.get("payload"))
    values.append(listing.get("sync_status"))
    return " ".join(str(value).lower() for value in values if value not in (None, ""))


def _listing_matches_status_group(listing: dict[str, Any], status_group: str | None) -> bool:
    if not status_group:
        return True

    status_text = _listing_status_text(listing)
    is_platform_disabled = any(token in status_text for token in PLATFORM_DISABLED_TOKENS)
    is_seller_disabled = any(token in status_text for token in SELLER_DISABLED_TOKENS)
    is_buyable = (
        bool(BUYABLE_STATUS_RE.search(status_text))
        and not bool(DISABLED_STATUS_RE.search(status_text))
        and not is_platform_disabled
        and not is_seller_disabled
    )

    if status_group == "buyable":
        return is_buyable
    if status_group == "not_buyable":
        return not is_buyable
    if status_group == "platform_disabled":
        return is_platform_disabled
    if status_group == "seller_disabled":
        return is_seller_disabled
    return True


def _listing_buybox_price(listing: dict[str, Any], rules: dict[str, dict[str, Any]]) -> float | None:
    rule = rules.get(listing.get("sku"))
    value = rule.get("last_buybox_price") if rule else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _bidding_rule_owns_buybox(rule: dict[str, Any]) -> bool:
    decision = rule.get("last_decision")
    return bool(rule.get("is_active") and isinstance(decision, dict) and decision.get("owns_buybox") is True)


def _bidding_rule_lost_buybox(rule: dict[str, Any]) -> bool:
    return bool(
        rule.get("is_active")
        and rule.get("last_buybox_price") is not None
        and not _bidding_rule_owns_buybox(rule)
    )


def _bidding_rule_has_alert(rule: dict[str, Any]) -> bool:
    if not rule.get("is_active"):
        return False
    if rule.get("buybox_status") == "blocked":
        return True
    if rule.get("last_cycle_error") or rule.get("repricing_blocked_reason"):
        return True
    if rule.get("last_action") == "floor":
        return True
    floor_price = _listing_buybox_price({"sku": rule.get("sku")}, {rule.get("sku"): {"last_buybox_price": rule.get("floor_price")}})
    buybox_price = _listing_buybox_price({"sku": rule.get("sku")}, {rule.get("sku"): rule})
    return bool(
        floor_price is not None
        and buybox_price is not None
        and buybox_price < floor_price
        and not _bidding_rule_owns_buybox(rule)
    )


def _json_number(payload: dict[str, Any] | None, *keys: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _sum_warehouse_quantity(value: Any) -> float | None:
    if not isinstance(value, list):
        return None
    total = 0.0
    found = False
    for item in value:
        if not isinstance(item, dict):
            continue
        quantity = item.get("quantity_available") or item.get("quantityAvailable") or item.get("quantity")
        try:
            total += float(quantity)
            found = True
        except (TypeError, ValueError):
            continue
    return total if found else None


def _sum_warehouse_metric(value: Any, *keys: str) -> float | None:
    if not isinstance(value, list):
        return None
    total = 0.0
    found = False
    for item in value:
        if not isinstance(item, dict):
            continue
        for key in keys:
            quantity = item.get(key)
            try:
                total += float(quantity)
                found = True
                break
            except (TypeError, ValueError):
                continue
    return total if found else None


def _listing_sort_value(
    listing: dict[str, Any],
    *,
    sort_by: str,
    rules: dict[str, dict[str, Any]],
) -> Any:
    payload = listing.get("raw_payload") if isinstance(listing.get("raw_payload"), dict) else {}
    if sort_by == "createdAt":
        return listing.get("created_at")
    if sort_by == "stockOnHand":
        return listing.get("stock_quantity") or 0
    if sort_by == "availableStock":
        return (
            _json_number(payload, "total_merchant_stock", "seller_stock_quantity")
            or _sum_warehouse_quantity(payload.get("seller_warehouse_stock"))
            or 0
        )
    if sort_by == "buyBoxPrice":
        return _listing_buybox_price(listing, rules) or -1
    if sort_by == "sellingPrice":
        return listing.get("platform_price") or 0
    if sort_by == "sales30d":
        return (
            _json_number(payload, "quantity_sold_30_days", "sales_30_days", "sales_30d", "quantity_sold_30d")
            or _sum_warehouse_metric(payload.get("takealot_warehouse_stock"), "quantity_sold_30_days", "quantitySold30Days")
            or 0
        )
    if sort_by == "cvr30d":
        return _json_number(payload, "conversion_percentage_30_days", "conversion_rate_30_days", "conversion_rate", "cvr") or 0
    if sort_by == "pageViews30d":
        return _json_number(payload, "page_views_30_days", "page_views_30d", "page_views_7_days", "page_views_7d") or 0
    if sort_by == "wishlist30d":
        return _json_number(payload, "wishlist_30_days", "wishlist_30d", "total_wishlist") or 0
    if sort_by == "returns30d":
        return _json_number(payload, "quantity_returned_30_days", "returns_30_days", "returns_30d", "quantity_returned_30d") or 0
    if sort_by == "listingQuality":
        return _json_number(payload, "listing_quality") or 0
    return listing.get("updated_at")


def bidding_runtime_defaults(now: datetime | None = None) -> dict[str, Any]:
    return {
        "next_check_at": now,
        "buybox_fetch_fail_count": 0,
        "buybox_last_error": "",
        "buybox_last_success_at": None,
        "buybox_next_retry_at": None,
        "buybox_status": "idle",
        "repricing_blocked_reason": "",
        "last_action": "",
        "last_reprice_at": None,
        "last_suggested_price": None,
        "last_applied_price": None,
        "last_buybox_price": None,
        "last_next_offer_price": None,
        "last_cycle_dry_run": True,
        "last_cycle_error": "",
        "last_decision": None,
    }


def bidding_store_runtime_defaults(store_id: str, now: datetime | None = None) -> dict[str, Any]:
    return {
        "store_id": store_id,
        "is_running": False,
        "last_started_at": None,
        "last_stopped_at": None,
        "last_manual_cycle_at": None,
        "last_worker_cycle_at": None,
        "last_cycle_summary": None,
        "created_at": now or utcnow(),
        "updated_at": now or utcnow(),
    }


def _build_demo_selection_products(now: datetime) -> dict[str, dict[str, Any]]:
    samples = [
        {
            "platform_product_id": "92000001",
            "image_url": "https://media.takealot.com/covers_images/placeholder/400x400-1.jpg",
            "title": "Wireless Rechargeable LED Desk Lamp",
            "main_category": "Home & Kitchen",
            "category_level1": "Lighting",
            "category_level2": "Desk Lamps",
            "category_level3": "Rechargeable Lamps",
            "brand": "Lumora",
            "current_price": 249.0,
            "rating": 4.6,
            "total_review_count": 1840,
            "rating_5_count": 1298,
            "rating_4_count": 366,
            "rating_3_count": 112,
            "rating_2_count": 42,
            "rating_1_count": 22,
            "stock_status": "in_stock",
            "offer_count": 7,
        },
        {
            "platform_product_id": "92000002",
            "image_url": "https://media.takealot.com/covers_images/placeholder/400x400-2.jpg",
            "title": "Kids Wooden Busy Board With LED Switches",
            "main_category": "Baby & Toddler",
            "category_level1": "Toys",
            "category_level2": "Learning Toys",
            "category_level3": "Activity Boards",
            "brand": "LittleSkill",
            "current_price": 799.0,
            "rating": 4.8,
            "total_review_count": 426,
            "rating_5_count": 361,
            "rating_4_count": 44,
            "rating_3_count": 13,
            "rating_2_count": 5,
            "rating_1_count": 3,
            "stock_status": "in_stock",
            "offer_count": 3,
        },
        {
            "platform_product_id": "92000003",
            "image_url": "https://media.takealot.com/covers_images/placeholder/400x400-3.jpg",
            "title": "Pet Stainless Steel Water Fountain 2L",
            "main_category": "Pets",
            "category_level1": "Cats",
            "category_level2": "Feeding",
            "category_level3": "Water Fountains",
            "brand": "PawSpring",
            "current_price": 329.0,
            "rating": 4.3,
            "total_review_count": 936,
            "rating_5_count": 612,
            "rating_4_count": 187,
            "rating_3_count": 91,
            "rating_2_count": 27,
            "rating_1_count": 19,
            "stock_status": "limited",
            "offer_count": 11,
        },
        {
            "platform_product_id": "92000004",
            "image_url": "https://media.takealot.com/covers_images/placeholder/400x400-4.jpg",
            "title": "USB-C 65W GaN Fast Charger",
            "main_category": "Electronics",
            "category_level1": "Accessories",
            "category_level2": "Chargers",
            "category_level3": "Wall Chargers",
            "brand": "VoltNest",
            "current_price": 399.0,
            "rating": 4.7,
            "total_review_count": 3120,
            "rating_5_count": 2460,
            "rating_4_count": 451,
            "rating_3_count": 138,
            "rating_2_count": 42,
            "rating_1_count": 29,
            "stock_status": "in_stock",
            "offer_count": 18,
        },
        {
            "platform_product_id": "92000005",
            "image_url": "https://media.takealot.com/covers_images/placeholder/400x400-5.jpg",
            "title": "Silicone Air Fryer Basket Liner Set",
            "main_category": "Home & Kitchen",
            "category_level1": "Kitchen",
            "category_level2": "Cookware Accessories",
            "category_level3": "Air Fryer Accessories",
            "brand": "CookEase",
            "current_price": 119.0,
            "rating": 4.1,
            "total_review_count": 688,
            "rating_5_count": 398,
            "rating_4_count": 161,
            "rating_3_count": 78,
            "rating_2_count": 32,
            "rating_1_count": 19,
            "stock_status": "in_stock",
            "offer_count": 24,
        },
        {
            "platform_product_id": "92000006",
            "image_url": "https://media.takealot.com/covers_images/placeholder/400x400-6.jpg",
            "title": "Portable Neck Fan With 3 Speed Modes",
            "main_category": "Appliances",
            "category_level1": "Cooling",
            "category_level2": "Fans",
            "category_level3": "Portable Fans",
            "brand": "BreezeGo",
            "current_price": 189.0,
            "rating": 3.9,
            "total_review_count": 274,
            "rating_5_count": 126,
            "rating_4_count": 73,
            "rating_3_count": 48,
            "rating_2_count": 18,
            "rating_1_count": 9,
            "stock_status": "out_of_stock",
            "offer_count": 2,
        },
    ]
    products: dict[str, dict[str, Any]] = {}
    for index, sample in enumerate(samples):
        product_id = new_id()
        products[product_id] = {
            "id": product_id,
            "platform": "takealot",
            "currency": "ZAR",
            "current_snapshot_week": now.date(),
            "latest_review_at": now - timedelta(days=index + 1),
            "status": "active",
            "first_seen_at": now - timedelta(days=30 + index),
            "last_seen_at": now - timedelta(hours=index + 1),
            "created_at": now - timedelta(days=30 + index),
            "updated_at": now - timedelta(hours=index + 1),
            **sample,
        }
    return products


DEMO_TENANT_ID = "11111111-1111-1111-1111-111111111111"
ADMIN_USER_ID = "22222222-2222-2222-2222-222222222222"
TENANT_ADMIN_USER_ID = "33333333-3333-3333-3333-333333333333"
OPERATOR_USER_ID = "44444444-4444-4444-4444-444444444444"
STORE_PRIMARY_ID = "55555555-5555-5555-5555-555555555555"
STORE_SANDBOX_ID = "66666666-6666-6666-6666-666666666666"
TASK_SYNC_ID = "77777777-7777-7777-7777-777777777777"
TASK_VALIDATE_ID = "88888888-8888-8888-8888-888888888888"

DEFAULT_RELEASE_SWITCHES: list[tuple[str, Any, str, str]] = [
    ("auth_enabled", True, "boolean", "登录主开关"),
    ("admin_enabled", True, "boolean", "Admin 主开关"),
    ("store_sync_enabled", True, "boolean", "店铺同步开关"),
    ("fulfillment_write_enabled", True, "boolean", "Fulfillment 写能力"),
    ("autobid_read_enabled", True, "boolean", "竞价查看能力"),
    ("autobid_write_enabled", False, "boolean", "竞价写能力"),
    ("listing_jobs_enabled", False, "boolean", "自动铺货任务"),
    ("finance_recalc_enabled", "restricted", "string", "财务重算能力"),
    ("maintenance_mode", False, "boolean", "整站维护模式"),
]


DEFAULT_PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "starter": {
        "plan_name": "Starter",
        "max_users": 3,
        "max_stores": 1,
        "max_active_sync_tasks": 2,
        "max_listings": 500,
        "autobid_enabled": False,
        "sync_enabled": True,
    },
    "growth": {
        "plan_name": "Growth",
        "max_users": 10,
        "max_stores": 3,
        "max_active_sync_tasks": 5,
        "max_listings": 5000,
        "autobid_enabled": True,
        "sync_enabled": True,
    },
    "scale": {
        "plan_name": "Scale",
        "max_users": 100,
        "max_stores": 20,
        "max_active_sync_tasks": 20,
        "max_listings": 50000,
        "autobid_enabled": True,
        "sync_enabled": True,
    },
    "war-room": {
        "plan_name": "War Room",
        "max_users": 1000,
        "max_stores": 200,
        "max_active_sync_tasks": 100,
        "max_listings": 1000000,
        "autobid_enabled": True,
        "sync_enabled": True,
    },
}


logger = logging.getLogger(__name__)


class MemoryAppState:
    backend_name = "memory"
    backend_status = "stub"

    def __init__(self) -> None:
        now = utcnow()
        self.backend_detail = "Using in-memory dev state"
        self.tenants: dict[str, dict[str, Any]] = {
            DEMO_TENANT_ID: {
                "id": DEMO_TENANT_ID,
                "slug": "demo-tenant",
                "name": "Demo Tenant",
                "status": "active",
                "plan": "war-room",
                "created_at": now,
                "updated_at": now,
            }
        }
        self.tenant_plan_limits = deepcopy(DEFAULT_PLAN_LIMITS)
        self.tenant_subscriptions: dict[str, dict[str, Any]] = {
            DEMO_TENANT_ID: {
                "tenant_id": DEMO_TENANT_ID,
                "plan": "war-room",
                "status": "active",
                "trial_ends_at": None,
                "current_period_ends_at": None,
                "created_at": now,
                "updated_at": now,
            }
        }
        self.users: dict[str, dict[str, Any]] = {
            ADMIN_USER_ID: {
                "id": ADMIN_USER_ID,
                "tenant_id": DEMO_TENANT_ID,
                "username": "admin",
                "email": "admin@demo.local",
                "password": "admin123",
                "role": "super_admin",
                "status": "active",
                "expires_at": None,
                "force_password_reset": False,
                "last_login_at": None,
                "subscription_status": "active",
                "created_at": now,
                "updated_at": now,
                "version": 1,
            },
            TENANT_ADMIN_USER_ID: {
                "id": TENANT_ADMIN_USER_ID,
                "tenant_id": DEMO_TENANT_ID,
                "username": "tenant_admin",
                "email": "tenant_admin@demo.local",
                "password": "tenant123",
                "role": "tenant_admin",
                "status": "active",
                "expires_at": now + timedelta(days=30),
                "force_password_reset": False,
                "last_login_at": now - timedelta(hours=5),
                "subscription_status": "active",
                "created_at": now - timedelta(days=7),
                "updated_at": now - timedelta(days=1),
                "version": 2,
            },
            OPERATOR_USER_ID: {
                "id": OPERATOR_USER_ID,
                "tenant_id": DEMO_TENANT_ID,
                "username": "operator",
                "email": "operator@demo.local",
                "password": "operator123",
                "role": "operator",
                "status": "active",
                "expires_at": None,
                "force_password_reset": False,
                "last_login_at": now - timedelta(hours=1),
                "subscription_status": "active",
                "created_at": now - timedelta(days=3),
                "updated_at": now - timedelta(hours=8),
                "version": 1,
            },
        }
        self.user_feature_flags: list[dict[str, Any]] = [
            {
                "id": new_id(),
                "user_id": ADMIN_USER_ID,
                "feature_key": "admin",
                "enabled": True,
                "source": "manual",
                "updated_by": ADMIN_USER_ID,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": new_id(),
                "user_id": ADMIN_USER_ID,
                "feature_key": "selection",
                "enabled": True,
                "source": "manual",
                "updated_by": ADMIN_USER_ID,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": new_id(),
                "user_id": TENANT_ADMIN_USER_ID,
                "feature_key": "admin",
                "enabled": True,
                "source": "manual",
                "updated_by": ADMIN_USER_ID,
                "created_at": now - timedelta(days=2),
                "updated_at": now - timedelta(days=2),
            },
            {
                "id": new_id(),
                "user_id": OPERATOR_USER_ID,
                "feature_key": "selection",
                "enabled": True,
                "source": "manual",
                "updated_by": ADMIN_USER_ID,
                "created_at": now - timedelta(days=1),
                "updated_at": now - timedelta(days=1),
            },
        ]
        self.system_settings: dict[str, dict[str, Any]] = {
            key: {
                "id": new_id(),
                "setting_key": key,
                "value": value,
                "value_type": value_type,
                "description": description,
                "updated_by": ADMIN_USER_ID,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            for key, value, value_type, description in DEFAULT_RELEASE_SWITCHES
        }
        self.stores: dict[str, dict[str, Any]] = {
            STORE_PRIMARY_ID: {
                "id": STORE_PRIMARY_ID,
                "tenant_id": DEMO_TENANT_ID,
                "name": "Takealot Main",
                "platform": "takealot",
                "status": "active",
                "api_key_status": "valid",
                "credential_status": "valid",
                "masked_api_key": "tl_********_1234",
                "last_synced_at": now - timedelta(minutes=45),
                "feature_policies": {
                    "bidding_enabled": True,
                    "listing_enabled": False,
                    "sync_enabled": True,
                },
                "created_at": now - timedelta(days=14),
                "updated_at": now - timedelta(hours=2),
                "version": 3,
            },
            STORE_SANDBOX_ID: {
                "id": STORE_SANDBOX_ID,
                "tenant_id": DEMO_TENANT_ID,
                "name": "Takealot Sandbox",
                "platform": "takealot",
                "status": "disabled",
                "api_key_status": "stale",
                "credential_status": "expired",
                "masked_api_key": "tl_********_9876",
                "last_synced_at": now - timedelta(days=2),
                "feature_policies": {
                    "bidding_enabled": False,
                    "listing_enabled": False,
                    "sync_enabled": True,
                },
                "created_at": now - timedelta(days=20),
                "updated_at": now - timedelta(days=2),
                "version": 2,
            },
        }
        self.store_credentials: dict[str, dict[str, Any]] = {
            STORE_PRIMARY_ID: {
                "platform": "takealot",
                "api_key": "demo-takealot-key",
                "api_secret": "demo-takealot-secret",
                "last_validated_at": now.isoformat(),
            },
            STORE_SANDBOX_ID: {
                "platform": "takealot",
                "api_key": "demo-sandbox-key",
                "api_secret": "demo-sandbox-secret",
                "last_validated_at": now.isoformat(),
            },
        }
        self.selection_products = _build_demo_selection_products(now)
        self.library_products: dict[str, dict[str, Any]] = {}
        self.tenant_product_guardrails: dict[str, dict[str, Any]] = {}
        self.extension_auth_tokens: dict[str, dict[str, Any]] = {}
        self.listing_jobs: dict[str, dict[str, Any]] = {}
        self.listings: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.order_items: dict[str, dict[str, Any]] = {}
        self.order_events: list[dict[str, Any]] = []
        self.bidding_rules: dict[str, dict[str, Any]] = {}
        self.bidding_store_runtime: dict[str, dict[str, Any]] = {
            store_id: bidding_store_runtime_defaults(store_id, now)
            for store_id in self.stores
        }
        self.task_runs: dict[str, dict[str, Any]] = {
            TASK_SYNC_ID: {
                "id": TASK_SYNC_ID,
                "task_type": "store.sync.full",
                "domain": "store",
                "status": "succeeded",
                "stage": "completed",
                "progress_percent": 100,
                "progress_current": 100,
                "progress_total": 100,
                "priority": "high",
                "queue_name": "store-sync",
                "tenant_id": DEMO_TENANT_ID,
                "store_id": STORE_PRIMARY_ID,
                "actor_user_id": ADMIN_USER_ID,
                "actor_role": "super_admin",
                "source_type": "api",
                "target_type": "store",
                "target_id": STORE_PRIMARY_ID,
                "request_id": "req-store-sync-running",
                "idempotency_key": "store-sync-running",
                "parent_task_id": None,
                "root_task_id": None,
                "dependency_state": None,
                "attempt_count": 1,
                "max_retries": 3,
                "retryable": True,
                "next_retry_at": None,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "started_at": now - timedelta(minutes=10),
                "finished_at": now - timedelta(minutes=9),
                "last_heartbeat_at": now - timedelta(minutes=9),
                "cancel_requested_at": None,
                "cancel_reason": None,
                "error_code": None,
                "error_msg": None,
                "error_details": None,
                "ui_meta": {
                    "label": "Takealot Main 全量同步",
                    "next_action": "商品同步已完成",
                },
                "input_payload_ref": None,
                "output_payload_ref": None,
                "created_at": now - timedelta(minutes=10),
                "updated_at": now - timedelta(minutes=9),
            },
            TASK_VALIDATE_ID: {
                "id": TASK_VALIDATE_ID,
                "task_type": "store.credentials.validate",
                "domain": "store",
                "status": "succeeded",
                "stage": "completed",
                "progress_percent": 100,
                "progress_current": 1,
                "progress_total": 1,
                "priority": "medium",
                "queue_name": "store-sync",
                "tenant_id": DEMO_TENANT_ID,
                "store_id": STORE_PRIMARY_ID,
                "actor_user_id": TENANT_ADMIN_USER_ID,
                "actor_role": "tenant_admin",
                "source_type": "api",
                "target_type": "store",
                "target_id": STORE_PRIMARY_ID,
                "request_id": "req-store-credentials",
                "idempotency_key": "store-credentials-validate",
                "parent_task_id": None,
                "root_task_id": None,
                "dependency_state": None,
                "attempt_count": 1,
                "max_retries": 2,
                "retryable": False,
                "next_retry_at": None,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "started_at": now - timedelta(hours=3),
                "finished_at": now - timedelta(hours=3) + timedelta(minutes=1),
                "last_heartbeat_at": now - timedelta(hours=3),
                "cancel_requested_at": None,
                "cancel_reason": None,
                "error_code": None,
                "error_msg": None,
                "error_details": None,
                "ui_meta": {
                    "label": "店铺凭证校验",
                    "next_action": "校验完成",
                },
                "input_payload_ref": None,
                "output_payload_ref": None,
                "created_at": now - timedelta(hours=3),
                "updated_at": now - timedelta(hours=3) + timedelta(minutes=1),
            },
        }
        self.task_events: list[dict[str, Any]] = [
            {
                "id": new_id(),
                "task_id": TASK_SYNC_ID,
                "event_type": "task.created",
                "from_status": None,
                "to_status": "created",
                "stage": "created",
                "message": "已创建店铺同步任务",
                "details": None,
                "source": "api",
                "source_id": ADMIN_USER_ID,
                "created_at": now - timedelta(minutes=10),
            },
            {
                "id": new_id(),
                "task_id": TASK_SYNC_ID,
                "event_type": "task.started",
                "from_status": "queued",
                "to_status": "running",
                "stage": "syncing",
                "message": "开始拉取店铺商品与订单",
                "details": {"progress_percent": 12},
                "source": "worker",
                "source_id": "worker-1",
                "created_at": now - timedelta(minutes=9),
            },
            {
                "id": new_id(),
                "task_id": TASK_SYNC_ID,
                "event_type": "task.progress",
                "from_status": "running",
                "to_status": "running",
                "stage": "syncing",
                "message": "已完成 62/100",
                "details": {"progress_percent": 62},
                "source": "worker",
                "source_id": "worker-1",
                "created_at": now - timedelta(seconds=20),
            },
            {
                "id": new_id(),
                "task_id": TASK_VALIDATE_ID,
                "event_type": "task.succeeded",
                "from_status": "running",
                "to_status": "succeeded",
                "stage": "completed",
                "message": "凭证校验通过",
                "details": {"credential_status": "valid"},
                "source": "worker",
                "source_id": "worker-2",
                "created_at": now - timedelta(hours=3) + timedelta(minutes=1),
            },
        ]
        self.audit_logs: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self._seed_audits(now)

    def _seed_audits(self, now: datetime) -> None:
        self.append_audit(
            request_id="req-admin-flags",
            tenant_id=DEMO_TENANT_ID,
            actor_user_id=ADMIN_USER_ID,
            actor_role="super_admin",
            action="admin.user.feature_flags.update",
            action_label="修改用户功能权限",
            risk_level="critical",
            target_type="user",
            target_id=TENANT_ADMIN_USER_ID,
            target_label="tenant_admin",
            before={"feature_key": "admin", "enabled": False},
            after={"feature_key": "admin", "enabled": True},
            reason="开放控制面读写能力",
            result="success",
            task_id=None,
            created_at=now - timedelta(days=1),
        )
        self.append_audit(
            request_id="req-store-sync",
            tenant_id=DEMO_TENANT_ID,
            store_id=STORE_PRIMARY_ID,
            actor_user_id=ADMIN_USER_ID,
            actor_role="super_admin",
            action="store.sync.start",
            action_label="触发店铺同步",
            risk_level="medium",
            target_type="store",
            target_id=STORE_PRIMARY_ID,
            target_label="Takealot Main",
            before=None,
            after={"task_id": TASK_SYNC_ID, "status": "running"},
            reason="准备上线前校验同步链路",
            result="success",
            task_id=TASK_SYNC_ID,
            created_at=now - timedelta(minutes=10),
        )

    def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return [
            deepcopy(user)
            for user in self.users.values()
            if tenant_id is None or user["tenant_id"] == tenant_id
        ]

    def list_tenants(self) -> list[dict[str, Any]]:
        return sorted(
            [deepcopy(tenant) for tenant in self.tenants.values()],
            key=lambda tenant: tenant.get("created_at", utcnow()),
            reverse=True,
        )

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        tenant = self.tenants.get(tenant_id)
        return deepcopy(tenant) if tenant else None

    def get_tenant_by_slug(self, slug: str) -> dict[str, Any] | None:
        for tenant in self.tenants.values():
            if tenant["slug"] == slug:
                return deepcopy(tenant)
        return None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        user = self.users.get(user_id)
        return deepcopy(user) if user else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        for user in self.users.values():
            if user["username"] == username:
                return deepcopy(user)
        return None

    def verify_credentials(
        self,
        username: str,
        password: str,
    ) -> dict[str, Any] | None:
        user = self.get_user_by_username(username)
        if user is None:
            return None
        if password != user["password"]:
            return None
        if user["status"] != "active":
            return None
        tenant = self.tenants.get(user["tenant_id"])
        if tenant is None or tenant["status"] != "active":
            return None
        return user

    def create_session(self, user: dict[str, Any]) -> str:
        session_token = uuid4().hex
        self.sessions[session_token] = {
            "user_id": user["id"],
            "expires_at": utcnow() + timedelta(seconds=settings.session_max_age_seconds),
            "created_at": utcnow(),
        }
        return session_token

    def authenticate_and_create_session(
        self,
        username: str,
        password: str,
        *,
        profile: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        read_started_at = perf_counter()
        user = self.verify_credentials(username, password)
        read_elapsed_ms = (perf_counter() - read_started_at) * 1000
        verify_started_at = perf_counter()
        verify_elapsed_ms = (perf_counter() - verify_started_at) * 1000
        if user is None:
            if profile is not None:
                profile["db_read_ms"] = read_elapsed_ms
                profile["verify_ms"] = verify_elapsed_ms
                profile["db_write_ms"] = 0.0
                profile["reused"] = False
            return None
        now = utcnow()
        for session_token, session in self.sessions.items():
            if (
                session["user_id"] == user["id"]
                and session["expires_at"] > now
                and session.get("created_at", now) >= now - timedelta(minutes=5)
            ):
                if profile is not None:
                    profile["db_read_ms"] = read_elapsed_ms
                    profile["verify_ms"] = verify_elapsed_ms
                    profile["db_write_ms"] = 0.0
                    profile["reused"] = True
                return session_token, user
        if profile is not None:
            profile["db_read_ms"] = read_elapsed_ms
            profile["verify_ms"] = verify_elapsed_ms
            profile["db_write_ms"] = 0.0
            profile["reused"] = False
        return self.create_session(user), user

    def get_session_user(self, session_token: str | None) -> dict[str, Any] | None:
        if not session_token:
            return None
        self._prune_expired_sessions()
        session = self.sessions.get(session_token)
        if session is None:
            return None
        current_user = self.get_user(session["user_id"])
        if current_user is None or current_user["status"] != "active":
            self.sessions.pop(session_token, None)
            return None
        tenant = self.tenants.get(current_user["tenant_id"])
        if tenant is None or tenant["status"] != "active":
            self.sessions.pop(session_token, None)
            return None
        return current_user

    def delete_session(self, session_token: str | None) -> None:
        if not session_token:
            return
        self.sessions.pop(session_token, None)

    def delete_sessions_for_user(self, user_id: str) -> int:
        self._prune_expired_sessions()
        tokens = [
            session_token
            for session_token, session in self.sessions.items()
            if session["user_id"] == user_id
        ]
        for session_token in tokens:
            self.sessions.pop(session_token, None)
        return len(tokens)

    def delete_sessions_for_tenant(self, tenant_id: str) -> int:
        self._prune_expired_sessions()
        tenant_user_ids = {
            user["id"]
            for user in self.users.values()
            if user["tenant_id"] == tenant_id
        }
        tokens = [
            session_token
            for session_token, session in self.sessions.items()
            if session["user_id"] in tenant_user_ids
        ]
        for session_token in tokens:
            self.sessions.pop(session_token, None)
        return len(tokens)

    def count_sessions_for_user(self, user_id: str) -> int:
        self._prune_expired_sessions()
        return sum(
            1
            for session in self.sessions.values()
            if session["user_id"] == user_id
        )

    def _prune_expired_sessions(self) -> None:
        now = utcnow()
        expired_tokens = [
            session_token
            for session_token, session in self.sessions.items()
            if session["expires_at"] <= now
        ]
        for session_token in expired_tokens:
            self.sessions.pop(session_token, None)

    def update_user(self, user_id: str, **changes: Any) -> dict[str, Any]:
        user = self.users[user_id]
        user.update(changes)
        user["updated_at"] = utcnow()
        user["version"] += 1
        return deepcopy(user)

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        user_id = new_id()
        user = {
            "id": user_id,
            "tenant_id": payload.get("tenant_id", DEMO_TENANT_ID),
            "username": payload["username"],
            "email": payload.get("email"),
            "password": payload.get("password", "temp12345"),
            "role": payload["role"],
            "status": payload.get("status", "active"),
            "expires_at": payload.get("expires_at"),
            "force_password_reset": payload.get("force_password_reset", True),
            "last_login_at": None,
            "subscription_status": "active",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        self.users[user_id] = user
        return deepcopy(user)

    def create_tenant_with_admin(
        self,
        payload: dict[str, Any],
        updated_by: str,
    ) -> dict[str, dict[str, Any]]:
        now = utcnow()
        tenant_id = new_id()
        tenant = {
            "id": tenant_id,
            "slug": payload["slug"],
            "name": payload["name"],
            "status": "active",
            "plan": payload["plan"],
            "created_at": now,
            "updated_at": now,
        }
        subscription = {
            "tenant_id": tenant_id,
            "plan": payload["plan"],
            "status": payload["subscription_status"],
            "trial_ends_at": None,
            "current_period_ends_at": None,
            "updated_by": updated_by,
            "created_at": now,
            "updated_at": now,
        }
        admin_user = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "username": payload["admin_username"],
            "email": payload.get("admin_email"),
            "password": payload["admin_password"],
            "role": "tenant_admin",
            "status": "active",
            "expires_at": None,
            "force_password_reset": False,
            "last_login_at": None,
            "subscription_status": subscription["status"],
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        self.tenants[tenant_id] = tenant
        self.tenant_subscriptions[tenant_id] = subscription
        self.users[admin_user["id"]] = admin_user
        return {
            "tenant": deepcopy(tenant),
            "admin_user": deepcopy(admin_user),
            "subscription": deepcopy(subscription),
        }

    def update_tenant_subscription(
        self,
        tenant_id: str,
        *,
        plan: str | None,
        status: str | None,
        trial_ends_at: Any | None = None,
        current_period_ends_at: Any | None = None,
        update_trial_ends_at: bool = False,
        update_current_period_ends_at: bool = False,
        updated_by: str,
    ) -> dict[str, dict[str, Any]]:
        tenant = self.tenants[tenant_id]
        now = utcnow()
        subscription = self.tenant_subscriptions.setdefault(
            tenant_id,
            {
                "tenant_id": tenant_id,
                "plan": tenant["plan"],
                "status": "active",
                "trial_ends_at": None,
                "current_period_ends_at": None,
                "created_at": now,
            },
        )
        if plan is not None:
            tenant["plan"] = plan
            subscription["plan"] = plan
        if status is not None:
            subscription["status"] = status
        if update_trial_ends_at:
            subscription["trial_ends_at"] = trial_ends_at
        if update_current_period_ends_at:
            subscription["current_period_ends_at"] = current_period_ends_at
        tenant["updated_at"] = now
        subscription["updated_by"] = updated_by
        subscription["updated_at"] = now
        effective_status = self._effective_subscription_status(subscription)
        for user in self.users.values():
            if user["tenant_id"] == tenant_id:
                user["subscription_status"] = effective_status
        return {
            "tenant": deepcopy(tenant),
            "subscription": deepcopy(subscription),
        }

    def update_tenant_status(
        self,
        tenant_id: str,
        *,
        status: str,
    ) -> dict[str, Any]:
        tenant = self.tenants[tenant_id]
        tenant["status"] = status
        tenant["updated_at"] = utcnow()
        return deepcopy(tenant)

    def list_user_feature_flags(self, user_id: str) -> list[dict[str, Any]]:
        return [
            deepcopy(flag)
            for flag in self.user_feature_flags
            if flag["user_id"] == user_id
        ]

    def upsert_user_feature_flag(
        self,
        *,
        user_id: str,
        feature_key: str,
        enabled: bool,
        source: str,
        updated_by: str,
    ) -> dict[str, Any]:
        now = utcnow()
        for flag in self.user_feature_flags:
            if flag["user_id"] == user_id and flag["feature_key"] == feature_key:
                flag["enabled"] = enabled
                flag["source"] = source
                flag["updated_by"] = updated_by
                flag["updated_at"] = now
                return deepcopy(flag)

        flag = {
            "id": new_id(),
            "user_id": user_id,
            "feature_key": feature_key,
            "enabled": enabled,
            "source": source,
            "updated_by": updated_by,
            "created_at": now,
            "updated_at": now,
        }
        self.user_feature_flags.append(flag)
        return deepcopy(flag)

    def list_system_settings(self) -> list[dict[str, Any]]:
        return [deepcopy(setting) for setting in self.system_settings.values()]

    def get_system_setting(self, setting_key: str) -> dict[str, Any] | None:
        setting = self.system_settings.get(setting_key)
        return deepcopy(setting) if setting else None

    def is_setting_enabled(self, setting_key: str, default: bool = False) -> bool:
        setting = self.system_settings.get(setting_key)
        if setting is None:
            return default
        if setting["value_type"] != "boolean":
            return default
        return bool(setting["value"])

    def list_stores(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return [
            deepcopy(store)
            for store in self.stores.values()
            if tenant_id is None or store["tenant_id"] == tenant_id
        ]

    def get_store(self, store_id: str) -> dict[str, Any] | None:
        store = self.stores.get(store_id)
        return deepcopy(store) if store else None

    def create_store(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("platform", "takealot") != "takealot":
            raise ValueError("Only Takealot stores are supported")
        now = utcnow()
        store_id = new_id()
        store = {
            "id": store_id,
            "tenant_id": payload.get("tenant_id", DEMO_TENANT_ID),
            "name": payload["name"],
            "platform": payload.get("platform", "takealot"),
            "status": payload.get("status", "active"),
            "api_key_status": payload.get(
                "api_key_status",
                "configured" if payload.get("api_key") else "pending",
            ),
            "credential_status": payload.get(
                "credential_status",
                "configured"
                if payload.get("api_key") and payload.get("api_secret")
                else "missing",
            ),
            "masked_api_key": payload.get("masked_api_key", "not-set"),
            "platform_profile": deepcopy(payload.get("platform_profile")),
            "last_synced_at": None,
            "feature_policies": payload.get(
                "feature_policies",
                {
                    "bidding_enabled": False,
                    "listing_enabled": False,
                    "sync_enabled": True,
                },
            ),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        self.stores[store_id] = store
        self.bidding_store_runtime[store_id] = bidding_store_runtime_defaults(store_id, now)
        self.store_credentials[store_id] = {
            "platform": store["platform"],
            "api_key": payload.get("api_key", ""),
            "api_secret": payload.get("api_secret", ""),
            "leadtime_merchant_warehouse_id": payload.get("leadtime_merchant_warehouse_id"),
        }
        return deepcopy(store)

    def update_store(self, store_id: str, **changes: Any) -> dict[str, Any]:
        api_key = changes.pop("api_key", None)
        api_secret = changes.pop("api_secret", None)
        credential_platform = changes.pop("credential_platform", None)
        if credential_platform is not None and credential_platform != "takealot":
            raise ValueError("Only Takealot store credentials are supported")
        store = self.stores[store_id]
        store.update(changes)
        if api_key is not None and api_secret is not None:
            current_credentials = self.store_credentials.get(store_id, {})
            self.store_credentials[store_id] = {
                "platform": credential_platform or store["platform"],
                "api_key": api_key,
                "api_secret": api_secret,
                "leadtime_merchant_warehouse_id": (
                    changes.get("leadtime_merchant_warehouse_id")
                    if changes.get("leadtime_merchant_warehouse_id") is not None
                    else current_credentials.get("leadtime_merchant_warehouse_id")
                ),
                "last_validated_at": (
                    changes.get("last_validated_at")
                    if changes.get("last_validated_at") is not None
                    else current_credentials.get("last_validated_at")
                ),
                "platform_profile": (
                    deepcopy(changes.get("platform_profile"))
                    if changes.get("platform_profile") is not None
                    else current_credentials.get("platform_profile")
                ),
            }
        elif changes.get("leadtime_merchant_warehouse_id") is not None:
            credential_state = self.store_credentials.setdefault(
                store_id,
                {
                    "platform": credential_platform or store["platform"],
                    "api_key": "",
                    "api_secret": "",
                    "leadtime_merchant_warehouse_id": None,
                },
            )
            credential_state["leadtime_merchant_warehouse_id"] = changes["leadtime_merchant_warehouse_id"]
        elif (
            changes.get("last_validated_at") is not None
            or changes.get("platform_profile") is not None
        ):
            credential_state = self.store_credentials.setdefault(
                store_id,
                {
                    "platform": credential_platform or store["platform"],
                    "api_key": "",
                    "api_secret": "",
                    "leadtime_merchant_warehouse_id": None,
                },
            )
            if changes.get("last_validated_at") is not None:
                credential_state["last_validated_at"] = changes["last_validated_at"]
            if changes.get("platform_profile") is not None:
                credential_state["platform_profile"] = deepcopy(changes["platform_profile"])
        store["updated_at"] = utcnow()
        store["version"] += 1
        return deepcopy(store)

    def get_store_credentials(self, store_id: str) -> dict[str, Any] | None:
        credentials = self.store_credentials.get(store_id)
        return deepcopy(credentials) if credentials else None

    def delete_store(self, store_id: str) -> bool:
        if store_id not in self.stores:
            return False
        self.stores.pop(store_id, None)
        self.store_credentials.pop(store_id, None)
        self.bidding_store_runtime.pop(store_id, None)
        stale_listing_ids = {
            listing_id
            for listing_id, listing in self.listings.items()
            if listing["store_id"] == store_id
        }
        for listing_id in stale_listing_ids:
            self.listings.pop(listing_id, None)
        stale_rule_ids = [
            rule_id
            for rule_id, rule in self.bidding_rules.items()
            if rule["store_id"] == store_id
        ]
        for rule_id in stale_rule_ids:
            self.bidding_rules.pop(rule_id, None)
        stale_job_ids = [
            job_id
            for job_id, job in self.listing_jobs.items()
            if job["store_id"] == store_id
        ]
        for job_id in stale_job_ids:
            self.listing_jobs.pop(job_id, None)
        stale_order_ids = {
            order_id
            for order_id, order in self.orders.items()
            if order["store_id"] == store_id
        }
        stale_order_item_ids = [
            item_id
            for item_id, item in self.order_items.items()
            if item["order_id"] in stale_order_ids
        ]
        for item_id in stale_order_item_ids:
            self.order_items.pop(item_id, None)
        for order_id in stale_order_ids:
            self.orders.pop(order_id, None)
        self.order_events = [
            event
            for event in self.order_events
            if event.get("order_id") not in stale_order_ids
        ]
        return True

    def list_store_listings(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
        status_group: str | None = None,
        sku_filter: set[str] | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        bidding_rules_by_sku = {
            rule["sku"]: rule
            for rule in self.bidding_rules.values()
            if rule["store_id"] == store_id
        }
        listings = [
            {**listing, "buybox_price": _listing_buybox_price(listing, bidding_rules_by_sku)}
            for listing in self.listings.values()
            if listing["store_id"] == store_id
            and listing.get("sync_status") != "stale"
            and (sku_filter is None or listing["sku"] in sku_filter)
            and _listing_matches_status_group(listing, status_group)
            and (
                not sku_query
                or sku_query.lower() in listing["sku"].lower()
                or sku_query.lower() in listing["title"].lower()
            )
        ]
        sort_field = sort_by or "createdAt"
        reverse = sort_dir != "asc"
        listings.sort(
            key=lambda item: (
                _listing_sort_value(item, sort_by=sort_field, rules=bidding_rules_by_sku),
                item["sku"],
            ),
            reverse=reverse,
        )
        if limit is not None:
            listings = listings[offset:offset + limit]
        elif offset:
            listings = listings[offset:]
        return [deepcopy(listing) for listing in listings]

    def count_store_listings(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
        status_group: str | None = None,
        sku_filter: set[str] | None = None,
    ) -> int:
        return len(
            self.list_store_listings(
                store_id=store_id,
                sku_query=sku_query,
                status_group=status_group,
                sku_filter=sku_filter,
            )
        )

    def count_store_listing_status_groups(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
        sku_filter: set[str] | None = None,
    ) -> dict[str, int]:
        return {
            "all": self.count_store_listings(
                store_id=store_id,
                sku_query=sku_query,
                sku_filter=sku_filter,
            ),
            "buyable": self.count_store_listings(
                store_id=store_id,
                sku_query=sku_query,
                status_group="buyable",
                sku_filter=sku_filter,
            ),
            "not_buyable": self.count_store_listings(
                store_id=store_id,
                sku_query=sku_query,
                status_group="not_buyable",
                sku_filter=sku_filter,
            ),
            "platform_disabled": self.count_store_listings(
                store_id=store_id,
                sku_query=sku_query,
                status_group="platform_disabled",
                sku_filter=sku_filter,
            ),
            "seller_disabled": self.count_store_listings(
                store_id=store_id,
                sku_query=sku_query,
                status_group="seller_disabled",
                sku_filter=sku_filter,
            ),
        }

    def get_store_listing(
        self,
        *,
        store_id: str,
        listing_id: str,
    ) -> dict[str, Any] | None:
        listing = self.listings.get(listing_id)
        if (
            listing is None
            or listing["store_id"] != store_id
            or listing.get("sync_status") == "stale"
        ):
            return None
        bidding_rules_by_sku = {
            rule["sku"]: rule
            for rule in self.bidding_rules.values()
            if rule["store_id"] == store_id
        }
        return deepcopy(
            {
                **listing,
                "buybox_price": _listing_buybox_price(listing, bidding_rules_by_sku),
            }
        )

    def update_store_listing(
        self,
        *,
        store_id: str,
        listing_id: str,
        platform_price: float | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        listing = self.listings.get(listing_id)
        if (
            listing is None
            or listing["store_id"] != store_id
            or listing.get("sync_status") == "stale"
        ):
            return None
        if platform_price is not None:
            listing["platform_price"] = platform_price
        if raw_payload is not None:
            listing["raw_payload"] = deepcopy(raw_payload)
        listing["updated_at"] = utcnow()
        return self.get_store_listing(store_id=store_id, listing_id=listing_id)

    def upsert_store_listing(
        self,
        *,
        store_id: str,
        external_listing_id: str,
        platform_product_id: str | None,
        sku: str,
        title: str,
        platform_price: float | None,
        stock_quantity: int | None,
        currency: str,
        sync_status: str,
        raw_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        now = utcnow()
        for listing in self.listings.values():
            if (
                listing["store_id"] == store_id
                and listing["external_listing_id"] == external_listing_id
            ):
                listing.update(
                    {
                        "platform_product_id": platform_product_id or listing.get("platform_product_id"),
                        "sku": sku,
                        "title": title,
                        "platform_price": platform_price,
                        "stock_quantity": stock_quantity,
                        "currency": currency,
                        "sync_status": sync_status,
                        "raw_payload": deepcopy(raw_payload),
                        "last_synced_at": now,
                        "updated_at": now,
                    }
                )
                return deepcopy(listing)

        listing_id = new_id()
        listing = {
            "id": listing_id,
            "store_id": store_id,
            "external_listing_id": external_listing_id,
            "platform_product_id": platform_product_id,
            "sku": sku,
            "title": title,
            "platform_price": platform_price,
            "stock_quantity": stock_quantity,
            "currency": currency,
            "sync_status": sync_status,
            "raw_payload": deepcopy(raw_payload),
            "last_synced_at": now,
            "created_at": now,
            "updated_at": now,
        }
        self.listings[listing_id] = listing
        return deepcopy(listing)

    def upsert_store_listings_bulk(self, listings: list[dict[str, Any]]) -> int:
        for listing in listings:
            self.upsert_store_listing(**listing)
        return len(listings)

    def mark_store_listings_stale_except(
        self,
        *,
        store_id: str,
        external_listing_ids: list[str],
    ) -> int:
        active_external_ids = set(external_listing_ids)
        stale_count = 0
        for listing in self.listings.values():
            if listing["store_id"] != store_id:
                continue
            if listing["external_listing_id"] in active_external_ids:
                continue
            if listing.get("sync_status") == "stale":
                continue
            listing["sync_status"] = "stale"
            listing["updated_at"] = utcnow()
            stale_count += 1
        return stale_count

    def find_store_listing_by_platform_product_id(
        self,
        *,
        store_id: str,
        platform_product_id: str,
    ) -> dict[str, Any] | None:
        for listing in self.listings.values():
            if (
                listing["store_id"] == store_id
                and listing.get("platform_product_id") == platform_product_id
            ):
                return deepcopy(listing)
        return None

    def get_library_product(
        self,
        *,
        platform: str,
        external_product_id: str,
    ) -> dict[str, Any] | None:
        for product in self.library_products.values():
            if (
                product["platform"] == platform
                and product["external_product_id"] == external_product_id
            ):
                return deepcopy(product)
        return None

    def get_library_product_by_id(self, product_id: str) -> dict[str, Any] | None:
        product = self.library_products.get(product_id)
        return deepcopy(product) if product else None

    def upsert_library_product(
        self,
        *,
        platform: str,
        external_product_id: str,
        title: str,
        fact_status: str,
        raw_payload: dict[str, Any] | None,
        merchant_packaged_weight_raw: str | None = None,
        merchant_packaged_dimensions_raw: str | None = None,
        cbs_package_weight_raw: str | None = None,
        cbs_package_dimensions_raw: str | None = None,
        consolidated_packaged_dimensions_raw: str | None = None,
        last_refreshed_at: datetime | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        existing = self.get_library_product(
            platform=platform,
            external_product_id=external_product_id,
        )
        if existing is not None:
            stored = self.library_products[existing["id"]]
            stored.update(
                {
                    "title": title or stored["title"],
                    "fact_status": fact_status or stored["fact_status"],
                    "raw_payload": deepcopy(raw_payload) if raw_payload is not None else stored.get("raw_payload"),
                    "merchant_packaged_weight_raw": merchant_packaged_weight_raw or stored.get("merchant_packaged_weight_raw"),
                    "merchant_packaged_dimensions_raw": merchant_packaged_dimensions_raw or stored.get("merchant_packaged_dimensions_raw"),
                    "cbs_package_weight_raw": cbs_package_weight_raw or stored.get("cbs_package_weight_raw"),
                    "cbs_package_dimensions_raw": cbs_package_dimensions_raw or stored.get("cbs_package_dimensions_raw"),
                    "consolidated_packaged_dimensions_raw": consolidated_packaged_dimensions_raw or stored.get("consolidated_packaged_dimensions_raw"),
                    "last_refreshed_at": last_refreshed_at or stored.get("last_refreshed_at"),
                    "updated_at": now,
                }
            )
            return deepcopy(stored)

        product_id = new_id()
        product = {
            "id": product_id,
            "platform": platform,
            "external_product_id": external_product_id,
            "title": title,
            "brand": None,
            "category": None,
            "fact_status": fact_status,
            "merchant_packaged_weight_raw": merchant_packaged_weight_raw,
            "merchant_packaged_dimensions_raw": merchant_packaged_dimensions_raw,
            "cbs_package_weight_raw": cbs_package_weight_raw,
            "cbs_package_dimensions_raw": cbs_package_dimensions_raw,
            "consolidated_packaged_dimensions_raw": consolidated_packaged_dimensions_raw,
            "raw_payload": deepcopy(raw_payload) if raw_payload is not None else None,
            "last_refreshed_at": last_refreshed_at,
            "created_at": now,
            "updated_at": now,
        }
        self.library_products[product_id] = product
        return deepcopy(product)

    def list_selection_products(
        self,
        *,
        query: str | None = None,
        main_category: str | None = None,
        category_level1: str | None = None,
        category_level2: str | None = None,
        category_level3: str | None = None,
        brand: str | None = None,
        stock_status: str | None = None,
        latest_review_window: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        min_rating: float | None = None,
        min_reviews: int | None = None,
        min_offer_count: int | None = None,
        max_offer_count: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        products = list(self.selection_products.values())
        query_text = (query or "").strip().lower()
        if query_text:
            products = [
                product
                for product in products
                if query_text in product["title"].lower()
                or query_text in product["platform_product_id"].lower()
                or query_text in (product.get("brand") or "").lower()
            ]

        exact_filters = {
            "main_category": main_category,
            "category_level1": category_level1,
            "category_level2": category_level2,
            "category_level3": category_level3,
        }
        for key, value in exact_filters.items():
            if value:
                products = [product for product in products if product.get(key) == value]

        if brand == "__has_brand__":
            products = [product for product in products if product.get("brand")]
        elif brand == "__no_brand__":
            products = [product for product in products if not product.get("brand")]
        elif brand:
            products = [product for product in products if product.get("brand") == brand]

        if stock_status:
            products = [
                product
                for product in products
                if selection_stock_status_matches(product.get("stock_status"), stock_status)
            ]

        if latest_review_window:
            products = [
                product
                for product in products
                if selection_latest_review_matches(product.get("latest_review_at"), latest_review_window)
            ]

        def number_value(product: dict[str, Any], key: str) -> float | None:
            value = product.get(key)
            return float(value) if value is not None else None

        if min_price is not None:
            products = [
                product
                for product in products
                if number_value(product, "current_price") is not None
                and number_value(product, "current_price") >= min_price
            ]
        if max_price is not None:
            products = [
                product
                for product in products
                if number_value(product, "current_price") is not None
                and number_value(product, "current_price") <= max_price
            ]
        if min_rating is not None:
            products = [
                product
                for product in products
                if number_value(product, "rating") is not None
                and number_value(product, "rating") >= min_rating
            ]
        if min_reviews is not None:
            products = [
                product
                for product in products
                if number_value(product, "total_review_count") is not None
                and number_value(product, "total_review_count") >= min_reviews
            ]
        if min_offer_count is not None:
            products = [
                product
                for product in products
                if number_value(product, "offer_count") is not None
                and number_value(product, "offer_count") >= min_offer_count
            ]
        if max_offer_count is not None:
            products = [
                product
                for product in products
                if number_value(product, "offer_count") is not None
                and number_value(product, "offer_count") <= max_offer_count
            ]

        products.sort(
            key=lambda product: (
                product.get("total_review_count") or 0,
                product.get("updated_at") or utcnow(),
                product.get("rating") or 0,
            ),
            reverse=True,
        )
        total = len(products)
        return {
            "products": [deepcopy(product) for product in products[offset:offset + limit]],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_selection_filter_options(
        self,
        *,
        main_category: str | None = None,
        category_level1: str | None = None,
        category_level2: str | None = None,
        category_level3: str | None = None,
        brand: str | None = None,
        stock_status: str | None = None,
    ) -> dict[str, Any]:
        products = list(self.selection_products.values())
        filters = {
            "main_category": main_category,
            "category_level1": category_level1,
            "category_level2": category_level2,
            "category_level3": category_level3,
        }
        brand_filter = brand
        stock_filter = stock_status

        def distinct(key: str, limit: int = 100) -> list[str]:
            scoped_products = [
                product
                for product in products
                if all(
                    not value or column == key or product.get(column) == value
                    for column, value in filters.items()
                )
                and selection_brand_matches(product.get("brand"), brand_filter)
                and selection_stock_status_matches(product.get("stock_status"), stock_filter)
            ]
            values = sorted(
                {
                    str(product[key])
                    for product in scoped_products
                    if product.get(key) not in (None, "")
                }
            )
            return values[:limit]

        return {
            "main_categories": distinct("main_category"),
            "category_level1": distinct("category_level1"),
            "category_level2": distinct("category_level2"),
            "category_level3": distinct("category_level3"),
            "brands": ["__has_brand__", "__no_brand__"],
            "stock_statuses": [
                "__in_stock__",
                "__ships_in__",
                "__direct_ship__",
                "__pre_order__",
                "__out_of_stock__",
            ],
            "category_tree": self._selection_category_tree(products),
        }

    @staticmethod
    def _selection_category_tree(products: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
        tree_sets: dict[str, dict[str, set[str]]] = {}
        for product in products:
            main_category = product.get("main_category")
            category_level1 = product.get("category_level1")
            category_level2 = product.get("category_level2")
            if not main_category or not category_level1:
                continue
            branch = tree_sets.setdefault(str(main_category), {})
            leaves = branch.setdefault(str(category_level1), set())
            if category_level2:
                leaves.add(str(category_level2))

        return {
            main_category: {
                level1: sorted(level2_values)
                for level1, level2_values in sorted(branch.items())
            }
            for main_category, branch in sorted(tree_sets.items())
        }

    def get_tenant_product_guardrail(
        self,
        *,
        tenant_id: str,
        store_id: str,
        product_id: str,
    ) -> dict[str, Any] | None:
        for guardrail in self.tenant_product_guardrails.values():
            if (
                guardrail["tenant_id"] == tenant_id
                and guardrail["store_id"] == store_id
                and guardrail["product_id"] == product_id
            ):
                return deepcopy(guardrail)
        return None

    def upsert_tenant_product_guardrail(
        self,
        *,
        tenant_id: str,
        store_id: str,
        product_id: str,
        protected_floor_price: float,
        created_by: str | None,
        updated_by: str | None,
        status: str,
        autobid_sync_status: str,
        source: str,
    ) -> dict[str, Any]:
        now = utcnow()
        existing = self.get_tenant_product_guardrail(
            tenant_id=tenant_id,
            store_id=store_id,
            product_id=product_id,
        )
        if existing is not None:
            stored = self.tenant_product_guardrails[existing["id"]]
            stored.update(
                {
                    "protected_floor_price": protected_floor_price,
                    "status": status,
                    "autobid_sync_status": autobid_sync_status,
                    "source": source,
                    "updated_by": updated_by,
                    "updated_at": now,
                }
            )
            return deepcopy(stored)

        guardrail_id = new_id()
        guardrail = {
            "id": guardrail_id,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "product_id": product_id,
            "protected_floor_price": protected_floor_price,
            "status": status,
            "linked_listing_id": None,
            "linked_bidding_rule_id": None,
            "autobid_sync_status": autobid_sync_status,
            "source": source,
            "last_synced_at": None,
            "last_error_code": None,
            "last_error_message": None,
            "created_by": created_by,
            "updated_by": updated_by,
            "created_at": now,
            "updated_at": now,
        }
        self.tenant_product_guardrails[guardrail_id] = guardrail
        return deepcopy(guardrail)

    def update_tenant_product_guardrail(
        self,
        guardrail_id: str,
        **changes: Any,
    ) -> dict[str, Any] | None:
        guardrail = self.tenant_product_guardrails.get(guardrail_id)
        if guardrail is None:
            return None
        guardrail.update(changes | {"updated_at": utcnow()})
        if changes.get("autobid_sync_status") == "synced":
            guardrail["last_synced_at"] = utcnow()
        return deepcopy(guardrail)

    def list_guardrails_for_store_platform_product(
        self,
        *,
        store_id: str,
        platform: str,
        external_product_id: str,
    ) -> list[dict[str, Any]]:
        product = self.get_library_product(
            platform=platform,
            external_product_id=external_product_id,
        )
        if product is None:
            return []
        return [
            deepcopy(guardrail)
            for guardrail in self.tenant_product_guardrails.values()
            if guardrail["store_id"] == store_id and guardrail["product_id"] == product["id"]
        ]

    def create_extension_auth_token(
        self,
        *,
        token_hash: str,
        tenant_id: str,
        user_id: str,
        store_id: str | None,
        expires_at: datetime,
    ) -> dict[str, Any]:
        token_id = new_id()
        record = {
            "id": token_id,
            "token_hash": token_hash,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "store_id": store_id,
            "expires_at": expires_at,
            "last_seen_at": None,
            "created_at": utcnow(),
        }
        self.extension_auth_tokens[token_hash] = record
        return deepcopy(record)

    def get_extension_auth_token(self, token_hash: str) -> dict[str, Any] | None:
        record = self.extension_auth_tokens.get(token_hash)
        if record is None:
            return None
        if record["expires_at"] <= utcnow():
            self.extension_auth_tokens.pop(token_hash, None)
            return None
        return deepcopy(record)

    def touch_extension_auth_token(self, token_hash: str) -> dict[str, Any] | None:
        record = self.extension_auth_tokens.get(token_hash)
        if record is None:
            return None
        record["last_seen_at"] = utcnow()
        return deepcopy(record)

    def create_listing_job(
        self,
        *,
        tenant_id: str,
        store_id: str,
        product_id: str | None,
        guardrail_id: str | None,
        entry_task_id: str | None,
        processing_task_id: str | None,
        platform: str,
        source: str,
        source_ref: str | None,
        title: str,
        status: str,
        stage: str,
        note: str | None,
        raw_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        now = utcnow()
        job_id = new_id()
        job = {
            "id": job_id,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "product_id": product_id,
            "guardrail_id": guardrail_id,
            "entry_task_id": entry_task_id,
            "processing_task_id": processing_task_id,
            "platform": platform,
            "source": source,
            "source_ref": source_ref,
            "title": title,
            "status": status,
            "stage": stage,
            "note": note,
            "raw_payload": deepcopy(raw_payload) if raw_payload is not None else None,
            "created_at": now,
            "updated_at": now,
        }
        self.listing_jobs[job_id] = job
        return deepcopy(job)

    def update_listing_job(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        job = self.listing_jobs.get(job_id)
        if job is None:
            return None
        for key, value in changes.items():
            job[key] = deepcopy(value)
        job["updated_at"] = utcnow()
        return deepcopy(job)

    def get_listing_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.listing_jobs.get(job_id)
        return deepcopy(job) if job else None

    def list_listing_jobs(
        self,
        tenant_id: str | None = None,
        *,
        store_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        jobs = [
            deepcopy(job)
            for job in self.listing_jobs.values()
            if (tenant_id is None or job["tenant_id"] == tenant_id)
            and (store_id is None or job["store_id"] == store_id)
            and (status_filter is None or job["status"] == status_filter)
        ]
        jobs.sort(key=lambda item: item["created_at"], reverse=True)
        return jobs

    def list_orders(
        self,
        *,
        tenant_id: str | None = None,
        store_id: str | None = None,
        status_filter: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_query = query.lower() if query else None
        orders = [
            self._with_order_counts(order)
            for order in self.orders.values()
            if (tenant_id is None or order["tenant_id"] == tenant_id)
            and (store_id is None or order["store_id"] == store_id)
            and (status_filter is None or order["status"] == status_filter)
            and (
                normalized_query is None
                or normalized_query in order["external_order_id"].lower()
                or normalized_query in str(order.get("order_number") or "").lower()
                or any(
                    normalized_query in item["sku"].lower()
                    for item in self.order_items.values()
                    if item["order_id"] == order["id"]
                )
            )
        ]
        orders.sort(
            key=lambda item: item["placed_at"] or item["updated_at"],
            reverse=True,
        )
        return [deepcopy(order) for order in orders]

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        order = self.orders.get(order_id)
        return deepcopy(self._with_order_counts(order)) if order else None

    def list_order_items(self, order_id: str) -> list[dict[str, Any]]:
        items = [
            deepcopy(item)
            for item in self.order_items.values()
            if item["order_id"] == order_id
        ]
        items.sort(key=lambda item: item["sku"])
        return items

    def list_order_events(self, order_id: str) -> list[dict[str, Any]]:
        events = [
            deepcopy(event)
            for event in self.order_events
            if event["order_id"] == order_id
        ]
        events.sort(key=lambda item: item["created_at"], reverse=True)
        return events

    def get_dashboard_metrics(
        self,
        *,
        tenant_id: str | None,
        business_timezone: str,
        business_day_start: datetime,
        business_day_end: datetime,
        chart_start: datetime,
        chart_end: datetime,
    ) -> dict[str, Any]:
        business_zone = ZoneInfo(business_timezone)
        relevant_orders = [
            order
            for order in self.orders.values()
            if tenant_id is None or order["tenant_id"] == tenant_id
        ]
        today_orders = [
            order
            for order in relevant_orders
            if _is_at_or_after(order.get("placed_at") or order.get("created_at"), business_day_start)
            and _is_before(order.get("placed_at") or order.get("created_at"), business_day_end)
        ]
        order_quantities = self._dashboard_order_quantities()
        chart: dict[str, dict[str, Any]] = {}
        for order in relevant_orders:
            placed_at = order.get("placed_at") or order.get("created_at")
            if not _is_at_or_after(placed_at, chart_start) or not _is_before(placed_at, chart_end):
                continue
            key = _local_date_key(placed_at, business_zone)
            bucket = chart.setdefault(key, {"date": key, "sales": 0.0, "volume": 0})
            bucket["sales"] += float(order.get("total_amount") or 0)
            bucket["volume"] += order_quantities.get(order["id"], 0)

        relevant_jobs = [
            job
            for job in self.listing_jobs.values()
            if tenant_id is None or job["tenant_id"] == tenant_id
        ]
        today_jobs = [
            job
            for job in relevant_jobs
            if _is_at_or_after(job.get("updated_at"), business_day_start)
            and _is_before(job.get("updated_at"), business_day_end)
        ]
        order_sync_tasks = [
            task
            for task in self.task_runs.values()
            if task["task_type"] == "SYNC_TAKEALOT_ORDERS"
            and (tenant_id is None or task.get("tenant_id") == tenant_id)
        ]
        last_order_sync_at = max(
            (
                task.get("finished_at")
                or task.get("updated_at")
                or task.get("created_at")
                for task in order_sync_tasks
                if task.get("status") == "succeeded"
            ),
            default=None,
        )
        latest_order_sync = max(
            order_sync_tasks,
            key=lambda task: task.get("created_at") or task.get("updated_at"),
            default=None,
        )
        newest_order_at = max(
            (order.get("placed_at") or order.get("created_at") for order in relevant_orders),
            default=None,
        )

        return {
            "today_order_count": len(today_orders),
            "today_sales_quantity": sum(order_quantities.get(order["id"], 0) for order in today_orders),
            "today_sales_total": sum(float(order.get("total_amount") or 0) for order in today_orders),
            "today_listing_success_count": sum(1 for job in today_jobs if _dashboard_job_success(job)),
            "today_listing_failed_count": sum(1 for job in today_jobs if _dashboard_job_failed(job)),
            "chart_points": sorted(chart.values(), key=lambda item: item["date"]),
            "last_order_sync_at": last_order_sync_at,
            "latest_order_sync_at": (
                latest_order_sync.get("finished_at")
                or latest_order_sync.get("updated_at")
                or latest_order_sync.get("created_at")
                if latest_order_sync
                else None
            ),
            "latest_order_sync_status": latest_order_sync.get("status") if latest_order_sync else None,
            "latest_order_sync_error_code": latest_order_sync.get("error_code") if latest_order_sync else None,
            "latest_order_sync_error_msg": latest_order_sync.get("error_msg") if latest_order_sync else None,
            "newest_order_at": newest_order_at,
        }

    def _dashboard_order_quantities(self) -> dict[str, int]:
        quantities: dict[str, int] = {}
        for item in self.order_items.values():
            order_id = item["order_id"]
            quantities[order_id] = quantities.get(order_id, 0) + int(item.get("quantity") or 0)
        return quantities

    def list_store_listing_metrics(
        self,
        *,
        store_id: str,
        days: int = 30,
        sku_filter: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = utcnow() - timedelta(days=max(1, days))
        quantities: dict[str, int] = {}
        eligible_order_ids = {
            order["id"]
            for order in self.orders.values()
            if order["store_id"] == store_id
            and _is_at_or_after(order.get("placed_at") or order.get("created_at"), cutoff)
        }
        for item in self.order_items.values():
            if item["order_id"] not in eligible_order_ids:
                continue
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue
            if sku_filter is not None and sku not in sku_filter:
                continue
            quantities[sku] = quantities.get(sku, 0) + int(item.get("quantity") or 0)
        return [
            {"store_id": store_id, "sku": sku, "sales_30d": quantity}
            for sku, quantity in sorted(quantities.items())
        ]

    def upsert_order(
        self,
        *,
        tenant_id: str,
        store_id: str,
        external_order_id: str,
        order_number: str | None,
        status: str,
        fulfillment_status: str | None,
        total_amount: float | None,
        currency: str,
        placed_at: datetime | None,
        raw_payload: dict[str, Any] | None,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = utcnow()
        order = next(
            (
                existing
                for existing in self.orders.values()
                if existing["store_id"] == store_id
                and existing["external_order_id"] == external_order_id
            ),
            None,
        )
        previous_status = order["status"] if order else None
        if total_amount is None:
            total_amount = sum(
                float(item.get("unit_price") or 0) * int(item.get("quantity") or 1)
                for item in items
            )

        if order is None:
            order_id = new_id()
            order = {
                "id": order_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "external_order_id": external_order_id,
                "order_number": order_number,
                "status": status,
                "fulfillment_status": fulfillment_status,
                "total_amount": total_amount,
                "currency": currency,
                "placed_at": placed_at,
                "last_synced_at": now,
                "raw_payload": deepcopy(raw_payload),
                "created_at": now,
                "updated_at": now,
            }
            self.orders[order_id] = order
        else:
            order.update(
                {
                    "order_number": order_number,
                    "status": status,
                    "fulfillment_status": fulfillment_status,
                    "total_amount": total_amount,
                    "currency": currency,
                    "placed_at": placed_at,
                    "last_synced_at": now,
                    "raw_payload": deepcopy(raw_payload),
                    "updated_at": now,
                }
            )

        for item in items:
            self._upsert_order_item(order["id"], item, now)
        self._append_order_sync_event(
            order=order,
            previous_status=previous_status,
            payload=raw_payload,
            synced_at=now,
        )
        return deepcopy(self._with_order_counts(order))

    def _upsert_order_item(
        self,
        order_id: str,
        item: dict[str, Any],
        synced_at: datetime,
    ) -> dict[str, Any]:
        external_order_item_id = str(item["external_order_item_id"])
        existing = next(
            (
                current_item
                for current_item in self.order_items.values()
                if current_item["order_id"] == order_id
                and current_item["external_order_item_id"] == external_order_item_id
            ),
            None,
        )
        payload = {
            "order_id": order_id,
            "external_order_item_id": external_order_item_id,
            "sku": str(item["sku"]),
            "title": item.get("title"),
            "quantity": int(item.get("quantity") or 1),
            "unit_price": item.get("unit_price"),
            "status": item.get("status"),
            "raw_payload": deepcopy(item.get("raw_payload")),
            "updated_at": synced_at,
        }
        if existing is not None:
            existing.update(payload)
            return deepcopy(existing)

        item_id = new_id()
        created = {
            "id": item_id,
            **payload,
            "created_at": synced_at,
        }
        self.order_items[item_id] = created
        return deepcopy(created)

    def _append_order_sync_event(
        self,
        *,
        order: dict[str, Any],
        previous_status: str | None,
        payload: dict[str, Any] | None,
        synced_at: datetime,
    ) -> None:
        if previous_status is None:
            event_type = "order.created"
            message = "Order first seen from Takealot sales sync"
        elif previous_status != order["status"]:
            event_type = "order.status_changed"
            message = f"Order status changed from {previous_status} to {order['status']}"
        else:
            event_type = "order.synced"
            message = "Order refreshed from Takealot sales sync"
        self.order_events.append(
            {
                "id": new_id(),
                "order_id": order["id"],
                "event_type": event_type,
                "status": order["status"],
                "message": message,
                "payload": deepcopy(payload),
                "occurred_at": synced_at,
                "created_at": synced_at,
            }
        )

    def _with_order_counts(self, order: dict[str, Any]) -> dict[str, Any]:
        enriched = deepcopy(order)
        enriched["item_count"] = sum(
            1 for item in self.order_items.values() if item["order_id"] == order["id"]
        )
        return enriched

    def list_bidding_rules(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
    ) -> list[dict[str, Any]]:
        rules = [
            rule
            for rule in self.bidding_rules.values()
            if rule["store_id"] == store_id
            and (
                not sku_query
                or sku_query.lower() in rule["sku"].lower()
            )
        ]
        rules.sort(key=lambda item: (item["updated_at"], item["sku"]), reverse=True)
        return [deepcopy(rule) for rule in rules]

    def get_bidding_rule(self, rule_id: str) -> dict[str, Any] | None:
        rule = self.bidding_rules.get(rule_id)
        return deepcopy(rule) if rule else None

    def update_bidding_rule(self, rule_id: str, **changes: Any) -> dict[str, Any] | None:
        rule = self.bidding_rules.get(rule_id)
        if rule is None:
            return None
        for key in ("listing_id", "floor_price", "strategy_type", "is_active"):
            if key in changes:
                rule[key] = changes[key]
        rule["updated_at"] = utcnow()
        rule["version"] += 1
        return deepcopy(rule)

    def update_bidding_rule_runtime(self, rule_id: str, **changes: Any) -> dict[str, Any] | None:
        rule = self.bidding_rules.get(rule_id)
        if rule is None:
            return None
        allowed = set(bidding_runtime_defaults())
        for key, value in changes.items():
            if key in allowed:
                rule[key] = deepcopy(value)
        rule["updated_at"] = utcnow()
        rule["version"] += 1
        return deepcopy(rule)

    def list_bidding_cycle_candidates(
        self,
        *,
        store_id: str,
        limit: int,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        effective_now = now or utcnow()
        candidates: list[dict[str, Any]] = []
        for rule in self.bidding_rules.values():
            if rule["store_id"] != store_id or not rule.get("is_active"):
                continue
            if float(rule.get("floor_price") or 0) <= 0:
                continue
            next_check = rule.get("next_check_at")
            if next_check is not None and next_check > effective_now:
                continue
            listing = self._bidding_listing_for_rule(rule)
            candidates.append(
                {
                    "rule": deepcopy(rule),
                    "listing": deepcopy(listing) if listing else None,
                }
            )
        candidates.sort(
            key=lambda item: (
                item["rule"].get("next_check_at") or datetime.min.replace(tzinfo=UTC),
                item["rule"].get("updated_at") or datetime.min.replace(tzinfo=UTC),
            )
        )
        return candidates[: max(1, limit)]

    def bidding_runtime_summary(self, *, store_id: str) -> dict[str, int]:
        rules = [rule for rule in self.bidding_rules.values() if rule["store_id"] == store_id]
        now = utcnow()
        return {
            "active_rule_count": sum(1 for rule in rules if rule.get("is_active")),
            "due_rule_count": sum(
                1
                for rule in rules
                if rule.get("is_active")
                and float(rule.get("floor_price") or 0) > 0
                and (rule.get("next_check_at") is None or rule.get("next_check_at") <= now)
            ),
            "blocked_count": sum(1 for rule in rules if rule.get("buybox_status") == "blocked"),
            "retrying_count": sum(1 for rule in rules if rule.get("buybox_status") == "retrying"),
            "fresh_count": sum(1 for rule in rules if rule.get("buybox_status") == "fresh"),
            "won_buybox_count": sum(1 for rule in rules if _bidding_rule_owns_buybox(rule)),
            "lost_buybox_count": sum(1 for rule in rules if _bidding_rule_lost_buybox(rule)),
            "alert_count": sum(1 for rule in rules if _bidding_rule_has_alert(rule)),
        }

    def get_bidding_store_runtime_state(self, store_id: str) -> dict[str, Any]:
        runtime = self.bidding_store_runtime.get(store_id)
        if runtime is None:
            runtime = bidding_store_runtime_defaults(store_id)
            self.bidding_store_runtime[store_id] = runtime
        return deepcopy(runtime)

    def update_bidding_store_runtime_state(
        self,
        store_id: str,
        **changes: Any,
    ) -> dict[str, Any] | None:
        if store_id not in self.stores:
            return None
        runtime = self.bidding_store_runtime.setdefault(
            store_id,
            bidding_store_runtime_defaults(store_id),
        )
        allowed = set(bidding_store_runtime_defaults(store_id))
        for key, value in changes.items():
            if key in allowed and key not in {"store_id", "created_at", "updated_at"}:
                runtime[key] = deepcopy(value)
        runtime["updated_at"] = utcnow()
        return deepcopy(runtime)

    def _bidding_listing_for_rule(self, rule: dict[str, Any]) -> dict[str, Any] | None:
        listing_id = rule.get("listing_id")
        if listing_id and listing_id in self.listings:
            return self.listings[listing_id]
        for listing in self.listings.values():
            if listing["store_id"] == rule["store_id"] and listing["sku"] == rule["sku"]:
                return listing
        return None

    def upsert_bidding_rule(
        self,
        *,
        store_id: str,
        sku: str,
        floor_price: float | None,
        listing_id: str | None = None,
        strategy_type: str = "manual",
        is_active: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        for rule in self.bidding_rules.values():
            if rule["store_id"] == store_id and rule["sku"] == sku:
                before = deepcopy(rule)
                rule["floor_price"] = floor_price
                if listing_id is not None:
                    rule["listing_id"] = listing_id
                rule["strategy_type"] = strategy_type
                rule["is_active"] = is_active
                rule["updated_at"] = utcnow()
                rule["version"] += 1
                return deepcopy(rule), before

        now = utcnow()
        rule_id = new_id()
        rule = {
            "id": rule_id,
            "store_id": store_id,
            "sku": sku,
            "listing_id": listing_id,
            "floor_price": floor_price,
            "strategy_type": strategy_type,
            "is_active": is_active,
            **bidding_runtime_defaults(now),
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        self.bidding_rules[rule_id] = rule
        return deepcopy(rule), None

    def list_tasks(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        tasks = sorted(
            (
                task
                for task in self.task_runs.values()
                if tenant_id is None or task["tenant_id"] == tenant_id
            ),
            key=lambda item: item["created_at"],
            reverse=True,
        )
        return [deepcopy(task) for task in tasks]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task = self.task_runs.get(task_id)
        return deepcopy(task) if task else None

    def update_task(self, task_id: str, **changes: Any) -> dict[str, Any]:
        task = self.task_runs[task_id]
        task.update(changes)
        task["updated_at"] = utcnow()
        return deepcopy(task)

    def claim_queued_tasks(
        self,
        task_types: set[str],
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        if not task_types:
            return []
        now = utcnow()
        claimable = [
            task
            for task in sorted(self.task_runs.values(), key=lambda item: item["created_at"])
            if task["task_type"] in task_types
            and (
                task["status"] == "queued"
                or task["status"] == "waiting_retry"
                or (
                    task["status"] == "leased"
                    and task["lease_expires_at"] is not None
                    and task["lease_expires_at"] <= now
                )
            )
            and (task["next_retry_at"] is None or task["next_retry_at"] <= now)
        ][:limit]
        leased_tasks: list[dict[str, Any]] = []
        for task in claimable:
            previous_status = task["status"]
            task["status"] = "leased"
            task["stage"] = "leased"
            task["lease_owner"] = worker_id
            task["lease_token"] = new_id()
            task["lease_expires_at"] = now + timedelta(seconds=lease_seconds)
            task["attempt_count"] += 1
            task["updated_at"] = now
            self.add_task_event(
                task_id=task["id"],
                event_type="task.leased",
                from_status=previous_status,
                to_status="leased",
                stage="leased",
                message="Task claimed by worker lease",
                details={
                    "worker_id": worker_id,
                    "lease_expires_at": task["lease_expires_at"].isoformat(),
                },
                source="worker",
                source_id=worker_id,
            )
            leased_tasks.append(deepcopy(task))
        leased_tasks.sort(key=lambda item: item["created_at"], reverse=True)
        return leased_tasks

    def recover_stale_tasks(
        self,
        task_types: set[str] | None,
        *,
        stale_after_seconds: int,
        worker_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        now = utcnow()
        cutoff = now - timedelta(seconds=max(1, stale_after_seconds))
        recovered_tasks: list[dict[str, Any]] = []
        for task in sorted(
            self.task_runs.values(),
            key=lambda item: item.get("last_heartbeat_at") or item.get("started_at") or item["updated_at"],
        ):
            if len(recovered_tasks) >= limit:
                break
            if task["status"] != "running":
                continue
            if task_types and task["task_type"] not in task_types:
                continue
            heartbeat_at = task.get("last_heartbeat_at") or task.get("started_at") or task["updated_at"]
            if heartbeat_at is None or heartbeat_at > cutoff:
                continue

            can_retry = bool(task.get("retryable", True)) and int(task.get("attempt_count", 0)) < int(task.get("max_retries", 0))
            recovery_status = "waiting_retry" if can_retry else "failed_final"
            recovery_stage = "waiting_retry" if can_retry else "failed"
            retry_delay_seconds = min(300, 30 * (2 ** max(0, int(task.get("attempt_count", 0)))))
            next_retry_at = now + timedelta(seconds=retry_delay_seconds) if can_retry else None
            recovery_message = "Worker heartbeat stale; retry scheduled" if can_retry else "Worker heartbeat stale; task failed final"
            updated = self.update_task(
                task["id"],
                status=recovery_status,
                stage=recovery_stage,
                next_retry_at=next_retry_at,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                finished_at=None if can_retry else now,
                error_code="TASK_HEARTBEAT_STALE",
                error_msg=recovery_message,
                error_details={
                    "recovered_by": worker_id,
                    "stale_after_seconds": stale_after_seconds,
                    "detected_at": now.isoformat(),
                    "previous_heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
                    "attempt_count": task.get("attempt_count"),
                    "max_retries": task.get("max_retries"),
                    "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
                },
            )
            self.add_task_event(
                task_id=task["id"],
                event_type="task.recovered_stale",
                from_status="running",
                to_status=recovery_status,
                stage=recovery_stage,
                message=recovery_message,
                details={
                    "recovered_by": worker_id,
                    "stale_after_seconds": stale_after_seconds,
                    "previous_heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
                    "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
                },
                source="worker",
                source_id=worker_id,
            )
            updated["recovery_action"] = recovery_status
            recovered_tasks.append(updated)
        return recovered_tasks

    def list_task_events(self, task_id: str) -> list[dict[str, Any]]:
        events = [
            deepcopy(event)
            for event in self.task_events
            if event["task_id"] == task_id
        ]
        events.sort(key=lambda item: item["created_at"], reverse=True)
        return events

    def list_task_events_map(self, task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        events_by_task = {task_id: [] for task_id in task_ids}
        task_id_set = set(task_ids)
        for event in self.task_events:
            if event["task_id"] in task_id_set:
                events_by_task[event["task_id"]].append(deepcopy(event))
        for events in events_by_task.values():
            events.sort(key=lambda item: item["created_at"], reverse=True)
        return events_by_task

    def add_task_event(
        self,
        *,
        task_id: str,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        stage: str | None,
        message: str,
        details: dict[str, Any] | None,
        source: str,
        source_id: str | None,
    ) -> dict[str, Any]:
        event = {
            "id": new_id(),
            "task_id": task_id,
            "event_type": event_type,
            "from_status": from_status,
            "to_status": to_status,
            "stage": stage,
            "message": message,
            "details": deepcopy(details),
            "source": source,
            "source_id": source_id,
            "created_at": utcnow(),
        }
        self.task_events.append(event)
        return deepcopy(event)

    def create_task(
        self,
        *,
        task_type: str,
        domain: str,
        queue_name: str,
        actor_user_id: str | None,
        actor_role: str,
        tenant_id: str,
        store_id: str | None,
        target_type: str | None,
        target_id: str | None,
        request_id: str,
        label: str,
        next_action: str,
    ) -> dict[str, Any]:
        now = utcnow()
        task_id = new_id()
        task = {
            "id": task_id,
            "task_type": task_type,
            "domain": domain,
            "status": "queued",
            "stage": "queued",
            "progress_percent": 0,
            "progress_current": 0,
            "progress_total": None,
            "priority": "medium",
            "queue_name": queue_name,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "source_type": "api",
            "target_type": target_type,
            "target_id": target_id,
            "request_id": request_id,
            "idempotency_key": None,
            "parent_task_id": None,
            "root_task_id": None,
            "dependency_state": None,
            "attempt_count": 0,
            "max_retries": 3,
            "retryable": True,
            "next_retry_at": None,
            "lease_owner": None,
            "lease_token": None,
            "lease_expires_at": None,
            "started_at": None,
            "finished_at": None,
            "last_heartbeat_at": None,
            "cancel_requested_at": None,
            "cancel_reason": None,
            "error_code": None,
            "error_msg": None,
            "error_details": None,
            "ui_meta": {"label": label, "next_action": next_action},
            "input_payload_ref": None,
            "output_payload_ref": None,
            "created_at": now,
            "updated_at": now,
        }
        self.task_runs[task_id] = task
        self.add_task_event(
            task_id=task_id,
            event_type="task.created",
            from_status=None,
            to_status="created",
            stage="created",
            message=f"{label} 已创建",
            details=None,
            source="api",
            source_id=actor_user_id,
        )
        self.add_task_event(
            task_id=task_id,
            event_type="task.queued",
            from_status="created",
            to_status="queued",
            stage="queued",
            message=f"{label} 已入队",
            details=None,
            source="api",
            source_id=actor_user_id,
        )
        return deepcopy(task)

    def append_audit(
        self,
        *,
        request_id: str,
        tenant_id: str | None,
        actor_user_id: str | None,
        actor_role: str | None,
        action: str,
        action_label: str,
        risk_level: str,
        target_type: str,
        target_id: str | None,
        target_label: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str | None,
        result: str,
        task_id: str | None,
        store_id: str | None = None,
        error_code: str | None = None,
        created_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit_id = new_id()
        audit = {
            "id": audit_id,
            "request_id": request_id,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "actor_type": "user",
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "actor_display_name": self.users.get(actor_user_id, {}).get("username")
            if actor_user_id
            else None,
            "impersonator_user_id": None,
            "session_id": None,
            "source": "api",
            "ip": None,
            "user_agent": None,
            "action": action,
            "action_label": action_label,
            "risk_level": risk_level,
            "target_type": target_type,
            "target_id": target_id,
            "target_label": target_label,
            "before": deepcopy(before),
            "after": deepcopy(after),
            "diff": None,
            "reason": reason,
            "result": result,
            "error_code": error_code,
            "idempotency_key": None,
            "task_id": task_id,
            "approval_id": None,
            "metadata": deepcopy(metadata),
            "created_at": created_at or utcnow(),
        }
        self.audit_logs[audit_id] = audit
        return deepcopy(audit)

    def list_audits(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        audits = sorted(
            (
                audit
                for audit in self.audit_logs.values()
                if tenant_id is None or audit["tenant_id"] == tenant_id
            ),
            key=lambda item: item["created_at"],
            reverse=True,
        )
        return [deepcopy(audit) for audit in audits]

    def count_active_tasks(self, tenant_id: str | None = None) -> int:
        return sum(
            1
            for task in self.task_runs.values()
            if task["status"] in {"queued", "leased", "running", "waiting_retry"}
            and (tenant_id is None or task["tenant_id"] == tenant_id)
        )

    def health_counters(self, tenant_id: str | None = None) -> dict[str, int]:
        return {
            "active_task_count": self.count_active_tasks(tenant_id),
            "audit_log_count": len(self.list_audits(tenant_id)),
        }

    def get_tenant_entitlement(self, tenant_id: str) -> dict[str, Any]:
        tenant = self.tenants.get(tenant_id)
        subscription = self.tenant_subscriptions.get(tenant_id)
        plan = (
            subscription.get("plan")
            if subscription is not None
            else tenant.get("plan") if tenant is not None else "war-room"
        )
        if plan not in self.tenant_plan_limits:
            plan = "war-room"
        limits = deepcopy(self.tenant_plan_limits[plan])
        effective_status = (
            self._effective_subscription_status(subscription)
            if subscription
            else "active"
        )
        return {
            "tenant_id": tenant_id,
            "plan": plan,
            "plan_name": limits.pop("plan_name"),
            "subscription_status": effective_status,
            "trial_ends_at": subscription.get("trial_ends_at") if subscription else None,
            "current_period_ends_at": subscription.get("current_period_ends_at") if subscription else None,
            "limits": limits,
        }

    @staticmethod
    def _effective_subscription_status(subscription: dict[str, Any]) -> str:
        raw_status = subscription.get("status", "active")
        now = utcnow()
        if raw_status == "trialing":
            trial_ends_at = subscription.get("trial_ends_at")
            if trial_ends_at is not None and trial_ends_at <= now:
                return "past_due"
        if raw_status == "active":
            current_period_ends_at = subscription.get("current_period_ends_at")
            if current_period_ends_at is not None and current_period_ends_at <= now:
                return "past_due"
        return raw_status

    def get_tenant_usage(self, tenant_id: str) -> dict[str, int]:
        active_task_statuses = {"queued", "leased", "running", "waiting_retry"}
        active_sync_types = {"SYNC_STORE_LISTINGS", "store.sync.full"}
        active_store_ids = {
            store["id"]
            for store in self.stores.values()
            if store["tenant_id"] == tenant_id and store["status"] != "disabled"
        }
        return {
            "active_users": sum(
                1
                for user in self.users.values()
                if user["tenant_id"] == tenant_id and user["status"] != "disabled"
            ),
            "active_stores": len(active_store_ids),
            "listings": sum(
                1
                for listing in self.listings.values()
                if listing["store_id"] in active_store_ids
            ),
            "active_tasks": sum(
                1
                for task in self.task_runs.values()
                if task["tenant_id"] == tenant_id and task["status"] in active_task_statuses
            ),
            "active_sync_tasks": sum(
                1
                for task in self.task_runs.values()
                if task["tenant_id"] == tenant_id
                and task["status"] in active_task_statuses
                and task["task_type"] in active_sync_types
            ),
        }


def _is_at_or_after(value: datetime | None, cutoff: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value >= cutoff


def _is_before(value: datetime | None, cutoff: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value < cutoff


def _local_date_key(value: datetime, zone: ZoneInfo) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(zone).date().isoformat()


def _dashboard_job_success(job: dict[str, Any]) -> bool:
    text = f"{job.get('status')} {job.get('stage')}".lower()
    return any(token in text for token in ("success", "completed", "ready_to_submit", "buyable"))


def _dashboard_job_failed(job: dict[str, Any]) -> bool:
    text = f"{job.get('status')} {job.get('stage')}".lower()
    return any(token in text for token in ("failed", "error", "manual_intervention", "rejected"))


def selection_brand_matches(value: str | None, filter_value: str | None) -> bool:
    if not filter_value:
        return True
    if filter_value == "__has_brand__":
        return bool(value)
    if filter_value == "__no_brand__":
        return not bool(value)
    return value == filter_value


def selection_stock_status_matches(value: str | None, filter_value: str | None) -> bool:
    if not filter_value:
        return True
    if filter_value == "__direct_ship__":
        return value == "ships_in_14___16_work_days"
    if filter_value == "__in_stock__":
        return value in {"in_stock", "limited"}
    if filter_value == "__ships_in__":
        return bool(value and value.startswith("ships_in") and value != "ships_in_14___16_work_days")
    if filter_value == "__pre_order__":
        return bool(value and value.startswith("pre_order"))
    if filter_value == "__out_of_stock__":
        return value in {"out_of_stock", "unavailable"}
    return value == filter_value


def selection_latest_review_matches(value: datetime | str | None, filter_value: str | None) -> bool:
    if not filter_value:
        return True
    if filter_value == "__has_latest_review__":
        return value is not None
    if filter_value == "__missing_latest_review__":
        return value is None
    day_windows = {
        "__last_30_days__": 30,
        "__last_90_days__": 90,
        "__last_180_days__": 180,
        "__last_365_days__": 365,
    }
    days = day_windows.get(filter_value)
    if days is None or value is None:
        return False
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed >= utcnow() - timedelta(days=days)


def _build_app_state() -> Any:
    memory_state = MemoryAppState()
    if not settings.database_url:
        return memory_state

    try:
        from src.modules.common.postgres_state import DatabaseAppState

        return DatabaseAppState(memory_state)
    except Exception as exc:
        memory_state.backend_status = "warning"
        memory_state.backend_detail = (
            f"Postgres unavailable, falling back to memory: {exc}"
        )
        logger.warning(
            "Failed to initialize PostgreSQL app state, falling back to memory.",
            exc_info=True,
        )
        return memory_state


app_state = _build_app_state()
