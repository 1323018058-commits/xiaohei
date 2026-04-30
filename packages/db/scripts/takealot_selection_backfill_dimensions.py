from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.platform.db.session import get_db_session  # noqa: E402


DEFAULT_USER_AGENT = "Xiaohei-ERP/1.0"
DEFAULT_PORTAL_URL = os.environ.get("XH_TAKEALOT_PORTAL_URL", "https://seller.takealot.com")
DEFAULT_PROFILE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "XiaoheiERP" / "takealot-portal-profile"
)
MPV_URL = "https://seller-api.takealot.com/1/catalogue/mpv/{plid}"
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class ProductTarget:
    id: str
    platform_product_id: str


@dataclass(frozen=True)
class VariantDimension:
    product_id: str
    platform_product_id: str
    tsin_id: int
    gtin: str | None
    title: str | None
    size: str | None
    basic_colors: str | None
    color_name: str | None
    weight_kg: float | None
    length_cm: float | None
    width_cm: float | None
    height_cm: float | None
    volume_cm3: float | None
    weight_raw: str | None
    dimensions_raw: str | None
    raw_payload: dict[str, Any] | None


@dataclass(frozen=True)
class BackfillResult:
    product_id: str
    platform_product_id: str
    status: int | None
    latency_ms: int
    variants: list[VariantDimension]
    error: str | None = None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _attr_value(attributes: Any, key: str) -> str | None:
    if not isinstance(attributes, dict):
        return None
    node = attributes.get(key)
    if isinstance(node, dict):
        return _clean_text(node.get("value"))
    return _clean_text(node)


def parse_weight_kg(value: str | None) -> float | None:
    if not value:
        return None
    match = NUMBER_RE.search(value)
    if not match:
        return None
    amount = float(match.group(0))
    unit = value.lower()
    if "kg" in unit:
        return amount
    if "gram" in unit or re.search(r"\bg\b", unit):
        return amount / 1000
    if "mg" in unit:
        return amount / 1_000_000
    return amount


def parse_dimensions_cm(value: str | None) -> tuple[float, float, float] | None:
    if not value:
        return None
    numbers = [float(item) for item in NUMBER_RE.findall(value)]
    if len(numbers) < 3:
        return None
    length, width, height = numbers[:3]
    unit = value.lower()
    if "mm" in unit:
        return length / 10, width / 10, height / 10
    if re.search(r"\bm\b", unit) and "mm" not in unit and "cm" not in unit:
        return length * 100, width * 100, height * 100
    return length, width, height


def load_targets(limit: int, offset: int, *, refresh_stale_days: int | None) -> list[ProductTarget]:
    stale_filter = ""
    params: list[Any] = []
    if refresh_stale_days is not None and refresh_stale_days > 0:
        stale_filter = "or merchant_package_updated_at < now() - (%s::text || ' days')::interval"
        params.append(refresh_stale_days)

    query = f"""
        select id, platform_product_id
        from selection_products
        where platform = 'takealot'
          and (
            merchant_package_updated_at is null
            {stale_filter}
          )
        order by coalesce(total_review_count, 0) desc, updated_at desc
        limit %s offset %s
    """
    params.extend([limit, offset])
    with get_db_session() as connection:
        with connection.cursor() as cursor:
            rows = cursor.execute(query, tuple(params)).fetchall()
            connection.rollback()
    return [
        ProductTarget(
            id=str(row["id"]),
            platform_product_id=str(row["platform_product_id"]),
        )
        for row in rows
    ]


