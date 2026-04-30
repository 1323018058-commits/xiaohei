from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import sql


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.platform.db.session import get_db_session  # noqa: E402
from src.platform.settings.base import settings  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "reports" / "backups"


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


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_all(cursor: Any, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    rows = cursor.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def discover_tables(cursor: Any) -> list[str]:
    rows = fetch_all(
        cursor,
        """
        select table_name
        from information_schema.tables
        where table_schema = 'public'
          and table_type = 'BASE TABLE'
        order by table_name
        """,
    )
    return [row["table_name"] for row in rows]


def discover_columns(cursor: Any, table_name: str) -> list[str]:
    rows = fetch_all(
        cursor,
        """
        select column_name
        from information_schema.columns
        where table_schema = 'public'
          and table_name = %s
        order by ordinal_position
        """,
        (table_name,),
    )
    return [row["column_name"] for row in rows]


def write_json_line(handle: Any, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, default=json_default))
    handle.write("\n")


def backup_database(output_dir: Path) -> dict[str, Any]:
    if not settings.database_url:
        raise RuntimeError("XH_DATABASE_URL is not configured")

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
    backup_path = output_dir / f"xiaohei-logical-{timestamp}.jsonl.gz"
    temporary_path = backup_path.with_suffix(backup_path.suffix + ".tmp")

    started_at = utc_now()
    table_summaries: list[dict[str, Any]] = []
    total_rows = 0

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute("begin transaction isolation level repeatable read read only")
            db_info = dict(
                cursor.execute(
                    """
                    select
                      current_database() as database_name,
                      current_user as database_user,
                      current_setting('server_version') as server_version
                    """
                ).fetchone()
            )
            tables = discover_tables(cursor)

            with gzip.open(temporary_path, "wt", encoding="utf-8", newline="\n") as handle:
                write_json_line(
                    handle,
                    {
                        "type": "header",
                        "format": "xiaohei.logical.v1",
                        "generated_at": started_at.isoformat(),
                        "schema": "public",
                        "database": db_info,
                        "table_count": len(tables),
                    },
                )

                for table_name in tables:
                    columns = discover_columns(cursor, table_name)
                    row_count = int(
                        cursor.execute(
                            sql.SQL("select count(*) as count from {}.{}").format(
                                sql.Identifier("public"),
                                sql.Identifier(table_name),
                            )
                        ).fetchone()["count"]
                    )
                    write_json_line(
                        handle,
                        {
                            "type": "table_start",
                            "table": table_name,
                            "columns": columns,
                            "row_count": row_count,
                        },
                    )

                    cursor.execute(
                        sql.SQL("select * from {}.{} order by 1").format(
                            sql.Identifier("public"),
                            sql.Identifier(table_name),
                        )
                    )
                    written_rows = 0
                    while True:
                        batch = cursor.fetchmany(1000)
                        if not batch:
                            break
                        for row in batch:
                            write_json_line(
                                handle,
                                {
                                    "type": "row",
                                    "table": table_name,
                                    "data": dict(row),
                                },
                            )
                            written_rows += 1

                    write_json_line(
                        handle,
                        {
                            "type": "table_end",
                            "table": table_name,
                            "row_count": written_rows,
                        },
                    )
                    table_summaries.append(
                        {
                            "table": table_name,
                            "columns": len(columns),
                            "rows": written_rows,
                        }
                    )
                    total_rows += written_rows

                write_json_line(
                    handle,
                    {
                        "type": "footer",
                        "generated_at": utc_now().isoformat(),
                        "table_count": len(tables),
                        "total_rows": total_rows,
                    },
                )
            connection.rollback()

    temporary_path.replace(backup_path)
    sha256 = hash_file(backup_path)
    finished_at = utc_now()
    return {
        "passed": True,
        "format": "xiaohei.logical.v1",
        "generated_at": finished_at.isoformat(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        "backup_path": str(backup_path),
        "size_bytes": backup_path.stat().st_size,
        "sha256": sha256,
        "table_count": len(table_summaries),
        "total_rows": total_rows,
        "tables": table_summaries,
    }


def apply_retention(output_dir: Path, retention_days: int) -> list[str]:
    if retention_days <= 0 or not output_dir.exists():
        return []

    cutoff = utc_now().timestamp() - retention_days * 86400
    deleted: list[str] = []
    for pattern in ("xiaohei-logical-*.jsonl.gz", "logical-backup-*.json"):
        for candidate in output_dir.glob(pattern):
            if not candidate.is_file():
                continue
            if candidate.stat().st_mtime >= cutoff:
                continue
            candidate.unlink()
            deleted.append(str(candidate))
    return deleted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a logical JSONL backup for Xiaohei ERP")
    parser.add_argument("--output-dir", default=os.getenv("XH_BACKUP_OUTPUT_DIR") or str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--retention-days", type=int, default=int(os.getenv("XH_BACKUP_RETENTION_DAYS", "14")))
    parser.add_argument("--report-path")
    parser.add_argument("--no-fail", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    report_path = Path(args.report_path) if args.report_path else output_dir / f"logical-backup-{utc_now().strftime('%Y%m%d-%H%M%S')}.json"
    if not report_path.is_absolute():
        report_path = ROOT / report_path

    try:
        report = backup_database(output_dir)
        report["retention_days"] = args.retention_days
        report["deleted_old_files"] = apply_retention(output_dir, args.retention_days)
    except Exception as exc:
        report = {
            "passed": False,
            "format": "xiaohei.logical.v1",
            "generated_at": utc_now().isoformat(),
            "error": type(exc).__name__,
            "message": str(exc),
        }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    output = json.dumps(report, ensure_ascii=False, indent=2, default=json_default)
    report_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    if not report["passed"] and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
