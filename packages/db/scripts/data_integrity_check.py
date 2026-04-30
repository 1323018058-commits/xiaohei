from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import OperationalError


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.platform.db.session import get_db_session  # noqa: E402
from src.platform.settings.base import settings  # noqa: E402


REQUIRED_TABLES = {
    "tenants",
    "tenant_plan_limits",
    "tenant_subscriptions",
    "users",
    "user_passwords",
    "auth_sessions",
    "user_feature_flags",
    "system_settings",
    "audit_logs",
    "task_definitions",
    "stores",
    "store_credentials",
    "store_feature_policies",
    "task_runs",
    "task_events",
    "listings",
    "bidding_rules",
    "orders",
    "order_items",
    "order_events",
}
DEFAULT_TEST_TOKENS = (
    "smoke",
    "guardrail",
    "slice",
    "debug",
    "mock",
    "self-service",
    "self service",
)
READ_QUERY_ATTEMPTS = 2


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_default(value: Any) -> str | float:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _run_read_query(executor: Any) -> Any:
    for attempt in range(READ_QUERY_ATTEMPTS):
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    return executor(cursor)
        except OperationalError:
            if attempt + 1 >= READ_QUERY_ATTEMPTS:
                raise


def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    row = _run_read_query(lambda cursor: cursor.execute(sql, params).fetchone())
    return dict(row) if row else {}


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    rows = _run_read_query(lambda cursor: cursor.execute(sql, params).fetchall())
    return [dict(row) for row in rows]


def check_database() -> dict[str, Any]:
    if not settings.database_url:
        return {
            "name": "database",
            "status": "fail",
            "message": "XH_DATABASE_URL is not configured",
        }
    row = fetch_one("select now() as checked_at, current_database() as database_name")
    return {
        "name": "database",
        "status": "ok",
        "message": "database connection ok",
        "details": row,
    }


def check_required_tables() -> dict[str, Any]:
    rows = fetch_all(
        """
        select table_name
        from information_schema.tables
        where table_schema = 'public'
          and table_type = 'BASE TABLE'
        """
    )
    existing = {row["table_name"] for row in rows}
    missing = sorted(REQUIRED_TABLES - existing)
    return {
        "name": "required_tables",
        "status": "fail" if missing else "ok",
        "message": "required tables are missing" if missing else "required tables exist",
        "missing": missing,
        "table_count": len(existing),
    }