def extract_variants(target: ProductTarget, payload: Any) -> list[VariantDimension]:
    if not isinstance(payload, dict):
        return []
    variants = payload.get("variants")
    if not isinstance(variants, list):
        return []

    parsed: list[VariantDimension] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        tsin_raw = variant.get("tsinId")
        try:
            tsin_id = int(tsin_raw)
        except (TypeError, ValueError):
            continue
        attributes = variant.get("attributes")
        weight_raw = _attr_value(attributes, "merchant_packaged_weight")
        dimensions_raw = _attr_value(attributes, "merchant_packaged_dimensions")
        weight_kg = parse_weight_kg(weight_raw)
        dimensions = parse_dimensions_cm(dimensions_raw)
        length_cm: float | None = None
        width_cm: float | None = None
        height_cm: float | None = None
        volume_cm3: float | None = None
        if dimensions is not None:
            length_cm, width_cm, height_cm = dimensions
            volume_cm3 = length_cm * width_cm * height_cm
        parsed.append(
            VariantDimension(
                product_id=target.id,
                platform_product_id=target.platform_product_id,
                tsin_id=tsin_id,
                gtin=_clean_text(variant.get("gtin")),
                title=_clean_text(variant.get("title")),
                size=_clean_text(variant.get("size")),
                basic_colors=_clean_text(variant.get("basicColors")),
                color_name=_clean_text(variant.get("colorName")),
                weight_kg=weight_kg,
                length_cm=length_cm,
                width_cm=width_cm,
                height_cm=height_cm,
                volume_cm3=volume_cm3,
                weight_raw=weight_raw,
                dimensions_raw=dimensions_raw,
                # The MPV variant payload can be very large. The parsed merchant
                # weight/dimensions fields are what the backfill needs; keeping
                # raw JSON for every variant can exhaust PostgreSQL portal memory.
                raw_payload=None,
            )
        )
    return parsed


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_retries: int,
) -> tuple[int | None, Any | None, str | None, int]:
    started = time.perf_counter()
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            if attempt >= max_retries:
                latency_ms = int((time.perf_counter() - started) * 1000)
                return None, None, f"{type(exc).__name__}: {exc}", latency_ms
            await asyncio.sleep(min(12, 1.5 * (2**attempt)))
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt < max_retries:
            await asyncio.sleep(min(30, 1.5 * (2**attempt)))
            continue
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            return response.status_code, None, response.text[:240], latency_ms
        try:
            return response.status_code, response.json(), None, latency_ms
        except Exception as exc:
            return response.status_code, None, f"{type(exc).__name__}: {exc}", latency_ms
    latency_ms = int((time.perf_counter() - started) * 1000)
    return None, None, "max retries exceeded", latency_ms


async def backfill_one(
    client: httpx.AsyncClient,
    target: ProductTarget,
    semaphore: asyncio.Semaphore,
    *,
    max_retries: int,
) -> BackfillResult:
    async with semaphore:
        url = MPV_URL.format(plid=target.platform_product_id)
        status, payload, error, latency_ms = await fetch_json(client, url, max_retries=max_retries)
        variants = extract_variants(target, payload) if payload is not None else []
        return BackfillResult(
            product_id=target.id,
            platform_product_id=target.platform_product_id,
            status=status,
            latency_ms=latency_ms,
            variants=variants,
            error=error,
        )


def _summary_values(variants: list[VariantDimension]) -> dict[str, float | int | None]:
    weights = [variant.weight_kg for variant in variants if variant.weight_kg is not None]
    lengths = [variant.length_cm for variant in variants if variant.length_cm is not None]
    widths = [variant.width_cm for variant in variants if variant.width_cm is not None]
    heights = [variant.height_cm for variant in variants if variant.height_cm is not None]
    volumes = [variant.volume_cm3 for variant in variants if variant.volume_cm3 is not None]
    return {
        "weight_kg": max(weights) if weights else None,
        "length_cm": max(lengths) if lengths else None,
        "width_cm": max(widths) if widths else None,
        "height_cm": max(heights) if heights else None,
        "volume_cm3": max(volumes) if volumes else None,
        "variant_count": len(variants),
    }


