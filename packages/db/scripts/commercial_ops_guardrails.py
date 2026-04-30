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


FAILING_SYNC_STATUSES = {
    "failed",
    "partial",
    "failed_retryable",
    "failed_final",
    "dead_letter",
    "manual_intervention",
    "timed_out",
    "quarantined",
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
TEST_ARTIFACT_NESTED_KEYS = (
    "label",
    "store_name",
    "tenant_slug",
    "tenant_name",
    "username",
    "email",
)
READ_QUERY_ATTEMPTS = 2


def json_default(value: Any) -> str | float:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def latest_json_report(directory: Path, pattern: str) -> tuple[Path | None, dict[str, Any] | None]:
    candidates = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return None, None
    path = candidates[0]
    return path, json.loads(path.read_text(encoding="utf-8"))


def report_age_hours(report: dict[str, Any] | None) -> float | None:
    if not report:
        return None
    finished_at = parse_iso_datetime(report.get("finished_at"))
    if finished_at is None:
        return None
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)
    return (utc_now() - finished_at.astimezone(UTC)).total_seconds() / 3600


def evaluate_execution_report(
    *,
    name: str,
    path: Path | None,
    report: dict[str, Any] | None,
    max_age_hours: float,
    required_users: int | None = None,
    enabled: bool = True,
    disabled_message: str | None = None,
) -> dict[str, Any]:
    if not enabled:
        return {
            "name": name,
            "status": "ok",
            "message": disabled_message or f"{name} check is not required in the current environment",
            "path": str(path.relative_to(ROOT)) if path is not None else None,
            "metrics": None,
            "not_applicable": True,
        }

    if not report or path is None:
        return {
            "name": name,
            "status": "fail",
            "message": f"No {name} report found",
            "path": None,
        }

    age_hours = report_age_hours(report)
    messages: list[str] = []
    passed = bool(report.get("passed"))
    if not passed:
        messages.append("report did not pass")
    if age_hours is None or age_hours > max_age_hours:
        messages.append(f"report is older than {max_age_hours:g}h")
    if required_users is not None and int(report.get("users") or 0) < required_users:
        messages.append(f"users below required {required_users}")

    return {
        "name": name,
        "status": "fail" if messages else "ok",
        "message": "; ".join(messages) if messages else "report is fresh and passed",
        "path": str(path.relative_to(ROOT)),
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "metrics": {
            "users": report.get("users"),
            "iterations": report.get("iterations"),
            "concurrency": report.get("concurrency"),
            "requests_per_second": report.get("requests_per_second"),
            "error_count": report.get("error_count"),
            "five_xx_count": report.get("five_xx_count"),
            "global_p95_ms": (report.get("global") or {}).get("p95_ms"),
            "global_p99_ms": (report.get("global") or {}).get("p99_ms"),
            "login_p95_ms": ((report.get("steps") or {}).get("login") or {}).get("p95_ms"),
        },
    }


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


def check_schema_indexes() -> dict[str, Any]:
    required_indexes = {
        "auth_sessions": {
            "idx_auth_sessions_user_id",
            "idx_auth_sessions_user_active_recent",
            "idx_auth_sessions_expires_at",
        },
        "task_runs": {
            "idx_task_runs_claim_ready",
            "idx_task_runs_lease_expiry",
            "idx_task_runs_retry_schedule",
            "idx_task_runs_task_type_status",
        },
        "listings": {
            "idx_listings_store_sku",
            "idx_listings_store_sync_status",
        },
    }
    rows = fetch_all(
        """
        select tablename, indexname
        from pg_indexes
        where schemaname = 'public'
          and tablename in ('auth_sessions', 'task_runs', 'listings')
        """
    )
    existing = {
        table: {row["indexname"] for row in rows if row["tablename"] == table}
        for table in required_indexes
    }
    missing = {
        table: sorted(indexes - existing.get(table, set()))
        for table, indexes in required_indexes.items()
        if indexes - existing.get(table, set())
    }
    unique_session = fetch_one(
        """
        select count(*) as count
        from pg_constraint
        where conrelid = 'auth_sessions'::regclass
          and contype = 'u'
          and pg_get_constraintdef(oid) ilike %s
        """,
        ("%session_token%",),
    )
    if int(unique_session.get("count") or 0) <= 0:
        missing["auth_sessions"] = sorted(
            set(missing.get("auth_sessions", [])) | {"unique(session_token)"}
        )

    return {
        "name": "schema_indexes",
        "status": "fail" if missing else "ok",
        "message": "missing required indexes" if missing else "required hot-path indexes exist",
        "missing": missing,
    }


