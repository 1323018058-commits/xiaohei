from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.platform.db.session import get_db_session  # noqa: E402
from takealot_selection_crawl import (  # noqa: E402
    CategorySeed,
    compact_latest_review_payload,
    compact_takealot_detail_payload,
    extract_latest_review_at,
    extract_records,
    numeric_product_id,
    parse_response_payload,
)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DETAIL_URL = "https://api.takealot.com/rest/v-1-16-0/product-details/{plid}"
REVIEW_URL = "https://api.takealot.com/rest/v-1-16-0/product-reviews/plid/{numeric_plid}?sort=SO_LATEST"


@dataclass(frozen=True)
class ProductTarget:
    id: str
    platform_product_id: str
    title: str
    main_category: str | None
    category_level1: str | None
    category_level2: str | None
    category_level3: str | None
    need_offer_count: bool
    need_latest_review_at: bool


@dataclass(frozen=True)
class BackfillResult:
    product_id: str
    platform_product_id: str
    offer_count: int | None
    latest_review_at: str | None
    image_url: str | None
    detail_status: int | None
    review_status: int | None
    detail_error: str | None = None
    review_error: str | None = None


def load_targets(limit: int, offset: int) -> list[ProductTarget]:
    with get_db_session() as connection:
        with connection.cursor() as cursor:
            rows = cursor.execute(
                """
                select id, platform_product_id, title,
                       main_category, category_level1, category_level2, category_level3,
                       offer_count is null as need_offer_count,
                       latest_review_at is null and coalesce(total_review_count, 0) > 0 as need_latest_review_at
                from selection_products
                where platform = 'takealot'
                  and (
                    offer_count is null
                    or (latest_review_at is null and coalesce(total_review_count, 0) > 0)
                  )
                order by coalesce(total_review_count, 0) desc, updated_at desc
                limit %s offset %s
                """,
                (limit, offset),
            ).fetchall()
            connection.rollback()
    return [
        ProductTarget(
            id=str(row["id"]),
            platform_product_id=row["platform_product_id"],
            title=row["title"],
            main_category=row["main_category"],
            category_level1=row["category_level1"],
            category_level2=row["category_level2"],
            category_level3=row["category_level3"],
            need_offer_count=bool(row["need_offer_count"]),
            need_latest_review_at=bool(row["need_latest_review_at"]),
        )
        for row in rows
    ]


async def fetch_json(client: httpx.AsyncClient, url: str, max_retries: int) -> tuple[int | None, Any | None, str | None]:
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            if attempt >= max_retries:
                return None, None, f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(min(8, 1.5 * (2**attempt)))
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt < max_retries:
            await asyncio.sleep(min(10, 1.5 * (2**attempt)))
            continue
        if response.status_code >= 400:
            return response.status_code, None, response.text[:200]
        try:
            return response.status_code, parse_response_payload(response), None
        except Exception as exc:
            return response.status_code, None, f"{type(exc).__name__}: {exc}"
    return None, None, "max retries exceeded"


async def backfill_one(
    client: httpx.AsyncClient,
    target: ProductTarget,
    semaphore: asyncio.Semaphore,
    *,
    max_retries: int,
) -> BackfillResult:
    async with semaphore:
        seed = CategorySeed(
            name=target.main_category or "detail",
            category_ref="detail",
            main_category=target.main_category,
            category_level1=target.category_level1,
            category_level2=target.category_level2,
            category_level3=target.category_level3,
        )
        offer_count: int | None = None
        latest_review_at: str | None = None
        image_url: str | None = None
        detail_status: int | None = None
        review_status: int | None = None
        detail_error: str | None = None
        review_error: str | None = None

        if target.need_offer_count:
            detail_url = DETAIL_URL.format(plid=target.platform_product_id)
            detail_status, detail_payload, detail_error = await fetch_json(client, detail_url, max_retries)
            if detail_payload is not None:
                records = extract_records(detail_payload, seed)
                matching = next(
                    (
                        record
                        for record in records
                        if record.platform_product_id == target.platform_product_id
                    ),
                    records[0] if records else None,
                )
                if matching is not None:
                    offer_count = matching.offer_count
                    image_url = matching.image_url

        if target.need_latest_review_at:
            review_url = REVIEW_URL.format(numeric_plid=numeric_product_id(target.platform_product_id))
            review_status, review_payload, review_error = await fetch_json(client, review_url, max_retries)
            if review_payload is not None:
                latest_review_at = extract_latest_review_at(review_payload)

        return BackfillResult(
            product_id=target.id,
            platform_product_id=target.platform_product_id,
            offer_count=offer_count,
            latest_review_at=latest_review_at,
            image_url=image_url,
            detail_status=detail_status,
            review_status=review_status,
            detail_error=detail_error,
            review_error=review_error,
        )


