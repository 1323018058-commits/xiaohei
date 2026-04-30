from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.platform.db.session import get_db_session  # noqa: E402


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TAKEALOT_DEFAULT_PRICE_RANGES = (
    (0, 50),
    (50, 100),
    (100, 200),
    (200, 300),
    (300, 500),
    (500, 750),
    (750, 1000),
    (1000, 1500),
    (1500, 2500),
    (2500, 5000),
    (5000, 10000),
    (10000, 25000),
    (25000, 100000),
)
PRODUCT_ID_KEYS = (
    "platform_product_id",
    "productline_id",
    "productlineId",
    "product_line_id",
    "product_id",
    "productId",
    "plid",
    "id",
)
TITLE_KEYS = ("title", "name", "product_title", "productTitle", "display_name")
IMAGE_KEYS = (
    "image_url",
    "imageUrl",
    "main_image",
    "mainImage",
    "thumbnail",
    "thumbnail_url",
    "thumbnailUrl",
    "product_image",
    "productImage",
)
PRICE_KEYS = (
    "current_price",
    "price",
    "selling_price",
    "sellingPrice",
    "buybox_price",
    "buy_box_price",
)
TOTAL_KEYS = (
    "total",
    "total_results",
    "totalResults",
    "result_count",
    "results_count",
    "count",
    "num_results",
)


@dataclass(frozen=True)
class CategorySeed:
    name: str
    category_ref: str
    department_slug: str | None = None
    main_category: str | None = None
    category_level1: str | None = None
    category_level2: str | None = None
    category_level3: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class PriceBucket:
    seed: CategorySeed
    min_price: float
    max_price: float
    depth: int = 0
    db_id: str | None = None

    @property
    def key(self) -> str:
        department = self.seed.department_slug or "all"
        return f"{department}:{self.seed.category_ref}:{self.min_price:g}:{self.max_price:g}:d{self.depth}"


@dataclass
class ProductRecord:
    platform_product_id: str
    title: str
    image_url: str | None = None
    main_category: str | None = None
    category_level1: str | None = None
    category_level2: str | None = None
    category_level3: str | None = None
    brand: str | None = None
    currency: str = "ZAR"
    current_price: float | None = None
    rating: float | None = None
    total_review_count: int | None = None
    rating_5_count: int | None = None
    rating_4_count: int | None = None
    rating_3_count: int | None = None
    rating_2_count: int | None = None
    rating_1_count: int | None = None
    latest_review_at: str | None = None
    stock_status: str | None = None
    offer_count: int | None = None
    raw_payload: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "platform_product_id": self.platform_product_id,
            "image_url": self.image_url,
            "title": self.title,
            "main_category": self.main_category,
            "category_level1": self.category_level1,
            "category_level2": self.category_level2,
            "category_level3": self.category_level3,
            "brand": self.brand,
            "currency": self.currency or "ZAR",
            "current_price": self.current_price,
            "rating": self.rating,
            "total_review_count": self.total_review_count,
            "rating_5_count": self.rating_5_count,
            "rating_4_count": self.rating_4_count,
            "rating_3_count": self.rating_3_count,
            "rating_2_count": self.rating_2_count,
            "rating_1_count": self.rating_1_count,
            "latest_review_at": self.latest_review_at,
            "stock_status": self.stock_status,
            "offer_count": self.offer_count,
            "raw_payload": self.raw_payload,
        }


@dataclass
class PageResult:
    records: list[ProductRecord]
    total_count: int | None
    status_code: int
    url: str
    next_after: str | None = None