def check_takealot_only() -> dict[str, Any]:
    row = fetch_one(
        """
        select count(*) as non_takealot_count
        from stores
        where platform <> 'takealot'
        """
    )
    count = int(row.get("non_takealot_count") or 0)
    return {
        "name": "takealot_only",
        "status": "fail" if count else "ok",
        "message": "non-Takealot stores detected" if count else "all stores are Takealot",
        "non_takealot_count": count,
    }


def is_test_artifact(row: dict[str, Any], tokens: tuple[str, ...]) -> bool:
    values: list[Any] = [
        row.get("request_id"),
        row.get("target_label"),
        row.get("name"),
        row.get("slug"),
        row.get("tenant_slug"),
        row.get("tenant_name"),
        row.get("username"),
        row.get("email"),
    ]
    for nested_key in ("ui_meta", "metadata"):
        nested = row.get(nested_key)
        if not isinstance(nested, dict):
            continue
        values.extend(nested.get(key) for key in TEST_ARTIFACT_NESTED_KEYS)
    haystack = " ".join(str(value or "") for value in values).lower()
    return any(token in haystack for token in tokens)


def filter_test_artifacts(
    rows: list[dict[str, Any]],
    *,
    exclude_test_artifacts: bool,
    tokens: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not exclude_test_artifacts:
        return rows
    return [row for row in rows if not is_test_artifact(row, tokens)]


def filter_active_sync_store_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    active_rows: list[dict[str, Any]] = []
    excluded_count = 0
    for row in rows:
        store_status = row.get("store_status")
        sync_enabled = row.get("sync_enabled")
        if store_status is not None and store_status != "active":
            excluded_count += 1
            continue
        if sync_enabled is not None and not sync_enabled:
            excluded_count += 1
            continue
        active_rows.append(row)
    return active_rows, excluded_count


def is_inactive_listing(row: dict[str, Any]) -> bool:
    raw_payload = row.get("raw_payload")
    if not isinstance(raw_payload, dict):
        return False
    status = str(raw_payload.get("status") or "").lower()
    if status in {"disabled_by_takealot", "disabled_by_seller"}:
        return True
    return bool(
        raw_payload.get("disabled_by_takealot")
        or raw_payload.get("disabled_by_seller")
    )


def filter_active_listing_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    active_rows: list[dict[str, Any]] = []
    excluded_count = 0
    for row in rows:
        if is_inactive_listing(row):
            excluded_count += 1
            continue
        active_rows.append(row)
    return active_rows, excluded_count


def check_sync_failure_budget(args: argparse.Namespace) -> dict[str, Any]:
    rows = fetch_all(
        """
        select
          tr.id,
          tr.status,
          tr.error_code,
          tr.error_msg,
          tr.request_id,
          tr.ui_meta,
          tr.created_at,
          s.status as store_status,
          coalesce(sfp.sync_enabled, true) as sync_enabled
        from task_runs tr
        left join stores s on s.id = tr.store_id
        left join store_feature_policies sfp on sfp.store_id = tr.store_id
        where task_type = 'SYNC_STORE_LISTINGS'
          and tr.created_at >= now() - (%s * interval '1 hour')
        """,
        (args.sync_window_hours,),
    )
    artifact_filtered_rows = filter_test_artifacts(
        rows,
        exclude_test_artifacts=not args.include_test_artifacts,
        tokens=tuple(args.test_artifact_tokens),
    )
    production_rows, excluded_inactive_store_count = filter_active_sync_store_rows(artifact_filtered_rows)
    total_count = len(production_rows)
    failed_rows = [row for row in production_rows if row["status"] in FAILING_SYNC_STATUSES]
    failure_rate = len(failed_rows) / total_count if total_count else 0.0
    status = "ok"
    message = "sync failure budget is within threshold"
    if total_count == 0:
        status = "warn"
        message = "no production sync tasks in the observation window"
    elif failure_rate > args.max_sync_failure_rate:
        status = "fail"
        message = "sync task failure rate exceeds budget"
    return {
        "name": "sync_failure_budget",
        "status": status,
        "message": message,
        "window_hours": args.sync_window_hours,
        "total_count": total_count,
        "failed_count": len(failed_rows),
        "failure_rate": round(failure_rate, 4),
        "max_failure_rate": args.max_sync_failure_rate,
        "excluded_test_artifact_count": len(rows) - len(artifact_filtered_rows),
        "excluded_inactive_store_count": excluded_inactive_store_count,
        "recent_failures": [
            {
                "id": str(row["id"]),
                "status": row["status"],
                "error_code": row["error_code"],
                "created_at": row["created_at"],
                "label": (row.get("ui_meta") or {}).get("label"),
            }
            for row in failed_rows[:5]
        ],
    }


def check_sync_error_budget(args: argparse.Namespace) -> dict[str, Any]:
    rows = fetch_all(
        """
        select
          al.request_id,
          al.target_label,
          al.result,
          al.error_code,
          al.metadata,
          al.created_at,
          s.status as store_status,
          coalesce(sfp.sync_enabled, true) as sync_enabled
        from audit_logs al
        left join stores s on s.id::text = coalesce(al.metadata ->> 'store_id', '')
        left join store_feature_policies sfp on sfp.store_id = s.id
        where al.action = 'store.sync.worker'
          and al.result in ('failed', 'partial')
          and al.created_at >= now() - (%s * interval '1 hour')
        """,
        (args.sync_window_hours,),
    )
    artifact_filtered_rows = filter_test_artifacts(
        rows,
        exclude_test_artifacts=not args.include_test_artifacts,
        tokens=tuple(args.test_artifact_tokens),
    )
    production_rows, excluded_inactive_store_count = filter_active_sync_store_rows(artifact_filtered_rows)
    auth_failures = [
        row for row in production_rows if row.get("error_code") == "STORE_AUTH_FAILED"
    ]
    platform_failures = [
        row for row in production_rows if row.get("error_code") == "STORE_PLATFORM_UNAVAILABLE"
    ]
    other_failures = [
        row
        for row in production_rows
        if row.get("error_code") not in {"STORE_AUTH_FAILED", "STORE_PLATFORM_UNAVAILABLE"}
    ]
    fail_reasons: list[str] = []
    if len(auth_failures) > args.max_sync_auth_failures:
        fail_reasons.append("auth failures exceed budget")
    if len(platform_failures) > args.max_sync_platform_failures:
        fail_reasons.append("platform temporary failures exceed budget")
    return {
        "name": "sync_error_budget",
        "status": "fail" if fail_reasons else "ok",
        "message": "; ".join(fail_reasons) if fail_reasons else "sync error counts are within budget",
        "window_hours": args.sync_window_hours,
        "auth_failure_count": len(auth_failures),
        "max_auth_failures": args.max_sync_auth_failures,
        "platform_failure_count": len(platform_failures),
        "max_platform_failures": args.max_sync_platform_failures,
        "other_failure_count": len(other_failures),
        "excluded_test_artifact_count": len(rows) - len(artifact_filtered_rows),
        "excluded_inactive_store_count": excluded_inactive_store_count,
    }


def check_store_freshness(args: argparse.Namespace) -> dict[str, Any]:
    rows = fetch_all(
        """
        select
          s.id,
          s.name,
          s.status,
          s.platform,
          s.last_synced_at,
          sc.credential_status,
          sfp.sync_enabled
        from stores s
        left join store_credentials sc on sc.store_id = s.id
        left join store_feature_policies sfp on sfp.store_id = s.id
        where s.status = 'active'
          and s.platform = 'takealot'
          and coalesce(sfp.sync_enabled, true) = true
        """
    )
    production_rows = filter_test_artifacts(
        rows,
        exclude_test_artifacts=not args.include_test_artifacts,
        tokens=tuple(args.test_artifact_tokens),
    )
    stale_rows = []
    invalid_credential_rows = []
    for row in production_rows:
        last_synced_at = row.get("last_synced_at")
        if last_synced_at is None:
            stale_rows.append(row)
        else:
            age_hours = (utc_now() - last_synced_at.astimezone(UTC)).total_seconds() / 3600
            if age_hours > args.max_store_sync_age_hours:
                stale_rows.append(row)
        if row.get("credential_status") not in {"valid", "configured", "validating"}:
            invalid_credential_rows.append(row)

    status = "ok"
    message = "active Takealot stores are fresh enough"
    if stale_rows or invalid_credential_rows:
        status = "warn"
        message = "active Takealot store freshness or credentials need operator review"

    return {
        "name": "store_freshness",
        "status": status,
        "message": message,
        "max_store_sync_age_hours": args.max_store_sync_age_hours,
        "active_store_count": len(production_rows),
        "stale_store_count": len(stale_rows),
        "invalid_credential_count": len(invalid_credential_rows),
        "excluded_test_artifact_count": len(rows) - len(production_rows),
        "sample_stale_stores": [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "last_synced_at": row["last_synced_at"],
                "credential_status": row["credential_status"],
            }
            for row in stale_rows[:5]
        ],
    }