def check_orphan_references() -> dict[str, Any]:
    queries = [
        (
            "tenant_subscriptions_without_tenant",
            """
            select count(*) as count
            from tenant_subscriptions ts
            left join tenants t on t.id = ts.tenant_id
            where t.id is null
            """,
        ),
        (
            "tenant_subscriptions_without_plan",
            """
            select count(*) as count
            from tenant_subscriptions ts
            left join tenant_plan_limits tpl on tpl.plan = ts.plan
            where tpl.plan is null
            """,
        ),
        (
            "users_without_tenant",
            """
            select count(*) as count
            from users u
            left join tenants t on t.id = u.tenant_id
            where t.id is null
            """,
        ),
        (
            "user_passwords_without_user",
            """
            select count(*) as count
            from user_passwords p
            left join users u on u.id = p.user_id
            where u.id is null
            """,
        ),
        (
            "feature_flags_without_user",
            """
            select count(*) as count
            from user_feature_flags f
            left join users u on u.id = f.user_id
            where u.id is null
            """,
        ),
        (
            "stores_without_tenant",
            """
            select count(*) as count
            from stores s
            left join tenants t on t.id = s.tenant_id
            where t.id is null
            """,
        ),
        (
            "store_credentials_without_store",
            """
            select count(*) as count
            from store_credentials c
            left join stores s on s.id = c.store_id
            where s.id is null
            """,
        ),
        (
            "store_policies_without_store",
            """
            select count(*) as count
            from store_feature_policies p
            left join stores s on s.id = p.store_id
            where s.id is null
            """,
        ),
        (
            "listings_without_store",
            """
            select count(*) as count
            from listings l
            left join stores s on s.id = l.store_id
            where s.id is null
            """,
        ),
        (
            "bidding_rules_without_store",
            """
            select count(*) as count
            from bidding_rules b
            left join stores s on s.id = b.store_id
            where s.id is null
            """,
        ),
        (
            "orders_without_store",
            """
            select count(*) as count
            from orders o
            left join stores s on s.id = o.store_id
            where s.id is null
            """,
        ),
        (
            "orders_without_tenant",
            """
            select count(*) as count
            from orders o
            left join tenants t on t.id = o.tenant_id
            where t.id is null
            """,
        ),
        (
            "order_items_without_order",
            """
            select count(*) as count
            from order_items oi
            left join orders o on o.id = oi.order_id
            where o.id is null
            """,
        ),
        (
            "order_events_without_order",
            """
            select count(*) as count
            from order_events oe
            left join orders o on o.id = oe.order_id
            where o.id is null
            """,
        ),
        (
            "task_runs_without_tenant",
            """
            select count(*) as count
            from task_runs tr
            left join tenants t on t.id = tr.tenant_id
            where tr.tenant_id is not null and t.id is null
            """,
        ),
        (
            "task_runs_without_store",
            """
            select count(*) as count
            from task_runs tr
            left join stores s on s.id = tr.store_id
            where tr.store_id is not null and s.id is null
            """,
        ),
        (
            "task_events_without_task",
            """
            select count(*) as count
            from task_events te
            left join task_runs tr on tr.id = te.task_id
            where tr.id is null
            """,
        ),
        (
            "audit_logs_without_task",
            """
            select count(*) as count
            from audit_logs al
            left join task_runs tr on tr.id = al.task_id
            where al.task_id is not null and tr.id is null
            """,
        ),
        (
            "audit_logs_without_store",
            """
            select count(*) as count
            from audit_logs al
            left join stores s on s.id = al.store_id
            where al.store_id is not null and s.id is null
            """,
        ),
        (
            "audit_logs_without_actor",
            """
            select count(*) as count
            from audit_logs al
            left join users u on u.id = al.actor_user_id
            where al.actor_user_id is not null and u.id is null
            """,
        ),
        (
            "child_tasks_without_parent",
            """
            select count(*) as count
            from task_runs child
            left join task_runs parent on parent.id = child.parent_task_id
            where child.parent_task_id is not null and parent.id is null
            """,
        ),
        (
            "tasks_without_root",
            """
            select count(*) as count
            from task_runs child
            left join task_runs root on root.id = child.root_task_id
            where child.root_task_id is not null and root.id is null
            """,
        ),
    ]
    counts = {name: int(fetch_one(query).get("count") or 0) for name, query in queries}
    total = sum(counts.values())
    return {
        "name": "orphan_references",
        "status": "fail" if total else "ok",
        "message": "orphan references detected" if total else "no orphan references detected",
        "total": total,
        "counts": counts,
    }


def check_takealot_only() -> dict[str, Any]:
    row = fetch_one(
        """
        select count(*) as count
        from stores
        where platform <> 'takealot'
        """
    )
    count = int(row.get("count") or 0)
    return {
        "name": "takealot_only",
        "status": "fail" if count else "ok",
        "message": "non-Takealot stores detected" if count else "all stores are Takealot",
        "non_takealot_count": count,
    }


def check_pricing_bounds() -> dict[str, Any]:
    queries = [
        ("bidding_floor_nonpositive", "select count(*) as count from bidding_rules where floor_price <= 0"),
        (
            "bidding_ceiling_below_floor",
            "select count(*) as count from bidding_rules where ceiling_price is not null and ceiling_price < floor_price",
        ),
        (
            "listing_negative_price",
            "select count(*) as count from listings where platform_price is not null and platform_price < 0",
        ),
        (
            "listing_negative_stock",
            "select count(*) as count from listings where stock_quantity is not null and stock_quantity < 0",
        ),
        (
            "order_negative_total",
            "select count(*) as count from orders where total_amount is not null and total_amount < 0",
        ),
        (
            "order_item_nonpositive_quantity",
            "select count(*) as count from order_items where quantity <= 0",
        ),
        (
            "order_item_negative_price",
            "select count(*) as count from order_items where unit_price is not null and unit_price < 0",
        ),
    ]
    counts = {name: int(fetch_one(query).get("count") or 0) for name, query in queries}
    total = sum(counts.values())
    return {
        "name": "pricing_and_listing_bounds",
        "status": "fail" if total else "ok",
        "message": "invalid pricing or listing bounds detected" if total else "pricing and listing bounds are valid",
        "total": total,
        "counts": counts,
    }


def is_test_artifact(row: dict[str, Any], tokens: tuple[str, ...]) -> bool:
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("name", "credential_status", "masked_api_key")
    ).lower()
    return any(token in haystack for token in tokens)


