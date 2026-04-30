from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
REPORT_DIR = ROOT / "reports" / "db"
CONFIRM_TOKEN = "DELETE_SMOKE_ARTIFACTS"

sys.path.insert(0, str(API_ROOT))

from src.platform.db.session import get_db_session  # noqa: E402


CANDIDATE_WHERE = """
    s.name like 'Smoke Takealot %%'
    or s.name like 'Guardrail Quota Store %%'
    or s.name like 'Extension Guardrail %%'
    or s.name like 'Self Service Store %%'
    or s.name like 'Smoke Onboarding Store %%'
    or s.name like 'Onboarding Store %%'
    or s.name like 'Guardrail Store %%'
    or s.name = 'Takealot Real Sync Smoke'
    or s.name like 'Slice4 Ozon %%'
    or s.name in ('Takealot Main', 'Takealot Sandbox')
"""

RELATED_CTE = f"""
with candidate_stores as (
  select s.id, s.tenant_id, s.name, s.status, s.deleted_at, s.created_at
  from stores s
  where {CANDIDATE_WHERE}
),
candidate_task_runs as (
  select tr.id
  from task_runs tr
  where tr.store_id in (select id from candidate_stores)
),
candidate_orders as (
  select o.id
  from orders o
  where o.store_id in (select id from candidate_stores)
),
candidate_guardrails as (
  select g.id
  from tenant_product_guardrails g
  where g.store_id in (select id from candidate_stores)
)
"""

COUNT_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "stores",
        RELATED_CTE + "select count(*) as count from candidate_stores",
    ),
    (
        "store_credentials",
        RELATED_CTE
        + """
          select count(*) as count
          from store_credentials
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "store_feature_policies",
        RELATED_CTE
        + """
          select count(*) as count
          from store_feature_policies
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "listings",
        RELATED_CTE
        + """
          select count(*) as count
          from listings
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "bidding_rules",
        RELATED_CTE
        + """
          select count(*) as count
          from bidding_rules
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "orders",
        RELATED_CTE
        + """
          select count(*) as count
          from orders
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "order_items",
        RELATED_CTE
        + """
          select count(*) as count
          from order_items
          where order_id in (select id from candidate_orders)
        """,
    ),
    (
        "order_events",
        RELATED_CTE
        + """
          select count(*) as count
          from order_events
          where order_id in (select id from candidate_orders)
        """,
    ),
    (
        "task_runs",
        RELATED_CTE
        + """
          select count(*) as count
          from task_runs
          where id in (select id from candidate_task_runs)
        """,
    ),
    (
        "task_events",
        RELATED_CTE
        + """
          select count(*) as count
          from task_events
          where task_id in (select id from candidate_task_runs)
        """,
    ),
    (
        "audit_logs",
        RELATED_CTE
        + """
          select count(*) as count
          from audit_logs
          where store_id in (select id from candidate_stores)
             or task_id in (select id from candidate_task_runs)
             or (
               target_type = 'store'
               and target_id in (select id::text from candidate_stores)
             )
             or target_label in (select name from candidate_stores)
        """,
    ),
    (
        "tenant_product_guardrails",
        RELATED_CTE
        + """
          select count(*) as count
          from tenant_product_guardrails
          where id in (select id from candidate_guardrails)
        """,
    ),
    (
        "extension_auth_tokens",
        RELATED_CTE
        + """
          select count(*) as count
          from extension_auth_tokens
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "listing_jobs",
        RELATED_CTE
        + """
          select count(*) as count
          from listing_jobs
          where store_id in (select id from candidate_stores)
             or guardrail_id in (select id from candidate_guardrails)
             or entry_task_id in (select id from candidate_task_runs)
             or processing_task_id in (select id from candidate_task_runs)
        """,
    ),
)

