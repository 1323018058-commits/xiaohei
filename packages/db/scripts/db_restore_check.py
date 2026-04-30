from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKUP_DIR = ROOT / "reports" / "backups"
REQUIRED_TABLES = {
    "tenants",
    "tenant_plan_limits",
    "tenant_subscriptions",
    "users",
    "user_passwords",
    "auth_sessions",
    "stores",
    "store_credentials",
    "store_feature_policies",
    "task_definitions",
    "task_runs",
    "task_events",
    "audit_logs",
    "listings",
    "bidding_rules",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_backup(backup_dir: Path) -> Path | None:
    candidates: list[Path] = []
    for pattern in ("xiaohei-pgdump-*.dump", "xiaohei-logical-*.jsonl.gz"):
        candidates.extend(backup_dir.glob(pattern))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def check_logical_backup(path: Path) -> dict[str, Any]:
    started_at = utc_now()
    seen_header = False
    seen_footer = False
    declared_rows: dict[str, int] = {}
    actual_rows: dict[str, int] = defaultdict(int)
    tables: set[str] = set()
    line_count = 0
    errors: list[str] = []

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line_count += 1
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid json: {exc}")
                continue

            payload_type = payload.get("type")
            if payload_type == "header":
                seen_header = payload.get("format") == "xiaohei.logical.v1"
                if not seen_header:
                    errors.append("header format is not xiaohei.logical.v1")
            elif payload_type == "table_start":
                table = str(payload.get("table") or "")
                tables.add(table)
                declared_rows[table] = int(payload.get("row_count") or 0)
            elif payload_type == "row":
                table = str(payload.get("table") or "")
                if not table:
                    errors.append(f"line {line_number}: row without table")
                else:
                    actual_rows[table] += 1
            elif payload_type == "table_end":
                table = str(payload.get("table") or "")
                ended_rows = int(payload.get("row_count") or 0)
                if actual_rows[table] != ended_rows:
                    errors.append(
                        f"table {table}: table_end row_count {ended_rows} != actual {actual_rows[table]}"
                    )
            elif payload_type == "footer":
                seen_footer = True

    if not seen_header:
        errors.append("missing valid header")
    if not seen_footer:
        errors.append("missing footer")

    for table, declared_count in declared_rows.items():
        if actual_rows[table] != declared_count:
            errors.append(
                f"table {table}: declared row_count {declared_count} != actual {actual_rows[table]}"
            )

    missing_tables = sorted(REQUIRED_TABLES - tables)
    if missing_tables:
        errors.append("missing required tables: " + ", ".join(missing_tables))

    finished_at = utc_now()
    return {
        "passed": not errors,
        "format": "xiaohei.logical.v1",
        "generated_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        "backup_path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hash_file(path),
        "line_count": line_count,
        "table_count": len(tables),
        "total_rows": sum(actual_rows.values()),
        "missing_tables": missing_tables,
        "row_counts": dict(sorted(actual_rows.items())),
        "errors": errors,
    }


def check_pgdump_backup(path: Path) -> dict[str, Any]:
    started_at = utc_now()
    pg_restore = shutil.which("pg_restore")
    if not pg_restore:
        return {
            "passed": False,
            "format": "postgres.custom",
            "generated_at": utc_now().isoformat(),
            "backup_path": str(path),
            "message": "pg_restore is not available; cannot validate custom-format dump",
        }

    completed = subprocess.run(
        [pg_restore, "--list", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    tables: set[str] = set()
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "TABLE" and parts[4] == "public":
            tables.add(parts[5])

    missing_tables = sorted(REQUIRED_TABLES - tables)
    errors: list[str] = []
    if completed.returncode != 0:
        errors.append(completed.stderr.strip() or "pg_restore --list failed")
    if missing_tables:
        errors.append("missing required tables: " + ", ".join(missing_tables))

    finished_at = utc_now()
    return {
        "passed": not errors,
        "format": "postgres.custom",
        "generated_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        "backup_path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hash_file(path),
        "table_count": len(tables),
        "missing_tables": missing_tables,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the latest Xiaohei ERP backup artifact")
    parser.add_argument("--backup-path")
    parser.add_argument("--backup-dir", default=os.getenv("XH_BACKUP_OUTPUT_DIR") or str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--report-path")
    parser.add_argument("--no-fail", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    backup_dir = Path(args.backup_dir)
    if not backup_dir.is_absolute():
        backup_dir = ROOT / backup_dir
    backup_path = Path(args.backup_path) if args.backup_path else latest_backup(backup_dir)
    report_path = Path(args.report_path) if args.report_path else backup_dir / f"db-restore-check-{utc_now().strftime('%Y%m%d-%H%M%S')}.json"
    if not report_path.is_absolute():
        report_path = ROOT / report_path

    if backup_path is None:
        report = {
            "passed": False,
            "generated_at": utc_now().isoformat(),
            "message": "no backup artifact found",
            "backup_dir": str(backup_dir),
        }
    else:
        if not backup_path.is_absolute():
            backup_path = ROOT / backup_path
        if backup_path.name.endswith(".jsonl.gz"):
            report = check_logical_backup(backup_path)
        elif backup_path.suffix == ".dump":
            report = check_pgdump_backup(backup_path)
        else:
            report = {
                "passed": False,
                "generated_at": utc_now().isoformat(),
                "backup_path": str(backup_path),
                "message": "unsupported backup file extension",
            }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    report_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if not report.get("passed") and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