def persist_results(results: list[BackfillResult], *, dry_run: bool) -> int:
    variant_payload: list[dict[str, Any]] = []
    product_payload: list[dict[str, Any]] = []
    for result in results:
        if result.status != 200:
            continue
        summary = _summary_values(result.variants)
        product_payload.append(
            {
                "product_id": result.product_id,
                "weight_kg": summary["weight_kg"],
                "length_cm": summary["length_cm"],
                "width_cm": summary["width_cm"],
                "height_cm": summary["height_cm"],
                "volume_cm3": summary["volume_cm3"],
                "variant_count": summary["variant_count"],
            }
        )
        for variant in result.variants:
            variant_payload.append(
                {
                    "product_id": variant.product_id,
                    "platform_product_id": variant.platform_product_id,
                    "tsin_id": variant.tsin_id,
                    "gtin": variant.gtin,
                    "title": variant.title,
                    "size": variant.size,
                    "basic_colors": variant.basic_colors,
                    "color_name": variant.color_name,
                    "weight_kg": variant.weight_kg,
                    "length_cm": variant.length_cm,
                    "width_cm": variant.width_cm,
                    "height_cm": variant.height_cm,
                    "volume_cm3": variant.volume_cm3,
                    "weight_raw": variant.weight_raw,
                    "dimensions_raw": variant.dimensions_raw,
                    "raw_payload": variant.raw_payload,
                }
            )
    if dry_run or (not variant_payload and not product_payload):
        return len(variant_payload)

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            if variant_payload:
                cursor.execute(
                    """
                    with incoming as (
                      select *
                      from jsonb_to_recordset(%s::jsonb) as x(
                        product_id uuid,
                        platform_product_id text,
                        tsin_id bigint,
                        gtin text,
                        title text,
                        size text,
                        basic_colors text,
                        color_name text,
                        weight_kg numeric,
                        length_cm numeric,
                        width_cm numeric,
                        height_cm numeric,
                        volume_cm3 numeric,
                        weight_raw text,
                        dimensions_raw text,
                        raw_payload jsonb
                      )
                    )
                    insert into selection_product_variants (
                      product_id, platform, platform_product_id, tsin_id, gtin, title, size,
                      basic_colors, color_name, merchant_package_weight_kg,
                      merchant_package_length_cm, merchant_package_width_cm,
                      merchant_package_height_cm, merchant_package_volume_cm3,
                      merchant_package_weight_raw, merchant_package_dimensions_raw,
                      raw_payload, updated_at
                    )
                    select
                      product_id, 'takealot', platform_product_id, tsin_id, gtin, title, size,
                      basic_colors, color_name, weight_kg, length_cm, width_cm, height_cm,
                      volume_cm3, weight_raw, dimensions_raw, raw_payload, now()
                    from incoming
                    on conflict (platform, tsin_id) do update
                    set product_id = excluded.product_id,
                        platform_product_id = excluded.platform_product_id,
                        gtin = excluded.gtin,
                        title = excluded.title,
                        size = excluded.size,
                        basic_colors = excluded.basic_colors,
                        color_name = excluded.color_name,
                        merchant_package_weight_kg = excluded.merchant_package_weight_kg,
                        merchant_package_length_cm = excluded.merchant_package_length_cm,
                        merchant_package_width_cm = excluded.merchant_package_width_cm,
                        merchant_package_height_cm = excluded.merchant_package_height_cm,
                        merchant_package_volume_cm3 = excluded.merchant_package_volume_cm3,
                        merchant_package_weight_raw = excluded.merchant_package_weight_raw,
                        merchant_package_dimensions_raw = excluded.merchant_package_dimensions_raw,
                        raw_payload = excluded.raw_payload,
                        updated_at = now()
                    """,
                    (json.dumps(variant_payload, ensure_ascii=False),),
                )
            cursor.execute(
                """
                with incoming as (
                  select *
                  from jsonb_to_recordset(%s::jsonb) as x(
                    product_id uuid,
                    weight_kg numeric,
                    length_cm numeric,
                    width_cm numeric,
                    height_cm numeric,
                    volume_cm3 numeric,
                    variant_count integer
                  )
                )
                update selection_products p
                set merchant_package_weight_kg = incoming.weight_kg,
                    merchant_package_length_cm = incoming.length_cm,
                    merchant_package_width_cm = incoming.width_cm,
                    merchant_package_height_cm = incoming.height_cm,
                    merchant_package_volume_cm3 = incoming.volume_cm3,
                    merchant_package_variant_count = incoming.variant_count,
                    merchant_package_source = 'takealot_catalogue_mpv',
                    merchant_package_updated_at = now(),
                    updated_at = now()
                from incoming
                where p.id = incoming.product_id
                """,
                (json.dumps(product_payload, ensure_ascii=False),),
            )
        connection.commit()
    return len(variant_payload)


def get_bearer_from_profile(profile_dir: str, portal_url: str, *, headless: bool) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SystemExit(
            "Python Playwright is required for --auth-source portal. "
            "Run: python -m pip install playwright && python -m playwright install chromium"
        ) from exc

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=headless,
        )
        page = context.new_page()
        page.goto(portal_url, wait_until="domcontentloaded", timeout=30_000)
        token = page.evaluate(
            """() => {
              try {
                const raw = localStorage.getItem('usr_st_auth');
                const auth = raw ? JSON.parse(raw) : null;
                return auth?.api_key || null;
              } catch (_) {
                return null;
              }
            }"""
        )
        context.close()
    return str(token) if token else None