def check_listing_health(args: argparse.Namespace) -> dict[str, Any]:
    rows = fetch_all(
        """
        select
          l.id,
          l.sync_status,
          l.last_synced_at,
          l.raw_payload,
          s.name
        from listings l
        join stores s on s.id = l.store_id
        where s.platform = 'takealot'
        """
    )
    artifact_filtered_rows = filter_test_artifacts(
        rows,
        exclude_test_artifacts=not args.include_test_artifacts,
        tokens=tuple(args.test_artifact_tokens),
    )
    production_rows, excluded_inactive_listing_count = filter_active_listing_rows(
        artifact_filtered_rows
    )
    total_count = len(production_rows)
    unhealthy_count = sum(
        1 for row in production_rows if row.get("sync_status") in {"error", "stale"}
    )
    stale_age_count = 0
    for row in production_rows:
        last_synced_at = row.get("last_synced_at")
        if last_synced_at is None:
            stale_age_count += 1
            continue
        age_hours = (utc_now() - last_synced_at.astimezone(UTC)).total_seconds() / 3600
        if age_hours > args.max_listing_sync_age_hours:
            stale_age_count += 1
    unhealthy_rate = unhealthy_count / total_count if total_count else 0.0
    status = "ok"
    message = "listing health is within budget"
    if total_count == 0:
        status = "warn"
        message = "no production listings observed"
    elif unhealthy_rate > args.max_unhealthy_listing_rate:
        status = "fail"
        message = "listing unhealthy rate exceeds budget"
    elif stale_age_count:
        status = "warn"
        message = "some listings are older than the freshness target"
    return {
        "name": "listing_health",
        "status": status,
        "message": message,
        "total_count": total_count,
        "unhealthy_count": unhealthy_count,
        "unhealthy_rate": round(unhealthy_rate, 4),
        "max_unhealthy_rate": args.max_unhealthy_listing_rate,
        "stale_age_count": stale_age_count,
        "max_listing_sync_age_hours": args.max_listing_sync_age_hours,
        "excluded_test_artifact_count": len(rows) - len(artifact_filtered_rows),
        "excluded_inactive_listing_count": excluded_inactive_listing_count,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    load_path, load_report = latest_json_report(ROOT / "reports" / "load", "commercial-load-*.json")
    warmup_path, warmup_report = latest_json_report(ROOT / "reports" / "warmup", "api-warmup-*.json")
    load_base_url = os.getenv("XH_LOAD_BASE_URL", "").strip()
    has_deploy_load_target = bool(load_base_url)
    checks = [
        check_database(),
        check_schema_indexes(),
        check_takealot_only(),
        evaluate_execution_report(
            name="latest_commercial_gate",
            path=load_path,
            report=load_report,
            max_age_hours=args.max_load_report_age_hours,
            required_users=args.required_load_users,
            enabled=has_deploy_load_target,
            disabled_message="XH_LOAD_BASE_URL is not configured; skipping commercial gate freshness until deploy URL is ready",
        ),
        evaluate_execution_report(
            name="latest_api_warmup",
            path=warmup_path,
            report=warmup_report,
            max_age_hours=args.max_warmup_report_age_hours,
            required_users=None,
            enabled=has_deploy_load_target,
            disabled_message="XH_LOAD_BASE_URL is not configured; skipping API warmup freshness until deploy URL is ready",
        ),
        check_sync_failure_budget(args),
        check_sync_error_budget(args),
        check_store_freshness(args),
        check_listing_health(args),
    ]
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
    parser = argparse.ArgumentParser(description="Commercial operations guardrail report")
    parser.add_argument("--sync-window-hours", type=float, default=float(os.getenv("XH_OPS_SYNC_WINDOW_HOURS", "6")))
    parser.add_argument("--max-sync-failure-rate", type=float, default=float(os.getenv("XH_OPS_MAX_SYNC_FAILURE_RATE", "0.05")))
    parser.add_argument("--max-sync-auth-failures", type=int, default=int(os.getenv("XH_OPS_MAX_SYNC_AUTH_FAILURES", "0")))
    parser.add_argument("--max-sync-platform-failures", type=int, default=int(os.getenv("XH_OPS_MAX_SYNC_PLATFORM_FAILURES", "10")))
    parser.add_argument("--max-store-sync-age-hours", type=float, default=float(os.getenv("XH_OPS_MAX_STORE_SYNC_AGE_HOURS", "6")))
    parser.add_argument("--max-listing-sync-age-hours", type=float, default=float(os.getenv("XH_OPS_MAX_LISTING_SYNC_AGE_HOURS", "12")))
    parser.add_argument("--max-unhealthy-listing-rate", type=float, default=float(os.getenv("XH_OPS_MAX_UNHEALTHY_LISTING_RATE", "0.01")))
    parser.add_argument("--max-load-report-age-hours", type=float, default=float(os.getenv("XH_OPS_MAX_LOAD_REPORT_AGE_HOURS", "24")))
    parser.add_argument("--max-warmup-report-age-hours", type=float, default=float(os.getenv("XH_OPS_MAX_WARMUP_REPORT_AGE_HOURS", "24")))
    parser.add_argument("--required-load-users", type=int, default=int(os.getenv("XH_OPS_REQUIRED_LOAD_USERS", "1000")))
    parser.add_argument("--include-test-artifacts", action="store_true")
    parser.add_argument("--test-artifact-tokens", nargs="*", default=list(DEFAULT_TEST_TOKENS))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", default=os.getenv("XH_OPS_GUARDRAILS_OUTPUT"))
    parser.add_argument("--no-fail", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args)
    output = json.dumps(report, ensure_ascii=False, indent=2, default=json_default)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if not report["passed"] and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