def persist_results(results: list[BackfillResult], *, snapshot_week: date, dry_run: bool) -> int:
    payload = [
        {
            "product_id": result.product_id,
            "platform_product_id": result.platform_product_id,
            "offer_count": result.offer_count,
            "latest_review_at": result.latest_review_at,
            "image_url": result.image_url,
        }
        for result in results
        if result.offer_count is not None or result.latest_review_at is not None or result.image_url is not None
    ]
    if dry_run or not payload:
        return len(payload)

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                with incoming as (
                  select *
                  from jsonb_to_recordset(%s::jsonb) as x(
                    product_id uuid,
                    platform_product_id text,
                    offer_count integer,
                    latest_review_at text,
                    image_url text
                  )
                )
                update selection_products p
                set offer_count = coalesce(incoming.offer_count, p.offer_count),
                    latest_review_at = coalesce(nullif(incoming.latest_review_at, '')::timestamptz, p.latest_review_at),
                    image_url = coalesce(incoming.image_url, p.image_url),
                    updated_at = now()
                from incoming
                where p.id = incoming.product_id
                """,
                (json.dumps(payload, ensure_ascii=False),),
            )
        connection.commit()
    return len(payload)


async def process_targets(
    args: argparse.Namespace,
    targets: list[ProductTarget],
    *,
    snapshot_week: date,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(
        max_connections=max(1, args.concurrency * 2),
        max_keepalive_connections=max(1, args.concurrency),
    )
    results: list[BackfillResult] = []
    async with httpx.AsyncClient(headers=headers, timeout=timeout, limits=limits, follow_redirects=True) as client:
        for start in range(0, len(targets), args.batch_size):
            batch = targets[start:start + args.batch_size]
            batch_results = await asyncio.gather(
                *[
                    backfill_one(client, target, semaphore, max_retries=args.max_retries)
                    for target in batch
                ]
            )
            results.extend(batch_results)
            persisted = persist_results(batch_results, snapshot_week=snapshot_week, dry_run=args.dry_run)
            if args.progress_jsonl:
                append_progress(args.progress_jsonl, batch_results, persisted, start + len(batch), len(targets))
            if args.request_delay_ms > 0:
                await asyncio.sleep(args.request_delay_ms / 1000)

    offer_updates = sum(1 for result in results if result.offer_count is not None)
    review_updates = sum(1 for result in results if result.latest_review_at is not None)
    image_updates = sum(1 for result in results if result.image_url is not None)
    return {
        "target_count": len(targets),
        "offer_updates": offer_updates,
        "review_updates": review_updates,
        "image_updates": image_updates,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    snapshot_week = date.fromisoformat(args.snapshot_week)
    total_targets = 0
    total_offer_updates = 0
    total_review_updates = 0
    total_image_updates = 0
    cycles = 0

    while True:
        cycles += 1
        targets = load_targets(args.limit, args.offset)
        if not targets:
            break

        cycle_result = await process_targets(args, targets, snapshot_week=snapshot_week)
        total_targets += cycle_result["target_count"]
        total_offer_updates += cycle_result["offer_updates"]
        total_review_updates += cycle_result["review_updates"]
        total_image_updates += cycle_result["image_updates"]

        if not args.loop:
            break
        if args.max_cycles and cycles >= args.max_cycles:
            break
        if args.loop_sleep_seconds > 0:
            await asyncio.sleep(args.loop_sleep_seconds)

    return {
        "dry_run": args.dry_run,
        "loop": args.loop,
        "cycles": cycles if total_targets > 0 else cycles - 1,
        "target_count": total_targets,
        "offer_updates": total_offer_updates,
        "review_updates": total_review_updates,
        "image_updates": total_image_updates,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def append_progress(
    path_value: str,
    results: list[BackfillResult],
    persisted: int,
    processed: int,
    total: int,
) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "at": datetime.now(UTC).isoformat(),
        "processed": processed,
        "total": total,
        "persisted": persisted,
        "offer_updates": sum(1 for result in results if result.offer_count is not None),
        "review_updates": sum(1 for result in results if result.latest_review_at is not None),
        "detail_errors": sum(1 for result in results if result.detail_error),
        "review_errors": sum(1 for result in results if result.review_error),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill Takealot selection offer count and latest review time")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--request-delay-ms", type=int, default=0)
    parser.add_argument("--snapshot-week", default=date.today().isoformat())
    parser.add_argument("--progress-jsonl")
    parser.add_argument("--loop", action="store_true", help="Keep loading new missing rows until none remain")
    parser.add_argument("--max-cycles", type=int, default=0, help="0 means unlimited when --loop is set")
    parser.add_argument("--loop-sleep-seconds", type=float, default=5)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    result = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