class SelectionWriter:
    def __init__(
        self,
        *,
        dry_run: bool,
        snapshot_week: date,
        output_jsonl: str | None = None,
        skip_snapshots: bool = False,
    ) -> None:
        self.dry_run = dry_run
        self.snapshot_week = snapshot_week
        self.output_jsonl = Path(output_jsonl) if output_jsonl else None
        self.skip_snapshots = skip_snapshots
        self.ingest_run_id: str | None = None
        self.discovered_count = 0
        self.persisted_count = 0
        self.failed_count = 0
        self.bucket_count = 0
        self.price_bucket_count = 0

    def start(self, metadata: dict[str, Any]) -> None:
        if self.dry_run:
            self.ingest_run_id = "dry-run"
            return

        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    insert into selection_ingest_runs (
                      platform, status, source, strategy,
                      category_bucket_count, price_bucket_count,
                      metadata, started_at, created_at, updated_at
                    )
                    values (
                      'takealot', 'running', 'takealot_site',
                      'category_price_buckets', 0, 0, %s, now(), now(), now()
                    )
                    returning id
                    """,
                    (Jsonb(metadata),),
                ).fetchone()
            connection.commit()
        self.ingest_run_id = str(row["id"])

    def resume(self, ingest_run_id: str) -> None:
        self.ingest_run_id = ingest_run_id
        if self.dry_run:
            return
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                row = cursor.execute(
                    """
                    update selection_ingest_runs
                    set status = 'running',
                        started_at = coalesce(started_at, now()),
                        finished_at = null,
                        updated_at = now()
                    where id = %s
                    returning id, discovered_count, processed_count, failed_count,
                              category_bucket_count, price_bucket_count
                    """,
                    (ingest_run_id,),
                ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError(f"Selection ingest run not found: {ingest_run_id}")
        self.discovered_count = int(row["discovered_count"] or 0)
        self.persisted_count = int(row["processed_count"] or 0)
        self.failed_count = int(row["failed_count"] or 0)
        self.bucket_count = int(row["category_bucket_count"] or 0)
        self.price_bucket_count = int(row["price_bucket_count"] or 0)

    def persist_bucket_plan(self, buckets: list[PriceBucket]) -> list[PriceBucket]:
        if not buckets:
            return []
        if self.dry_run:
            return buckets
        if self.ingest_run_id is None:
            raise RuntimeError("Ingest run was not started")
        payload = [bucket_to_plan_json(bucket) for bucket in buckets]
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    with incoming as (
                      select *
                      from jsonb_to_recordset(%s::jsonb) as x(
                        bucket_key text,
                        seed_name text,
                        department_slug text,
                        category_ref text,
                        main_category text,
                        category_level1 text,
                        category_level2 text,
                        category_level3 text,
                        url text,
                        min_price numeric,
                        max_price numeric,
                        depth integer
                      )
                    )
                    insert into selection_ingest_buckets (
                      ingest_run_id,
                      bucket_key,
                      seed_name,
                      department_slug,
                      category_ref,
                      main_category,
                      category_level1,
                      category_level2,
                      category_level3,
                      url,
                      min_price,
                      max_price,
                      depth,
                      status,
                      created_at,
                      updated_at
                    )
                    select
                      %s::uuid,
                      bucket_key,
                      seed_name,
                      department_slug,
                      category_ref,
                      main_category,
                      category_level1,
                      category_level2,
                      category_level3,
                      url,
                      min_price,
                      max_price,
                      depth,
                      'queued',
                      now(),
                      now()
                    from incoming
                    on conflict (ingest_run_id, bucket_key)
                    do update set
                      seed_name = excluded.seed_name,
                      department_slug = excluded.department_slug,
                      category_ref = excluded.category_ref,
                      main_category = excluded.main_category,
                      category_level1 = excluded.category_level1,
                      category_level2 = excluded.category_level2,
                      category_level3 = excluded.category_level3,
                      url = excluded.url,
                      min_price = excluded.min_price,
                      max_price = excluded.max_price,
                      depth = excluded.depth,
                      updated_at = now()
                    returning id, bucket_key
                    """,
                    (Jsonb(payload), self.ingest_run_id),
                ).fetchall()
            connection.commit()
        ids_by_key = {row["bucket_key"]: str(row["id"]) for row in rows}
        return [
            replace(bucket, db_id=ids_by_key.get(bucket.key, bucket.db_id))
            for bucket in buckets
        ]

    def load_resumable_buckets(self) -> list[PriceBucket]:
        if self.dry_run:
            return []
        if self.ingest_run_id is None:
            raise RuntimeError("Ingest run was not started")
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                rows = cursor.execute(
                    """
                    update selection_ingest_buckets
                    set status = 'queued',
                        started_at = null,
                        finished_at = null,
                        updated_at = now()
                    where ingest_run_id = %s
                      and status in ('running', 'failed', 'queued')
                    returning *
                    """,
                    (self.ingest_run_id,),
                ).fetchall()
            connection.commit()
        return [bucket_from_row(row) for row in rows]

    def mark_bucket_running(self, bucket: PriceBucket) -> None:
        if getattr(self, "skip_mark_running", False):
            return
        if self.dry_run or not bucket.db_id:
            return
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update selection_ingest_buckets
                    set status = 'running',
                        started_at = coalesce(started_at, now()),
                        finished_at = null,
                        error_message = null,
                        updated_at = now()
                    where id = %s
                    """,
                    (bucket.db_id,),
                )
            connection.commit()

    def mark_bucket_done(
        self,
        bucket: PriceBucket,
        *,
        status: str,
        page_count: int,
        total_count: int | None,
        discovered_count: int,
        persisted_count: int,
        failed_count: int,
        error_message: str | None = None,
    ) -> None:
        if self.dry_run or not bucket.db_id:
            return
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update selection_ingest_buckets
                    set status = %s,
                        page_count = %s,
                        total_count = %s,
                        discovered_count = %s,
                        persisted_count = %s,
                        failed_count = %s,
                        error_message = %s,
                        finished_at = now(),
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        status,
                        page_count,
                        total_count,
                        discovered_count,
                        persisted_count,
                        failed_count,
                        error_message,
                        bucket.db_id,
                    ),
                )
            connection.commit()

    def flush(self, records: list[ProductRecord]) -> int:
        if not records:
            return 0
        self.discovered_count += len(records)
        payload = [record.to_json() for record in records]
        if self.output_jsonl is not None:
            self.write_jsonl(payload)
        if self.dry_run:
            self.persisted_count += len(records)
            return len(records)
        if self.ingest_run_id is None:
            raise RuntimeError("Ingest run was not started")

        if self.skip_snapshots:
            written_count = self._flush_products_only(payload)
            self.persisted_count += written_count
            return written_count

        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    with incoming as (
                      select *
                      from jsonb_to_recordset(%s::jsonb) as x(
                        platform_product_id text,
                        image_url text,
                        title text,
                        main_category text,
                        category_level1 text,
                        category_level2 text,
                        category_level3 text,
                        brand text,
                        currency text,
                        current_price numeric,
                        rating numeric,
                        total_review_count integer,
                        rating_5_count integer,
                        rating_4_count integer,
                        rating_3_count integer,
                        rating_2_count integer,
                        rating_1_count integer,
                        latest_review_at text,
                        stock_status text,
                        offer_count integer,
                        raw_payload jsonb
                      )
                    ),
                    normalized as (
                      select *
                      from incoming
                      where nullif(platform_product_id, '') is not null
                        and nullif(title, '') is not null
                    ),
                    upserted as (
                      insert into selection_products (
                        platform,
                        platform_product_id,
                        image_url,
                        title,
                        main_category,
                        category_level1,
                        category_level2,
                        category_level3,
                        brand,
                        currency,
                        current_price,
                        rating,
                        total_review_count,
                        rating_5_count,
                        rating_4_count,
                        rating_3_count,
                        rating_2_count,
                        rating_1_count,
                        latest_review_at,
                        stock_status,
                        offer_count,
                        current_snapshot_week,
                        status,
                        first_seen_at,
                        last_seen_at,
                        updated_at
                      )
                      select
                        'takealot',
                        platform_product_id,
                        image_url,
                        title,
                        main_category,
                        category_level1,
                        category_level2,
                        category_level3,
                        brand,
                        coalesce(nullif(currency, ''), 'ZAR'),
                        current_price,
                        rating,
                        total_review_count,
                        rating_5_count,
                        rating_4_count,
                        rating_3_count,
                        rating_2_count,
                        rating_1_count,
                        nullif(latest_review_at, '')::timestamptz,
                        stock_status,
                        offer_count,
                        %s::date,
                        'active',
                        now(),
                        now(),
                        now()
                      from normalized
                      on conflict (platform, platform_product_id)
                      do update set
                        image_url = coalesce(excluded.image_url, selection_products.image_url),
                        title = excluded.title,
                        main_category = coalesce(excluded.main_category, selection_products.main_category),
                        category_level1 = coalesce(excluded.category_level1, selection_products.category_level1),
                        category_level2 = coalesce(excluded.category_level2, selection_products.category_level2),
                        category_level3 = coalesce(excluded.category_level3, selection_products.category_level3),
                        brand = coalesce(excluded.brand, selection_products.brand),
                        currency = excluded.currency,
                        current_price = coalesce(excluded.current_price, selection_products.current_price),
                        rating = coalesce(excluded.rating, selection_products.rating),
                        total_review_count = coalesce(excluded.total_review_count, selection_products.total_review_count),
                        rating_5_count = coalesce(excluded.rating_5_count, selection_products.rating_5_count),
                        rating_4_count = coalesce(excluded.rating_4_count, selection_products.rating_4_count),
                        rating_3_count = coalesce(excluded.rating_3_count, selection_products.rating_3_count),
                        rating_2_count = coalesce(excluded.rating_2_count, selection_products.rating_2_count),
                        rating_1_count = coalesce(excluded.rating_1_count, selection_products.rating_1_count),
                        latest_review_at = coalesce(excluded.latest_review_at, selection_products.latest_review_at),
                        stock_status = coalesce(excluded.stock_status, selection_products.stock_status),
                        offer_count = coalesce(excluded.offer_count, selection_products.offer_count),
                        current_snapshot_week = excluded.current_snapshot_week,
                        status = 'active',
                        last_seen_at = now(),
                        updated_at = now()
                      returning id, platform_product_id
                    )
                    insert into selection_product_snapshots (
                      product_id,
                      ingest_run_id,
                      snapshot_week,
                      currency,
                      current_price,
                      rating,
                      total_review_count,
                      rating_5_count,
                      rating_4_count,
                      rating_3_count,
                      rating_2_count,
                      rating_1_count,
                      latest_review_at,
                      stock_status,
                      offer_count,
                      raw_payload,
                      captured_at
                    )
                    select
                      upserted.id,
                      %s::uuid,
                      %s::date,
                      coalesce(nullif(normalized.currency, ''), 'ZAR'),
                      normalized.current_price,
                      normalized.rating,
                      normalized.total_review_count,
                      normalized.rating_5_count,
                      normalized.rating_4_count,
                      normalized.rating_3_count,
                      normalized.rating_2_count,
                      normalized.rating_1_count,
                      nullif(normalized.latest_review_at, '')::timestamptz,
                      normalized.stock_status,
                      normalized.offer_count,
                      normalized.raw_payload,
                      now()
                    from normalized
                    join upserted on upserted.platform_product_id = normalized.platform_product_id
                    on conflict (product_id, snapshot_week)
                    do update set
                      ingest_run_id = excluded.ingest_run_id,
                      currency = excluded.currency,
                      current_price = coalesce(excluded.current_price, selection_product_snapshots.current_price),
                      rating = coalesce(excluded.rating, selection_product_snapshots.rating),
                      total_review_count = coalesce(excluded.total_review_count, selection_product_snapshots.total_review_count),
                      rating_5_count = coalesce(excluded.rating_5_count, selection_product_snapshots.rating_5_count),
                      rating_4_count = coalesce(excluded.rating_4_count, selection_product_snapshots.rating_4_count),
                      rating_3_count = coalesce(excluded.rating_3_count, selection_product_snapshots.rating_3_count),
                      rating_2_count = coalesce(excluded.rating_2_count, selection_product_snapshots.rating_2_count),
                      rating_1_count = coalesce(excluded.rating_1_count, selection_product_snapshots.rating_1_count),
                      latest_review_at = coalesce(excluded.latest_review_at, selection_product_snapshots.latest_review_at),
                      stock_status = coalesce(excluded.stock_status, selection_product_snapshots.stock_status),
                      offer_count = coalesce(excluded.offer_count, selection_product_snapshots.offer_count),
                      raw_payload = coalesce(excluded.raw_payload, selection_product_snapshots.raw_payload),
                      captured_at = now()
                    """,
                    (
                        Jsonb(payload),
                        self.snapshot_week.isoformat(),
                        self.ingest_run_id,
                        self.snapshot_week.isoformat(),
                    ),
                )
                written_count = int(cursor.rowcount or 0)
            connection.commit()

        self.persisted_count += written_count
        return written_count

    def _flush_products_only(self, payload: list[dict[str, Any]]) -> int:
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    with incoming as (
                      select *
                      from jsonb_to_recordset(%s::jsonb) as x(
                        platform_product_id text,
                        image_url text,
                        title text,
                        main_category text,
                        category_level1 text,
                        category_level2 text,
                        category_level3 text,
                        brand text,
                        currency text,
                        current_price numeric,
                        rating numeric,
                        total_review_count integer,
                        rating_5_count integer,
                        rating_4_count integer,
                        rating_3_count integer,
                        rating_2_count integer,
                        rating_1_count integer,
                        latest_review_at text,
                        stock_status text,
                        offer_count integer,
                        raw_payload jsonb
                      )
                    ),
                    normalized as (
                      select *
                      from incoming
                      where nullif(platform_product_id, '') is not null
                        and nullif(title, '') is not null
                    )
                    insert into selection_products (
                      platform,
                      platform_product_id,
                      image_url,
                      title,
                      main_category,
                      category_level1,
                      category_level2,
                      category_level3,
                      brand,
                      currency,
                      current_price,
                      rating,
                      total_review_count,
                      rating_5_count,
                      rating_4_count,
                      rating_3_count,
                      rating_2_count,
                      rating_1_count,
                      latest_review_at,
                      stock_status,
                      offer_count,
                      current_snapshot_week,
                      status,
                      first_seen_at,
                      last_seen_at,
                      updated_at
                    )
                    select
                      'takealot',
                      platform_product_id,
                      image_url,
                      title,
                      main_category,
                      category_level1,
                      category_level2,
                      category_level3,
                      brand,
                      coalesce(nullif(currency, ''), 'ZAR'),
                      current_price,
                      rating,
                      total_review_count,
                      rating_5_count,
                      rating_4_count,
                      rating_3_count,
                      rating_2_count,
                      rating_1_count,
                      nullif(latest_review_at, '')::timestamptz,
                      stock_status,
                      offer_count,
                      %s::date,
                      'active',
                      now(),
                      now(),
                      now()
                    from normalized
                    on conflict (platform, platform_product_id)
                    do update set
                      image_url = coalesce(excluded.image_url, selection_products.image_url),
                      title = excluded.title,
                      main_category = coalesce(excluded.main_category, selection_products.main_category),
                      category_level1 = coalesce(excluded.category_level1, selection_products.category_level1),
                      category_level2 = coalesce(excluded.category_level2, selection_products.category_level2),
                      category_level3 = coalesce(excluded.category_level3, selection_products.category_level3),
                      brand = coalesce(excluded.brand, selection_products.brand),
                      currency = excluded.currency,
                      current_price = coalesce(excluded.current_price, selection_products.current_price),
                      rating = coalesce(excluded.rating, selection_products.rating),
                      total_review_count = coalesce(excluded.total_review_count, selection_products.total_review_count),
                      rating_5_count = coalesce(excluded.rating_5_count, selection_products.rating_5_count),
                      rating_4_count = coalesce(excluded.rating_4_count, selection_products.rating_4_count),
                      rating_3_count = coalesce(excluded.rating_3_count, selection_products.rating_3_count),
                      rating_2_count = coalesce(excluded.rating_2_count, selection_products.rating_2_count),
                      rating_1_count = coalesce(excluded.rating_1_count, selection_products.rating_1_count),
                      latest_review_at = coalesce(excluded.latest_review_at, selection_products.latest_review_at),
                      stock_status = coalesce(excluded.stock_status, selection_products.stock_status),
                      offer_count = coalesce(excluded.offer_count, selection_products.offer_count),
                      current_snapshot_week = excluded.current_snapshot_week,
                      status = 'active',
                      last_seen_at = now(),
                      updated_at = now()
                    """,
                    (Jsonb(payload), self.snapshot_week.isoformat()),
                )
                written_count = int(cursor.rowcount or 0)
            connection.commit()
        return written_count

    def write_jsonl(self, payload: list[dict[str, Any]]) -> None:
        if self.output_jsonl is None:
            return
        self.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with self.output_jsonl.open("a", encoding="utf-8") as handle:
            for item in payload:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":"), default=str))
                handle.write("\n")

    def heartbeat(self, metadata: dict[str, Any]) -> None:
        if self.dry_run or self.ingest_run_id is None:
            return
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update selection_ingest_runs
                    set discovered_count = %s,
                        processed_count = %s,
                        inserted_count = %s,
                        failed_count = %s,
                        category_bucket_count = %s,
                        price_bucket_count = %s,
                        metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        self.discovered_count,
                        self.persisted_count,
                        self.persisted_count,
                        self.failed_count,
                        self.bucket_count,
                        self.price_bucket_count,
                        Jsonb(metadata),
                        self.ingest_run_id,
                    ),
                )
            connection.commit()

    def finish(self, *, status: str, metadata: dict[str, Any], error_message: str | None = None) -> None:
        if self.dry_run or self.ingest_run_id is None:
            return
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update selection_ingest_runs
                    set status = %s,
                        discovered_count = %s,
                        processed_count = %s,
                        inserted_count = %s,
                        failed_count = %s,
                        category_bucket_count = %s,
                        price_bucket_count = %s,
                        metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                        error_message = %s,
                        finished_at = now(),
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        status,
                        self.discovered_count,
                        self.persisted_count,
                        self.persisted_count,
                        self.failed_count,
                        self.bucket_count,
                        self.price_bucket_count,
                        Jsonb(metadata),
                        error_message,
                        self.ingest_run_id,
                    ),
                )
            connection.commit()

    def pause(self, *, status: str, metadata: dict[str, Any]) -> None:
        if self.dry_run or self.ingest_run_id is None:
            return
        with get_db_session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update selection_ingest_runs
                    set status = %s,
                        discovered_count = %s,
                        processed_count = %s,
                        inserted_count = %s,
                        failed_count = %s,
                        category_bucket_count = %s,
                        price_bucket_count = %s,
                        metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        status,
                        self.discovered_count,
                        self.persisted_count,
                        self.persisted_count,
                        self.failed_count,
                        self.bucket_count,
                        self.price_bucket_count,
                        Jsonb(metadata),
                        self.ingest_run_id,
                    ),
                )
            connection.commit()


class TakealotSelectionCrawler:
    def __init__(self, args: argparse.Namespace, writer: SelectionWriter) -> None:
        self.args = args
        self.writer = writer
        self.writer.skip_mark_running = bool(args.skip_mark_running)
        self.headers = load_headers(args)
        self.seen_product_ids: set[str] = set()
        self.seen_bucket_keys: set[str] = set()
        self.queue: asyncio.Queue[PriceBucket] = asyncio.Queue()
        self.buffer: list[ProductRecord] = []
        self.buffer_lock = asyncio.Lock()
        self.detail_semaphore = asyncio.Semaphore(max(1, args.detail_concurrency))
        self.started_at = time.monotonic()
        self.bucket_done_count = 0
        self.page_count = 0
        self.request_count = 0
        self.detail_request_count = 0
        self.retry_count = 0
        self.rate_limited_count = 0

    async def run(self, buckets: list[PriceBucket]) -> dict[str, Any]:
        for bucket in buckets:
            await self.queue.put(bucket)
            self.seen_bucket_keys.add(bucket.key)

        timeout = httpx.Timeout(self.args.timeout)
        limits = httpx.Limits(
            max_connections=max(1, self.args.concurrency * 2),
            max_keepalive_connections=max(1, self.args.concurrency),
        )
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
        ) as client:
            workers = [
                asyncio.create_task(self._worker(client, index))
                for index in range(self.args.concurrency)
            ]
            await self.queue.join()
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await self._flush_buffer()

        return self.summary()

    async def _worker(self, client: httpx.AsyncClient, worker_index: int) -> None:
        del worker_index
        while True:
            bucket = await self.queue.get()
            try:
                await self._crawl_bucket(client, bucket)
            finally:
                self.queue.task_done()

    async def _crawl_bucket(self, client: httpx.AsyncClient, bucket: PriceBucket) -> None:
        if len(self.seen_product_ids) >= self.args.max_products:
            return
        self.writer.mark_bucket_running(bucket)
        self.writer.price_bucket_count += 1
        self.writer.bucket_count = len(self.seen_bucket_keys)
        bucket_records = 0
        bucket_discovered = 0
        bucket_failed = 0
        bucket_pages = 0
        bucket_was_split = False
        first_total: int | None = None
        after_token: str | None = None
        using_cursor = self.args.pagination_mode == "cursor"

        try:
            for page in range(1, self.args.max_pages_per_bucket + 1):
                if len(self.seen_product_ids) >= self.args.max_products:
                    break
                result = await self._fetch_page(client, bucket, page, after_token=after_token)
                self.page_count += 1
                bucket_pages += 1
                if result.status_code == 0 or result.status_code >= 400:
                    bucket_failed += 1
                if first_total is None:
                    first_total = result.total_count
                    bucket_was_split = await self._maybe_split_bucket(bucket, first_total)

                records = dedupe_records(result.records, self.seen_product_ids)
                if len(self.seen_product_ids) > self.args.max_products:
                    records = records[: max(0, self.args.max_products - (len(self.seen_product_ids) - len(records)))]
                bucket_discovered += len(result.records)
                if records:
                    if self.args.detail_url_template or self.args.review_url_template:
                        records = await self._hydrate_details(client, records, bucket.seed)
                    accepted = await self._store_records(records)
                    bucket_records += accepted

                if self.args.verbose:
                    print(
                        json.dumps(
                            {
                                "event": "page",
                                "bucket": bucket.key,
                                "page": page,
                                "status_code": result.status_code,
                                "records": len(result.records),
                                "new_records": len(records),
                                "persisted_total": self.writer.persisted_count + len(self.buffer),
                                "next_after": result.next_after,
                                "url": redact_url(result.url),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )

                if len(result.records) == 0:
                    break
                if bucket_was_split:
                    break
                if self.args.pagination_mode == "auto" and (using_cursor or result.next_after):
                    using_cursor = True
                if using_cursor:
                    if not result.next_after:
                        break
                    after_token = result.next_after
                elif len(result.records) < self.args.page_size and not self.args.no_short_page_stop:
                    break
                if self.args.request_delay_ms > 0:
                    await asyncio.sleep(self.args.request_delay_ms / 1000)
        except Exception as exc:
            self.writer.mark_bucket_done(
                bucket,
                status="failed",
                page_count=bucket_pages,
                total_count=first_total,
                discovered_count=bucket_discovered,
                persisted_count=bucket_records,
                failed_count=max(1, bucket_failed),
                error_message=str(exc),
            )
            raise

        self.bucket_done_count += 1
        self.writer.mark_bucket_done(
            bucket,
            status="split" if bucket_was_split and bucket_failed == 0 else ("succeeded" if bucket_failed == 0 else "failed"),
            page_count=bucket_pages,
            total_count=first_total,
            discovered_count=bucket_discovered,
            persisted_count=bucket_records,
            failed_count=bucket_failed,
            error_message=None if bucket_failed == 0 else "One or more pages failed",
        )
        if self.bucket_done_count % max(1, self.args.heartbeat_buckets) == 0:
            self.writer.heartbeat(self.summary())

        if self.args.verbose:
            print(
                json.dumps(
                    {
                        "event": "bucket_done",
                        "bucket": bucket.key,
                        "records": bucket_records,
                        "first_total": first_total,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    async def _hydrate_details(
        self,
        client: httpx.AsyncClient,
        records: list[ProductRecord],
        seed: CategorySeed,
    ) -> list[ProductRecord]:
        hydrated = await asyncio.gather(
            *[self._fetch_detail(client, record, seed) for record in records],
            return_exceptions=True,
        )
        output: list[ProductRecord] = []
        for index, result in enumerate(hydrated):
            if isinstance(result, ProductRecord):
                output.append(result)
            else:
                self.writer.failed_count += 1
                output.append(records[index])
        return output

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        record: ProductRecord,
        seed: CategorySeed,
    ) -> ProductRecord:
        async with self.detail_semaphore:
            hydrated = record
            if self.args.detail_url_template:
                hydrated = await self._fetch_product_detail(client, hydrated, seed)
            if self.args.review_url_template:
                hydrated = await self._fetch_latest_review(client, hydrated)
            return hydrated

    async def _fetch_product_detail(
        self,
        client: httpx.AsyncClient,
        record: ProductRecord,
        seed: CategorySeed,
    ) -> ProductRecord:
        url = render_record_url(self.args.detail_url_template, record)
        self.detail_request_count += 1
        response = await self._get_with_retries(client, url)
        if response is None:
            return record
        if response.status_code >= 400:
            return record
        payload = parse_response_payload(response)
        details = extract_records(payload, seed)
        matching = next(
            (
                detail
                for detail in details
                if detail.platform_product_id == record.platform_product_id
            ),
            details[0] if details else None,
        )
        if matching is None:
            return record
        return merge_product_record(record, matching, raw_key="detail")

    async def _fetch_latest_review(
        self,
        client: httpx.AsyncClient,
        record: ProductRecord,
    ) -> ProductRecord:
        url = render_record_url(self.args.review_url_template, record)
        self.detail_request_count += 1
        response = await self._get_with_retries(client, url)
        if response is None:
            return record
        if response.status_code >= 400:
            return record
        payload = parse_response_payload(response)
        latest_review_at = extract_latest_review_at(payload)
        if latest_review_at is None:
            return record
        review_record = ProductRecord(
            platform_product_id=record.platform_product_id,
            title=record.title,
            latest_review_at=latest_review_at,
            raw_payload={"latest_review": compact_latest_review_payload(payload)},
        )
        return merge_product_record(record, review_record, raw_key="reviews")

    async def _store_records(self, records: list[ProductRecord]) -> int:
        if not records:
            return 0
        records = prepare_records_for_storage(records, self.args.raw_payload_mode)
        to_flush: list[ProductRecord] = []
        async with self.buffer_lock:
            self.buffer.extend(records)
            if len(self.buffer) >= self.args.flush_size:
                to_flush = self.buffer
                self.buffer = []
        if to_flush:
            await asyncio.to_thread(self.writer.flush, to_flush)
        return len(records)

    async def _flush_buffer(self) -> None:
        async with self.buffer_lock:
            to_flush = self.buffer
            self.buffer = []
        if to_flush:
            await asyncio.to_thread(self.writer.flush, to_flush)

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        bucket: PriceBucket,
        page: int,
        *,
        after_token: str | None = None,
    ) -> PageResult:
        url = render_url(self.args.url_template, bucket, page, self.args.page_size, after_token=after_token)
        self.request_count += 1
        try:
            response = await self._get_with_retries(client, url)
        except httpx.HTTPError as exc:
            self.writer.failed_count += 1
            if self.args.fail_fast:
                raise
            return PageResult([], None, 0, f"{url}#error={type(exc).__name__}")
        if response is None:
            self.writer.failed_count += 1
            return PageResult([], None, 0, f"{url}#error=max_retries")

        if response.status_code in {401, 403, 429}:
            self.writer.failed_count += 1
            message = response.text[:160].replace("\n", " ")
            if self.args.fail_fast:
                raise RuntimeError(f"HTTP {response.status_code} for {redact_url(url)}: {message}")
            return PageResult([], None, response.status_code, url)
        if response.status_code >= 500:
            self.writer.failed_count += 1
            return PageResult([], None, response.status_code, url)

        payload = parse_response_payload(response)
        records = extract_records(payload, bucket.seed)
        total_count = extract_total_count(payload)
        next_after = extract_next_after(payload)
        return PageResult(records, total_count, response.status_code, url, next_after)

    async def _get_with_retries(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> httpx.Response | None:
        last_error: httpx.HTTPError | None = None
        for attempt in range(self.args.max_retries + 1):
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.args.max_retries:
                    raise
                self.retry_count += 1
                await asyncio.sleep(self._retry_delay_seconds(attempt, None))
                continue

            if response.status_code == 429:
                self.rate_limited_count += 1
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            if attempt >= self.args.max_retries:
                return response
            self.retry_count += 1
            await asyncio.sleep(self._retry_delay_seconds(attempt, response))
        if last_error is not None:
            raise last_error
        return None

    def _retry_delay_seconds(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                return min(float(retry_after), self.args.retry_max_delay_ms / 1000)
            except ValueError:
                pass
        base = max(0, self.args.retry_base_delay_ms) / 1000
        cap = max(base, self.args.retry_max_delay_ms / 1000)
        delay = min(cap, base * (2 ** attempt))
        jitter = random.uniform(0, min(0.5, delay * 0.25)) if delay > 0 else 0
        return delay + jitter

    async def _maybe_split_bucket(self, bucket: PriceBucket, total_count: int | None) -> bool:
        if total_count is None:
            return False
        if total_count <= self.args.split_threshold:
            return False
        if bucket.depth >= self.args.max_split_depth:
            return False
        if bucket.max_price - bucket.min_price <= self.args.min_price_width:
            return False
        if len(self.seen_bucket_keys) >= self.args.max_buckets:
            return False

        midpoint = round((bucket.min_price + bucket.max_price) / 2, 2)
        candidates = [
            PriceBucket(bucket.seed, bucket.min_price, midpoint, bucket.depth + 1),
            PriceBucket(bucket.seed, midpoint, bucket.max_price, bucket.depth + 1),
        ]
        if not self.args.no_persist_plan:
            candidates = self.writer.persist_bucket_plan(candidates)
        for candidate in candidates:
            if candidate.key in self.seen_bucket_keys:
                continue
            self.seen_bucket_keys.add(candidate.key)
            await self.queue.put(candidate)
        return True

    def summary(self) -> dict[str, Any]:
        elapsed_seconds = max(0.001, time.monotonic() - self.started_at)
        buffered_count = len(self.buffer)
        return {
            "ingest_run_id": self.writer.ingest_run_id,
            "dry_run": self.writer.dry_run,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "requests": self.request_count,
            "detail_requests": self.detail_request_count,
            "retries": self.retry_count,
            "rate_limited": self.rate_limited_count,
            "pages": self.page_count,
            "bucket_seen": len(self.seen_bucket_keys),
            "bucket_done": self.bucket_done_count,
            "discovered": self.writer.discovered_count + buffered_count,
            "persisted": self.writer.persisted_count + buffered_count,
            "failed": self.writer.failed_count,
            "products_per_second": round((self.writer.persisted_count + buffered_count) / elapsed_seconds, 2),
        }


def load_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if args.headers_json:
        headers.update(json.loads(Path(args.headers_json).read_text(encoding="utf-8-sig")))
    if args.cookie:
        headers["Cookie"] = args.cookie
    if args.cookie_env and os.environ.get(args.cookie_env):
        headers["Cookie"] = os.environ[args.cookie_env]
    return {key: value for key, value in headers.items() if value not in (None, "")}


def initial_buckets(seeds: list[CategorySeed], args: argparse.Namespace) -> list[PriceBucket]:
    ranges = parse_price_ranges(args.price_ranges)
    if not ranges:
        if args.price_profile == "takealot":
            ranges = [
                (min_price, max_price)
                for min_price, max_price in TAKEALOT_DEFAULT_PRICE_RANGES
                if max_price > args.price_min and min_price < args.price_max
            ]
        else:
            ranges = build_price_ranges(
                min_price=args.price_min,
                max_price=args.price_max,
                step=args.initial_price_step,
            )
    buckets = [
        PriceBucket(seed=seed, min_price=min_price, max_price=max_price)
        for seed in seeds
        for min_price, max_price in ranges
    ]
    return buckets[:args.max_buckets]


def bucket_to_plan_json(bucket: PriceBucket) -> dict[str, Any]:
    seed = bucket.seed
    return {
        "bucket_key": bucket.key,
        "seed_name": seed.name,
        "department_slug": seed.department_slug,
        "category_ref": seed.category_ref,
        "main_category": seed.main_category,
        "category_level1": seed.category_level1,
        "category_level2": seed.category_level2,
        "category_level3": seed.category_level3,
        "url": seed.url,
        "min_price": bucket.min_price,
        "max_price": bucket.max_price,
        "depth": bucket.depth,
    }


def bucket_from_row(row: dict[str, Any]) -> PriceBucket:
    seed = CategorySeed(
        name=row["seed_name"],
        category_ref=row["category_ref"],
        department_slug=row.get("department_slug"),
        main_category=row["main_category"],
        category_level1=row["category_level1"],
        category_level2=row["category_level2"],
        category_level3=row["category_level3"],
        url=row["url"],
    )
    return PriceBucket(
        seed=seed,
        min_price=float(row["min_price"]),
        max_price=float(row["max_price"]),
        depth=int(row["depth"]),
        db_id=str(row["id"]),
    )


def parse_price_ranges(value: str | None) -> list[tuple[float, float]]:
    if not value:
        return []
    ranges: list[tuple[float, float]] = []
    for part in value.split(","):
        if not part.strip():
            continue
        left, _, right = part.partition(":")
        if not right:
            raise ValueError(f"Invalid price range: {part}")
        ranges.append((float(left), float(right)))
    return ranges


def build_price_ranges(*, min_price: float, max_price: float, step: float) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    current = min_price
    while current < max_price:
        next_price = min(max_price, current + step)
        ranges.append((round(current, 2), round(next_price, 2)))
        current = next_price
    return ranges


def load_seeds(args: argparse.Namespace) -> list[CategorySeed]:
    seeds: list[CategorySeed] = []
    for value in args.category or []:
        parts = [part.strip() for part in value.split("|")]
        name = parts[0]
        category_ref = parts[1] if len(parts) > 1 and parts[1] else slugify(name)
        department_slug = parts[2] if len(parts) > 2 and parts[2] else None
        main_category = parts[3] if len(parts) > 3 and parts[3] else name
        category_level1 = parts[4] if len(parts) > 4 and parts[4] else None
        category_level2 = parts[5] if len(parts) > 5 and parts[5] else None
        category_level3 = parts[6] if len(parts) > 6 and parts[6] else None
        seeds.append(
            CategorySeed(
                name=name,
                category_ref=category_ref,
                department_slug=department_slug,
                main_category=main_category,
                category_level1=category_level1,
                category_level2=category_level2,
                category_level3=category_level3,
            )
        )

    for value in args.seed_url or []:
        name, _, url = value.partition("|")
        if not url:
            url = name
            name = stable_short_name(url)
        parsed = seed_values_from_url(url)
        seeds.append(
            CategorySeed(
                name=name.strip(),
                category_ref=parsed.get("category_slug") or slugify(name),
                department_slug=parsed.get("department_slug"),
                url=url.strip(),
            )
        )

    if args.categories_file:
        seeds.extend(load_seeds_file(Path(args.categories_file)))

    if not seeds:
        seeds.append(CategorySeed(name="all", category_ref="all", main_category=None))
    return seeds


def load_seeds_file(path: Path) -> list[CategorySeed]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError("Seed JSON must be a list")
        return [seed_from_mapping(item) for item in payload if isinstance(item, dict)]

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [seed_from_mapping(row) for row in reader]


def seed_from_mapping(row: dict[str, Any]) -> CategorySeed:
    name = text_value(row, "name", "category", "label", "category_name") or "category"
    url = text_value(row, "url", "href")
    parsed = seed_values_from_url(url)
    category_ref = (
        text_value(row, "category_ref", "category_slug", "slug", "id", "url_key")
        or parsed.get("category_slug")
        or slugify(name)
    )
    return CategorySeed(
        name=name,
        category_ref=category_ref,
        department_slug=text_value(row, "department_slug", "department") or parsed.get("department_slug"),
        main_category=text_value(row, "main_category", "main"),
        category_level1=text_value(row, "category_level1", "level1"),
        category_level2=text_value(row, "category_level2", "level2"),
        category_level3=text_value(row, "category_level3", "level3"),
        url=url,
    )


def seed_values_from_url(url: str | None) -> dict[str, str]:
    if not url:
        return {}
    query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    return {
        key: value
        for key, value in {
            "category_slug": query.get("category_slug"),
            "department_slug": query.get("department_slug"),
        }.items()
        if value
    }


def render_url(
    template: str,
    bucket: PriceBucket,
    page: int,
    page_size: int,
    *,
    after_token: str | None = None,
) -> str:
    seed = bucket.seed
    url_template = seed.url or template
    uses_after_placeholder = "{after" in url_template
    values = {
        "category": seed.category_ref,
        "category_name": seed.name,
        "category_slug": seed.category_ref,
        "department_slug": seed.department_slug or "",
        "min_price": f"{bucket.min_price:g}",
        "max_price": f"{bucket.max_price:g}",
        "price_min": f"{bucket.min_price:g}",
        "price_max": f"{bucket.max_price:g}",
        "price_filter": price_filter_value(bucket.min_price, bucket.max_price),
        "page": str(page),
        "page_size": str(page_size),
        "limit": str(page_size),
        "offset": str((page - 1) * page_size),
        "after": after_token or "",
    }
    rendered = url_template.format(**values)
    if after_token and not uses_after_placeholder:
        rendered = with_query_param(rendered, "after", after_token)
    return rendered


def price_filter_value(min_price: float, max_price: float) -> str:
    if min_price <= 0:
        return f"*-{max_price:g}"
    if max_price >= 100000:
        return f"{min_price:g}-*"
    return f"{min_price:g}-{max_price:g}"


def with_query_param(url: str, key: str, value: str) -> str:
    parsed = urlsplit(url)
    query = [(name, item) for name, item in parse_qsl(parsed.query, keep_blank_values=True) if name != key]
    query.append((key, value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def render_detail_url(template: str, record: ProductRecord) -> str:
    return render_record_url(template, record)


def render_record_url(template: str, record: ProductRecord) -> str:
    numeric_plid = numeric_product_id(record.platform_product_id)
    variant = takealot_record_variant(record) or ""
    values = {
        "platform_product_id": record.platform_product_id,
        "plid": record.platform_product_id,
        "plid_numeric": numeric_plid,
        "numeric_plid": numeric_plid,
        "product_id_numeric": numeric_plid,
        "title_slug": slugify(record.title),
        "brand": record.brand or "",
        "variant": variant,
        "size": variant,
    }
    return template.format(**values)


def merge_product_record(
    list_record: ProductRecord,
    detail_record: ProductRecord,
    *,
    raw_key: str = "detail",
) -> ProductRecord:
    raw_payload = merge_raw_payloads(list_record.raw_payload, raw_key, detail_record.raw_payload)
    return ProductRecord(
        platform_product_id=list_record.platform_product_id,
        title=detail_record.title or list_record.title,
        image_url=detail_record.image_url or list_record.image_url,
        main_category=detail_record.main_category or list_record.main_category,
        category_level1=detail_record.category_level1 or list_record.category_level1,
        category_level2=detail_record.category_level2 or list_record.category_level2,
        category_level3=detail_record.category_level3 or list_record.category_level3,
        brand=detail_record.brand or list_record.brand,
        currency=detail_record.currency or list_record.currency,
        current_price=detail_record.current_price if detail_record.current_price is not None else list_record.current_price,
        rating=detail_record.rating if detail_record.rating is not None else list_record.rating,
        total_review_count=(
            detail_record.total_review_count
            if detail_record.total_review_count is not None
            else list_record.total_review_count
        ),
        rating_5_count=detail_record.rating_5_count if detail_record.rating_5_count is not None else list_record.rating_5_count,
        rating_4_count=detail_record.rating_4_count if detail_record.rating_4_count is not None else list_record.rating_4_count,
        rating_3_count=detail_record.rating_3_count if detail_record.rating_3_count is not None else list_record.rating_3_count,
        rating_2_count=detail_record.rating_2_count if detail_record.rating_2_count is not None else list_record.rating_2_count,
        rating_1_count=detail_record.rating_1_count if detail_record.rating_1_count is not None else list_record.rating_1_count,
        latest_review_at=detail_record.latest_review_at or list_record.latest_review_at,
        stock_status=detail_record.stock_status or list_record.stock_status,
        offer_count=detail_record.offer_count if detail_record.offer_count is not None else list_record.offer_count,
        raw_payload=raw_payload,
    )


def prepare_records_for_storage(records: list[ProductRecord], raw_payload_mode: str) -> list[ProductRecord]:
    if raw_payload_mode == "full":
        return records
    output: list[ProductRecord] = []
    for record in records:
        if raw_payload_mode == "none":
            output.append(replace(record, raw_payload=None))
        else:
            output.append(replace(record, raw_payload=compact_storage_payload(record.raw_payload)))
    return output


def compact_storage_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if any(key in value for key in ("list", "detail", "reviews")):
        return {
            key: compact_storage_payload(item)
            for key, item in value.items()
            if key in {"list", "detail", "reviews"} and item is not None
        }
    return {
        key: value.get(key)
        for key in (
            "core",
            "gallery",
            "review_summary",
            "buybox_summary",
            "stock_availability_summary",
            "enhanced_ecommerce_click",
            "buybox",
            "reviews",
            "seller_detail",
            "other_offers",
            "data_layer",
            "event_data",
            "latest_review",
        )
        if key in value
    }


def merge_raw_payloads(base: dict[str, Any] | None, key: str, value: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(base, dict) and any(name in base for name in ("list", "detail", "reviews")):
        merged = dict(base)
    else:
        merged = {"list": base}
    if value is not None:
        merged[key] = value
    return merged


def numeric_product_id(platform_product_id: str) -> str:
    match = re.search(r"(\d+)", platform_product_id)
    return match.group(1) if match else platform_product_id


def takealot_record_variant(record: ProductRecord) -> str | None:
    payload = record.raw_payload
    if not isinstance(payload, dict):
        return None
    for event_key in (
        "enhanced_ecommerce_click",
        "enhanced_ecommerce_impression",
        "enhanced_ecommerce_add_to_cart",
        "enhanced_ecommerce_detail",
    ):
        product = takealot_ecommerce_product({event_key: payload.get(event_key)})
        variant = text_value(product, "dimension1", "variant")
        if variant:
            return variant
    product = takealot_ecommerce_product(payload)
    return text_value(product, "dimension1", "variant")


def parse_response_payload(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "").lower()
    text = response.text
    if "json" in content_type:
        return response.json()
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return extract_json_payloads_from_html(text)


def extract_json_payloads_from_html(text: str) -> list[Any]:
    payloads: list[Any] = []
    for match in re.finditer(r"<script[^>]*>(.*?)</script>", text, flags=re.I | re.S):
        script = html_unescape(match.group(1).strip())
        if not script or "product" not in script.lower():
            continue
        if script.startswith("{") or script.startswith("["):
            try:
                payloads.append(json.loads(script))
                continue
            except json.JSONDecodeError:
                pass
        for pattern in (
            r"window\.__INITIAL_STATE__\s*=\s*({.*?});",
            r"window\.__APOLLO_STATE__\s*=\s*({.*?});",
            r"__NEXT_DATA__\s*=\s*({.*?});",
        ):
            found = re.search(pattern, script, flags=re.S)
            if found:
                try:
                    payloads.append(json.loads(found.group(1)))
                except json.JSONDecodeError:
                    continue
    return payloads


def extract_records(payload: Any, seed: CategorySeed) -> list[ProductRecord]:
    if takealot_products_section(payload) is not None:
        return extract_takealot_search_records(payload, seed)
    detail_record = extract_takealot_detail_record(payload, seed)
    if detail_record is not None:
        return [detail_record]

    records: list[ProductRecord] = []
    for item in iter_product_like_dicts(payload):
        record = normalize_product(item, seed)
        if record is not None:
            records.append(record)
    return records


def extract_takealot_detail_record(payload: Any, seed: CategorySeed) -> ProductRecord | None:
    if not isinstance(payload, dict):
        return None
    core = dict_value(payload, "core")
    buybox = dict_value(payload, "buybox")
    reviews = dict_value(payload, "reviews")
    if not core or not buybox:
        return None

    ecommerce_product = takealot_ecommerce_product(payload)
    selected_buybox_item = takealot_selected_buybox_item(buybox)
    stock = dict_value(selected_buybox_item, "stock_availability")
    distribution = dict_value(reviews, "distribution")
    categories = takealot_detail_category_values(payload, seed)
    title = (
        text_value(core, "title")
        or text_value(payload, "title")
        or text_value(ecommerce_product, "name")
    )
    product_id = (
        normalize_product_id(text_value(ecommerce_product, "id"))
        or normalize_takealot_product_id(first_present(buybox, "plid"))
        or normalize_takealot_product_id(first_present(core, "id"))
    )
    if not title or not product_id:
        return None

    return ProductRecord(
        platform_product_id=product_id,
        title=title,
        image_url=takealot_detail_image_url(payload),
        main_category=categories[0],
        category_level1=categories[1],
        category_level2=categories[2],
        category_level3=categories[3],
        brand=text_value(core, "brand") or text_value(ecommerce_product, "brand"),
        currency=takealot_currency(payload),
        current_price=takealot_detail_price(selected_buybox_item, ecommerce_product, payload),
        rating=number_value(first_present(reviews, "star_rating") or first_present(core, "star_rating")),
        total_review_count=integer_value(first_present(reviews, "count") or first_present(core, "reviews")),
        rating_5_count=integer_value(first_present(distribution, "num_5_star_ratings")),
        rating_4_count=integer_value(first_present(distribution, "num_4_star_ratings")),
        rating_3_count=integer_value(first_present(distribution, "num_3_star_ratings")),
        rating_2_count=integer_value(first_present(distribution, "num_2_star_ratings")),
        rating_1_count=integer_value(first_present(distribution, "num_1_star_ratings")),
        latest_review_at=None,
        stock_status=normalize_stock_status(text_value(stock, "status")),
        offer_count=takealot_offer_count(payload),
        raw_payload=compact_takealot_detail_payload(payload),
    )


def extract_takealot_search_records(payload: Any, seed: CategorySeed) -> list[ProductRecord]:
    products_section = takealot_products_section(payload)
    if not products_section:
        return []
    results = products_section.get("results")
    if not isinstance(results, list):
        return []

    categories = takealot_category_values(payload, seed)
    records: list[ProductRecord] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        product_view = result.get("product_views")
        if not isinstance(product_view, dict):
            continue
        record = normalize_takealot_product_view(product_view, seed, categories)
        if record is not None:
            records.append(record)
    return records


def takealot_products_section(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return None
    products = sections.get("products")
    if not isinstance(products, dict):
        return None
    if not isinstance(products.get("results"), list):
        return None
    return products


def takealot_selected_buybox_item(buybox: dict[str, Any]) -> dict[str, Any]:
    items = buybox.get("items")
    if not isinstance(items, list):
        return {}
    first_item: dict[str, Any] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if first_item is None:
            first_item = item
        if item.get("is_selected") is True:
            return item
    return first_item or {}


def takealot_detail_price(
    selected_buybox_item: dict[str, Any],
    ecommerce_product: dict[str, Any],
    payload: dict[str, Any],
) -> float | None:
    data_layer = dict_value(payload, "data_layer")
    return number_value(
        first_present(selected_buybox_item, "price", "pretty_price")
        or first_present(ecommerce_product, "price")
        or first_present(data_layer, "totalPrice")
    )


def takealot_offer_count(payload: dict[str, Any]) -> int | None:
    count = 0
    buybox = dict_value(payload, "buybox")
    if takealot_selected_buybox_item(buybox):
        count += 1

    other_offers = dict_value(payload, "other_offers")
    conditions = other_offers.get("conditions")
    if isinstance(conditions, list):
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            condition_count = integer_value(condition.get("count"))
            if condition_count is not None:
                count += condition_count
                continue
            items = condition.get("items")
            if isinstance(items, list):
                count += sum(1 for item in items if isinstance(item, dict))
    return count if count > 0 else None


def takealot_detail_image_url(payload: dict[str, Any]) -> str | None:
    gallery = dict_value(payload, "gallery")
    for key in ("images", "entries", "items"):
        found = image_url_from_unknown(gallery.get(key))
        if found:
            return found.replace("{size}", "300x300")
    return image_url(payload)


def takealot_detail_category_values(
    payload: dict[str, Any],
    seed: CategorySeed,
) -> tuple[str | None, str | None, str | None, str | None]:
    data_layer = dict_value(payload, "data_layer")
    department = text_value(data_layer, "departmentname")
    category_names = data_layer.get("categoryname")
    if isinstance(category_names, list):
        parts = [department] if department else []
        parts.extend(str(item).strip() for item in category_names if str(item).strip())
        return category_tuple_from_parts(parts, seed)

    breadcrumbs = payload.get("breadcrumbs")
    parts: list[str] = []
    if isinstance(breadcrumbs, list):
        for item in breadcrumbs:
            if isinstance(item, dict):
                value = text_value(item, "display_value", "title", "name")
                if value:
                    parts.append(value)
    elif isinstance(breadcrumbs, dict):
        for key in ("items", "entries", "results"):
            values = breadcrumbs.get(key)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        value = text_value(item, "display_value", "title", "name")
                        if value:
                            parts.append(value)
    return category_tuple_from_parts(parts, seed)


def compact_takealot_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "core",
            "buybox",
            "reviews",
            "seller_detail",
            "other_offers",
            "variants",
            "data_layer",
            "event_data",
            "enhanced_ecommerce_detail",
        )
        if key in payload
    }


def normalize_takealot_product_view(
    product_view: dict[str, Any],
    seed: CategorySeed,
    categories: tuple[str | None, str | None, str | None, str | None],
) -> ProductRecord | None:
    core = dict_value(product_view, "core")
    review_summary = dict_value(product_view, "review_summary")
    buybox_summary = dict_value(product_view, "buybox_summary")
    stock_summary = dict_value(product_view, "stock_availability_summary")
    ecommerce_product = takealot_ecommerce_product(product_view)

    title = (
        text_value(core, "title")
        or text_value(ecommerce_product, "name")
        or text_value(product_view, "title", "name")
    )
    if not title:
        return None

    product_id = (
        normalize_product_id(text_value(ecommerce_product, "id"))
        or normalize_takealot_product_id(first_present(core, "id"))
        or normalize_takealot_product_id(first_present(buybox_summary, "product_id"))
    )
    if not product_id:
        return None

    distribution = dict_value(review_summary, "distribution")
    return ProductRecord(
        platform_product_id=product_id,
        title=title,
        image_url=takealot_image_url(product_view),
        main_category=categories[0],
        category_level1=categories[1],
        category_level2=categories[2],
        category_level3=categories[3],
        brand=text_value(core, "brand") or text_value(ecommerce_product, "brand"),
        currency=takealot_currency(product_view),
        current_price=takealot_price(buybox_summary, ecommerce_product),
        rating=number_value(first_present(review_summary, "star_rating") or first_present(core, "star_rating")),
        total_review_count=integer_value(
            first_present(review_summary, "review_count")
            or first_present(core, "reviews")
        ),
        rating_5_count=integer_value(first_present(distribution, "num_5_star_ratings")),
        rating_4_count=integer_value(first_present(distribution, "num_4_star_ratings")),
        rating_3_count=integer_value(first_present(distribution, "num_3_star_ratings")),
        rating_2_count=integer_value(first_present(distribution, "num_2_star_ratings")),
        rating_1_count=integer_value(first_present(distribution, "num_1_star_ratings")),
        latest_review_at=None,
        stock_status=normalize_stock_status(text_value(stock_summary, "status")),
        offer_count=integer_value(first_present(product_view, "offer_count", "offers_count", "number_of_offers")),
        raw_payload=product_view,
    )


def dict_value(item: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def takealot_ecommerce_product(product_view: dict[str, Any]) -> dict[str, Any]:
    for event_key in (
        "enhanced_ecommerce_click",
        "enhanced_ecommerce_impression",
        "enhanced_ecommerce_add_to_cart",
    ):
        event = dict_value(product_view, event_key)
        ecommerce = dict_value(event, "ecommerce")
        for branch_key in ("click", "add", "detail"):
            branch = dict_value(ecommerce, branch_key)
            products = branch.get("products")
            if isinstance(products, list):
                for product in products:
                    if isinstance(product, dict):
                        return product
        impressions = ecommerce.get("impressions")
        if isinstance(impressions, list):
            for product in impressions:
                if isinstance(product, dict):
                    return product
    return {}


def takealot_image_url(product_view: dict[str, Any]) -> str | None:
    gallery = dict_value(product_view, "gallery")
    images = gallery.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, str) and item.strip():
                return normalize_url(item.replace("{size}", "300x300"))
    return image_url(product_view)


def takealot_price(buybox_summary: dict[str, Any], ecommerce_product: dict[str, Any]) -> float | None:
    prices = first_present(buybox_summary, "prices", "app_prices")
    if isinstance(prices, list):
        for value in prices:
            price = number_value(value)
            if price is not None:
                return price
    return number_value(
        first_present(buybox_summary, "listing_price", "pretty_price", "app_pretty_price")
        or first_present(ecommerce_product, "price")
    )


def takealot_currency(product_view: dict[str, Any]) -> str:
    for event_key in (
        "enhanced_ecommerce_click",
        "enhanced_ecommerce_impression",
        "enhanced_ecommerce_add_to_cart",
    ):
        event = dict_value(product_view, event_key)
        ecommerce = dict_value(event, "ecommerce")
        currency = text_value(ecommerce, "currencyCode", "currency")
        if currency:
            return currency
    return "ZAR"


def normalize_takealot_product_id(value: Any) -> str | None:
    product_id = normalize_product_id(value)
    if not product_id:
        return None
    if product_id.upper().startswith("PLID"):
        return product_id.upper()
    if re.fullmatch(r"\d{6,}", product_id):
        return f"PLID{product_id}"
    return product_id


def normalize_stock_status(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.strip().lower().replace(" ", "_").replace("-", "_")
    if "out" in lowered and "stock" in lowered:
        return "out_of_stock"
    if "in_stock" in lowered or "available" in lowered:
        return "in_stock"
    if "limited" in lowered or "low" in lowered:
        return "limited"
    return lowered or None


def takealot_category_values(
    payload: Any,
    seed: CategorySeed,
) -> tuple[str | None, str | None, str | None, str | None]:
    parts: list[str] = []
    if isinstance(payload, dict):
        breadcrumbs = payload.get("sections", {}).get("breadcrumbs", {}) if isinstance(payload.get("sections"), dict) else {}
        results = breadcrumbs.get("results") if isinstance(breadcrumbs, dict) else None
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                breadcrumb = item.get("breadcrumb")
                if not isinstance(breadcrumb, dict):
                    continue
                value = text_value(breadcrumb, "display_value")
                if value:
                    parts.append(value)
    return category_tuple_from_parts(parts, seed)


def category_tuple_from_parts(
    parts: list[str],
    seed: CategorySeed,
) -> tuple[str | None, str | None, str | None, str | None]:
    cleaned = [part for part in parts if part]
    return (
        seed.main_category or (cleaned[0] if len(cleaned) > 0 else None),
        seed.category_level1 or (cleaned[1] if len(cleaned) > 1 else None),
        seed.category_level2 or (cleaned[2] if len(cleaned) > 2 else None),
        seed.category_level3 or (" > ".join(cleaned[3:]) if len(cleaned) > 3 else None),
    )


def iter_product_like_dicts(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    stack = [payload]
    visited = 0
    while stack and visited < 20000:
        value = stack.pop()
        visited += 1
        if isinstance(value, list):
            stack.extend(value)
            continue
        if not isinstance(value, dict):
            continue
        if looks_like_product(value):
            candidates.append(value)
        stack.extend(value.values())
    return candidates


def looks_like_product(value: dict[str, Any]) -> bool:
    has_title = any(value.get(key) not in (None, "") for key in TITLE_KEYS)
    has_id = any(value.get(key) not in (None, "") for key in PRODUCT_ID_KEYS)
    has_price = any(value.get(key) not in (None, "") for key in PRICE_KEYS)
    url = text_value(value, "url", "href", "product_url", "productUrl")
    has_product_url = bool(url and re.search(r"/p/|PLID|\d{7,}", url, flags=re.I))
    return has_title and (has_id or has_product_url or has_price)


def normalize_product(item: dict[str, Any], seed: CategorySeed) -> ProductRecord | None:
    title = text_value(item, *TITLE_KEYS)
    if not title:
        return None

    product_id = normalize_product_id(first_present(item, *PRODUCT_ID_KEYS))
    if not product_id:
        url = text_value(item, "url", "href", "product_url", "productUrl")
        product_id = extract_product_id_from_url(url)
    if not product_id:
        return None

    review_counts = rating_counts(item)
    categories = category_values(item, seed)
    return ProductRecord(
        platform_product_id=product_id,
        title=title,
        image_url=image_url(item),
        main_category=categories[0],
        category_level1=categories[1],
        category_level2=categories[2],
        category_level3=categories[3],
        brand=text_value(item, "brand", "brand_name", "brandName"),
        currency=text_value(item, "currency") or "ZAR",
        current_price=number_value(first_present(item, *PRICE_KEYS)),
        rating=number_value(first_present(item, "rating", "star_rating", "average_rating", "averageRating")),
        total_review_count=integer_value(
            first_present(item, "total_review_count", "review_count", "reviews_count", "rating_count")
        ),
        rating_5_count=review_counts.get(5),
        rating_4_count=review_counts.get(4),
        rating_3_count=review_counts.get(3),
        rating_2_count=review_counts.get(2),
        rating_1_count=review_counts.get(1),
        latest_review_at=text_value(item, "latest_review_at", "latestReviewAt", "last_review_date"),
        stock_status=stock_status(item),
        offer_count=integer_value(first_present(item, "offer_count", "offers_count", "number_of_offers")),
        raw_payload=item,
    )


def extract_total_count(payload: Any) -> int | None:
    products_section = takealot_products_section(payload)
    if products_section:
        paging = products_section.get("paging")
        if isinstance(paging, dict):
            total = integer_value(paging.get("total_num_found"))
            if total is not None:
                return total

    stack = [payload]
    visited = 0
    while stack and visited < 5000:
        value = stack.pop()
        visited += 1
        if isinstance(value, list):
            stack.extend(value)
            continue
        if not isinstance(value, dict):
            continue
        for key in TOTAL_KEYS:
            number = integer_value(value.get(key))
            if number is not None and number >= 0:
                return number
        stack.extend(value.values())
    return None


def extract_next_after(payload: Any) -> str | None:
    products_section = takealot_products_section(payload)
    if not products_section:
        return None
    paging = products_section.get("paging")
    if not isinstance(paging, dict):
        return None
    return text_value(paging, "next_is_after")


def extract_latest_review_at(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        return None
    for review in reviews:
        if not isinstance(review, dict):
            continue
        parsed = parse_takealot_review_date(text_value(review, "date"))
        if parsed:
            return parsed
    return None


def parse_takealot_review_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    for pattern in ("%d %b %Y", "%d %B %Y"):
        try:
            parsed = datetime.strptime(text, pattern).replace(tzinfo=UTC)
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def compact_latest_review_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    reviews = payload.get("reviews")
    first_review = reviews[0] if isinstance(reviews, list) and reviews else None
    return {
        "first_review": first_review,
        "page_info": payload.get("page_info"),
        "sort_options": payload.get("sort_options"),
    }


def dedupe_records(records: list[ProductRecord], seen: set[str]) -> list[ProductRecord]:
    output: list[ProductRecord] = []
    for record in records:
        if record.platform_product_id in seen:
            continue
        seen.add(record.platform_product_id)
        output.append(record)
    return output


def category_values(
    item: dict[str, Any],
    seed: CategorySeed,
) -> tuple[str | None, str | None, str | None, str | None]:
    path = first_present(item, "category_path", "categories", "breadcrumbs")
    parts: list[str] = []
    if isinstance(path, str):
        parts = [part.strip() for part in re.split(r">|/|\|", path) if part.strip()]
    elif isinstance(path, list):
        for value in path:
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif isinstance(value, dict):
                text = text_value(value, "name", "title", "label")
                if text:
                    parts.append(text)
    return (
        text_value(item, "main_category") or seed.main_category or (parts[0] if len(parts) > 0 else None),
        text_value(item, "category_level1") or seed.category_level1 or (parts[1] if len(parts) > 1 else None),
        text_value(item, "category_level2") or seed.category_level2 or (parts[2] if len(parts) > 2 else None),
        text_value(item, "category_level3") or seed.category_level3 or (parts[3] if len(parts) > 3 else None),
    )


def image_url(item: dict[str, Any]) -> str | None:
    direct = text_value(item, *IMAGE_KEYS)
    if direct:
        return normalize_url(direct)
    for key in ("image", "images", "media"):
        found = image_url_from_unknown(item.get(key))
        if found:
            return found
    return None


def image_url_from_unknown(value: Any) -> str | None:
    if isinstance(value, str):
        return normalize_url(value)
    if isinstance(value, list):
        for item in value:
            found = image_url_from_unknown(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("url", "src", "href", "image_url", "thumbnail", "large", "medium"):
            found = image_url_from_unknown(value.get(key))
            if found:
                return found
    return None


def rating_counts(item: dict[str, Any]) -> dict[int, int | None]:
    output: dict[int, int | None] = {
        5: integer_value(first_present(item, "rating_5_count", "five_star_count", "rating5")),
        4: integer_value(first_present(item, "rating_4_count", "four_star_count", "rating4")),
        3: integer_value(first_present(item, "rating_3_count", "three_star_count", "rating3")),
        2: integer_value(first_present(item, "rating_2_count", "two_star_count", "rating2")),
        1: integer_value(first_present(item, "rating_1_count", "one_star_count", "rating1")),
    }
    nested = first_present(item, "rating_counts", "ratings", "review_summary", "reviewSummary")
    if isinstance(nested, dict):
        for star in range(1, 6):
            output[star] = output[star] or integer_value(
                first_present(nested, str(star), f"{star}_star", f"star_{star}")
            )
    return output


def stock_status(item: dict[str, Any]) -> str | None:
    direct = text_value(item, "stock_status", "stockStatus", "availability", "availability_status")
    if direct:
        lowered = direct.lower().replace(" ", "_").replace("-", "_")
        if "out" in lowered and "stock" in lowered:
            return "out_of_stock"
        if "limited" in lowered or "low" in lowered:
            return "limited"
        if "available" in lowered or "in_stock" in lowered:
            return "in_stock"
        return lowered
    stock = integer_value(first_present(item, "stock", "stock_quantity", "quantity_available"))
    if stock is None:
        return None
    if stock <= 0:
        return "out_of_stock"
    if stock <= 5:
        return "limited"
    return "in_stock"


def first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def text_value(item: dict[str, Any], *keys: str) -> str | None:
    value = first_present(item, *keys)
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def number_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        value = first_present(value, "value", "amount", "price")
    if isinstance(value, str):
        value = re.sub(r"[^\d.\-]", "", value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def integer_value(value: Any) -> int | None:
    number = number_value(value)
    if number is None:
        return None
    return int(number)


def normalize_product_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"true", "false", "none", "null"}:
        return None
    return text


def extract_product_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    for pattern in (r"(PLID\d+)", r"/p/([^/?#]+)", r"(\d{7,})"):
        match = re.search(pattern, url, flags=re.I)
        if match:
            return match.group(1)
    return f"url:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"


def normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.startswith("//"):
        return f"https:{text}"
    return text


def html_unescape(value: str) -> str:
    return value.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or stable_short_name(value)


def stable_short_name(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def redact_url(url: str) -> str:
    return re.sub(r"([?&](?:token|cookie|session|key|auth)=[^&]+)", r"\1<redacted>", url, flags=re.I)


def normalize_db_json(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (
            item.isoformat()
            if isinstance(item, (datetime, date))
            else item
        )
        for key, item in value.items()
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl Takealot public product data into selection library")
    parser.add_argument(
        "--url-template",
        default=os.environ.get("XH_TAKEALOT_SELECTION_URL_TEMPLATE", ""),
        help=(
            "URL template. Supported placeholders: {category}, {category_slug}, "
            "{department_slug}, {price_filter}, {min_price}, {max_price}, "
            "{page}, {page_size}, {limit}, {offset}, {after}."
        ),
    )
    parser.add_argument(
        "--detail-url-template",
        default=os.environ.get("XH_TAKEALOT_SELECTION_DETAIL_URL_TEMPLATE", ""),
        help=(
            "Optional product-details URL template. Supported placeholders: "
            "{platform_product_id}, {plid}, {plid_numeric}, {numeric_plid}, "
            "{title_slug}, {brand}, {variant}, {size}."
        ),
    )
    parser.add_argument(
        "--review-url-template",
        default=os.environ.get("XH_TAKEALOT_SELECTION_REVIEW_URL_TEMPLATE", ""),
        help=(
            "Optional product-reviews URL template for latest review time. Supported placeholders: "
            "{platform_product_id}, {plid}, {plid_numeric}, {numeric_plid}, {title_slug}, {brand}."
        ),
    )
    parser.add_argument("--categories-file", help="CSV or JSON seed file with category/url columns")
    parser.add_argument(
        "--category",
        action="append",
        help="Category seed as name or name|category_ref|department_slug|main|level1|level2|level3",
    )
    parser.add_argument("--seed-url", action="append", help="Direct seed URL as url or name|url")
    parser.add_argument("--price-ranges", help="Explicit ranges, e.g. 0:50,50:100,100:200")
    parser.add_argument("--price-profile", choices=["takealot", "linear"], default="takealot")
    parser.add_argument("--price-min", type=float, default=0)
    parser.add_argument("--price-max", type=float, default=100000)
    parser.add_argument("--initial-price-step", type=float, default=100)
    parser.add_argument("--min-price-width", type=float, default=10)
    parser.add_argument("--page-size", type=int, default=36)
    parser.add_argument("--max-pages-per-bucket", type=int, default=20)
    parser.add_argument("--pagination-mode", choices=["auto", "cursor", "page"], default="auto")
    parser.add_argument("--split-threshold", type=int, default=900)
    parser.add_argument("--max-split-depth", type=int, default=5)
    parser.add_argument("--max-buckets", type=int, default=500)
    parser.add_argument("--max-products", type=int, default=10000)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--detail-concurrency", type=int, default=8)
    parser.add_argument("--flush-size", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--request-delay-ms", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-delay-ms", type=int, default=1000)
    parser.add_argument("--retry-max-delay-ms", type=int, default=12000)
    parser.add_argument(
        "--raw-payload-mode",
        choices=["none", "compact", "full"],
        default="compact",
        help="How much raw API payload to store in snapshots. Use none for fastest full-site discovery.",
    )
    parser.add_argument("--output-jsonl", help="Also write parsed product records to a local JSONL file")
    parser.add_argument("--headers-json", help="JSON file with HTTP headers")
    parser.add_argument("--cookie", help="Cookie header value")
    parser.add_argument("--cookie-env", default="XH_TAKEALOT_SELECTION_COOKIE")
    parser.add_argument("--snapshot-week", default=date.today().isoformat())
    parser.add_argument("--skip-snapshots", action="store_true", help="Only upsert selection_products; do not write weekly snapshot rows")
    parser.add_argument("--heartbeat-buckets", type=int, default=10)
    parser.add_argument(
        "--skip-mark-running",
        action="store_true",
        help="Skip per-bucket running updates; faster for long single-worker full-site crawls.",
    )
    parser.add_argument("--resume-run-id", help="Resume queued/running/failed buckets from a previous ingest run")
    parser.add_argument("--status-run-id", help="Print ingest run and bucket status, then exit")
    parser.add_argument("--preview-urls", type=int, default=0, help="Print concrete list/detail URLs, then exit")
    parser.add_argument("--inspect-url", help="Fetch one URL and show parsed product fields, then exit")
    parser.add_argument("--inspect-category", help="Category label used while inspecting one URL")
    parser.add_argument("--plan-only", action="store_true", help="Create the ingest run and bucket plan, then exit")
    parser.add_argument("--no-persist-plan", action="store_true", help="Keep bucket plan only in memory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-short-page-stop", action="store_true")
    return parser


def print_run_status(ingest_run_id: str) -> None:
    with get_db_session() as connection:
        with connection.cursor() as cursor:
            run = cursor.execute(
                """
                select id, status, discovered_count, processed_count, failed_count,
                       category_bucket_count, price_bucket_count, started_at,
                       finished_at, error_message, metadata, created_at, updated_at
                from selection_ingest_runs
                where id = %s
                """,
                (ingest_run_id,),
            ).fetchone()
            if run is None:
                raise SystemExit(f"Selection ingest run not found: {ingest_run_id}")
            bucket_rows = cursor.execute(
                """
                select status, count(*) as count,
                       coalesce(sum(discovered_count), 0) as discovered,
                       coalesce(sum(persisted_count), 0) as persisted,
                       coalesce(sum(failed_count), 0) as failed
                from selection_ingest_buckets
                where ingest_run_id = %s
                group by status
                order by status
                """,
                (ingest_run_id,),
            ).fetchall()
            failures = cursor.execute(
                """
                select bucket_key, status, error_message, updated_at
                from selection_ingest_buckets
                where ingest_run_id = %s
                  and status = 'failed'
                order by updated_at desc
                limit 5
                """,
                (ingest_run_id,),
            ).fetchall()
            connection.rollback()

    print(
        json.dumps(
            {
                "run": normalize_db_json(dict(run)),
                "buckets": [normalize_db_json(dict(row)) for row in bucket_rows],
                "recent_failures": [normalize_db_json(dict(row)) for row in failures],
            },
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )


def print_preview_urls(args: argparse.Namespace, limit: int) -> None:
    seeds = load_seeds(args)
    buckets = initial_buckets(seeds, args)
    urls: list[dict[str, Any]] = []
    for bucket in buckets:
        if len(urls) >= limit:
            break
        urls.append(
            {
                "type": "list",
                "bucket": bucket.key,
                "url": render_url(args.url_template, bucket, 1, args.page_size),
            }
        )
    if args.detail_url_template:
        sample = ProductRecord(
            platform_product_id="PLID00000000",
            title="sample product",
            brand="sample",
        )
        urls.append(
            {
                "type": "detail_sample",
                "url": render_detail_url(args.detail_url_template, sample),
            }
        )
    if args.review_url_template:
        sample = ProductRecord(
            platform_product_id="PLID00000000",
            title="sample product",
            brand="sample",
        )
        urls.append(
            {
                "type": "review_sample",
                "url": render_record_url(args.review_url_template, sample),
            }
        )
    print(json.dumps({"urls": urls}, ensure_ascii=False, indent=2), flush=True)


def inspect_url(args: argparse.Namespace) -> None:
    category = args.inspect_category or "inspect"
    seed = CategorySeed(name=category, category_ref=slugify(category))
    headers = load_headers(args)
    with httpx.Client(headers=headers, timeout=args.timeout, follow_redirects=True) as client:
        try:
            response = client.get(args.inspect_url)
            text_preview = response.text[:500]
            payload: Any = None
            records: list[ProductRecord] = []
            total_count: int | None = None
            latest_review_at: str | None = None
            parse_error: str | None = None
            try:
                payload = parse_response_payload(response)
                records = extract_records(payload, seed)
                total_count = extract_total_count(payload)
                latest_review_at = extract_latest_review_at(payload)
            except Exception as exc:
                parse_error = str(exc)
            first_record = records[0].to_json() if records else None
            if first_record is not None:
                first_record["raw_payload"] = compact_raw_payload(first_record.get("raw_payload"))
            result = {
                "url": redact_url(str(response.url)),
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "content_length": len(response.content),
                "payload_shape": payload_shape(payload),
                "total_count": total_count,
                "latest_review_at": latest_review_at,
                "record_count": len(records),
                "first_record": first_record,
                "parse_error": parse_error,
                "text_preview": text_preview,
            }
        except httpx.HTTPError as exc:
            result = {
                "url": redact_url(args.inspect_url),
                "error": type(exc).__name__,
                "message": str(exc),
            }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)


def compact_raw_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: value[key] for key in list(value.keys())[:30]}


def payload_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "first": payload_shape(value[0]) if value else None,
        }
    if isinstance(value, dict):
        keys = list(value.keys())
        return {
            "type": "dict",
            "keys": keys[:30],
            "key_count": len(keys),
        }
    return {"type": type(value).__name__}


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    if not args.resume_run_id and not args.url_template and not args.seed_url and not args.categories_file:
        raise SystemExit("Provide --url-template, --seed-url, or a seed file with url values.")
    snapshot_week = date.fromisoformat(args.snapshot_week)
    writer = SelectionWriter(
        dry_run=args.dry_run,
        snapshot_week=snapshot_week,
        output_jsonl=args.output_jsonl,
        skip_snapshots=args.skip_snapshots,
    )
    metadata: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "price_ranges": args.price_ranges,
        "price_min": args.price_min,
        "price_max": args.price_max,
        "initial_price_step": args.initial_price_step,
        "page_size": args.page_size,
        "pagination_mode": args.pagination_mode,
        "concurrency": args.concurrency,
        "detail_concurrency": args.detail_concurrency,
        "has_detail_template": bool(args.detail_url_template),
        "has_review_template": bool(args.review_url_template),
        "max_retries": args.max_retries,
        "retry_base_delay_ms": args.retry_base_delay_ms,
        "retry_max_delay_ms": args.retry_max_delay_ms,
        "raw_payload_mode": args.raw_payload_mode,
        "skip_snapshots": args.skip_snapshots,
        "output_jsonl": args.output_jsonl,
        "max_products": args.max_products,
        "headers": sorted(key for key in load_headers(args) if key.lower() != "cookie"),
    }
    if args.resume_run_id:
        writer.resume(args.resume_run_id)
        buckets = writer.load_resumable_buckets()
        metadata["resume_run_id"] = args.resume_run_id
        metadata["resumable_bucket_count"] = len(buckets)
    else:
        seeds = load_seeds(args)
        metadata["seed_count"] = len(seeds)
        writer.start(metadata)
        buckets = initial_buckets(seeds, args)
        if not args.no_persist_plan:
            buckets = writer.persist_bucket_plan(buckets)
            writer.bucket_count = len(buckets)

    if args.plan_only:
        writer.pause(status="queued", metadata={"planned_bucket_count": len(buckets)})
        summary = {
            "ingest_run_id": writer.ingest_run_id,
            "dry_run": writer.dry_run,
            "plan_only": True,
            "bucket_count": len(buckets),
        }
        return summary

    crawler = TakealotSelectionCrawler(args, writer)
    try:
        summary = await crawler.run(buckets)
    except Exception as exc:
        writer.finish(status="failed", metadata={"failed_at": datetime.now(UTC).isoformat()}, error_message=str(exc))
        raise
    final_status = "failed" if writer.persisted_count == 0 and writer.failed_count > 0 else "succeeded"
    writer.finish(status=final_status, metadata=summary)
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.status_run_id:
        print_run_status(args.status_run_id)
        return
    if args.preview_urls > 0:
        print_preview_urls(args, args.preview_urls)
        return
    if args.inspect_url:
        inspect_url(args)
        return
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.detail_concurrency < 1:
        raise SystemExit("--detail-concurrency must be >= 1")
    if args.max_products < 1:
        raise SystemExit("--max-products must be >= 1")
    if args.flush_size < 1:
        raise SystemExit("--flush-size must be >= 1")
    summary = asyncio.run(async_main(args))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