def filter_test_artifacts(
    rows: list[dict[str, Any]],
    *,
    include_test_artifacts: bool,
    tokens: tuple[str, ...],
) -> list[dict[str, Any]]:
    if include_test_artifacts:
        return rows
    return [row for row in rows if not is_test_artifact(row, tokens)]


def check_active_store_credentials(args: argparse.Namespace) -> dict[str, Any]:
    rows = fetch_all(
        """
        select
          s.id,
          s.name,
          s.status,
          sc.credential_status,
          sc.masked_api_key,
          case
            when sc.api_key_encrypted like '-----BEGIN PGP MESSAGE-----%%' then true
            else false
          end as pgp_encrypted
        from stores s
        left join store_credentials sc on sc.store_id = s.id
        where s.status = 'active'
          and s.deleted_at is null
          and s.platform = 'takealot'
        order by s.created_at desc
        """
    )
    production_rows = filter_test_artifacts(
        rows,
        include_test_artifacts=args.include_test_artifacts,
        tokens=tuple(args.test_artifact_tokens),
    )
    missing = [row for row in production_rows if row.get("credential_status") is None]
    invalid_status = [
        row
        for row in production_rows
        if row.get("credential_status") is not None
        and row.get("credential_status") not in {"valid", "configured", "validating"}
    ]
    non_pgp_active = [
        row
        for row in production_rows
        if row.get("credential_status") is not None and not bool(row.get("pgp_encrypted"))
    ]
    warn_count = len(missing) + len(invalid_status) + len(non_pgp_active)
    return {
        "name": "active_store_credentials",
        "status": "warn" if warn_count else "ok",
        "message": "active store credentials need operator review" if warn_count else "active store credentials look usable",
        "active_store_count": len(production_rows),
        "excluded_test_artifact_count": len(rows) - len(production_rows),
        "missing_credential_count": len(missing),
        "invalid_status_count": len(invalid_status),
        "non_pgp_active_count": len(non_pgp_active),
        "sample": [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "credential_status": row.get("credential_status"),
                "pgp_encrypted": bool(row.get("pgp_encrypted")),
            }
            for row in (missing + invalid_status + non_pgp_active)[:5]
        ],
    }


def check_recent_session_hotspots() -> dict[str, Any]:
    rows = fetch_all(
        """
        select user_id, count(*) as active_session_count
        from auth_sessions
        where status = 'active'
          and expires_at > now()
          and created_at >= now() - interval '5 minutes'
        group by user_id
        having count(*) > 1
        order by count(*) desc
        limit 10
        """
    )
    return {
        "name": "recent_session_hotspots",
        "status": "warn" if rows else "ok",
        "message": "recent duplicate active sessions detected" if rows else "no recent session hotspot detected",
        "hotspot_user_count": len(rows),
        "sample": [
            {
                "user_id": str(row["user_id"]),
                "active_session_count": int(row["active_session_count"]),
            }
            for row in rows
        ],
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    checks = [check_database()]
    if checks[0]["status"] == "fail":
        hard_failures = checks
        return {
            "passed": False,
            "strict": args.strict,
            "generated_at": utc_now().isoformat(),
            "checks": checks,
            "summary": {"ok": 0, "warn": 0, "fail": len(hard_failures)},
        }

    required_tables = check_required_tables()
    checks.append(required_tables)
    if required_tables["status"] == "ok":
        checks.extend(
            [
                check_orphan_references(),
                check_takealot_only(),
                check_pricing_bounds(),
                check_active_store_credentials(args),
                check_recent_session_hotspots(),
            ]
        )

    hard_failures = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warn"]
    passed = not hard_failures and (not args.strict or not warnings)
    return {
        "passed": passed,
        "strict": args.strict,
        "generated_at": utc_now().isoformat(),
        "checks": checks,
        "summary": {
            "ok": sum(1 for check in checks if check["status"] == "ok"),
            "warn": len(warnings),
            "fail": len(hard_failures),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Xiaohei ERP data integrity invariants")
    parser.add_argument("--output", default=os.getenv("XH_DATA_INTEGRITY_OUTPUT"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--include-test-artifacts", action="store_true")
    parser.add_argument("--test-artifact-tokens", nargs="*", default=list(DEFAULT_TEST_TOKENS))
    parser.add_argument("--no-fail", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args)
    output = json.dumps(report, ensure_ascii=False, indent=2, default=json_default)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if not report["passed"] and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
