from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.platform.db.session import get_db_session  # noqa: E402


CRAWL_SCRIPT = Path(__file__).with_name("takealot_selection_crawl.py")


def run_status(run_id: str) -> dict[str, Any]:
    with get_db_session() as connection:
        with connection.cursor() as cursor:
            run = cursor.execute(
                """
                select id, status, discovered_count, processed_count, failed_count,
                       category_bucket_count, price_bucket_count, error_message
                from selection_ingest_runs
                where id = %s
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise RuntimeError(f"Selection ingest run not found: {run_id}")
            bucket_rows = cursor.execute(
                """
                select status, count(*) as count,
                       coalesce(sum(discovered_count), 0) as discovered,
                       coalesce(sum(persisted_count), 0) as processed,
                       coalesce(sum(failed_count), 0) as failed
                from selection_ingest_buckets
                where ingest_run_id = %s
                group by status
                order by status
                """,
                (run_id,),
            ).fetchall()
            snapshot_count = cursor.execute(
                """
                select count(*) as snapshots
                from selection_product_snapshots
                where ingest_run_id = %s
                """,
                (run_id,),
            ).fetchone()["snapshots"]

    buckets = [dict(row) for row in bucket_rows]
    queued = sum(int(row["count"]) for row in buckets if row["status"] == "queued")
    running = sum(int(row["count"]) for row in buckets if row["status"] == "running")
    failed = sum(int(row["count"]) for row in buckets if row["status"] == "failed")
    succeeded = sum(int(row["count"]) for row in buckets if row["status"] == "succeeded")
    return {
        "run": dict(run),
        "buckets": buckets,
        "queued_buckets": queued,
        "running_buckets": running,
        "failed_buckets": failed,
        "succeeded_buckets": succeeded,
        "snapshot_count": int(snapshot_count),
    }


def crawl_stage(args: argparse.Namespace, stage_index: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(CRAWL_SCRIPT),
        "--resume-run-id",
        args.run_id,
        "--url-template",
        args.url_template,
        "--max-products",
        str(args.max_products_per_stage),
        "--page-size",
        str(args.page_size),
        "--max-pages-per-bucket",
        str(args.max_pages_per_bucket),
        "--concurrency",
        str(args.concurrency),
        "--detail-concurrency",
        str(args.detail_concurrency),
        "--request-delay-ms",
        str(args.request_delay_ms),
        "--timeout",
        str(args.timeout),
        "--max-retries",
        str(args.max_retries),
        "--retry-base-delay-ms",
        str(args.retry_base_delay_ms),
        "--retry-max-delay-ms",
        str(args.retry_max_delay_ms),
        "--raw-payload-mode",
        args.raw_payload_mode,
        "--flush-size",
        str(args.flush_size),
        "--heartbeat-buckets",
        str(args.heartbeat_buckets),
    ]
    if args.skip_snapshots:
        command.append("--skip-snapshots")
    if args.skip_mark_running:
        command.append("--skip-mark-running")
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        command.extend(["--output-jsonl", str(output_dir / f"stage_{stage_index:04d}.jsonl")])

    started_at = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    elapsed = round(time.monotonic() - started_at, 3)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    summary: dict[str, Any] | None = None
    if stdout:
        try:
            summary = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            summary = None
    payload = {
        "stage": stage_index,
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "summary": summary,
        "stdout_tail": stdout.splitlines()[-5:],
        "stderr_tail": stderr.splitlines()[-20:],
        "finished_at": datetime.now(UTC).isoformat(),
    }
    if result.returncode != 0:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def write_jsonl(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def main() -> None:
    args = build_parser().parse_args()
    log_path = Path(args.log_jsonl) if args.log_jsonl else None
    if args.status_only:
        print(json.dumps({"done": False, "status": run_status(args.run_id)}, ensure_ascii=False, default=str), flush=True)
        return
    stage_index = 0
    while True:
        status_before = run_status(args.run_id)
        write_jsonl(
            log_path,
            {
                "event": "status_before",
                "stage": stage_index + 1,
                "status": status_before,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        if status_before["queued_buckets"] == 0 and status_before["running_buckets"] == 0 and status_before["failed_buckets"] == 0:
            print(json.dumps({"done": True, "status": status_before}, ensure_ascii=False, default=str), flush=True)
            return
        if args.max_stages and stage_index >= args.max_stages:
            print(
                json.dumps(
                    {"done": False, "stopped": "max_stages", "status": status_before},
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            )
            return

        stage_index += 1
        stage_payload = crawl_stage(args, stage_index)
        status_after = run_status(args.run_id)
        payload = {
            "event": "stage_finished",
            "stage": stage_index,
            "stage_payload": stage_payload,
            "status_after": status_after,
            "at": datetime.now(UTC).isoformat(),
        }
        write_jsonl(log_path, payload)
        print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Takealot selection ingest run in resumable stages")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--url-template", required=True)
    parser.add_argument("--max-products-per-stage", type=int, default=10000)
    parser.add_argument("--max-stages", type=int, default=1, help="0 runs until every bucket is terminal")
    parser.add_argument("--status-only", action="store_true", help="Print controller status and exit without crawling")
    parser.add_argument("--page-size", type=int, default=36)
    parser.add_argument("--max-pages-per-bucket", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--detail-concurrency", type=int, default=1)
    parser.add_argument("--request-delay-ms", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-base-delay-ms", type=int, default=1500)
    parser.add_argument("--retry-max-delay-ms", type=int, default=12000)
    parser.add_argument("--raw-payload-mode", choices=["none", "compact", "full"], default="none")
    parser.add_argument("--skip-snapshots", action="store_true", help="Pass --skip-snapshots to crawl stages")
    parser.add_argument("--flush-size", type=int, default=1000)
    parser.add_argument("--heartbeat-buckets", type=int, default=10)
    parser.add_argument(
        "--skip-mark-running",
        action="store_true",
        help="Do not write per-bucket running state in stage crawlers.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=5)
    parser.add_argument("--output-dir", help="Optional per-stage JSONL product output directory")
    parser.add_argument("--log-jsonl", help="Optional controller progress log")
    return parser


if __name__ == "__main__":
    main()
