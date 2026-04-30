from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock
from time import monotonic, perf_counter
from typing import Any
from uuid import UUID, uuid4

from psycopg import sql
from psycopg.types.json import Jsonb

from src.platform.db.session import get_db_session
from src.platform.settings.base import settings


PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 120_000
PASSWORD_SALT_BYTES = 16
def _listing_status_text_sql(alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    return f"""
lower(concat_ws(' ',
  coalesce({prefix}raw_payload->>'status', ''),
  coalesce({prefix}raw_payload->>'offer_status', ''),
  coalesce({prefix}raw_payload->>'availability', ''),
  coalesce({prefix}raw_payload->>'state', ''),
  coalesce({prefix}raw_payload->'payload'->>'status', ''),
  coalesce({prefix}sync_status, '')
))
"""
BUYABLE_STATUS_PATTERN = (
    r"(^|[^a-z])(active|buyable|enabled|live|listed|published|available|synced|webhook_synced)([^a-z]|$)"
)
DISABLED_STATUS_PATTERN = (
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
NUMERIC_TEXT_PATTERN_SQL = r"^-?[0-9]+(\.[0-9]+)?$"


def _numeric_text_sql(expression: str) -> str:
    cleaned = f"replace(nullif({expression}, ''), ',', '')"
    return f"case when {cleaned} ~ '{NUMERIC_TEXT_PATTERN_SQL}' then {cleaned}::numeric end"


def _like_any_status(tokens: tuple[str, ...], alias: str | None = None) -> tuple[str, list[Any]]:
    status_text_sql = _listing_status_text_sql(alias)
    return (
        "(" + " or ".join(f"{status_text_sql} like %s" for _ in tokens) + ")",
        [f"%{token}%" for token in tokens],
    )


def _buyable_status_sql(alias: str | None = None) -> tuple[str, list[Any]]:
    status_text_sql = _listing_status_text_sql(alias)
    platform_sql, platform_params = _like_any_status(PLATFORM_DISABLED_TOKENS, alias)
    seller_sql, seller_params = _like_any_status(SELLER_DISABLED_TOKENS, alias)
    return (
        f"({status_text_sql} ~ %s and not ({status_text_sql} ~ %s) "
        f"and not {platform_sql} and not {seller_sql})",
        [BUYABLE_STATUS_PATTERN, DISABLED_STATUS_PATTERN, *platform_params, *seller_params],
    )


def _listing_status_filter_sql(
    status_group: str | None,
    alias: str | None = None,
) -> tuple[str, list[Any]]:
    if status_group == "platform_disabled":
        return _like_any_status(PLATFORM_DISABLED_TOKENS, alias)
    if status_group == "seller_disabled":
        return _like_any_status(SELLER_DISABLED_TOKENS, alias)
    if status_group == "buyable":
        return _buyable_status_sql(alias)
    if status_group == "not_buyable":
        buyable_sql, buyable_params = _buyable_status_sql(alias)
        return f"not {buyable_sql}", buyable_params
    return "", []


SELLER_STOCK_SQL = """
coalesce(
  {total_merchant_stock},
  {seller_stock_quantity},
  (
    select sum({quantity_available})
    from jsonb_array_elements(
      case
        when jsonb_typeof(l.raw_payload->'seller_warehouse_stock') = 'array'
        then l.raw_payload->'seller_warehouse_stock'
        else '[]'::jsonb
      end
    ) as item
  ),
  0
)
""".format(
    total_merchant_stock=_numeric_text_sql("l.raw_payload->>'total_merchant_stock'"),
    seller_stock_quantity=_numeric_text_sql("l.raw_payload->>'seller_stock_quantity'"),
    quantity_available=_numeric_text_sql("item->>'quantity_available'"),
)
TAKEALOT_WAREHOUSE_SALES_SQL = """
(
  select sum(coalesce({quantity_sold_30_days}, {quantity_sold_30_days_camel}))
  from jsonb_array_elements(
    case
      when jsonb_typeof(l.raw_payload->'takealot_warehouse_stock') = 'array'
      then l.raw_payload->'takealot_warehouse_stock'
      else '[]'::jsonb
    end
  ) as item
)
""".format(
    quantity_sold_30_days=_numeric_text_sql("item->>'quantity_sold_30_days'"),
    quantity_sold_30_days_camel=_numeric_text_sql("item->>'quantitySold30Days'"),
)
SORT_SQL_BY_FIELD = {
    "createdAt": "l.created_at",
    "stockOnHand": "coalesce(l.stock_quantity, 0)",
    "availableStock": SELLER_STOCK_SQL,
    "buyBoxPrice": "coalesce(br.last_buybox_price, -1)",
    "sellingPrice": "coalesce(l.platform_price, 0)",
    "sales30d": "coalesce({quantity_sold_30_days}, {sales_30_days}, {sales_30d}, {warehouse_sales}, 0)".format(
        quantity_sold_30_days=_numeric_text_sql("l.raw_payload->>'quantity_sold_30_days'"),
        sales_30_days=_numeric_text_sql("l.raw_payload->>'sales_30_days'"),
        sales_30d=_numeric_text_sql("l.raw_payload->>'sales_30d'"),
        warehouse_sales=TAKEALOT_WAREHOUSE_SALES_SQL,
    ),
    "cvr30d": "coalesce({conversion_percentage_30_days}, {conversion_rate_30_days}, {conversion_rate}, 0)".format(
        conversion_percentage_30_days=_numeric_text_sql("l.raw_payload->>'conversion_percentage_30_days'"),
        conversion_rate_30_days=_numeric_text_sql("l.raw_payload->>'conversion_rate_30_days'"),
        conversion_rate=_numeric_text_sql("l.raw_payload->>'conversion_rate'"),
    ),
    "pageViews30d": "coalesce({page_views_30_days}, {page_views_30d}, {page_views_7_days}, 0)".format(
        page_views_30_days=_numeric_text_sql("l.raw_payload->>'page_views_30_days'"),
        page_views_30d=_numeric_text_sql("l.raw_payload->>'page_views_30d'"),
        page_views_7_days=_numeric_text_sql("l.raw_payload->>'page_views_7_days'"),
    ),
    "wishlist30d": "coalesce({wishlist_30_days}, {wishlist_30d}, {total_wishlist}, 0)".format(
        wishlist_30_days=_numeric_text_sql("l.raw_payload->>'wishlist_30_days'"),
        wishlist_30d=_numeric_text_sql("l.raw_payload->>'wishlist_30d'"),
        total_wishlist=_numeric_text_sql("l.raw_payload->>'total_wishlist'"),
    ),
    "returns30d": "coalesce({quantity_returned_30_days}, {returns_30_days}, {returns_30d}, {quantity_returned_30d}, 0)".format(
        quantity_returned_30_days=_numeric_text_sql("l.raw_payload->>'quantity_returned_30_days'"),
        returns_30_days=_numeric_text_sql("l.raw_payload->>'returns_30_days'"),
        returns_30d=_numeric_text_sql("l.raw_payload->>'returns_30d'"),
        quantity_returned_30d=_numeric_text_sql("l.raw_payload->>'quantity_returned_30d'"),
    ),
    "listingQuality": "coalesce({listing_quality}, 0)".format(
        listing_quality=_numeric_text_sql("l.raw_payload->>'listing_quality'"),
    ),
}


def _listing_sort_sql(sort_by: str | None, sort_dir: str | None) -> str:
    expression = SORT_SQL_BY_FIELD.get(sort_by or "", SORT_SQL_BY_FIELD["createdAt"])
    direction = "asc" if sort_dir == "asc" else "desc"
    nulls = "nulls first" if direction == "asc" else "nulls last"
    return f"{expression} {direction} {nulls}, l.sku asc"


def legacy_hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = os.urandom(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        (
            PASSWORD_HASH_SCHEME,
            str(PASSWORD_HASH_ITERATIONS),
            salt.hex(),
            digest.hex(),
        )
    )


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith(f"{PASSWORD_HASH_SCHEME}$"):
        try:
            _, iterations_value, salt_hex, digest_hex = password_hash.split("$", 3)
            iterations = int(iterations_value)
            salt = bytes.fromhex(salt_hex)
            expected_digest = bytes.fromhex(digest_hex)
        except (TypeError, ValueError):
            return False
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual_digest, expected_digest)
    return hmac.compare_digest(password_hash, legacy_hash_password(password))


def needs_password_rehash(password_hash: str) -> bool:
    if not password_hash.startswith(f"{PASSWORD_HASH_SCHEME}$"):
        return True
    try:
        _, iterations_value, _, _ = password_hash.split("$", 3)
        return int(iterations_value) < PASSWORD_HASH_ITERATIONS
    except (TypeError, ValueError):
        return True


def password_fingerprint(password: str) -> str:
    return legacy_hash_password(password)


def append_selection_brand_sql(
    where_parts: list[Any],
    params: list[Any],
    filter_value: str | None,
) -> None:
    if filter_value == "__has_brand__":
        where_parts.append(sql.SQL("brand is not null and brand <> ''"))
    elif filter_value == "__no_brand__":
        where_parts.append(sql.SQL("(brand is null or brand = '')"))
    elif filter_value:
        where_parts.append(sql.SQL("brand = %s"))
        params.append(filter_value)


def append_selection_stock_status_sql(
    where_parts: list[Any],
    params: list[Any],
    filter_value: str | None,
) -> None:
    if filter_value == "__direct_ship__":
        where_parts.append(sql.SQL("stock_status = 'ships_in_14___16_work_days'"))
    elif filter_value == "__in_stock__":
        where_parts.append(sql.SQL("stock_status in ('in_stock', 'limited')"))
    elif filter_value == "__ships_in__":
        where_parts.append(sql.SQL("stock_status like %s and stock_status <> 'ships_in_14___16_work_days'"))
        params.append("ships_in%")
    elif filter_value == "__pre_order__":
        where_parts.append(sql.SQL("stock_status like %s"))
        params.append("pre_order%")
    elif filter_value == "__out_of_stock__":
        where_parts.append(sql.SQL("stock_status in ('out_of_stock', 'unavailable')"))
    elif filter_value:
        where_parts.append(sql.SQL("stock_status = %s"))
        params.append(filter_value)


def build_selection_category_tree(rows: list[Any]) -> dict[str, dict[str, list[str]]]:
    tree: dict[str, dict[str, list[str]]] = {}
    seen: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        main_category = row["main_category"]
        category_level1 = row["category_level1"]
        category_level2 = row["category_level2"]
        if not main_category or not category_level1:
            continue
        branch = tree.setdefault(main_category, {})
        branch.setdefault(category_level1, [])
        if not category_level2:
            continue
        seen_key = (main_category, category_level1)
        seen_values = seen.setdefault(seen_key, set())
        if category_level2 in seen_values:
            continue
        seen_values.add(category_level2)
        branch[category_level1].append(category_level2)
    return tree


class DatabaseAppState:
    backend_name = "postgres"
    backend_status = "ok"
    _AUTH_RECORD_CACHE_SECONDS = 60
    _RECENT_SESSION_CACHE_SECONDS = 300
    _PASSWORD_VERIFY_CACHE_SECONDS = 300
    _SYSTEM_SETTINGS_CACHE_SECONDS = 60
    _STORE_LIST_CACHE_SECONDS = 60
    _TASK_LIST_CACHE_SECONDS = 60

    def __init__(self, seed_state: Any) -> None:
        self._seed_state = seed_state
        self.backend_detail = "Using PostgreSQL control-plane persistence"
        self._auth_record_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._recent_session_cache: dict[str, tuple[float, str]] = {}
        self._password_verify_cache: dict[str, tuple[float, str, str]] = {}
        self._system_settings_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
        self._store_list_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._task_list_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._login_locks: dict[str, Lock] = {}
        self._cache_lock = Lock()
        self._login_locks_lock = Lock()
        if settings.db_bootstrap_demo_data:
            self._bootstrap_if_needed()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _default_tenant_id(self) -> str:
        return next(iter(self._seed_state.tenants.keys()))

    def _bootstrap_if_needed(self) -> None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                tenant_count = cursor.execute(
                    "select count(*) as count from tenants"
                ).fetchone()["count"]
                if tenant_count:
                    connection.rollback()
                    return
                self._bootstrap_demo_data(cursor)
            connection.commit()

    def _bootstrap_demo_data(self, cursor: Any) -> None:
        for tenant in self._seed_state.tenants.values():
            cursor.execute(
                """
                insert into tenants (id, slug, name, status, plan, created_at, updated_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do nothing
                """,
                (
                    tenant["id"],
                    tenant["slug"],
                    tenant["name"],
                    tenant["status"],
                    tenant["plan"],
                    self._now(),
                    self._now(),
                ),
            )

        for user in self._seed_state.users.values():
            cursor.execute(
                """
                insert into users (
                  id, tenant_id, username, email, role, status, expires_at,
                  force_password_reset, last_login_at, version, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do nothing
                """,
                (
                    user["id"],
                    user["tenant_id"],
                    user["username"],
                    user["email"],
                    user["role"],
                    user["status"],
                    user["expires_at"],
                    user["force_password_reset"],
                    user["last_login_at"],
                    user["version"],
                    user["created_at"],
                    user["updated_at"],
                ),
            )
            cursor.execute(
                """
                insert into user_passwords (user_id, password_hash, password_version, updated_at)
                values (%s, %s, %s, %s)
                on conflict (user_id) do nothing
                """,
                (
                    user["id"],
                    hash_password(user["password"]),
                    1,
                    user["updated_at"],
                ),
            )

        for flag in self._seed_state.user_feature_flags:
            cursor.execute(
                """
                insert into user_feature_flags (
                  id, user_id, feature_key, enabled, source, updated_by, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (user_id, feature_key) do nothing
                """,
                (
                    flag["id"],
                    flag["user_id"],
                    flag["feature_key"],
                    flag["enabled"],
                    flag["source"],
                    flag["updated_by"],
                    flag["created_at"],
                    flag["updated_at"],
                ),
            )

        for setting in self._seed_state.system_settings.values():
            cursor.execute(
                """
                insert into system_settings (
                  id, setting_key, value_type, value_json, description, updated_by,
                  change_reason, version, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (setting_key) do nothing
                """,
                (
                    setting["id"],
                    setting["setting_key"],
                    setting["value_type"],
                    Jsonb(setting["value"]),
                    setting["description"],
                    setting["updated_by"],
                    "bootstrap demo data",
                    setting["version"],
                    setting["created_at"],
                    setting["updated_at"],
                ),
            )

        for store in self._seed_state.stores.values():
            cursor.execute(
                """
                insert into stores (
                  id, tenant_id, name, platform, status, api_key_status,
                  last_synced_at, version, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do nothing
                """,
                (
                    store["id"],
                    store["tenant_id"],
                    store["name"],
                    store["platform"],
                    store["status"],
                    store["api_key_status"],
                    store["last_synced_at"],
                    store["version"],
                    store["created_at"],
                    store["updated_at"],
                ),
            )
            cursor.execute(
                """
                insert into store_credentials (
                  store_id, api_key_encrypted, masked_api_key, credential_status,
                  last_validated_at, created_at, updated_at
                )
                values (%s, armor(pgp_sym_encrypt(%s, %s)), %s, %s, %s, %s, %s)
                on conflict (store_id) do nothing
                """,
                (
                    store["id"],
                    self._serialize_store_credentials(
                        {
                            "platform": store["platform"],
                            "api_key": f"bootstrap-{store['platform']}-key",
                            "api_secret": f"bootstrap-{store['platform']}-secret",
                        }
                    ),
                    settings.store_credential_encryption_key,
                    store["masked_api_key"],
                    store["credential_status"],
                    store["last_synced_at"],
                    store["created_at"],
                    store["updated_at"],
                ),
            )
            cursor.execute(
                """
                insert into store_feature_policies (
                  store_id, bidding_enabled, listing_enabled, sync_enabled, created_at, updated_at
                )
                values (%s, %s, %s, %s, %s, %s)
                on conflict (store_id) do nothing
                """,
                (
                    store["id"],
                    store["feature_policies"]["bidding_enabled"],
                    store["feature_policies"]["listing_enabled"],
                    store["feature_policies"]["sync_enabled"],
                    store["created_at"],
                    store["updated_at"],
                ),
            )

        seeded_task_types: set[str] = set()
        for task in self._seed_state.task_runs.values():
            if task["task_type"] not in seeded_task_types:
                cursor.execute(
                    """
                    insert into task_definitions (
                      task_type, domain, display_name, queue_name, priority,
                      max_retries, lease_timeout_seconds, is_cancellable,
                      is_high_risk, idempotency_scope, retention_days, enabled
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (task_type) do nothing
                    """,
                    (
                        task["task_type"],
                        task["domain"],
                        task["ui_meta"]["label"],
                        task["queue_name"],
                        task["priority"],
                        task["max_retries"],
                        900,
                        True,
                        False,
                        "task_type+target",
                        30,
                        True,
                    ),
                )
                seeded_task_types.add(task["task_type"])

            cursor.execute(
                """
                insert into task_runs (
                  id, task_type, domain, status, stage, progress_percent, progress_current,
                  progress_total, priority, queue_name, tenant_id, store_id, actor_user_id,
                  actor_role, source_type, target_type, target_id, request_id, idempotency_key,
                  parent_task_id, root_task_id, dependency_state, attempt_count, max_retries,
                  retryable, next_retry_at, lease_owner, lease_token, lease_expires_at,
                  started_at, finished_at, last_heartbeat_at, cancel_requested_at, cancel_reason,
                  error_code, error_msg, error_details, ui_meta, input_payload_ref,
                  output_payload_ref, created_at, updated_at
                )
                values (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                on conflict (id) do nothing
                """,
                (
                    task["id"],
                    task["task_type"],
                    task["domain"],
                    task["status"],
                    task["stage"],
                    task["progress_percent"],
                    task["progress_current"],
                    task["progress_total"],
                    task["priority"],
                    task["queue_name"],
                    task["tenant_id"],
                    task["store_id"],
                    task["actor_user_id"],
                    task["actor_role"],
                    task["source_type"],
                    task["target_type"],
                    task["target_id"],
                    task["request_id"],
                    task["idempotency_key"],
                    task["parent_task_id"],
                    task["root_task_id"],
                    task["dependency_state"],
                    task["attempt_count"],
                    task["max_retries"],
                    task["retryable"],
                    task["next_retry_at"],
                    task["lease_owner"],
                    task["lease_token"],
                    task["lease_expires_at"],
                    task["started_at"],
                    task["finished_at"],
                    task["last_heartbeat_at"],
                    task["cancel_requested_at"],
                    task["cancel_reason"],
                    task["error_code"],
                    task["error_msg"],
                    Jsonb(task["error_details"]) if task["error_details"] is not None else None,
                    Jsonb(task["ui_meta"]),
                    task["input_payload_ref"],
                    task["output_payload_ref"],
                    task["created_at"],
                    task["updated_at"],
                ),
            )

        for event in self._seed_state.task_events:
            cursor.execute(
                """
                insert into task_events (
                  id, task_id, event_type, from_status, to_status, stage, message,
                  details, source, source_id, created_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do nothing
                """,
                (
                    event["id"],
                    event["task_id"],
                    event["event_type"],
                    event["from_status"],
                    event["to_status"],
                    event["stage"],
                    event["message"],
                    Jsonb(event["details"]) if event["details"] is not None else None,
                    event["source"],
                    event["source_id"],
                    event["created_at"],
                ),
            )

        for audit in self._seed_state.audit_logs.values():
            cursor.execute(
                """
                insert into audit_logs (
                  id, request_id, tenant_id, store_id, actor_type, actor_user_id, actor_role,
                  actor_display_name, source, action, action_label, risk_level, target_type,
                  target_id, target_label, before, after, reason, result, error_code, task_id,
                  created_at
                )
                values (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s
                )
                on conflict (id) do nothing
                """,
                (
                    audit["id"],
                    audit["request_id"],
                    audit["tenant_id"],
                    audit["store_id"],
                    audit["actor_type"],
                    audit["actor_user_id"],
                    audit["actor_role"],
                    audit["actor_display_name"],
                    audit["source"],
                    audit["action"],
                    audit["action_label"],
                    audit["risk_level"],
                    audit["target_type"],
                    audit["target_id"],
                    audit["target_label"],
                    Jsonb(audit["before"]) if audit["before"] is not None else None,
                    Jsonb(audit["after"]) if audit["after"] is not None else None,
                    audit["reason"],
                    audit["result"],
                    audit["error_code"],
                    audit["task_id"],
                    audit["created_at"],
                ),
            )

    @staticmethod
    def _decode_json(value: Any) -> Any:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return DatabaseAppState._normalize_value(value)
        return DatabaseAppState._normalize_value(value)

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, list):
            return [DatabaseAppState._normalize_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: DatabaseAppState._normalize_value(item)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _row_get(row: Any, key: str, default: Any = None) -> Any:
        try:
            return row[key]
        except Exception:
            return default

    @staticmethod
    def _effective_subscription_status(
        raw_status: str,
        trial_ends_at: datetime | None,
        current_period_ends_at: datetime | None,
    ) -> str:
        now = datetime.now(UTC)
        if raw_status == "trialing" and trial_ends_at is not None and trial_ends_at <= now:
            return "past_due"
        if raw_status == "active" and current_period_ends_at is not None and current_period_ends_at <= now:
            return "past_due"
        return raw_status

    @staticmethod
    def _serialize_store_credentials(payload: dict[str, Any]) -> str:
        platform = payload.get("platform") or payload.get("credential_platform") or "takealot"
        if platform != "takealot":
            raise ValueError("Only Takealot store credentials are supported")
        return json.dumps(
            {
                "platform": platform,
                "api_key": payload.get("api_key") or "",
                "api_secret": payload.get("api_secret") or "",
                "leadtime_merchant_warehouse_id": payload.get("leadtime_merchant_warehouse_id"),
                "platform_profile": payload.get("platform_profile"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def verify_credentials(self, username: str, password: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select
                      u.id, u.tenant_id, u.username, u.email, u.role, u.status,
                      u.expires_at, u.force_password_reset, u.last_login_at,
                      u.version, u.created_at, u.updated_at,
                      up.password_hash,
                      t.status as tenant_status,
                      case
                        when coalesce(ts.status, 'active') = 'trialing'
                          and ts.trial_ends_at is not null
                          and ts.trial_ends_at <= now()
                          then 'past_due'
                        when coalesce(ts.status, 'active') = 'active'
                          and ts.current_period_ends_at is not null
                          and ts.current_period_ends_at <= now()
                          then 'past_due'
                        else coalesce(ts.status, 'active')
                      end as subscription_status
                    from users u
                    join user_passwords up on up.user_id = u.id
                    join tenants t on t.id = u.tenant_id
                    left join tenant_subscriptions ts on ts.tenant_id = u.tenant_id
                    where u.username = %s
                    """,
                    (username,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return None
                if row["status"] != "active" or row["tenant_status"] != "active":
                    connection.rollback()
                    return None
                if not verify_password(password, row["password_hash"]):
                    connection.rollback()
                    return None
                if needs_password_rehash(row["password_hash"]):
                    cursor.execute(
                        """
                        update user_passwords
                        set password_hash = %s,
                            password_version = password_version + 1,
                            updated_at = now()
                        where user_id = %s
                        """,
                        (hash_password(password), row["id"]),
                    )
                    connection.commit()
                else:
                    connection.rollback()
        return self._to_user(row)

    def create_session(self, user: dict[str, Any]) -> str:
        session_token = uuid4().hex
        expires_at = self._now() + timedelta(
            seconds=settings.session_max_age_seconds
        )
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into auth_sessions (
                      user_id, session_token, status, expires_at, created_at
                    )
                    values (%s, %s, 'active', %s, now())
                    """,
                    (user["id"], session_token, expires_at),
                )
            connection.commit()
        return session_token

    def authenticate_and_create_session(
        self,
        username: str,
        password: str,
        *,
        profile: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        with self._get_login_lock(username):
            session_token = uuid4().hex
            expires_at = self._now() + timedelta(
                seconds=settings.session_max_age_seconds
            )
            db_read_started_at = perf_counter()
            row = self._cached_auth_record(username)
            if row is None:
                with get_db_session() as connection:
                    with connection.cursor() as cursor:
                        row = cursor.execute(
                            """
                            select
                              u.id, u.tenant_id, u.username, u.email, u.role, u.status,
                              u.expires_at, u.force_password_reset, u.last_login_at,
                              u.version, u.created_at, u.updated_at,
                              up.password_hash,
                              t.status as tenant_status,
                              case
                                when coalesce(ts.status, 'active') = 'trialing'
                                  and ts.trial_ends_at is not null
                                  and ts.trial_ends_at <= now()
                                  then 'past_due'
                                when coalesce(ts.status, 'active') = 'active'
                                  and ts.current_period_ends_at is not null
                                  and ts.current_period_ends_at <= now()
                                  then 'past_due'
                                else coalesce(ts.status, 'active')
                              end as subscription_status,
                              recent_session.session_token as recent_session_token,
                              recent_session.expires_at as recent_session_expires_at,
                              coalesce(
                                (
                                  select jsonb_agg(
                                    jsonb_build_object(
                                      'feature_key', uff.feature_key,
                                      'enabled', uff.enabled,
                                      'source', uff.source
                                    )
                                    order by uff.feature_key asc
                                  )
                                  from user_feature_flags uff
                                  where uff.user_id = u.id
                                ),
                                '[]'::jsonb
                              ) as feature_flags
                            from users u
                            join user_passwords up on up.user_id = u.id
                            join tenants t on t.id = u.tenant_id
                            left join tenant_subscriptions ts on ts.tenant_id = u.tenant_id
                            left join lateral (
                              select s.session_token, s.expires_at
                              from auth_sessions s
                              where s.user_id = u.id
                                and s.status = 'active'
                                and s.expires_at > now()
                                and s.created_at >= now() - interval '5 minutes'
                              order by s.created_at desc
                              limit 1
                            ) recent_session on true
                            where u.username = %s
                            """,
                            (username,),
                        ).fetchone()
                        connection.rollback()
                if row is not None:
                    row = dict(row)
                    self._remember_auth_record(username, row)

            db_read_elapsed_ms = (perf_counter() - db_read_started_at) * 1000
            if profile is not None:
                profile["db_read_ms"] = db_read_elapsed_ms

            if row is None or row["status"] != "active" or row["tenant_status"] != "active":
                if profile is not None:
                    profile["verify_ms"] = 0.0
                    profile["db_write_ms"] = 0.0
                    profile["reused"] = False
                return None

            verify_started_at = perf_counter()
            is_valid_password = self._cached_password_verification(
                username,
                password,
                row["password_hash"],
            )
            if not is_valid_password:
                is_valid_password = verify_password(password, row["password_hash"])
                if is_valid_password:
                    self._remember_password_verification(
                        username,
                        password,
                        row["password_hash"],
                    )
            verify_elapsed_ms = (perf_counter() - verify_started_at) * 1000
            if profile is not None:
                profile["verify_ms"] = verify_elapsed_ms
            if not is_valid_password:
                if profile is not None:
                    profile["db_write_ms"] = 0.0
                    profile["reused"] = False
                return None

            user_id = self._normalize_value(row["id"])
            if needs_password_rehash(row["password_hash"]):
                upgraded_hash = hash_password(password)
                self._update_password_hash(user_id, upgraded_hash)
                row["password_hash"] = upgraded_hash
                self._remember_auth_record(username, row)
                self._remember_password_verification(username, password, upgraded_hash)

            cached_session_token = self._cached_recent_session(user_id)
            if cached_session_token is not None:
                if profile is not None:
                    profile["db_write_ms"] = 0.0
                    profile["reused"] = True
                return cached_session_token, self._to_user(row)

            existing_session_token = row.get("recent_session_token")
            existing_session_expires_at = row.get("recent_session_expires_at")
            if existing_session_token is not None and existing_session_expires_at is not None:
                self._remember_recent_session(
                    user_id,
                    existing_session_token,
                    existing_session_expires_at,
                )
                if profile is not None:
                    profile["db_write_ms"] = 0.0
                    profile["reused"] = True
                return existing_session_token, self._to_user(row)

            db_write_started_at = perf_counter()
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        insert into auth_sessions (
                          user_id, session_token, status, expires_at, created_at
                        )
                        values (%s, %s, 'active', %s, now())
                        """,
                        (row["id"], session_token, expires_at),
                    )
                connection.commit()
            self._remember_recent_session(user_id, session_token, expires_at)
            if profile is not None:
                profile["db_write_ms"] = (perf_counter() - db_write_started_at) * 1000
                profile["reused"] = False
            return session_token, self._to_user(row)

    def get_session_user(self, session_token: str | None) -> dict[str, Any] | None:
        if not session_token:
            return None
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select
                      u.*,
                      t.status as tenant_status,
                      case
                        when coalesce(ts.status, 'active') = 'trialing'
                          and ts.trial_ends_at is not null
                          and ts.trial_ends_at <= now()
                          then 'past_due'
                        when coalesce(ts.status, 'active') = 'active'
                          and ts.current_period_ends_at is not null
                          and ts.current_period_ends_at <= now()
                          then 'past_due'
                        else coalesce(ts.status, 'active')
                      end as subscription_status,
                      coalesce(
                        (
                          select jsonb_agg(
                            jsonb_build_object(
                              'feature_key', uff.feature_key,
                              'enabled', uff.enabled,
                              'source', uff.source
                            )
                            order by uff.feature_key asc
                          )
                          from user_feature_flags uff
                          where uff.user_id = u.id
                        ),
                        '[]'::jsonb
                      ) as feature_flags
                    from auth_sessions s
                    join users u on u.id = s.user_id
                    join tenants t on t.id = u.tenant_id
                    left join tenant_subscriptions ts on ts.tenant_id = u.tenant_id
                    where s.session_token = %s
                      and s.status = 'active'
                      and s.expires_at > now()
                      and u.status = 'active'
                      and t.status = 'active'
                    """,
                    (session_token,),
                ).fetchone()
                connection.rollback()
        return self._to_user(row) if row else None

    def delete_session(self, session_token: str | None) -> None:
        if not session_token:
            return
        self._forget_recent_session_token(session_token)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update auth_sessions
                    set status = 'revoked', revoked_at = now()
                    where session_token = %s and status = 'active'
                    """,
                    (session_token,),
                )
            connection.commit()

    def delete_sessions_for_user(self, user_id: str) -> int:
        self._forget_recent_session_user(user_id)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update auth_sessions
                    set status = 'forced_logout', revoked_at = now()
                    where user_id = %s and status = 'active'
                    """,
                    (user_id,),
                )
                count = cursor.rowcount
            connection.commit()
        return count

    def delete_sessions_for_tenant(self, tenant_id: str) -> int:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                users = cursor.execute(
                    "select id, username from users where tenant_id = %s",
                    (tenant_id,),
                ).fetchall()
                cursor.execute(
                    """
                    update auth_sessions s
                    set status = 'forced_logout', revoked_at = now()
                    from users u
                    where s.user_id = u.id
                      and u.tenant_id = %s
                      and s.status = 'active'
                    """,
                    (tenant_id,),
                )
                count = cursor.rowcount
            connection.commit()
        with self._cache_lock:
            for user in users:
                user_id = self._normalize_value(user["id"])
                self._recent_session_cache.pop(user_id, None)
                self._auth_record_cache.pop(user["username"], None)
                self._password_verify_cache.pop(user["username"], None)
        return count

    def count_sessions_for_user(self, user_id: str) -> int:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select count(*) as count
                    from auth_sessions
                    where user_id = %s and status = 'active' and expires_at > now()
                    """,
                    (user_id,),
                ).fetchone()
                connection.rollback()
        return row["count"]

    def count_sessions_for_users(self, user_ids: list[str]) -> dict[str, int]:
        if not user_ids:
            return {}
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    select user_id, count(*) as count
                    from auth_sessions
                    where user_id = any(%s::uuid[])
                      and status = 'active'
                      and expires_at > now()
                    group by user_id
                    """,
                    ([UUID(user_id) for user_id in user_ids],),
                ).fetchall()
                connection.rollback()
        counts = {user_id: 0 for user_id in user_ids}
        for row in rows:
            counts[self._normalize_value(row["user_id"])] = row["count"]
        return counts

    def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from users"
        params: list[Any] = []
        if tenant_id is not None:
            query += " where tenant_id = %s"
            params.append(tenant_id)
        query += " order by created_at desc"
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(query, params).fetchall()
                connection.rollback()
        return [self._to_user(row) for row in rows]

    def list_tenants(self) -> list[dict[str, Any]]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    "select * from tenants order by created_at desc"
                ).fetchall()
                connection.rollback()
        return [self._to_tenant(row) for row in rows]

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from tenants where id = %s",
                    (tenant_id,),
                ).fetchone()
                connection.rollback()
        return self._to_tenant(row) if row else None

    def get_tenant_by_slug(self, slug: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from tenants where slug = %s",
                    (slug,),
                ).fetchone()
                connection.rollback()
        return self._to_tenant(row) if row else None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from users where id = %s",
                    (user_id,),
                ).fetchone()
                connection.rollback()
        return self._to_user(row) if row else None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from users where username = %s",
                    (username,),
                ).fetchone()
                connection.rollback()
        return self._to_user(row) if row else None

    def update_user(self, user_id: str, **changes: Any) -> dict[str, Any]:
        user_fields = {
            key: value
            for key, value in changes.items()
            if key in {"email", "role", "status", "expires_at", "force_password_reset", "last_login_at"}
        }
        password = changes.get("password")
        existing_user = self.get_user(user_id)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                if user_fields:
                    assignments = [
                        sql.SQL("{} = %s").format(sql.Identifier(column))
                        for column in user_fields
                    ]
                    query = sql.SQL(
                        "update users set {}, updated_at = now(), version = version + 1 where id = %s"
                    ).format(sql.SQL(", ").join(assignments))
                    cursor.execute(query, (*user_fields.values(), user_id))
                if password is not None:
                    cursor.execute(
                        """
                        update user_passwords
                        set password_hash = %s, password_version = password_version + 1, updated_at = now()
                        where user_id = %s
                        """,
                        (hash_password(password), user_id),
                    )
            connection.commit()
        if existing_user is not None:
            self._forget_auth_record(existing_user["username"])
            self._forget_recent_session_user(user_id)
        return self.get_user(user_id)

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(uuid4())
        password = payload.get("password", "temp12345")
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into users (
                      id, tenant_id, username, email, role, status, expires_at,
                      force_password_reset, version, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, 1, now(), now())
                    returning *
                    """,
                    (
                        user_id,
                        payload.get("tenant_id", self._default_tenant_id()),
                        payload["username"],
                        payload.get("email"),
                        payload["role"],
                        payload.get("status", "active"),
                        payload.get("expires_at"),
                        payload.get("force_password_reset", True),
                    ),
                ).fetchone()
                cursor.execute(
                    """
                    insert into user_passwords (user_id, password_hash, password_version, updated_at)
                    values (%s, %s, 1, now())
                    """,
                    (user_id, hash_password(password)),
                )
            connection.commit()
        self._forget_auth_record(payload["username"])
        return self._to_user(row)

    def create_tenant_with_admin(
        self,
        payload: dict[str, Any],
        updated_by: str,
    ) -> dict[str, dict[str, Any]]:
        tenant_id = str(uuid4())
        user_id = str(uuid4())
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                tenant_row = cursor.execute(
                    """
                    insert into tenants (id, slug, name, status, plan, created_at, updated_at)
                    values (%s, %s, %s, 'active', %s, now(), now())
                    returning *
                    """,
                    (
                        tenant_id,
                        payload["slug"],
                        payload["name"],
                        payload["plan"],
                    ),
                ).fetchone()
                subscription_row = cursor.execute(
                    """
                    insert into tenant_subscriptions (
                      tenant_id, plan, status, updated_by, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, now(), now())
                    returning *
                    """,
                    (
                        tenant_id,
                        payload["plan"],
                        payload["subscription_status"],
                        updated_by,
                    ),
                ).fetchone()
                user_row = cursor.execute(
                    """
                    insert into users (
                      id, tenant_id, username, email, role, status,
                      force_password_reset, version, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, 'tenant_admin', 'active', false, 1, now(), now())
                    returning *
                    """,
                    (
                        user_id,
                        tenant_id,
                        payload["admin_username"],
                        payload.get("admin_email"),
                    ),
                ).fetchone()
                cursor.execute(
                    """
                    insert into user_passwords (user_id, password_hash, password_version, updated_at)
                    values (%s, %s, 1, now())
                    """,
                    (user_id, hash_password(payload["admin_password"])),
                )
            connection.commit()
        self._forget_auth_record(payload["admin_username"])
        return {
            "tenant": self._to_tenant(tenant_row),
            "admin_user": self._to_user(user_row),
            "subscription": self._to_subscription(subscription_row),
        }

    def _cached_auth_record(self, username: str) -> dict[str, Any] | None:
        now = monotonic()
        with self._cache_lock:
            entry = self._auth_record_cache.get(username)
            if entry is None:
                return None
            expires_at, row = entry
            if expires_at <= now:
                self._auth_record_cache.pop(username, None)
                return None
            return dict(row)

    def _remember_auth_record(self, username: str, row: dict[str, Any]) -> None:
        with self._cache_lock:
            self._auth_record_cache[username] = (
                monotonic() + self._AUTH_RECORD_CACHE_SECONDS,
                dict(row),
            )

    def _forget_auth_record(self, username: str) -> None:
        with self._cache_lock:
            self._auth_record_cache.pop(username, None)
            self._password_verify_cache.pop(username, None)

    def _cached_password_verification(
        self,
        username: str,
        password: str,
        password_hash: str,
    ) -> bool:
        now = monotonic()
        with self._cache_lock:
            entry = self._password_verify_cache.get(username)
            if entry is None:
                return False
            expires_at, cached_password_hash, cached_fingerprint = entry
            if expires_at <= now or cached_password_hash != password_hash:
                self._password_verify_cache.pop(username, None)
                return False
            return hmac.compare_digest(cached_fingerprint, password_fingerprint(password))

    def _remember_password_verification(
        self,
        username: str,
        password: str,
        password_hash: str,
    ) -> None:
        with self._cache_lock:
            self._password_verify_cache[username] = (
                monotonic() + self._PASSWORD_VERIFY_CACHE_SECONDS,
                password_hash,
                password_fingerprint(password),
            )

    def _update_password_hash(self, user_id: str, password_hash: str) -> None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update user_passwords
                    set password_hash = %s,
                        password_version = password_version + 1,
                        updated_at = now()
                    where user_id = %s
                    """,
                    (password_hash, user_id),
                )
            connection.commit()

    def _cached_recent_session(self, user_id: str) -> str | None:
        now = monotonic()
        with self._cache_lock:
            entry = self._recent_session_cache.get(user_id)
            if entry is None:
                return None
            expires_at, session_token = entry
            if expires_at <= now:
                self._recent_session_cache.pop(user_id, None)
                return None
            return session_token

    def _remember_recent_session(
        self,
        user_id: str,
        session_token: str,
        session_expires_at: datetime,
    ) -> None:
        ttl_seconds = min(
            self._RECENT_SESSION_CACHE_SECONDS,
            max(1.0, (session_expires_at - self._now()).total_seconds()),
        )
        with self._cache_lock:
            self._recent_session_cache[user_id] = (
                monotonic() + ttl_seconds,
                session_token,
            )

    def _forget_recent_session_token(self, session_token: str) -> None:
        with self._cache_lock:
            stale_user_ids = [
                user_id
                for user_id, (_, cached_session_token) in self._recent_session_cache.items()
                if cached_session_token == session_token
            ]
            for user_id in stale_user_ids:
                self._recent_session_cache.pop(user_id, None)

    def _forget_recent_session_user(self, user_id: str) -> None:
        with self._cache_lock:
            self._recent_session_cache.pop(user_id, None)

    def _cached_system_settings(self) -> list[dict[str, Any]] | None:
        now = monotonic()
        with self._cache_lock:
            expires_at, settings_rows = self._system_settings_cache
            if expires_at <= now:
                return None
            return [dict(setting) for setting in settings_rows]

    def _cache_key(self, tenant_id: str | None) -> str:
        return tenant_id or "__all__"

    def _cached_records(
        self,
        cache: dict[str, tuple[float, list[dict[str, Any]]]],
        cache_key: str,
    ) -> list[dict[str, Any]] | None:
        now = monotonic()
        with self._cache_lock:
            entry = cache.get(cache_key)
            if entry is None:
                return None
            expires_at, records = entry
            if expires_at <= now:
                cache.pop(cache_key, None)
                return None
            return [dict(record) for record in records]

    def _remember_records(
        self,
        cache: dict[str, tuple[float, list[dict[str, Any]]]],
        cache_key: str,
        records: list[dict[str, Any]],
        ttl_seconds: int,
    ) -> None:
        with self._cache_lock:
            cache[cache_key] = (
                monotonic() + ttl_seconds,
                [dict(record) for record in records],
            )

    def _forget_store_list_cache(self) -> None:
        with self._cache_lock:
            self._store_list_cache.clear()

    def _forget_task_list_cache(self) -> None:
        with self._cache_lock:
            self._task_list_cache.clear()

    def _get_login_lock(self, username: str) -> Lock:
        with self._login_locks_lock:
            login_lock = self._login_locks.get(username)
            if login_lock is None:
                login_lock = Lock()
                self._login_locks[username] = login_lock
            return login_lock

    def list_user_feature_flags(self, user_id: str) -> list[dict[str, Any]]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    select id, user_id, feature_key, enabled, source, updated_by, created_at, updated_at
                    from user_feature_flags
                    where user_id = %s
                    order by feature_key asc
                    """,
                    (user_id,),
                ).fetchall()
                connection.rollback()
        return [dict(row) for row in rows]

    def list_user_feature_flags_map(self, user_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not user_ids:
            return {}
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    select id, user_id, feature_key, enabled, source, updated_by, created_at, updated_at
                    from user_feature_flags
                    where user_id = any(%s::uuid[])
                    order by user_id asc, feature_key asc
                    """,
                    ([UUID(user_id) for user_id in user_ids],),
                ).fetchall()
                connection.rollback()
        feature_flags = {user_id: [] for user_id in user_ids}
        for row in rows:
            normalized_row = self._normalize_value(dict(row))
            feature_flags[normalized_row["user_id"]].append(normalized_row)
        return feature_flags

    def upsert_user_feature_flag(
        self,
        *,
        user_id: str,
        feature_key: str,
        enabled: bool,
        source: str,
        updated_by: str,
    ) -> dict[str, Any]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into user_feature_flags (
                      id, user_id, feature_key, enabled, source, updated_by, version, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, 1, now(), now())
                    on conflict (user_id, feature_key)
                    do update set
                      enabled = excluded.enabled,
                      source = excluded.source,
                      updated_by = excluded.updated_by,
                      version = user_feature_flags.version + 1,
                      updated_at = now()
                    returning id, user_id, feature_key, enabled, source, updated_by, created_at, updated_at
                    """,
                    (str(uuid4()), user_id, feature_key, enabled, source, updated_by),
                ).fetchone()
            connection.commit()
        return self._normalize_value(dict(row))

    def list_system_settings(self) -> list[dict[str, Any]]:
        cached_settings = self._cached_system_settings()
        if cached_settings is not None:
            return cached_settings
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    select id, setting_key, value_type, value_json, description, updated_by,
                           created_at, updated_at, version
                    from system_settings
                    order by setting_key asc
                    """
                ).fetchall()
                connection.rollback()
        settings_rows = [self._to_system_setting(row) for row in rows]
        with self._cache_lock:
            self._system_settings_cache = (
                monotonic() + self._SYSTEM_SETTINGS_CACHE_SECONDS,
                [dict(setting) for setting in settings_rows],
            )
        return settings_rows

    def get_system_setting(self, setting_key: str) -> dict[str, Any] | None:
        for setting in self.list_system_settings():
            if setting["setting_key"] == setting_key:
                return setting
        return None

    def is_setting_enabled(self, setting_key: str, default: bool = False) -> bool:
        setting = self.get_system_setting(setting_key)
        if setting is None or setting["value_type"] != "boolean":
            return default
        return bool(setting["value"])

    def list_stores(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        cache_key = self._cache_key(tenant_id)
        cached_stores = self._cached_records(self._store_list_cache, cache_key)
        if cached_stores is not None:
            return cached_stores
        query = self._store_select_sql()
        params: list[Any] = []
        clauses = ["s.deleted_at is null"]
        if tenant_id is not None:
            clauses.append("s.tenant_id = %s")
            params.append(tenant_id)
        query += " where " + " and ".join(clauses)
        query += " order by s.created_at desc"
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(query, params).fetchall()
                connection.rollback()
        stores = [self._to_store(row) for row in rows]
        self._remember_records(
            self._store_list_cache,
            cache_key,
            stores,
            self._STORE_LIST_CACHE_SECONDS,
        )
        return stores

    def get_store(self, store_id: str) -> dict[str, Any] | None:
        query = self._store_select_sql() + " where s.id = %s and s.deleted_at is null"
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(query, (store_id,)).fetchone()
                connection.rollback()
        return self._to_store(row) if row else None

    def create_store(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("platform", "takealot") != "takealot":
            raise ValueError("Only Takealot stores are supported")
        store_id = str(uuid4())
        credential_payload = self._serialize_store_credentials(payload)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into stores (
                      id, tenant_id, name, platform, status, api_key_status, version, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, 1, now(), now())
                    """,
                    (
                        store_id,
                        payload.get("tenant_id", self._default_tenant_id()),
                        payload["name"],
                        payload.get("platform", "takealot"),
                        payload.get("status", "active"),
                        payload.get("api_key_status", "pending"),
                    ),
                )
                cursor.execute(
                    """
                    insert into store_credentials (
                      store_id, api_key_encrypted, masked_api_key, credential_status, created_at, updated_at
                    )
                    values (%s, armor(pgp_sym_encrypt(%s, %s)), %s, %s, now(), now())
                    """,
                    (
                        store_id,
                        credential_payload,
                        settings.store_credential_encryption_key,
                        payload.get("masked_api_key", "not-set"),
                        payload.get("credential_status", "missing"),
                    ),
                )
                feature_policies = payload.get(
                    "feature_policies",
                    {"bidding_enabled": False, "listing_enabled": False, "sync_enabled": True},
                )
                cursor.execute(
                    """
                    insert into store_feature_policies (
                      store_id, bidding_enabled, listing_enabled, sync_enabled, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, now(), now())
                    """,
                    (
                        store_id,
                        feature_policies["bidding_enabled"],
                        feature_policies["listing_enabled"],
                        feature_policies["sync_enabled"],
                    ),
                )
            connection.commit()
        self._forget_store_list_cache()
        return self.get_store(store_id)

    def update_store(self, store_id: str, **changes: Any) -> dict[str, Any]:
        store_changes = {
            key: value
            for key, value in changes.items()
            if key in {"name", "status", "api_key_status", "last_synced_at"}
        }
        credential_changes = {
            key: value
            for key, value in changes.items()
            if key in {"credential_status", "masked_api_key", "last_validated_at"}
        }
        credential_payload = None
        if changes.get("api_key") is not None and changes.get("api_secret") is not None:
            current_credentials = self.get_store_credentials(store_id) or {
                "platform": "takealot",
                "api_key": "",
                "api_secret": "",
            }
            credential_payload = self._serialize_store_credentials(
                {
                    **current_credentials,
                    **{
                        key: value
                        for key, value in changes.items()
                        if key in {"credential_platform", "platform", "api_key", "api_secret"}
                    },
                    "leadtime_merchant_warehouse_id": (
                        changes.get("leadtime_merchant_warehouse_id")
                        if changes.get("leadtime_merchant_warehouse_id") is not None
                        else current_credentials.get("leadtime_merchant_warehouse_id")
                    ),
                }
            )
        elif (
            changes.get("leadtime_merchant_warehouse_id") is not None
            or changes.get("platform_profile") is not None
        ):
            current_credentials = self.get_store_credentials(store_id) or {"platform": "takealot", "api_key": "", "api_secret": ""}
            credential_payload = self._serialize_store_credentials(
                {
                    **current_credentials,
                    "leadtime_merchant_warehouse_id": (
                        changes.get("leadtime_merchant_warehouse_id")
                        if changes.get("leadtime_merchant_warehouse_id") is not None
                        else current_credentials.get("leadtime_merchant_warehouse_id")
                    ),
                    "platform_profile": (
                        changes.get("platform_profile")
                        if changes.get("platform_profile") is not None
                        else current_credentials.get("platform_profile")
                    ),
                }
            )
        feature_policies = changes.get("feature_policies")
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                if store_changes:
                    assignments = [
                        sql.SQL("{} = %s").format(sql.Identifier(column))
                        for column in store_changes
                    ]
                    query = sql.SQL(
                        "update stores set {}, updated_at = now(), version = version + 1 where id = %s"
                    ).format(sql.SQL(", ").join(assignments))
                    cursor.execute(query, (*store_changes.values(), store_id))
                if credential_changes:
                    assignments = [
                        sql.SQL("{} = %s").format(sql.Identifier(column))
                        for column in credential_changes
                    ]
                    query = sql.SQL(
                        "update store_credentials set {}, updated_at = now() where store_id = %s"
                    ).format(sql.SQL(", ").join(assignments))
                    cursor.execute(query, (*credential_changes.values(), store_id))
                if credential_payload is not None:
                    cursor.execute(
                        """
                        update store_credentials
                        set api_key_encrypted = armor(pgp_sym_encrypt(%s, %s)),
                            updated_at = now()
                        where store_id = %s
                        """,
                        (
                            credential_payload,
                            settings.store_credential_encryption_key,
                            store_id,
                        ),
                    )
                if feature_policies is not None:
                    cursor.execute(
                        """
                        update store_feature_policies
                        set bidding_enabled = %s,
                            listing_enabled = %s,
                            sync_enabled = %s,
                            updated_at = now()
                        where store_id = %s
                        """,
                        (
                            feature_policies["bidding_enabled"],
                            feature_policies["listing_enabled"],
                            feature_policies["sync_enabled"],
                            store_id,
                        ),
                    )
            connection.commit()
        self._forget_store_list_cache()
        return self.get_store(store_id)

    def delete_store(self, store_id: str) -> bool:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    update stores
                    set status = 'disabled',
                        deleted_at = now(),
                        updated_at = now(),
                        version = version + 1
                    where id = %s and deleted_at is null
                    returning id
                    """,
                    (store_id,),
                ).fetchone()
            connection.commit()
        self._forget_store_list_cache()
        return row is not None

    def get_store_credentials(self, store_id: str) -> dict[str, Any] | None:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        """
                        select
                          pgp_sym_decrypt(dearmor(api_key_encrypted), %s) as payload,
                          last_validated_at
                        from store_credentials
                        where store_id = %s
                        """,
                        (settings.store_credential_encryption_key, store_id),
                    ).fetchone()
                    connection.rollback()
        except Exception:
            return None

        if row is None or not row["payload"]:
            return None
        payload = self._decode_json(row["payload"])
        if not isinstance(payload, dict):
            return None
        return {
            "platform": str(payload.get("platform") or ""),
            "api_key": str(payload.get("api_key") or ""),
            "api_secret": str(payload.get("api_secret") or ""),
            "leadtime_merchant_warehouse_id": payload.get("leadtime_merchant_warehouse_id"),
            "last_validated_at": row["last_validated_at"],
            "platform_profile": payload.get("platform_profile"),
        }

    def list_store_listings(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
        status_group: str | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = """
            select l.*, br.last_buybox_price as buybox_price
            from listings l
            left join bidding_rules br
              on br.store_id = l.store_id
             and br.sku = l.sku
            where l.store_id = %s and l.sync_status <> 'stale'
        """
        params: list[Any] = [store_id]
        if sku_query:
            query += " and (l.sku ilike %s or l.title ilike %s)"
            params.extend([f"%{sku_query}%", f"%{sku_query}%"])
        status_clause, status_params = _listing_status_filter_sql(status_group, alias="l")
        if status_clause:
            query += f" and {status_clause}"
            params.extend(status_params)
        query += f" order by {_listing_sort_sql(sort_by, sort_dir)}"
        if limit is not None:
            query += " limit %s offset %s"
            params.extend([limit, max(0, offset)])
        elif offset:
            query += " offset %s"
            params.append(max(0, offset))
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(query, params).fetchall()
                connection.rollback()
        return [self._to_listing(row) for row in rows]

    def count_store_listings(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
        status_group: str | None = None,
    ) -> int:
        query = "select count(*) as listing_count from listings where store_id = %s and sync_status <> 'stale'"
        params: list[Any] = [store_id]
        if sku_query:
            query += " and (sku ilike %s or title ilike %s)"
            params.extend([f"%{sku_query}%", f"%{sku_query}%"])
        status_clause, status_params = _listing_status_filter_sql(status_group)
        if status_clause:
            query += f" and {status_clause}"
            params.extend(status_params)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(query, params).fetchone()
                connection.rollback()
        return int(row["listing_count"] or 0)

    def count_store_listing_status_groups(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
    ) -> dict[str, int]:
        buyable_sql, buyable_params = _listing_status_filter_sql("buyable")
        not_buyable_sql, not_buyable_params = _listing_status_filter_sql("not_buyable")
        platform_sql, platform_params = _listing_status_filter_sql("platform_disabled")
        seller_sql, seller_params = _listing_status_filter_sql("seller_disabled")
        query = f"""
            select
              count(*) as all_count,
              count(*) filter (where {buyable_sql}) as buyable_count,
              count(*) filter (where {not_buyable_sql}) as not_buyable_count,
              count(*) filter (where {platform_sql}) as platform_disabled_count,
              count(*) filter (where {seller_sql}) as seller_disabled_count
            from listings
            where store_id = %s and sync_status <> 'stale'
        """
        params: list[Any] = [
            *buyable_params,
            *not_buyable_params,
            *platform_params,
            *seller_params,
            store_id,
        ]
        if sku_query:
            query += " and (sku ilike %s or title ilike %s)"
            params.extend([f"%{sku_query}%", f"%{sku_query}%"])
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(query, params).fetchone()
                connection.rollback()
        return {
            "all": int(row["all_count"] or 0),
            "buyable": int(row["buyable_count"] or 0),
            "not_buyable": int(row["not_buyable_count"] or 0),
            "platform_disabled": int(row["platform_disabled_count"] or 0),
            "seller_disabled": int(row["seller_disabled_count"] or 0),
        }

    def get_store_listing(
        self,
        *,
        store_id: str,
        listing_id: str,
    ) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select l.*, br.last_buybox_price as buybox_price
                    from listings l
                    left join bidding_rules br
                      on br.store_id = l.store_id
                     and br.sku = l.sku
                    where l.store_id = %s
                      and l.id = %s
                      and l.sync_status <> 'stale'
                    limit 1
                    """,
                    (store_id, listing_id),
                ).fetchone()
                connection.rollback()
        return self._to_listing(row) if row else None

    def update_store_listing(
        self,
        *,
        store_id: str,
        listing_id: str,
        platform_price: float | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        assignments = ["updated_at = now()"]
        params: list[Any] = []
        if platform_price is not None:
            assignments.append("platform_price = %s")
            params.append(platform_price)
        if raw_payload is not None:
            assignments.append("raw_payload = %s")
            params.append(Jsonb(self._normalize_value(raw_payload)))
        params.extend([store_id, listing_id])
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    f"""
                    update listings
                    set {", ".join(assignments)}
                    where store_id = %s
                      and id = %s
                      and sync_status <> 'stale'
                    returning *
                    """,
                    params,
                ).fetchone()
            connection.commit()
        if row is None:
            return None
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
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into listings (
                      store_id, external_listing_id, platform_product_id, sku, title, platform_price,
                      stock_quantity, currency, sync_status, raw_payload,
                      last_synced_at, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), now())
                    on conflict (store_id, external_listing_id) do update
                    set platform_product_id = coalesce(excluded.platform_product_id, listings.platform_product_id),
                        sku = excluded.sku,
                        title = excluded.title,
                        platform_price = excluded.platform_price,
                        stock_quantity = excluded.stock_quantity,
                        currency = excluded.currency,
                        sync_status = excluded.sync_status,
                        raw_payload = excluded.raw_payload,
                        last_synced_at = now(),
                        updated_at = now()
                    returning *
                    """,
                    (
                        store_id,
                        external_listing_id,
                        platform_product_id,
                        sku,
                        title,
                        platform_price,
                        stock_quantity,
                        currency,
                        sync_status,
                        Jsonb(self._normalize_value(raw_payload)) if raw_payload is not None else None,
                    ),
                ).fetchone()
            connection.commit()
        return self._to_listing(row)

    def upsert_store_listings_bulk(self, listings: list[dict[str, Any]]) -> int:
        if not listings:
            return 0
        rows = [
            (
                listing["store_id"],
                listing["external_listing_id"],
                listing.get("platform_product_id"),
                listing["sku"],
                listing["title"],
                listing.get("platform_price"),
                listing.get("stock_quantity"),
                listing.get("currency") or "ZAR",
                listing.get("sync_status") or "synced",
                Jsonb(self._normalize_value(listing.get("raw_payload")))
                if listing.get("raw_payload") is not None
                else None,
            )
            for listing in listings
        ]
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into listings (
                      store_id, external_listing_id, platform_product_id, sku, title, platform_price,
                      stock_quantity, currency, sync_status, raw_payload,
                      last_synced_at, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), now())
                    on conflict (store_id, external_listing_id) do update
                    set platform_product_id = coalesce(excluded.platform_product_id, listings.platform_product_id),
                        sku = excluded.sku,
                        title = excluded.title,
                        platform_price = excluded.platform_price,
                        stock_quantity = excluded.stock_quantity,
                        currency = excluded.currency,
                        sync_status = excluded.sync_status,
                        raw_payload = excluded.raw_payload,
                        last_synced_at = now(),
                        updated_at = now()
                    """,
                    rows,
                )
            connection.commit()
        return len(rows)

    def mark_store_listings_stale_except(
        self,
        *,
        store_id: str,
        external_listing_ids: list[str],
    ) -> int:
        if not external_listing_ids:
            return 0
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    update listings
                    set sync_status = 'stale',
                        updated_at = now()
                    where store_id = %s
                      and sync_status <> 'stale'
                      and not (external_listing_id = any(%s::text[]))
                    returning id
                    """,
                    (store_id, external_listing_ids),
                ).fetchall()
            connection.commit()
        return len(rows)

    def find_store_listing_by_platform_product_id(
        self,
        *,
        store_id: str,
        platform_product_id: str,
    ) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select *
                    from listings
                    where store_id = %s and platform_product_id = %s
                    order by updated_at desc
                    limit 1
                    """,
                    (store_id, platform_product_id),
                ).fetchone()
                connection.rollback()
        return self._to_listing(row) if row else None

    def get_library_product(
        self,
        *,
        platform: str,
        external_product_id: str,
    ) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select *
                    from library_products
                    where platform = %s and external_product_id = %s
                    """,
                    (platform, external_product_id),
                ).fetchone()
                connection.rollback()
        return self._to_library_product(row) if row else None

    def get_library_product_by_id(self, product_id: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from library_products where id = %s",
                    (product_id,),
                ).fetchone()
                connection.rollback()
        return self._to_library_product(row) if row else None

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
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into library_products (
                      platform, external_product_id, title, fact_status,
                      merchant_packaged_weight_raw, merchant_packaged_dimensions_raw,
                      cbs_package_weight_raw, cbs_package_dimensions_raw,
                      consolidated_packaged_dimensions_raw, raw_payload, last_refreshed_at,
                      created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    on conflict (platform, external_product_id) do update
                    set title = coalesce(excluded.title, library_products.title),
                        fact_status = excluded.fact_status,
                        merchant_packaged_weight_raw = coalesce(excluded.merchant_packaged_weight_raw, library_products.merchant_packaged_weight_raw),
                        merchant_packaged_dimensions_raw = coalesce(excluded.merchant_packaged_dimensions_raw, library_products.merchant_packaged_dimensions_raw),
                        cbs_package_weight_raw = coalesce(excluded.cbs_package_weight_raw, library_products.cbs_package_weight_raw),
                        cbs_package_dimensions_raw = coalesce(excluded.cbs_package_dimensions_raw, library_products.cbs_package_dimensions_raw),
                        consolidated_packaged_dimensions_raw = coalesce(excluded.consolidated_packaged_dimensions_raw, library_products.consolidated_packaged_dimensions_raw),
                        raw_payload = coalesce(excluded.raw_payload, library_products.raw_payload),
                        last_refreshed_at = coalesce(excluded.last_refreshed_at, library_products.last_refreshed_at),
                        updated_at = now()
                    returning *
                    """,
                    (
                        platform,
                        external_product_id,
                        title,
                        fact_status,
                        merchant_packaged_weight_raw,
                        merchant_packaged_dimensions_raw,
                        cbs_package_weight_raw,
                        cbs_package_dimensions_raw,
                        consolidated_packaged_dimensions_raw,
                        Jsonb(self._normalize_value(raw_payload)) if raw_payload is not None else None,
                        last_refreshed_at,
                    ),
                ).fetchone()
            connection.commit()
        return self._to_library_product(row)

    def get_tenant_product_guardrail(
        self,
        *,
        tenant_id: str,
        store_id: str,
        product_id: str,
    ) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select *
                    from tenant_product_guardrails
                    where tenant_id = %s and store_id = %s and product_id = %s
                    """,
                    (tenant_id, store_id, product_id),
                ).fetchone()
                connection.rollback()
        return self._to_tenant_product_guardrail(row) if row else None

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
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into tenant_product_guardrails (
                      tenant_id, store_id, product_id, protected_floor_price, status,
                      autobid_sync_status, source, created_by, updated_by, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    on conflict (tenant_id, store_id, product_id) do update
                    set protected_floor_price = excluded.protected_floor_price,
                        status = excluded.status,
                        autobid_sync_status = excluded.autobid_sync_status,
                        source = excluded.source,
                        updated_by = excluded.updated_by,
                        updated_at = now()
                    returning *
                    """,
                    (
                        tenant_id,
                        store_id,
                        product_id,
                        protected_floor_price,
                        status,
                        autobid_sync_status,
                        source,
                        created_by,
                        updated_by,
                    ),
                ).fetchone()
            connection.commit()
        return self._to_tenant_product_guardrail(row)

    def update_tenant_product_guardrail(
        self,
        guardrail_id: str,
        **changes: Any,
    ) -> dict[str, Any] | None:
        allowed_columns = {
            "status",
            "linked_listing_id",
            "linked_bidding_rule_id",
            "autobid_sync_status",
            "last_synced_at",
            "last_error_code",
            "last_error_message",
            "updated_by",
        }
        updates = {
            key: value
            for key, value in changes.items()
            if key in allowed_columns
        }
        if not updates:
            return None
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                assignments = [
                    sql.SQL("{} = %s").format(sql.Identifier(column))
                    for column in updates
                ]
                row = cursor.execute(
                    sql.SQL(
                        "update tenant_product_guardrails set {}, updated_at = now() where id = %s returning *"
                    ).format(sql.SQL(", ").join(assignments)),
                    (*updates.values(), guardrail_id),
                ).fetchone()
            connection.commit()
        return self._to_tenant_product_guardrail(row) if row else None

    def list_guardrails_for_store_platform_product(
        self,
        *,
        store_id: str,
        platform: str,
        external_product_id: str,
    ) -> list[dict[str, Any]]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    select g.*
                    from tenant_product_guardrails g
                    inner join library_products p on p.id = g.product_id
                    where g.store_id = %s
                      and p.platform = %s
                      and p.external_product_id = %s
                    order by g.updated_at desc
                    """,
                    (store_id, platform, external_product_id),
                ).fetchall()
                connection.rollback()
        return [self._to_tenant_product_guardrail(row) for row in rows]

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
        where_parts = ["platform = 'takealot'"]
        params: list[Any] = []

        if query:
            where_parts.append(
                "(title ilike %s or platform_product_id ilike %s or brand ilike %s)"
            )
            like_query = f"%{query.strip()}%"
            params.extend([like_query, like_query, like_query])

        exact_filters = {
            "main_category": main_category,
            "category_level1": category_level1,
            "category_level2": category_level2,
            "category_level3": category_level3,
        }
        for column, value in exact_filters.items():
            if value:
                where_parts.append(f"{column} = %s")
                params.append(value)

        if brand == "__has_brand__":
            where_parts.append("brand is not null and brand <> ''")
        elif brand == "__no_brand__":
            where_parts.append("(brand is null or brand = '')")
        elif brand:
            where_parts.append("brand = %s")
            params.append(brand)

        if stock_status == "__direct_ship__":
            where_parts.append("stock_status = 'ships_in_14___16_work_days'")
        elif stock_status == "__in_stock__":
            where_parts.append("stock_status in ('in_stock', 'limited')")
        elif stock_status == "__ships_in__":
            where_parts.append("stock_status like %s and stock_status <> 'ships_in_14___16_work_days'")
            params.append("ships_in%")
        elif stock_status == "__pre_order__":
            where_parts.append("stock_status like %s")
            params.append("pre_order%")
        elif stock_status == "__out_of_stock__":
            where_parts.append("stock_status in ('out_of_stock', 'unavailable')")
        elif stock_status:
            where_parts.append("stock_status = %s")
            params.append(stock_status)

        if latest_review_window == "__has_latest_review__":
            where_parts.append("latest_review_at is not null")
        elif latest_review_window == "__missing_latest_review__":
            where_parts.append("latest_review_at is null")
        elif latest_review_window in {
            "__last_30_days__",
            "__last_90_days__",
            "__last_180_days__",
            "__last_365_days__",
        }:
            days_by_window = {
                "__last_30_days__": 30,
                "__last_90_days__": 90,
                "__last_180_days__": 180,
                "__last_365_days__": 365,
            }
            where_parts.append("latest_review_at is not null and latest_review_at >= %s")
            params.append(datetime.now(UTC) - timedelta(days=days_by_window[latest_review_window]))

        range_filters: list[tuple[str, str, Any]] = [
            ("current_price", ">=", min_price),
            ("current_price", "<=", max_price),
            ("rating", ">=", min_rating),
            ("total_review_count", ">=", min_reviews),
            ("offer_count", ">=", min_offer_count),
            ("offer_count", "<=", max_offer_count),
        ]
        for column, operator, value in range_filters:
            if value is not None:
                where_parts.append(f"{column} is not null and {column} {operator} %s")
                params.append(value)

        where_sql = " and ".join(f"({part})" for part in where_parts)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                total_row = cursor.execute(
                    f"select count(*) as count from selection_products where {where_sql}",
                    params,
                ).fetchone()
                rows = cursor.execute(
                    f"""
                    select *
                    from selection_products
                    where {where_sql}
                    order by total_review_count desc nulls last,
                             updated_at desc,
                             rating desc nulls last
                    limit %s offset %s
                    """,
                    [*params, limit, offset],
                ).fetchall()
                connection.rollback()
        return {
            "products": [self._to_selection_product(row) for row in rows],
            "total": int(total_row["count"] if total_row else 0),
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
        columns = {
            "main_categories": "main_category",
            "category_level1": "category_level1",
            "category_level2": "category_level2",
            "category_level3": "category_level3",
        }
        filters = {
            "main_category": main_category,
            "category_level1": category_level1,
            "category_level2": category_level2,
            "category_level3": category_level3,
        }
        options: dict[str, list[str]] = {}

        with get_db_session() as connection:
            with connection.cursor() as cursor:
                for key, column in columns.items():
                    where_parts = [sql.SQL("{column} is not null and {column} <> ''").format(column=sql.Identifier(column))]
                    params: list[Any] = []
                    for filter_column, value in filters.items():
                        if value and filter_column != column:
                            where_parts.append(
                                sql.SQL("{column} = %s").format(column=sql.Identifier(filter_column))
                            )
                            params.append(value)
                    append_selection_brand_sql(where_parts, params, brand)
                    append_selection_stock_status_sql(where_parts, params, stock_status)

                    rows = cursor.execute(
                        sql.SQL(
                            """
                            select {column} as value
                            from selection_products
                            where {where_sql}
                            group by {column}
                            order by count(*) desc, {column} asc
                            limit %s
                            """
                        ).format(
                            column=sql.Identifier(column),
                            where_sql=sql.SQL(" and ").join(where_parts),
                        ),
                        (*params, 200),
                    ).fetchall()
                    options[key] = [row["value"] for row in rows]
                tree_rows = cursor.execute(
                    """
                    select main_category, category_level1, category_level2, count(*) as product_count
                    from selection_products
                    where platform = 'takealot'
                      and main_category is not null and main_category <> ''
                      and category_level1 is not null and category_level1 <> ''
                    group by main_category, category_level1, category_level2
                    order by main_category asc, category_level1 asc, product_count desc, category_level2 asc
                    """
                ).fetchall()
                connection.rollback()

        options["brands"] = ["__has_brand__", "__no_brand__"]
        options["stock_statuses"] = [
            "__in_stock__",
            "__ships_in__",
            "__direct_ship__",
            "__pre_order__",
            "__out_of_stock__",
        ]
        options["category_tree"] = build_selection_category_tree(tree_rows)
        return options

    def create_extension_auth_token(
        self,
        *,
        token_hash: str,
        tenant_id: str,
        user_id: str,
        store_id: str | None,
        expires_at: datetime,
    ) -> dict[str, Any]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into extension_auth_tokens (
                      token_hash, tenant_id, user_id, store_id, expires_at, created_at
                    )
                    values (%s, %s, %s, %s, %s, now())
                    returning *
                    """,
                    (token_hash, tenant_id, user_id, store_id, expires_at),
                ).fetchone()
            connection.commit()
        return self._to_extension_auth_token(row)

    def get_extension_auth_token(self, token_hash: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select *
                    from extension_auth_tokens
                    where token_hash = %s and expires_at > now()
                    """,
                    (token_hash,),
                ).fetchone()
                connection.rollback()
        return self._to_extension_auth_token(row) if row else None

    def touch_extension_auth_token(self, token_hash: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    update extension_auth_tokens
                    set last_seen_at = now()
                    where token_hash = %s and expires_at > now()
                    returning *
                    """,
                    (token_hash,),
                ).fetchone()
            connection.commit()
        return self._to_extension_auth_token(row) if row else None

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
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into listing_jobs (
                      tenant_id, store_id, product_id, guardrail_id, entry_task_id, processing_task_id,
                      platform, source, source_ref, title, status, stage, note, raw_payload, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    returning *
                    """,
                    (
                        tenant_id,
                        store_id,
                        product_id,
                        guardrail_id,
                        entry_task_id,
                        processing_task_id,
                        platform,
                        source,
                        source_ref,
                        title,
                        status,
                        stage,
                        note,
                        Jsonb(self._normalize_value(raw_payload)) if raw_payload is not None else None,
                    ),
                ).fetchone()
            connection.commit()
        return self._to_listing_job(row)

    def update_listing_job(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        if not changes:
            return self.get_listing_job(job_id)
        updates = {
            key: Jsonb(value) if key == "raw_payload" and value is not None else value
            for key, value in changes.items()
        }
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                assignments = [
                    sql.SQL("{} = %s").format(sql.Identifier(column))
                    for column in updates
                ]
                row = cursor.execute(
                    sql.SQL(
                        "update listing_jobs set {}, updated_at = now() where id = %s returning *"
                    ).format(sql.SQL(", ").join(assignments)),
                    (*updates.values(), job_id),
                ).fetchone()
            connection.commit()
        return self._to_listing_job(row) if row else None

    def get_listing_job(self, job_id: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from listing_jobs where id = %s",
                    (job_id,),
                ).fetchone()
                connection.rollback()
        return self._to_listing_job(row) if row else None

    def list_listing_jobs(
        self,
        tenant_id: str | None = None,
        *,
        store_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            filters.append("tenant_id = %s")
            params.append(tenant_id)
        if store_id is not None:
            filters.append("store_id = %s")
            params.append(store_id)
        if status_filter is not None:
            filters.append("status = %s")
            params.append(status_filter)
        query = "select * from listing_jobs"
        if filters:
            query += " where " + " and ".join(filters)
        query += " order by created_at desc"
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(query, params).fetchall()
                connection.rollback()
        return [self._to_listing_job(row) for row in rows]

    def list_orders(
        self,
        *,
        tenant_id: str | None = None,
        store_id: str | None = None,
        status_filter: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            filters.append("o.tenant_id = %s")
            params.append(tenant_id)
        if store_id is not None:
            filters.append("o.store_id = %s")
            params.append(store_id)
        if status_filter is not None:
            filters.append("o.status = %s")
            params.append(status_filter)
        if query:
            filters.append(
                """
                (
                  o.external_order_id ilike %s
                  or o.order_number ilike %s
                  or exists (
                    select 1
                    from order_items oi_query
                    where oi_query.order_id = o.id
                      and oi_query.sku ilike %s
                  )
                )
                """
            )
            like_query = f"%{query}%"
            params.extend([like_query, like_query, like_query])
        where_clause = f"where {' and '.join(filters)}" if filters else ""
        sql_text = f"""
            select o.*, count(oi.id) as item_count
            from orders o
            left join order_items oi on oi.order_id = o.id
            {where_clause}
            group by o.id
            order by coalesce(o.placed_at, o.updated_at) desc
            limit 200
        """
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(sql_text, params).fetchall()
                connection.rollback()
        return [self._to_order(row) for row in rows]

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select o.*, count(oi.id) as item_count
                    from orders o
                    left join order_items oi on oi.order_id = o.id
                    where o.id = %s
                    group by o.id
                    """,
                    (order_id,),
                ).fetchone()
                connection.rollback()
        return self._to_order(row) if row else None

    def list_order_items(self, order_id: str) -> list[dict[str, Any]]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    "select * from order_items where order_id = %s order by sku asc",
                    (order_id,),
                ).fetchall()
                connection.rollback()
        return [self._to_order_item(row) for row in rows]

    def list_order_events(self, order_id: str) -> list[dict[str, Any]]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    "select * from order_events where order_id = %s order by created_at desc",
                    (order_id,),
                ).fetchall()
                connection.rollback()
        return [self._to_order_event(row) for row in rows]

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
        order_tenant_clause = ""
        job_tenant_clause = ""
        task_tenant_clause = ""
        today_order_params: list[Any] = [business_day_start, business_day_end]
        chart_params: list[Any] = [business_timezone, chart_start, chart_end]
        job_params: list[Any] = [business_day_start, business_day_end]
        sync_params: list[Any] = []
        newest_order_params: list[Any] = []

        if tenant_id is not None:
            order_tenant_clause = " and tenant_id = %s"
            job_tenant_clause = " and tenant_id = %s"
            task_tenant_clause = " and tenant_id = %s"
            today_order_params.append(tenant_id)
            chart_params.append(tenant_id)
            job_params.append(tenant_id)
            sync_params.append(tenant_id)
            newest_order_params.append(tenant_id)

        with get_db_session() as connection:
            with connection.cursor() as cursor:
                today_order_row = cursor.execute(
                    f"""
                    with scoped_orders as (
                        select id, total_amount
                        from orders
                        where coalesce(placed_at, created_at) >= %s
                          and coalesce(placed_at, created_at) < %s
                          {order_tenant_clause}
                    ),
                    order_quantities as (
                        select order_id, coalesce(sum(quantity), 0)::int as quantity
                        from order_items
                        where order_id in (select id from scoped_orders)
                        group by order_id
                    )
                    select
                        count(scoped_orders.id)::int as order_count,
                        coalesce(sum(scoped_orders.total_amount), 0)::float8 as sales_total,
                        coalesce(sum(order_quantities.quantity), 0)::int as sales_quantity
                    from scoped_orders
                    left join order_quantities on order_quantities.order_id = scoped_orders.id
                    """,
                    today_order_params,
                ).fetchone()
                chart_rows = cursor.execute(
                    f"""
                    with scoped_orders as (
                        select
                          id,
                          timezone(%s, coalesce(placed_at, created_at))::date as bucket_date,
                          total_amount
                        from orders
                        where coalesce(placed_at, created_at) >= %s
                          and coalesce(placed_at, created_at) < %s
                          {order_tenant_clause}
                    ),
                    order_quantities as (
                        select order_id, coalesce(sum(quantity), 0)::int as quantity
                        from order_items
                        where order_id in (select id from scoped_orders)
                        group by order_id
                    )
                    select
                        scoped_orders.bucket_date,
                        coalesce(sum(order_quantities.quantity), 0)::int as volume,
                        coalesce(sum(scoped_orders.total_amount), 0)::float8 as sales
                    from scoped_orders
                    left join order_quantities on order_quantities.order_id = scoped_orders.id
                    group by scoped_orders.bucket_date
                    order by bucket_date asc
                    """,
                    chart_params,
                ).fetchall()
                listing_job_row = cursor.execute(
                    f"""
                    select
                      count(*) filter (
                        where lower(concat_ws(' ', status, stage)) like any(%s)
                      )::int as success_count,
                      count(*) filter (
                        where lower(concat_ws(' ', status, stage)) like any(%s)
                      )::int as failed_count
                    from listing_jobs
                    where updated_at >= %s
                      and updated_at < %s
                      {job_tenant_clause}
                    """,
                    [
                        ["%success%", "%completed%", "%ready_to_submit%", "%buyable%"],
                        ["%failed%", "%error%", "%manual_intervention%", "%rejected%"],
                        *job_params,
                    ],
                ).fetchone()
                sync_row = cursor.execute(
                    f"""
                    select max(coalesce(finished_at, updated_at, created_at)) as last_order_sync_at
                    from task_runs
                    where task_type = 'SYNC_TAKEALOT_ORDERS'
                      and status = 'succeeded'
                      {task_tenant_clause}
                    """,
                    sync_params,
                ).fetchone()
                latest_sync_row = cursor.execute(
                    f"""
                    select
                      coalesce(finished_at, updated_at, created_at) as latest_order_sync_at,
                      status as latest_order_sync_status,
                      error_code as latest_order_sync_error_code,
                      error_msg as latest_order_sync_error_msg
                    from task_runs
                    where task_type = 'SYNC_TAKEALOT_ORDERS'
                      {task_tenant_clause}
                    order by created_at desc
                    limit 1
                    """,
                    sync_params,
                ).fetchone()
                newest_order_row = cursor.execute(
                    f"""
                    select max(coalesce(placed_at, created_at)) as newest_order_at
                    from orders
                    where true
                      {order_tenant_clause}
                    """,
                    newest_order_params,
                ).fetchone()
                connection.rollback()

        return {
              "today_order_count": int(today_order_row["order_count"] or 0),
              "today_sales_total": float(today_order_row["sales_total"] or 0),
              "today_sales_quantity": int(today_order_row["sales_quantity"] or 0),
              "today_listing_success_count": int(listing_job_row["success_count"] or 0),
            "today_listing_failed_count": int(listing_job_row["failed_count"] or 0),
            "chart_points": [
                {
                    "date": row["bucket_date"].isoformat(),
                    "sales": float(row["sales"] or 0),
                    "volume": int(row["volume"] or 0),
                }
                for row in chart_rows
            ],
            "last_order_sync_at": sync_row["last_order_sync_at"],
            "latest_order_sync_at": latest_sync_row["latest_order_sync_at"] if latest_sync_row else None,
            "latest_order_sync_status": latest_sync_row["latest_order_sync_status"] if latest_sync_row else None,
            "latest_order_sync_error_code": latest_sync_row["latest_order_sync_error_code"] if latest_sync_row else None,
            "latest_order_sync_error_msg": latest_sync_row["latest_order_sync_error_msg"] if latest_sync_row else None,
            "newest_order_at": newest_order_row["newest_order_at"],
        }

    def list_store_listing_metrics(
        self,
        *,
        store_id: str,
        days: int = 30,
        sku_filter: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, days))
        params: list[Any] = [store_id, cutoff]
        sku_clause = ""
        if sku_filter is not None:
            sku_values = sorted(sku for sku in sku_filter if sku)
            if not sku_values:
                return []
            sku_clause = " and oi.sku = any(%s::text[])"
            params.append(sku_values)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    f"""
                    select
                      o.store_id,
                      oi.sku,
                      coalesce(sum(oi.quantity), 0)::int as sales_30d
                    from order_items oi
                    join orders o on o.id = oi.order_id
                    where o.store_id = %s
                      and coalesce(o.placed_at, o.created_at) >= %s
                      {sku_clause}
                    group by o.store_id, oi.sku
                    order by oi.sku asc
                    """,
                    params,
                ).fetchall()
                connection.rollback()
        return [
            {
                "store_id": str(row["store_id"]),
                "sku": str(row["sku"]),
                "sales_30d": int(row["sales_30d"] or 0),
            }
            for row in rows
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
        if total_amount is None:
            total_amount = sum(
                float(item.get("unit_price") or 0) * int(item.get("quantity") or 1)
                for item in items
            )
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                previous = cursor.execute(
                    """
                    select id, status
                    from orders
                    where store_id = %s and external_order_id = %s
                    """,
                    (store_id, external_order_id),
                ).fetchone()
                previous_status = previous["status"] if previous else None
                row = cursor.execute(
                    """
                    insert into orders (
                      tenant_id, store_id, external_order_id, order_number, status,
                      fulfillment_status, total_amount, currency, placed_at, last_synced_at,
                      raw_payload, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, now(), now())
                    on conflict (store_id, external_order_id) do update
                    set order_number = excluded.order_number,
                        status = excluded.status,
                        fulfillment_status = excluded.fulfillment_status,
                        total_amount = excluded.total_amount,
                        currency = excluded.currency,
                        placed_at = excluded.placed_at,
                        last_synced_at = now(),
                        raw_payload = excluded.raw_payload,
                        updated_at = now()
                    returning *
                    """,
                    (
                        tenant_id,
                        store_id,
                        external_order_id,
                        order_number,
                        status,
                        fulfillment_status,
                        total_amount,
                        currency,
                        placed_at,
                        Jsonb(self._normalize_value(raw_payload)) if raw_payload is not None else None,
                    ),
                ).fetchone()
                order_id = self._normalize_value(row["id"])
                for item in items:
                    cursor.execute(
                        """
                        insert into order_items (
                          order_id, external_order_item_id, sku, title, quantity,
                          unit_price, status, raw_payload, created_at, updated_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                        on conflict (order_id, external_order_item_id) do update
                        set sku = excluded.sku,
                            title = excluded.title,
                            quantity = excluded.quantity,
                            unit_price = excluded.unit_price,
                            status = excluded.status,
                            raw_payload = excluded.raw_payload,
                            updated_at = now()
                        """,
                        (
                            order_id,
                            str(item["external_order_item_id"]),
                            str(item["sku"]),
                            item.get("title"),
                            int(item.get("quantity") or 1),
                            item.get("unit_price"),
                            item.get("status"),
                            Jsonb(self._normalize_value(item.get("raw_payload")))
                            if item.get("raw_payload") is not None
                            else None,
                        ),
                    )
                event_type = "order.synced"
                message = "Order refreshed from Takealot sales sync"
                if previous_status is None:
                    event_type = "order.created"
                    message = "Order first seen from Takealot sales sync"
                elif previous_status != status:
                    event_type = "order.status_changed"
                    message = f"Order status changed from {previous_status} to {status}"
                cursor.execute(
                    """
                    insert into order_events (
                      order_id, event_type, status, message, payload, occurred_at, created_at
                    )
                    values (%s, %s, %s, %s, %s, now(), now())
                    """,
                    (
                        order_id,
                        event_type,
                        status,
                        message,
                        Jsonb(self._normalize_value(raw_payload)) if raw_payload is not None else None,
                    ),
                )
            connection.commit()
        return self.get_order(order_id)

    def list_bidding_rules(
        self,
        *,
        store_id: str,
        sku_query: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "select * from bidding_rules where store_id = %s"
        params: list[Any] = [store_id]
        if sku_query:
            query += " and sku ilike %s"
            params.append(f"%{sku_query}%")
        query += " order by updated_at desc, sku asc"
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(query, params).fetchall()
                connection.rollback()
        return [self._to_bidding_rule(row) for row in rows]

    def get_bidding_rule(self, rule_id: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from bidding_rules where id = %s",
                    (rule_id,),
                ).fetchone()
                connection.rollback()
        return self._to_bidding_rule(row) if row else None

    def update_bidding_rule(
        self,
        rule_id: str,
        **changes: Any,
    ) -> dict[str, Any] | None:
        allowed_columns = {
            "listing_id",
            "floor_price",
            "strategy_type",
            "is_active",
        }
        updates = {
            key: value
            for key, value in changes.items()
            if key in allowed_columns
        }
        if not updates:
            return self.get_bidding_rule(rule_id)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                assignments = [
                    sql.SQL("{} = %s").format(sql.Identifier(column))
                    for column in updates
                ]
                query = sql.SQL(
                    "update bidding_rules set {}, updated_at = now(), version = version + 1 where id = %s returning *"
                ).format(sql.SQL(", ").join(assignments))
                row = cursor.execute(query, (*updates.values(), rule_id)).fetchone()
            connection.commit()
        return self._to_bidding_rule(row) if row else None

    def update_bidding_rule_runtime(
        self,
        rule_id: str,
        **changes: Any,
    ) -> dict[str, Any] | None:
        allowed_columns = {
            "next_check_at",
            "buybox_fetch_fail_count",
            "buybox_last_error",
            "buybox_last_success_at",
            "buybox_next_retry_at",
            "buybox_status",
            "repricing_blocked_reason",
            "last_action",
            "last_reprice_at",
            "last_suggested_price",
            "last_applied_price",
            "last_buybox_price",
            "last_next_offer_price",
            "last_cycle_dry_run",
            "last_cycle_error",
            "last_decision",
        }
        updates = {
            key: (
                Jsonb(self._normalize_value(value))
                if key == "last_decision" and value is not None
                else value
            )
            for key, value in changes.items()
            if key in allowed_columns
        }
        if not updates:
            return self.get_bidding_rule(rule_id)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                assignments = [
                    sql.SQL("{} = %s").format(sql.Identifier(column))
                    for column in updates
                ]
                query = sql.SQL(
                    "update bidding_rules set {}, updated_at = now(), version = version + 1 where id = %s returning *"
                ).format(sql.SQL(", ").join(assignments))
                row = cursor.execute(query, (*updates.values(), rule_id)).fetchone()
            connection.commit()
        return self._to_bidding_rule(row) if row else None

    def list_bidding_cycle_candidates(
        self,
        *,
        store_id: str,
        limit: int,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        effective_now = now or datetime.now(UTC)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    select
                      br.*,
                      l.id as listing_row_id,
                      l.external_listing_id,
                      l.platform_product_id,
                      l.sku as listing_sku,
                      l.title as listing_title,
                      l.platform_price,
                      l.stock_quantity,
                      l.currency,
                      l.sync_status,
                      l.raw_payload,
                      l.last_synced_at as listing_last_synced_at,
                      l.created_at as listing_created_at,
                      l.updated_at as listing_updated_at
                    from bidding_rules br
                    left join listings l
                      on l.store_id = br.store_id
                     and (
                       l.id::text = br.listing_id
                       or l.sku = br.sku
                     )
                    where br.store_id = %s
                      and br.is_active = true
                      and br.floor_price > 0
                      and (br.next_check_at is null or br.next_check_at <= %s)
                    order by br.next_check_at nulls first, br.updated_at asc, br.sku asc
                    limit %s
                    """,
                    (store_id, effective_now, max(1, limit)),
                ).fetchall()
                connection.rollback()
        candidates: list[dict[str, Any]] = []
        seen_rules: set[str] = set()
        for row in rows:
            rule = self._to_bidding_rule(row)
            if rule["id"] in seen_rules:
                continue
            seen_rules.add(rule["id"])
            listing = None
            if row.get("listing_row_id") is not None:
                listing = {
                    "id": self._normalize_value(row["listing_row_id"]),
                    "store_id": self._normalize_value(row["store_id"]),
                    "external_listing_id": row["external_listing_id"],
                    "platform_product_id": row["platform_product_id"],
                    "sku": row["listing_sku"],
                    "title": row["listing_title"],
                    "platform_price": float(row["platform_price"]) if row["platform_price"] is not None else None,
                    "stock_quantity": row["stock_quantity"],
                    "currency": row["currency"],
                    "sync_status": row["sync_status"],
                    "raw_payload": self._decode_json(row["raw_payload"]),
                    "last_synced_at": row["listing_last_synced_at"],
                    "created_at": row["listing_created_at"],
                    "updated_at": row["listing_updated_at"],
                }
            candidates.append({"rule": rule, "listing": listing})
        return candidates

    def bidding_runtime_summary(self, *, store_id: str) -> dict[str, int]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select
                      count(*) filter (where is_active = true) as active_rule_count,
                      count(*) filter (
                        where is_active = true
                          and floor_price > 0
                          and (next_check_at is null or next_check_at <= now())
                      ) as due_rule_count,
                      count(*) filter (where buybox_status = 'blocked') as blocked_count,
                      count(*) filter (where buybox_status = 'retrying') as retrying_count,
                      count(*) filter (where buybox_status = 'fresh') as fresh_count,
                      count(*) filter (
                        where is_active = true
                          and coalesce(last_decision ->> 'owns_buybox', 'false') = 'true'
                      ) as won_buybox_count,
                      count(*) filter (
                        where is_active = true
                          and last_buybox_price is not null
                          and coalesce(last_decision ->> 'owns_buybox', 'false') <> 'true'
                      ) as lost_buybox_count,
                      count(*) filter (
                        where is_active = true
                          and (
                            buybox_status = 'blocked'
                            or coalesce(repricing_blocked_reason, '') <> ''
                            or coalesce(last_cycle_error, '') <> ''
                            or last_action = 'floor'
                            or (
                              floor_price is not null
                              and last_buybox_price is not null
                              and last_buybox_price < floor_price
                              and coalesce(last_decision ->> 'owns_buybox', 'false') <> 'true'
                            )
                          )
                      ) as alert_count
                    from bidding_rules br
                    where store_id = %s
                    """,
                    (store_id,),
                ).fetchone()
                connection.rollback()
        return {
            "active_rule_count": int(row["active_rule_count"] or 0),
            "due_rule_count": int(row["due_rule_count"] or 0),
            "blocked_count": int(row["blocked_count"] or 0),
            "retrying_count": int(row["retrying_count"] or 0),
            "fresh_count": int(row["fresh_count"] or 0),
            "won_buybox_count": int(row["won_buybox_count"] or 0),
            "lost_buybox_count": int(row["lost_buybox_count"] or 0),
            "alert_count": int(row["alert_count"] or 0),
        }

    def get_bidding_store_runtime_state(self, store_id: str) -> dict[str, Any]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select *
                    from bidding_store_runtime_state
                    where store_id = %s
                    """,
                    (store_id,),
                ).fetchone()
                connection.rollback()
        if row is None:
            now = datetime.now(UTC)
            return {
                "store_id": store_id,
                "is_running": False,
                "last_started_at": None,
                "last_stopped_at": None,
                "last_manual_cycle_at": None,
                "last_worker_cycle_at": None,
                "last_cycle_summary": None,
                "created_at": now,
                "updated_at": now,
            }
        return self._to_bidding_store_runtime(row)

    def update_bidding_store_runtime_state(
        self,
        store_id: str,
        **changes: Any,
    ) -> dict[str, Any] | None:
        allowed_columns = {
            "is_running",
            "last_started_at",
            "last_stopped_at",
            "last_manual_cycle_at",
            "last_worker_cycle_at",
            "last_cycle_summary",
        }
        updates = {
            key: (
                Jsonb(self._normalize_value(value))
                if key == "last_cycle_summary" and value is not None
                else value
            )
            for key, value in changes.items()
            if key in allowed_columns
        }
        if not updates:
            return self.get_bidding_store_runtime_state(store_id)
        columns = list(updates)
        insert_columns = ["store_id", *columns]
        insert_values = [store_id, *updates.values()]
        insert_placeholders = ["%s" for _ in insert_columns]
        conflict_assignments = [
            sql.SQL("{} = excluded.{}").format(sql.Identifier(column), sql.Identifier(column))
            for column in columns
        ]
        conflict_assignments.append(sql.SQL("updated_at = now()"))
        query = sql.SQL(
            """
            insert into bidding_store_runtime_state ({})
            values ({})
            on conflict (store_id) do update set {}
            returning *
            """
        ).format(
            sql.SQL(", ").join(sql.Identifier(column) for column in insert_columns),
            sql.SQL(", ").join(sql.SQL(placeholder) for placeholder in insert_placeholders),
            sql.SQL(", ").join(conflict_assignments),
        )
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(query, insert_values).fetchone()
            connection.commit()
        return self._to_bidding_store_runtime(row) if row else None

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
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                before_row = cursor.execute(
                    "select * from bidding_rules where store_id = %s and sku = %s",
                    (store_id, sku),
                ).fetchone()
                row = cursor.execute(
                    """
                    insert into bidding_rules (
                      store_id, sku, listing_id, floor_price, ceiling_price,
                      strategy_type, is_active, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, now(), now())
                    on conflict (store_id, sku) do update
                    set floor_price = excluded.floor_price,
                        listing_id = coalesce(excluded.listing_id, bidding_rules.listing_id),
                        ceiling_price = null,
                        strategy_type = excluded.strategy_type,
                        is_active = excluded.is_active,
                        updated_at = now(),
                        version = bidding_rules.version + 1
                    returning *
                    """,
                    (
                        store_id,
                        sku,
                        listing_id,
                        floor_price,
                        None,
                        strategy_type,
                        is_active,
                    ),
                ).fetchone()
            connection.commit()
        return self._to_bidding_rule(row), self._to_bidding_rule(before_row) if before_row else None

    def list_tasks(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        cache_key = self._cache_key(tenant_id)
        cached_tasks = self._cached_records(self._task_list_cache, cache_key)
        if cached_tasks is not None:
            return cached_tasks
        query = "select * from task_runs"
        params: list[Any] = []
        if tenant_id is not None:
            query += " where tenant_id = %s"
            params.append(tenant_id)
        query += " order by created_at desc"
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(query, params).fetchall()
                connection.rollback()
        tasks = [self._to_task(row) for row in rows]
        self._remember_records(
            self._task_list_cache,
            cache_key,
            tasks,
            self._TASK_LIST_CACHE_SECONDS,
        )
        return tasks

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    "select * from task_runs where id = %s",
                    (task_id,),
                ).fetchone()
                connection.rollback()
        return self._to_task(row) if row else None

    def update_task(self, task_id: str, **changes: Any) -> dict[str, Any]:
        if not changes:
            return self.get_task(task_id)
        updates = {}
        json_fields = {"error_details", "ui_meta"}
        for key, value in changes.items():
            updates[key] = Jsonb(value) if key in json_fields and value is not None else value
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                assignments = [
                    sql.SQL("{} = %s").format(sql.Identifier(column))
                    for column in updates
                ]
                query = sql.SQL(
                    "update task_runs set {}, updated_at = now() where id = %s"
                ).format(sql.SQL(", ").join(assignments))
                cursor.execute(query, (*updates.values(), task_id))
            connection.commit()
        self._forget_task_list_cache()
        return self.get_task(task_id)

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
        lease_token = str(uuid4())
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    with claimable as (
                      select id, status
                      from task_runs
                      where task_type = any(%s::text[])
                        and (
                          status = 'queued'
                          or status = 'waiting_retry'
                          or (
                            status = 'leased'
                            and lease_expires_at is not null
                            and lease_expires_at <= now()
                          )
                        )
                        and (next_retry_at is null or next_retry_at <= now())
                      order by created_at asc
                      limit %s
                      for update skip locked
                    )
                    update task_runs as task
                    set status = 'leased',
                        stage = 'leased',
                        lease_owner = %s,
                        lease_token = %s,
                        lease_expires_at = now() + (%s * interval '1 second'),
                        attempt_count = task.attempt_count + 1,
                        updated_at = now()
                    from claimable
                    where task.id = claimable.id
                    returning task.*, claimable.status as previous_status
                    """,
                    (list(task_types), limit, worker_id, lease_token, lease_seconds),
                ).fetchall()
                leased_tasks = []
                for row in rows:
                    task = self._to_task(row)
                    self._insert_task_event(
                        cursor,
                        task_id=task["id"],
                        event_type="task.leased",
                        from_status=row["previous_status"],
                        to_status="leased",
                        stage="leased",
                        message="Task claimed by worker lease",
                        details={
                            "worker_id": worker_id,
                            "lease_expires_at": (
                                task["lease_expires_at"].isoformat()
                                if task["lease_expires_at"] is not None
                                else None
                            ),
                        },
                        source="worker",
                        source_id=worker_id,
                    )
                    leased_tasks.append(task)
            connection.commit()
        self._forget_task_list_cache()
        return leased_tasks

    def recover_stale_tasks(
        self,
        task_types: set[str] | None,
        *,
        stale_after_seconds: int,
        worker_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        cutoff_interval_seconds = max(1, stale_after_seconds)
        task_type_filter = "and task_type = any(%s::text[])" if task_types else ""
        params: list[Any] = []
        if task_types:
            params.append(list(task_types))
        params.extend([cutoff_interval_seconds, limit])
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    f"""
                    with stale as (
                      select *,
                             (
                               retryable = true
                               and attempt_count < max_retries
                             ) as can_retry,
                             coalesce(last_heartbeat_at, started_at, updated_at) as heartbeat_at
                      from task_runs
                      where status = 'running'
                        {task_type_filter}
                        and coalesce(last_heartbeat_at, started_at, updated_at)
                          <= now() - (%s::int * interval '1 second')
                      order by coalesce(last_heartbeat_at, started_at, updated_at) asc
                      limit %s::int
                      for update skip locked
                    )
                    update task_runs as task
                    set status = case when stale.can_retry then 'waiting_retry' else 'failed_final' end,
                        stage = case when stale.can_retry then 'waiting_retry' else 'failed' end,
                        next_retry_at = case
                          when stale.can_retry then now() + (least(300.0, 30.0 * power(2.0, greatest(stale.attempt_count, 0))) * interval '1 second')
                          else null
                        end,
                        lease_owner = null,
                        lease_token = null,
                        lease_expires_at = null,
                        finished_at = case when stale.can_retry then null else now() end,
                        error_code = 'TASK_HEARTBEAT_STALE',
                        error_msg = case
                          when stale.can_retry then 'Worker heartbeat stale; retry scheduled'
                          else 'Worker heartbeat stale; task failed final'
                        end,
                        error_details = jsonb_build_object(
                          'recovered_by', %s::text,
                          'stale_after_seconds', %s::int,
                          'detected_at', now(),
                          'previous_heartbeat_at', stale.heartbeat_at,
                          'attempt_count', stale.attempt_count,
                          'max_retries', stale.max_retries
                        ),
                        updated_at = now()
                    from stale
                    where task.id = stale.id
                    returning task.*, stale.status as previous_status, stale.heartbeat_at, stale.can_retry
                    """,
                    (*params, worker_id, cutoff_interval_seconds),
                ).fetchall()
                recovered_tasks = []
                for row in rows:
                    task = self._to_task(row)
                    recovery_status = task["status"]
                    self._insert_task_event(
                        cursor,
                        task_id=task["id"],
                        event_type="task.recovered_stale",
                        from_status=row["previous_status"],
                        to_status=recovery_status,
                        stage=task["stage"],
                        message=task["error_msg"],
                        details={
                            "recovered_by": worker_id,
                            "stale_after_seconds": stale_after_seconds,
                            "previous_heartbeat_at": row["heartbeat_at"].isoformat() if row["heartbeat_at"] else None,
                        },
                        source="worker",
                        source_id=worker_id,
                    )
                    task["recovery_action"] = recovery_status
                    recovered_tasks.append(task)
            connection.commit()
        self._forget_task_list_cache()
        return recovered_tasks

    def list_task_events(self, task_id: str) -> list[dict[str, Any]]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    "select * from task_events where task_id = %s order by created_at desc",
                    (task_id,),
                ).fetchall()
                connection.rollback()
        return [self._to_task_event(row) for row in rows]

    def list_task_events_map(self, task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not task_ids:
            return {}
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    select *
                    from task_events
                    where task_id = any(%s::uuid[])
                    order by task_id asc, created_at desc
                    """,
                    ([UUID(task_id) for task_id in task_ids],),
                ).fetchall()
                connection.rollback()
        events_by_task = {task_id: [] for task_id in task_ids}
        for row in rows:
            event = self._to_task_event(row)
            events_by_task[event["task_id"]].append(event)
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
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = self._insert_task_event(
                    cursor,
                    task_id=task_id,
                    event_type=event_type,
                    from_status=from_status,
                    to_status=to_status,
                    stage=stage,
                    message=message,
                    details=details,
                    source=source,
                    source_id=source_id,
                )
            connection.commit()
        return row

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
        task_id = str(uuid4())
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into task_runs (
                      id, task_type, domain, status, stage, progress_percent, progress_current,
                      progress_total, priority, queue_name, tenant_id, store_id, actor_user_id,
                      actor_role, source_type, target_type, target_id, request_id, idempotency_key,
                      parent_task_id, root_task_id, dependency_state, attempt_count, max_retries,
                      retryable, next_retry_at, lease_owner, lease_token, lease_expires_at,
                      started_at, finished_at, last_heartbeat_at, cancel_requested_at, cancel_reason,
                      error_code, error_msg, error_details, ui_meta, input_payload_ref,
                      output_payload_ref, created_at, updated_at
                    )
                    values (
                      %s, %s, %s, 'queued', 'queued', 0, 0, null, 'medium', %s, %s, %s, %s,
                      %s, 'api', %s, %s, %s, null, null, null, null, 0, 3, true, null, null,
                      null, null, null, null, null, null, null, null, null, null, %s, null,
                      null, now(), now()
                    )
                    """,
                    (
                        task_id,
                        task_type,
                        domain,
                        queue_name,
                        tenant_id,
                        store_id,
                        actor_user_id,
                        actor_role,
                        target_type,
                        target_id,
                        request_id,
                        Jsonb({"label": label, "next_action": next_action}),
                    ),
                )
                self._insert_task_event(
                    cursor,
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
                self._insert_task_event(
                    cursor,
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
            connection.commit()
        self._forget_task_list_cache()
        return self.get_task(task_id)

    def _insert_task_event(self, cursor: Any, **payload: Any) -> dict[str, Any]:
        event_id = str(uuid4())
        row = cursor.execute(
            """
            insert into task_events (
              id, task_id, event_type, from_status, to_status, stage, message, details, source, source_id, created_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            returning *
            """,
            (
                event_id,
                payload["task_id"],
                payload["event_type"],
                payload["from_status"],
                payload["to_status"],
                payload["stage"],
                payload["message"],
                Jsonb(payload["details"]) if payload["details"] is not None else None,
                payload["source"],
                payload["source_id"],
            ),
        ).fetchone()
        return self._to_task_event(row)

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
        created_at: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit_id = str(uuid4())
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                actor_display_name = None
                if actor_user_id:
                    actor_row = cursor.execute(
                        "select username from users where id = %s",
                        (actor_user_id,),
                    ).fetchone()
                    actor_display_name = actor_row["username"] if actor_row else None
                row = cursor.execute(
                    """
                    insert into audit_logs (
                      id, request_id, tenant_id, store_id, actor_type, actor_user_id, actor_role,
                      actor_display_name, source, action, action_label, risk_level, target_type,
                      target_id, target_label, before, after, diff, reason, result, error_code,
                      idempotency_key, task_id, approval_id, metadata, created_at
                    )
                    values (
                      %s, %s, %s, %s, 'user', %s, %s, %s, 'api', %s, %s, %s, %s, %s, %s, %s, %s,
                      null, %s, %s, %s, null, %s, null, %s, %s
                    )
                    returning *
                    """,
                    (
                        audit_id,
                        request_id,
                        tenant_id,
                        store_id,
                        actor_user_id,
                        actor_role,
                        actor_display_name,
                        action,
                        action_label,
                        risk_level,
                        target_type,
                        target_id,
                        target_label,
                        Jsonb(self._normalize_value(before)) if before is not None else None,
                        Jsonb(self._normalize_value(after)) if after is not None else None,
                        reason,
                        result,
                        error_code,
                        task_id,
                        Jsonb(self._normalize_value(metadata)) if metadata is not None else None,
                        created_at or self._now(),
                    ),
                ).fetchone()
            connection.commit()
        return self._to_audit(row)

    def list_audits(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from audit_logs"
        params: list[Any] = []
        if tenant_id is not None:
            query += " where tenant_id = %s"
            params.append(tenant_id)
        query += " order by created_at desc"
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(query, params).fetchall()
                connection.rollback()
        return [self._to_audit(row) for row in rows]

    def count_active_tasks(self, tenant_id: str | None = None) -> int:
        query = """
            select count(*) as count
            from task_runs
            where status in ('queued', 'leased', 'running', 'waiting_retry')
        """
        params: list[Any] = []
        if tenant_id is not None:
            query += " and tenant_id = %s"
            params.append(tenant_id)
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(query, params).fetchone()
                connection.rollback()
        return row["count"]

    def health_counters(self, tenant_id: str | None = None) -> dict[str, int]:
        task_filter = ""
        audit_filter = ""
        params: list[Any] = []
        if tenant_id is not None:
            task_filter = " and tenant_id = %s"
            audit_filter = " where tenant_id = %s"
            params.extend([tenant_id, tenant_id])
        query = f"""
            select
              (
                select count(*)
                from task_runs
                where status in ('queued', 'leased', 'running', 'waiting_retry'){task_filter}
              ) as active_task_count,
              (
                select count(*)
                from audit_logs{audit_filter}
              ) as audit_log_count
        """
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(query, params).fetchone()
                connection.rollback()
        return {
            "active_task_count": row["active_task_count"],
            "audit_log_count": row["audit_log_count"],
        }

    def get_tenant_entitlement(self, tenant_id: str) -> dict[str, Any]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    with selected_tenant as (
                      select
                        t.id as tenant_id,
                        coalesce(
                          ts.plan,
                          case
                            when tenant_plan.plan is not null then t.plan
                            else 'war-room'
                          end
                        ) as plan,
                        coalesce(ts.status, 'active') as subscription_status,
                        ts.trial_ends_at,
                        ts.current_period_ends_at
                      from tenants t
                      left join tenant_subscriptions ts on ts.tenant_id = t.id
                      left join tenant_plan_limits tenant_plan on tenant_plan.plan = t.plan
                      where t.id = %s
                    )
                    select
                      st.tenant_id,
                      st.plan,
                      st.subscription_status,
                      st.trial_ends_at,
                      st.current_period_ends_at,
                      tpl.display_name,
                      tpl.max_users,
                      tpl.max_stores,
                      tpl.max_active_sync_tasks,
                      tpl.max_listings,
                      tpl.autobid_enabled,
                      tpl.sync_enabled
                    from selected_tenant st
                    join tenant_plan_limits tpl on tpl.plan = st.plan
                    """,
                    (tenant_id,),
                ).fetchone()
                connection.rollback()
        if row is None:
            return {
                "tenant_id": tenant_id,
                "plan": "war-room",
                "plan_name": "War Room",
                "subscription_status": "active",
                "trial_ends_at": None,
                "current_period_ends_at": None,
                "limits": {
                    "max_users": 1000,
                    "max_stores": 200,
                    "max_active_sync_tasks": 100,
                    "max_listings": 1000000,
                    "autobid_enabled": True,
                    "sync_enabled": True,
                },
            }
        effective_status = self._effective_subscription_status(
            row["subscription_status"],
            row["trial_ends_at"],
            row["current_period_ends_at"],
        )
        return {
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "plan": row["plan"],
            "plan_name": row["display_name"],
            "subscription_status": effective_status,
            "trial_ends_at": row["trial_ends_at"],
            "current_period_ends_at": row["current_period_ends_at"],
            "limits": {
                "max_users": row["max_users"],
                "max_stores": row["max_stores"],
                "max_active_sync_tasks": row["max_active_sync_tasks"],
                "max_listings": row["max_listings"],
                "autobid_enabled": row["autobid_enabled"],
                "sync_enabled": row["sync_enabled"],
            },
        }

    def get_tenant_usage(self, tenant_id: str) -> dict[str, int]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    select
                      (
                        select count(*)
                        from users
                        where tenant_id = %s
                          and status <> 'disabled'
                      ) as active_users,
                      (
                        select count(*)
                        from stores
                        where tenant_id = %s
                          and status <> 'disabled'
                          and deleted_at is null
                      ) as active_stores,
                      (
                        select count(*)
                        from listings l
                        join stores s on s.id = l.store_id
                        where s.tenant_id = %s
                          and s.deleted_at is null
                      ) as listings,
                      (
                        select count(*)
                        from task_runs
                        where tenant_id = %s
                          and status in ('queued', 'leased', 'running', 'waiting_retry')
                      ) as active_tasks,
                      (
                        select count(*)
                        from task_runs
                        where tenant_id = %s
                          and status in ('queued', 'leased', 'running', 'waiting_retry')
                          and task_type in ('SYNC_STORE_LISTINGS', 'store.sync.full')
                      ) as active_sync_tasks
                    """,
                    (tenant_id, tenant_id, tenant_id, tenant_id, tenant_id),
                ).fetchone()
                connection.rollback()
        return {
            "active_users": row["active_users"],
            "active_stores": row["active_stores"],
            "listings": row["listings"],
            "active_tasks": row["active_tasks"],
            "active_sync_tasks": row["active_sync_tasks"],
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
        current = self.get_tenant_entitlement(tenant_id)
        next_plan = plan or current["plan"]
        next_status = status or current["subscription_status"]
        next_trial_ends_at = (
            trial_ends_at
            if update_trial_ends_at
            else current.get("trial_ends_at")
        )
        next_current_period_ends_at = (
            current_period_ends_at
            if update_current_period_ends_at
            else current.get("current_period_ends_at")
        )
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                subscription_row = cursor.execute(
                    """
                    insert into tenant_subscriptions (
                      tenant_id, plan, status, trial_ends_at, current_period_ends_at,
                      updated_by, created_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, now(), now())
                    on conflict (tenant_id) do update set
                      plan = excluded.plan,
                      status = excluded.status,
                      trial_ends_at = excluded.trial_ends_at,
                      current_period_ends_at = excluded.current_period_ends_at,
                      updated_by = excluded.updated_by,
                      updated_at = now()
                    returning *
                    """,
                    (
                        tenant_id,
                        next_plan,
                        next_status,
                        next_trial_ends_at,
                        next_current_period_ends_at,
                        updated_by,
                    ),
                ).fetchone()
                tenant_row = cursor.execute(
                    """
                    update tenants
                    set plan = %s, updated_at = now()
                    where id = %s
                    returning *
                    """,
                    (next_plan, tenant_id),
                ).fetchone()
                users = cursor.execute(
                    "select id, username from users where tenant_id = %s",
                    (tenant_id,),
                ).fetchall()
            connection.commit()
        with self._cache_lock:
            for user in users:
                self._auth_record_cache.pop(user["username"], None)
                self._password_verify_cache.pop(user["username"], None)
        return {
            "tenant": self._to_tenant(tenant_row),
            "subscription": self._to_subscription(subscription_row),
        }

    def update_tenant_status(
        self,
        tenant_id: str,
        *,
        status: str,
    ) -> dict[str, Any]:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                tenant_row = cursor.execute(
                    """
                    update tenants
                    set status = %s, updated_at = now()
                    where id = %s
                    returning *
                    """,
                    (status, tenant_id),
                ).fetchone()
                users = cursor.execute(
                    "select id, username from users where tenant_id = %s",
                    (tenant_id,),
                ).fetchall()
            connection.commit()
        with self._cache_lock:
            for user in users:
                self._recent_session_cache.pop(self._normalize_value(user["id"]), None)
                self._auth_record_cache.pop(user["username"], None)
                self._password_verify_cache.pop(user["username"], None)
        return self._to_tenant(tenant_row)

    @staticmethod
    def _to_tenant(row: Any) -> dict[str, Any]:
        return {
            "id": DatabaseAppState._normalize_value(row["id"]),
            "slug": row["slug"],
            "name": row["name"],
            "status": row["status"],
            "plan": row["plan"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _to_subscription(row: Any) -> dict[str, Any]:
        return {
            "tenant_id": DatabaseAppState._normalize_value(row["tenant_id"]),
            "plan": row["plan"],
            "status": row["status"],
            "trial_ends_at": row["trial_ends_at"],
            "current_period_ends_at": row["current_period_ends_at"],
            "updated_by": DatabaseAppState._normalize_value(row["updated_by"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _to_user(row: Any) -> dict[str, Any]:
        user = {
            "id": DatabaseAppState._normalize_value(row["id"]),
            "tenant_id": DatabaseAppState._normalize_value(row["tenant_id"]),
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "status": row["status"],
            "expires_at": row["expires_at"],
            "force_password_reset": row["force_password_reset"],
            "last_login_at": row["last_login_at"],
            "subscription_status": DatabaseAppState._row_get(row, "subscription_status", "active"),
            "tenant_status": DatabaseAppState._row_get(row, "tenant_status", "active"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "version": row["version"],
        }
        try:
            feature_flags = row["feature_flags"]
        except Exception:
            feature_flags = None
        if feature_flags is not None:
            user["feature_flags"] = DatabaseAppState._decode_json(feature_flags)
        return user

    def _to_system_setting(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "setting_key": row["setting_key"],
            "value": self._decode_json(row["value_json"]),
            "value_type": row["value_type"],
            "description": row["description"],
            "updated_by": self._normalize_value(row["updated_by"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "version": row["version"],
        }

    @staticmethod
    def _store_select_sql() -> str:
        return """
            select
              s.id, s.tenant_id, s.name, s.platform, s.status, s.api_key_status, s.last_synced_at,
              s.created_at, s.updated_at, s.version,
              sc.masked_api_key, sc.credential_status,
              sfp.bidding_enabled, sfp.listing_enabled, sfp.sync_enabled
            from stores s
            left join store_credentials sc on sc.store_id = s.id
            left join store_feature_policies sfp on sfp.store_id = s.id
        """

    def _to_store(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "name": row["name"],
            "platform": row["platform"],
            "status": row["status"],
            "api_key_status": row["api_key_status"],
            "credential_status": row["credential_status"],
            "masked_api_key": row["masked_api_key"],
            "last_synced_at": row["last_synced_at"],
            "feature_policies": {
                "bidding_enabled": bool(row["bidding_enabled"]),
                "listing_enabled": bool(row["listing_enabled"]),
                "sync_enabled": bool(row["sync_enabled"]),
            },
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "version": row["version"],
        }

    def _to_bidding_store_runtime(self, row: Any) -> dict[str, Any]:
        return {
            "store_id": self._normalize_value(row["store_id"]),
            "is_running": bool(row["is_running"]),
            "last_started_at": row["last_started_at"],
            "last_stopped_at": row["last_stopped_at"],
            "last_manual_cycle_at": row["last_manual_cycle_at"],
            "last_worker_cycle_at": row["last_worker_cycle_at"],
            "last_cycle_summary": self._decode_json(row["last_cycle_summary"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_bidding_rule(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "sku": row["sku"],
            "listing_id": row["listing_id"],
            "floor_price": float(row["floor_price"]) if row["floor_price"] is not None else None,
            "strategy_type": row["strategy_type"],
            "is_active": row["is_active"],
            "next_check_at": row.get("next_check_at"),
            "buybox_fetch_fail_count": int(row.get("buybox_fetch_fail_count") or 0),
            "buybox_last_error": row.get("buybox_last_error") or "",
            "buybox_last_success_at": row.get("buybox_last_success_at"),
            "buybox_next_retry_at": row.get("buybox_next_retry_at"),
            "buybox_status": row.get("buybox_status") or "idle",
            "repricing_blocked_reason": row.get("repricing_blocked_reason") or "",
            "last_action": row.get("last_action") or "",
            "last_reprice_at": row.get("last_reprice_at"),
            "last_suggested_price": float(row["last_suggested_price"]) if row.get("last_suggested_price") is not None else None,
            "last_applied_price": float(row["last_applied_price"]) if row.get("last_applied_price") is not None else None,
            "last_buybox_price": float(row["last_buybox_price"]) if row.get("last_buybox_price") is not None else None,
            "last_next_offer_price": float(row["last_next_offer_price"]) if row.get("last_next_offer_price") is not None else None,
            "last_cycle_dry_run": bool(row.get("last_cycle_dry_run", True)),
            "last_cycle_error": row.get("last_cycle_error") or "",
            "last_decision": self._decode_json(row.get("last_decision")),
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_listing(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "external_listing_id": row["external_listing_id"],
            "platform_product_id": row["platform_product_id"],
            "sku": row["sku"],
            "title": row["title"],
            "platform_price": float(row["platform_price"]) if row["platform_price"] is not None else None,
            "buybox_price": float(row["buybox_price"]) if row.get("buybox_price") is not None else None,
            "stock_quantity": row["stock_quantity"],
            "currency": row["currency"],
            "sync_status": row["sync_status"],
            "raw_payload": self._decode_json(row["raw_payload"]),
            "last_synced_at": row["last_synced_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_library_product(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "platform": row["platform"],
            "external_product_id": row["external_product_id"],
            "title": row["title"],
            "brand": row["brand"],
            "category": row["category"],
            "fact_status": row["fact_status"],
            "merchant_packaged_weight_raw": row["merchant_packaged_weight_raw"],
            "merchant_packaged_dimensions_raw": row["merchant_packaged_dimensions_raw"],
            "cbs_package_weight_raw": row["cbs_package_weight_raw"],
            "cbs_package_dimensions_raw": row["cbs_package_dimensions_raw"],
            "consolidated_packaged_dimensions_raw": row["consolidated_packaged_dimensions_raw"],
            "raw_payload": self._decode_json(row["raw_payload"]),
            "last_refreshed_at": row["last_refreshed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_selection_product(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "platform": row["platform"],
            "platform_product_id": row["platform_product_id"],
            "image_url": row["image_url"],
            "title": row["title"],
            "main_category": row["main_category"],
            "category_level1": row["category_level1"],
            "category_level2": row["category_level2"],
            "category_level3": row["category_level3"],
            "brand": row["brand"],
            "currency": row["currency"],
            "current_price": float(row["current_price"]) if row["current_price"] is not None else None,
            "rating": float(row["rating"]) if row["rating"] is not None else None,
            "total_review_count": row["total_review_count"],
            "rating_5_count": row["rating_5_count"],
            "rating_4_count": row["rating_4_count"],
            "rating_3_count": row["rating_3_count"],
            "rating_2_count": row["rating_2_count"],
            "rating_1_count": row["rating_1_count"],
            "latest_review_at": row["latest_review_at"],
            "stock_status": row["stock_status"],
            "offer_count": row["offer_count"],
            "current_snapshot_week": row["current_snapshot_week"],
            "status": row["status"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_tenant_product_guardrail(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "product_id": self._normalize_value(row["product_id"]),
            "protected_floor_price": float(row["protected_floor_price"]),
            "status": row["status"],
            "linked_listing_id": self._normalize_value(row["linked_listing_id"]),
            "linked_bidding_rule_id": self._normalize_value(row["linked_bidding_rule_id"]),
            "autobid_sync_status": row["autobid_sync_status"],
            "source": row["source"],
            "last_synced_at": row["last_synced_at"],
            "last_error_code": row["last_error_code"],
            "last_error_message": row["last_error_message"],
            "created_by": self._normalize_value(row["created_by"]),
            "updated_by": self._normalize_value(row["updated_by"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_extension_auth_token(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "token_hash": row["token_hash"],
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "user_id": self._normalize_value(row["user_id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "expires_at": row["expires_at"],
            "last_seen_at": row["last_seen_at"],
            "created_at": row["created_at"],
        }

    def _to_listing_job(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "product_id": self._normalize_value(row["product_id"]),
            "guardrail_id": self._normalize_value(row["guardrail_id"]),
            "entry_task_id": self._normalize_value(row["entry_task_id"]),
            "processing_task_id": self._normalize_value(row["processing_task_id"]),
            "platform": row["platform"],
            "source": row["source"],
            "source_ref": row["source_ref"],
            "title": row["title"],
            "status": row["status"],
            "stage": row["stage"],
            "note": row["note"],
            "raw_payload": self._decode_json(row["raw_payload"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_order(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "external_order_id": row["external_order_id"],
            "order_number": row["order_number"],
            "status": row["status"],
            "fulfillment_status": row["fulfillment_status"],
            "total_amount": float(row["total_amount"]) if row["total_amount"] is not None else None,
            "currency": row["currency"],
            "placed_at": row["placed_at"],
            "last_synced_at": row["last_synced_at"],
            "raw_payload": self._decode_json(row["raw_payload"]),
            "item_count": int(self._row_get(row, "item_count", 0) or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_order_item(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "order_id": self._normalize_value(row["order_id"]),
            "external_order_item_id": row["external_order_item_id"],
            "sku": row["sku"],
            "title": row["title"],
            "quantity": row["quantity"],
            "unit_price": float(row["unit_price"]) if row["unit_price"] is not None else None,
            "status": row["status"],
            "raw_payload": self._decode_json(row["raw_payload"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_order_event(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "order_id": self._normalize_value(row["order_id"]),
            "event_type": row["event_type"],
            "status": row["status"],
            "message": row["message"],
            "payload": self._decode_json(row["payload"]),
            "occurred_at": row["occurred_at"],
            "created_at": row["created_at"],
        }

    def _to_task(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "task_type": row["task_type"],
            "domain": row["domain"],
            "status": row["status"],
            "stage": row["stage"],
            "progress_percent": float(row["progress_percent"]) if row["progress_percent"] is not None else None,
            "progress_current": row["progress_current"],
            "progress_total": row["progress_total"],
            "priority": row["priority"],
            "queue_name": row["queue_name"],
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "actor_user_id": self._normalize_value(row["actor_user_id"]),
            "actor_role": row["actor_role"],
            "source_type": row["source_type"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "request_id": row["request_id"],
            "idempotency_key": row["idempotency_key"],
            "parent_task_id": self._normalize_value(row["parent_task_id"]),
            "root_task_id": self._normalize_value(row["root_task_id"]),
            "dependency_state": row["dependency_state"],
            "attempt_count": row["attempt_count"],
            "max_retries": row["max_retries"],
            "retryable": row["retryable"],
            "next_retry_at": row["next_retry_at"],
            "lease_owner": row["lease_owner"],
            "lease_token": row["lease_token"],
            "lease_expires_at": row["lease_expires_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "cancel_requested_at": row["cancel_requested_at"],
            "cancel_reason": row["cancel_reason"],
            "error_code": row["error_code"],
            "error_msg": row["error_msg"],
            "error_details": self._decode_json(row["error_details"]),
            "ui_meta": self._decode_json(row["ui_meta"]),
            "input_payload_ref": row["input_payload_ref"],
            "output_payload_ref": row["output_payload_ref"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _to_task_event(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "task_id": self._normalize_value(row["task_id"]),
            "event_type": row["event_type"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
            "stage": row["stage"],
            "message": row["message"],
            "details": self._decode_json(row["details"]),
            "source": row["source"],
            "source_id": row["source_id"],
            "created_at": row["created_at"],
        }

    def _to_audit(self, row: Any) -> dict[str, Any]:
        return {
            "id": self._normalize_value(row["id"]),
            "request_id": row["request_id"],
            "tenant_id": self._normalize_value(row["tenant_id"]),
            "store_id": self._normalize_value(row["store_id"]),
            "actor_type": row["actor_type"],
            "actor_user_id": self._normalize_value(row["actor_user_id"]),
            "actor_role": row["actor_role"],
            "actor_display_name": row["actor_display_name"],
            "impersonator_user_id": self._normalize_value(row.get("impersonator_user_id")),
            "session_id": self._normalize_value(row.get("session_id")),
            "source": row["source"],
            "ip": row.get("ip"),
            "user_agent": row.get("user_agent"),
            "action": row["action"],
            "action_label": row["action_label"],
            "risk_level": row["risk_level"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "target_label": row["target_label"],
            "before": self._decode_json(row["before"]),
            "after": self._decode_json(row["after"]),
            "diff": self._decode_json(row.get("diff")),
            "reason": row["reason"],
            "result": row["result"],
            "error_code": row["error_code"],
            "idempotency_key": row.get("idempotency_key"),
            "task_id": self._normalize_value(row["task_id"]),
            "approval_id": self._normalize_value(row.get("approval_id")),
            "metadata": self._decode_json(row.get("metadata")),
            "created_at": row["created_at"],
        }