def resolve_bearer(args: argparse.Namespace) -> str:
    if args.bearer_token:
        return args.bearer_token.strip()
    env_token = os.environ.get("XH_TAKEALOT_CATALOG_BEARER", "").strip()
    if env_token:
        return env_token
    token = get_bearer_from_profile(
        args.profile_dir,
        args.portal_url,
        headless=not args.show_browser,
    )
    if not token:
        raise SystemExit(
            "Missing seller portal bearer token. Log in to Seller Portal with "
            "packages/db/scripts/takealot_portal_probe.py or pass --bearer-token."
        )
    return token


async def process_targets(args: argparse.Namespace, targets: list[ProductTarget], bearer: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {bearer}",
        "User-Agent": DEFAULT_USER_AGENT,
        "Origin": "https://seller.takealot.com",
        "Referer": "https://seller.takealot.com/",
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
            persisted = persist_results(batch_results, dry_run=args.dry_run)
            if args.progress_jsonl:
                append_progress(args.progress_jsonl, batch_results, persisted, start + len(batch), len(targets))
            if args.stop_on_auth_error and any(result.status in {401, 403} for result in batch_results):
                break
            if args.request_delay_ms > 0:
                await asyncio.sleep(args.request_delay_ms / 1000)

    latencies = [result.latency_ms for result in results if result.latency_ms >= 0]
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[str(result.status or "error")] = status_counts.get(str(result.status or "error"), 0) + 1
    variant_count = sum(len(result.variants) for result in results)
    dimension_updates = sum(
        1
        for result in results
        if any(variant.weight_kg is not None or variant.length_cm is not None for variant in result.variants)
    )
    return {
        "target_count": len(targets),
        "fetched_count": len(results),
        "status_counts": status_counts,
        "variant_count": variant_count,
        "dimension_updates": dimension_updates,
        "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_p95": round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else None,
        "latency_ms_avg": round(sum(latencies) / len(latencies), 1) if latencies else None,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    bearer = await asyncio.to_thread(resolve_bearer, args)
    total_targets = 0
    total_fetched = 0
    total_variants = 0
    total_dimension_updates = 0
    cycles = 0
    merged_status_counts: dict[str, int] = {}
    last_latency: dict[str, Any] = {}

    while True:
        cycles += 1
        targets = load_targets(args.limit, args.offset, refresh_stale_days=args.refresh_stale_days)
        if not targets:
            break

        cycle_result = await process_targets(args, targets, bearer)
        total_targets += cycle_result["target_count"]
        total_fetched += cycle_result["fetched_count"]
        total_variants += cycle_result["variant_count"]
        total_dimension_updates += cycle_result["dimension_updates"]
        last_latency = {
            "latency_ms_p50": cycle_result["latency_ms_p50"],
            "latency_ms_p95": cycle_result["latency_ms_p95"],
            "latency_ms_avg": cycle_result["latency_ms_avg"],
        }
        for status, count in cycle_result["status_counts"].items():
            merged_status_counts[status] = merged_status_counts.get(status, 0) + count

        if args.stop_on_auth_error and any(status in merged_status_counts for status in {"401", "403"}):
            break
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
        "fetched_count": total_fetched,
        "variant_count": total_variants,
        "dimension_updates": total_dimension_updates,
        "status_counts": merged_status_counts,
        **last_latency,
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
        "persisted_variants": persisted,
        "status_counts": {
            str(status): sum(1 for result in results if result.status == status)
            for status in sorted({result.status for result in results}, key=lambda value: str(value))
        },
        "variant_count": sum(len(result.variants) for result in results),
        "dimension_updates": sum(
            1
            for result in results
            if any(variant.weight_kg is not None or variant.length_cm is not None for variant in result.variants)
        ),
        "errors": sum(1 for result in results if result.error),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill Takealot selection merchant package dimensions and weight")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--request-delay-ms", type=int, default=250)
    parser.add_argument("--refresh-stale-days", type=int, default=0, help="0 means only missing rows")
    parser.add_argument("--progress-jsonl")
    parser.add_argument("--loop", action="store_true", help="Keep loading new missing rows until none remain")
    parser.add_argument("--max-cycles", type=int, default=0, help="0 means unlimited when --loop is set")
    parser.add_argument("--loop-sleep-seconds", type=float, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-auth-error", action="store_true", default=True)
    parser.add_argument("--bearer-token", help="Optional Seller Portal bearer token; otherwise profile/env is used")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--portal-url", default=DEFAULT_PORTAL_URL)
    parser.add_argument("--show-browser", action="store_true", help="Show browser when reading Seller Portal token")
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