DELETE_STATEMENTS: tuple[tuple[str, str], ...] = (
    (
        "listing_jobs",
        RELATED_CTE
        + """
          delete from listing_jobs
          where store_id in (select id from candidate_stores)
             or guardrail_id in (select id from candidate_guardrails)
             or entry_task_id in (select id from candidate_task_runs)
             or processing_task_id in (select id from candidate_task_runs)
        """,
    ),
    (
        "extension_auth_tokens",
        RELATED_CTE
        + """
          delete from extension_auth_tokens
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "audit_logs",
        RELATED_CTE
        + """
          delete from audit_logs
          where store_id in (select id from candidate_stores)
             or task_id in (select id from candidate_task_runs)
             or (
               target_type = 'store'
               and target_id in (select id::text from candidate_stores)
             )
             or target_label in (select name from candidate_stores)
        """,
    ),
    (
        "task_events",
        RELATED_CTE
        + """
          delete from task_events
          where task_id in (select id from candidate_task_runs)
        """,
    ),
    (
        "tenant_product_guardrails",
        RELATED_CTE
        + """
          delete from tenant_product_guardrails
          where id in (select id from candidate_guardrails)
        """,
    ),
    (
        "order_events",
        RELATED_CTE
        + """
          delete from order_events
          where order_id in (select id from candidate_orders)
        """,
    ),
    (
        "order_items",
        RELATED_CTE
        + """
          delete from order_items
          where order_id in (select id from candidate_orders)
        """,
    ),
    (
        "orders",
        RELATED_CTE
        + """
          delete from orders
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "bidding_rules",
        RELATED_CTE
        + """
          delete from bidding_rules
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "listings",
        RELATED_CTE
        + """
          delete from listings
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "store_feature_policies",
        RELATED_CTE
        + """
          delete from store_feature_policies
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "store_credentials",
        RELATED_CTE
        + """
          delete from store_credentials
          where store_id in (select id from candidate_stores)
        """,
    ),
    (
        "task_runs",
        RELATED_CTE
        + """
          delete from task_runs
          where id in (select id from candidate_task_runs)
        """,
    ),
    (
        "stores",
        RELATED_CTE
        + """
          delete from stores
          where id in (select id from candidate_stores)
        """,
    ),
)


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or execute cleanup for smoke/test stores and their dependent records."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete candidate records. Omit for dry-run.",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required with --execute. Must equal {CONFIRM_TOKEN}.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(REPORT_DIR),
        help="Directory where the JSON cleanup report is written.",
    )
    return parser.parse_args()


def fetch_candidate_stores(cursor: Any) -> list[dict[str, Any]]:
    rows = cursor.execute(
        f"""
        select
          s.id::text as id,
          s.tenant_id::text as tenant_id,
          s.name,
          s.status,
          s.api_key_status,
          s.deleted_at,
          s.created_at
        from stores s
        where {CANDIDATE_WHERE}
        order by s.created_at desc, s.name asc
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_counts(cursor: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name, query in COUNT_QUERIES:
        row = cursor.execute(query).fetchone()
        counts[table_name] = int((row or {}).get("count") or 0)
    return counts


def execute_deletes(cursor: Any) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for table_name, query in DELETE_STATEMENTS:
        result = cursor.execute(query)
        deleted[table_name] = int(result.rowcount if result.rowcount is not None else 0)
    return deleted


def write_report(report_dir: Path, payload: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    mode = "execute" if payload["execute"] else "dry_run"
    path = report_dir / f"smoke_cleanup_{mode}_{timestamp}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )
    return path


def main() -> int:
    args = parse_args()
    if args.execute and args.confirm != CONFIRM_TOKEN:
        print(f"Refusing to delete. Re-run with --execute --confirm {CONFIRM_TOKEN}.")
        return 2

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            candidates = fetch_candidate_stores(cursor)
            before_counts = fetch_counts(cursor)
            deleted_counts: dict[str, int] = {}
            if args.execute:
                deleted_counts = execute_deletes(cursor)
                after_counts = fetch_counts(cursor)
                connection.commit()
            else:
                after_counts = before_counts
                connection.rollback()

    report = {
        "execute": bool(args.execute),
        "candidate_prefixes": [
            "Smoke Takealot ",
            "Guardrail Quota Store ",
            "Extension Guardrail ",
            "Self Service Store ",
            "Smoke Onboarding Store ",
            "Onboarding Store ",
            "Guardrail Store ",
            "Takealot Real Sync Smoke",
            "Slice4 Ozon ",
            "Takealot Main",
            "Takealot Sandbox",
        ],
        "candidate_store_count": len(candidates),
        "candidate_stores": candidates,
        "before_counts": before_counts,
        "deleted_counts": deleted_counts,
        "after_counts": after_counts,
    }
    report_path = write_report(Path(args.report_dir), report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=json_default))
    print(f"Report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
