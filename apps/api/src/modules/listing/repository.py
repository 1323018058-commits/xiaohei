from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from psycopg import Error as PsycopgError
from psycopg.types.json import Jsonb

from src.platform.db.session import get_db_session


CATALOG_IMPORT_REQUIRED_MESSAGE = "需要导入 Takealot 类目库"
CATALOG_DATABASE_UNAVAILABLE_MESSAGE = "无法读取 PostgreSQL Takealot 类目库，需要先运行迁移并导入类目库"
LOADSHEET_SUBMIT_CLAIMABLE_STATUSES = {"content_queued", "content_submit_failed", "queue_failed", "content_submitting"}
LOADSHEET_SUBMIT_CLAIMABLE_STAGES = {"queued", "failed", "submitting"}
OFFER_FINALIZE_TERMINAL_STATUSES = {"offer_submitting", "offer_submitted"}
JSON_EMBEDDING_FALLBACK_PAGE_SIZE = 1000
JSON_EMBEDDING_FALLBACK_WARNING_THRESHOLD = 10000


class ListingCatalogUnavailable(RuntimeError):
    def __init__(self, message: str = CATALOG_DATABASE_UNAVAILABLE_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


class ListingCatalogRepository:
    def get_store_tenant_id(self, store_id: str) -> str | None:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        "select tenant_id::text as tenant_id from stores where id = %s",
                        (store_id,),
                    ).fetchone()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return row["tenant_id"] if row else None

    def insert_listing_asset(
        self,
        *,
        tenant_id: str,
        store_id: str,
        submission_id: str | None,
        asset: dict[str, Any],
        sort_order: int = 0,
    ) -> dict[str, Any]:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        """
                        insert into listing_assets (
                          tenant_id,
                          store_id,
                          submission_id,
                          asset_type,
                          source,
                          original_file_name,
                          file_name,
                          storage_path,
                          public_url,
                          external_url,
                          content_type,
                          size_bytes,
                          checksum_sha256,
                          width,
                          height,
                          sort_order,
                          validation_status,
                          validation_errors,
                          raw_payload
                        )
                        values (
                          %(tenant_id)s,
                          %(store_id)s,
                          %(submission_id)s,
                          %(asset_type)s,
                          %(source)s,
                          %(original_file_name)s,
                          %(file_name)s,
                          %(storage_path)s,
                          %(public_url)s,
                          %(external_url)s,
                          %(content_type)s,
                          %(size_bytes)s,
                          %(checksum_sha256)s,
                          %(width)s,
                          %(height)s,
                          %(sort_order)s,
                          %(validation_status)s,
                          %(validation_errors)s,
                          %(raw_payload)s
                        )
                        returning
                          id::text,
                          tenant_id::text,
                          store_id::text,
                          submission_id::text,
                          asset_type,
                          source,
                          original_file_name,
                          file_name,
                          storage_path,
                          public_url,
                          external_url,
                          content_type,
                          size_bytes,
                          checksum_sha256,
                          width,
                          height,
                          sort_order,
                          validation_status,
                          validation_errors,
                          raw_payload,
                          created_at,
                          updated_at
                        """,
                        {
                            "tenant_id": tenant_id,
                            "store_id": store_id,
                            "submission_id": submission_id,
                            "asset_type": asset.get("asset_type", "image"),
                            "source": asset.get("source", "upload"),
                            "original_file_name": asset.get("original_file_name"),
                            "file_name": asset.get("file_name"),
                            "storage_path": asset.get("storage_path"),
                            "public_url": asset.get("public_url"),
                            "external_url": asset.get("external_url"),
                            "content_type": asset.get("content_type"),
                            "size_bytes": asset.get("size_bytes"),
                            "checksum_sha256": asset.get("checksum_sha256"),
                            "width": asset.get("width"),
                            "height": asset.get("height"),
                            "sort_order": sort_order,
                            "validation_status": asset.get("validation_status", "pending"),
                            "validation_errors": Jsonb(asset.get("validation_errors") or []),
                            "raw_payload": Jsonb(asset.get("raw_payload") or {}),
                        },
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_asset(row)

    def list_listing_assets_by_ids(
        self,
        *,
        asset_ids: list[str],
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ids = self._dedupe_terms(asset_ids)
        if not ids:
            return []
        where_tenant = "and tenant_id = %s" if tenant_id else ""
        params: list[Any] = [ids]
        if tenant_id:
            params.append(tenant_id)
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    rows = cursor.execute(
                        f"""
                        select
                          id::text,
                          tenant_id::text,
                          store_id::text,
                          submission_id::text,
                          asset_type,
                          source,
                          original_file_name,
                          file_name,
                          storage_path,
                          public_url,
                          external_url,
                          content_type,
                          size_bytes,
                          checksum_sha256,
                          width,
                          height,
                          sort_order,
                          validation_status,
                          validation_errors,
                          raw_payload,
                          created_at,
                          updated_at
                        from listing_assets
                        where id = any(%s::uuid[])
                        {where_tenant}
                        order by sort_order asc, created_at asc
                        """,
                        params,
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return [self._normalize_asset(row) for row in rows]

    def recall_category_candidates(
        self,
        *,
        keywords: list[str],
        limit: int = 80,
    ) -> tuple[list[dict[str, Any]], bool]:
        terms = self._dedupe_terms(keywords)
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    catalog_ready = self._has_rows(cursor, "takealot_categories")
                    if not terms:
                        return [], catalog_ready
                    where_sql, where_params = self._category_recall_where(terms)
                    rows = cursor.execute(
                        f"""
                        {self._category_select_sql()}
                        {where_sql}
                        order by
                          {self._category_recall_rank_sql(terms)}
                          c.path_en asc
                        limit %s
                        """,
                        [
                            *where_params,
                            *self._category_recall_rank_params(terms),
                            limit,
                        ],
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc

        return [self._normalize_category(row) for row in rows], catalog_ready

    def fuzzy_recall_category_candidates(
        self,
        *,
        keywords: list[str],
        limit: int = 160,
    ) -> tuple[list[dict[str, Any]], bool]:
        terms = [
            term
            for term in self._dedupe_terms(keywords)
            if len(term) >= 2 and not re.fullmatch(r"[\u4e00-\u9fff]+", term)
        ][:16]
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    catalog_ready = self._has_rows(cursor, "takealot_categories")
                    if not terms:
                        return [], catalog_ready
                    score_sql, score_params = self._category_fuzzy_score_sql(terms)
                    rows = cursor.execute(
                        f"""
                        {self._category_select_sql(extra_columns=f", {score_sql} as fuzzy_score")}
                        order by
                          fuzzy_score desc,
                          c.min_required_images desc,
                          c.path_en asc
                        limit %s
                        """,
                        [*score_params, limit],
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc

        return [self._normalize_category(row) for row in rows], catalog_ready

    def upsert_category_embedding(
        self,
        *,
        category_id: int,
        embedding_model: str,
        embedding_dimensions: int,
        embedding_text: str,
        embedding_vector: list[float],
        embedding_hash: str,
    ) -> dict[str, Any]:
        normalized_vector = self._normalize_vector(embedding_vector)
        if len(normalized_vector) != embedding_dimensions:
            raise ValueError("embedding_vector length must match embedding_dimensions")
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    if not self._table_exists(cursor, "takealot_category_embeddings"):
                        raise ListingCatalogUnavailable("takealot_category_embeddings table missing; run migrations")
                    has_pgvector = embedding_dimensions == 1024 and self._embedding_vector_pg_available(cursor)
                    if has_pgvector:
                        row = cursor.execute(
                            """
                            insert into takealot_category_embeddings (
                              category_id,
                              embedding_model,
                              embedding_dimensions,
                              embedding_text,
                              embedding_vector,
                              embedding_vector_pg,
                              embedding_hash
                            )
                            values (%s, %s, %s, %s, %s, %s::vector, %s)
                            on conflict (category_id, embedding_model, embedding_dimensions)
                            do update set
                              embedding_text = excluded.embedding_text,
                              embedding_vector = excluded.embedding_vector,
                              embedding_vector_pg = excluded.embedding_vector_pg,
                              embedding_hash = excluded.embedding_hash,
                              updated_at = now()
                            returning
                              id::text,
                              category_id,
                              embedding_model,
                              embedding_dimensions,
                              embedding_text,
                              embedding_hash,
                              created_at,
                              updated_at
                            """,
                            (
                                category_id,
                                embedding_model,
                                embedding_dimensions,
                                embedding_text,
                                Jsonb(normalized_vector),
                                self._vector_literal(normalized_vector),
                                embedding_hash,
                            ),
                        ).fetchone()
                    else:
                        row = cursor.execute(
                            """
                            insert into takealot_category_embeddings (
                              category_id,
                              embedding_model,
                              embedding_dimensions,
                              embedding_text,
                              embedding_vector,
                              embedding_hash
                            )
                            values (%s, %s, %s, %s, %s, %s)
                            on conflict (category_id, embedding_model, embedding_dimensions)
                            do update set
                              embedding_text = excluded.embedding_text,
                              embedding_vector = excluded.embedding_vector,
                              embedding_hash = excluded.embedding_hash,
                              updated_at = now()
                            returning
                              id::text,
                              category_id,
                              embedding_model,
                              embedding_dimensions,
                              embedding_text,
                              embedding_hash,
                              created_at,
                              updated_at
                            """,
                            (
                                category_id,
                                embedding_model,
                                embedding_dimensions,
                                embedding_text,
                                Jsonb(normalized_vector),
                                embedding_hash,
                            ),
                        ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return dict(row)

    def get_categories_missing_embeddings(
        self,
        *,
        embedding_model: str,
        embedding_dimensions: int,
        limit: int = 100,
        include_existing: bool = False,
    ) -> list[dict[str, Any]]:
        where_missing = "" if include_existing else "where e.id is null"
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    if not self._table_exists(cursor, "takealot_category_embeddings"):
                        raise ListingCatalogUnavailable("takealot_category_embeddings table missing; run migrations")
                    rows = cursor.execute(
                        f"""
                        with selected_categories as (
                          select distinct on (c.category_id) c.id
                          from takealot_categories c
                          left join takealot_category_embeddings e
                            on e.category_id = c.category_id
                           and e.embedding_model = %s
                           and e.embedding_dimensions = %s
                          {where_missing}
                          order by c.category_id asc, c.updated_at desc, c.path_en asc
                          limit %s
                        )
                        {self._category_select_sql()}
                        join selected_categories sc on sc.id = c.id
                        left join takealot_category_embeddings e
                          on e.category_id = c.category_id
                         and e.embedding_model = %s
                         and e.embedding_dimensions = %s
                        order by c.category_id asc
                        """,
                        (
                            embedding_model,
                            embedding_dimensions,
                            limit,
                            embedding_model,
                            embedding_dimensions,
                        ),
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return [self._normalize_category(row) for row in rows]

    def search_category_embeddings(
        self,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_dimensions: int,
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_vector = self._normalize_vector(query_vector)
        if len(normalized_vector) != embedding_dimensions:
            return []
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    if not self._table_exists(cursor, "takealot_category_embeddings"):
                        return []
                    if embedding_dimensions == 1024 and self._embedding_vector_pg_available(cursor):
                        return self._search_category_embeddings_pgvector(
                            cursor,
                            query_vector=normalized_vector,
                            embedding_model=embedding_model,
                            embedding_dimensions=embedding_dimensions,
                            top_k=top_k,
                        )
                    return self._search_category_embeddings_json(
                        cursor,
                        query_vector=normalized_vector,
                        embedding_model=embedding_model,
                        embedding_dimensions=embedding_dimensions,
                        top_k=top_k,
                    )
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc

    def has_category_embeddings(
        self,
        *,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> bool:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    if not self._table_exists(cursor, "takealot_category_embeddings"):
                        return False
                    row = cursor.execute(
                        """
                        select exists(
                          select 1
                          from takealot_category_embeddings
                          where embedding_model = %s
                            and embedding_dimensions = %s
                            and jsonb_array_length(embedding_vector) = %s
                          limit 1
                        ) as has_embeddings
                        """,
                        (embedding_model, embedding_dimensions, embedding_dimensions),
                    ).fetchone()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return bool(row and row["has_embeddings"])

    def search_categories(
        self,
        *,
        query: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        query_text = (query or "").strip()
        offset = (page - 1) * page_size
        where_sql, where_params = self._category_where(query_text)

        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    total_row = cursor.execute(
                        f"select count(*) as total from takealot_categories c {where_sql}",
                        where_params,
                    ).fetchone()
                    total = int(total_row["total"] if total_row else 0)
                    catalog_ready = total > 0 or self._has_rows(cursor, "takealot_categories")
                    rows = cursor.execute(
                        f"""
                        {self._category_select_sql()}
                        {where_sql}
                        {self._category_order_sql(query_text)}
                        limit %s offset %s
                        """,
                        [
                            *where_params,
                            *self._category_order_params(query_text),
                            page_size,
                            offset,
                        ],
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc

        return [self._normalize_category(row, query_text=query_text) for row in rows], total, catalog_ready

    def get_category_requirements(self, category_id: int) -> tuple[dict[str, Any] | None, bool]:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        {self._category_select_sql(extra_columns=", count(*) over() as matching_variants")}
                        where c.category_id = %s
                        order by c.updated_at desc, c.path_en asc
                        limit 1
                        """,
                        (category_id,),
                    ).fetchone()
                    catalog_ready = row is not None or self._has_rows(cursor, "takealot_categories")
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc

        if row is None:
            return None, catalog_ready
        return self._normalize_category(row, include_raw=True), catalog_ready

    def search_brands(
        self,
        *,
        query: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        query_text = (query or "").strip()
        offset = (page - 1) * page_size
        where_sql, where_params = self._brand_where(query_text)

        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    total_row = cursor.execute(
                        f"select count(*) as total from takealot_brands b {where_sql}",
                        where_params,
                    ).fetchone()
                    total = int(total_row["total"] if total_row else 0)
                    catalog_ready = total > 0 or self._has_rows(cursor, "takealot_brands")
                    rows = cursor.execute(
                        f"""
                        select
                          b.id::text as id,
                          b.brand_id,
                          b.brand_name
                        from takealot_brands b
                        {where_sql}
                        {self._brand_order_sql(query_text)}
                        limit %s offset %s
                        """,
                        [
                            *where_params,
                            *self._brand_order_params(query_text),
                            page_size,
                            offset,
                        ],
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc

        return [self._normalize_brand(row, query_text=query_text) for row in rows], total, catalog_ready

    def find_brand(
        self,
        *,
        brand_id: str | None = None,
        brand_name: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        brand_id_text = (brand_id or "").strip()
        brand_name_text = (brand_name or "").strip()
        if not brand_id_text and not brand_name_text:
            return None, True

        conditions: list[str] = []
        params: list[Any] = []
        if brand_id_text:
            conditions.append("b.brand_id = %s")
            params.append(brand_id_text)
        if brand_name_text:
            conditions.append("lower(b.brand_name) = %s")
            params.append(brand_name_text.lower())

        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        select
                          b.id::text as id,
                          b.brand_id,
                          b.brand_name
                        from takealot_brands b
                        where {" or ".join(conditions)}
                        order by
                          case
                            when b.brand_id = %s then 0
                            when lower(b.brand_name) = %s then 1
                            else 2
                          end,
                          b.brand_name asc
                        limit 1
                        """,
                        [*params, brand_id_text, brand_name_text.lower()],
                    ).fetchone()
                    catalog_ready = row is not None or self._has_rows(cursor, "takealot_brands")
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc

        if row is None:
            return None, catalog_ready
        return self._normalize_brand(row), catalog_ready

    def create_listing_submission(
        self,
        *,
        submission: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        insert into listing_submissions (
                          tenant_id,
                          store_id,
                          idempotency_key,
                          platform,
                          sku,
                          barcode,
                          title,
                          subtitle,
                          description,
                          whats_in_the_box,
                          category_id,
                          takealot_category_row_id,
                          category_path,
                          brand_id,
                          brand_name,
                          selling_price,
                          rrp,
                          stock_quantity,
                          minimum_leadtime_days,
                          seller_warehouse_id,
                          length_cm,
                          width_cm,
                          height_cm,
                          weight_kg,
                          image_urls,
                          dynamic_attributes,
                          content_payload,
                          loadsheet_payload,
                          official_response,
                          status,
                          stage,
                          review_status
                        )
                        values (
                          %(tenant_id)s,
                          %(store_id)s,
                          %(idempotency_key)s,
                          'takealot',
                          %(sku)s,
                          %(barcode)s,
                          %(title)s,
                          %(subtitle)s,
                          %(description)s,
                          %(whats_in_the_box)s,
                          %(category_id)s,
                          %(takealot_category_row_id)s,
                          %(category_path)s,
                          %(brand_id)s,
                          %(brand_name)s,
                          %(selling_price)s,
                          %(rrp)s,
                          %(stock_quantity)s,
                          %(minimum_leadtime_days)s,
                          %(seller_warehouse_id)s,
                          %(length_cm)s,
                          %(width_cm)s,
                          %(height_cm)s,
                          %(weight_kg)s,
                          %(image_urls)s,
                          %(dynamic_attributes)s,
                          %(content_payload)s,
                          %(loadsheet_payload)s,
                          %(official_response)s,
                          %(status)s,
                          %(stage)s,
                          %(review_status)s
                        )
                        on conflict (store_id, idempotency_key)
                        where idempotency_key is not null
                        do update set
                          -- A duplicate client retry reuses the existing row
                          -- without mutating payload or queuing another task.
                          idempotency_key = listing_submissions.idempotency_key
                        returning {self._submission_returning_columns()},
                          (xmax = 0) as inserted
                        """,
                        {
                            **submission,
                            "image_urls": Jsonb(submission.get("image_urls") or []),
                            "dynamic_attributes": Jsonb(submission.get("dynamic_attributes") or {}),
                            "content_payload": Jsonb(submission.get("content_payload") or {}),
                            "loadsheet_payload": Jsonb(submission.get("loadsheet_payload") or {}),
                            "official_response": Jsonb(submission.get("official_response") or {}),
                        },
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        item = self._normalize_submission(row)
        item["reused_existing"] = not bool(row.get("inserted"))
        return item

    def get_listing_submission(
        self,
        submission_id: str,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        where_tenant = "and tenant_id = %s" if tenant_id else ""
        params: list[Any] = [submission_id]
        if tenant_id:
            params.append(tenant_id)
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        select {self._submission_returning_columns()}
                        from listing_submissions
                        where id = %s
                        {where_tenant}
                        """,
                        params,
                    ).fetchone()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_submission(row) if row else None

    def list_listing_submissions(
        self,
        *,
        store_id: str,
        tenant_id: str | None,
        status_filter: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = ["store_id = %s"]
        params: list[Any] = [store_id]
        if tenant_id:
            filters.append("tenant_id = %s")
            params.append(tenant_id)
        if status_filter:
            filters.append("status = %s")
            params.append(status_filter)
        where_sql = " and ".join(filters)
        offset = (page - 1) * page_size
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    total_row = cursor.execute(
                        f"select count(*) as total from listing_submissions where {where_sql}",
                        params,
                    ).fetchone()
                    rows = cursor.execute(
                        f"""
                        select {self._submission_returning_columns()}
                        from listing_submissions
                        where {where_sql}
                        order by created_at desc, id desc
                        limit %s offset %s
                        """,
                        [*params, page_size, offset],
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return [self._normalize_submission(row) for row in rows], int(total_row["total"] if total_row else 0)

    def update_listing_submission_task_id(
        self,
        *,
        submission_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        return self._update_submission(
            submission_id,
            processing_task_id=task_id,
            status="content_queued",
            stage="queued",
        )

    def update_listing_submission_loadsheet_payload(
        self,
        *,
        submission_id: str,
        loadsheet_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._update_submission(
            submission_id,
            loadsheet_payload=Jsonb(loadsheet_payload),
        )

    def update_listing_submission_status(
        self,
        *,
        submission_id: str,
        status: str,
        stage: str,
        error_code: str | None = None,
        error_message: str | None = None,
        official_response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        changes: dict[str, Any] = {
            "status": status,
            "stage": stage,
            "error_code": error_code,
            "error_message": error_message,
            "last_checked_at": "now()",
        }
        if official_response is not None:
            changes["official_response"] = Jsonb(official_response)
        return self._update_submission(submission_id, **changes)

    def claim_listing_submission_submit(
        self,
        *,
        submission_id: str,
        task_id: str,
        claim_token: str,
        claim_expires_at: datetime,
    ) -> dict[str, Any] | None:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set status = 'content_submitting',
                            stage = 'submitting',
                            processing_task_id = %s,
                            loadsheet_submit_claim_task_id = %s,
                            loadsheet_submit_claim_token = %s,
                            loadsheet_submit_claim_expires_at = %s,
                            error_code = null,
                            error_message = null,
                            last_checked_at = now(),
                            updated_at = now()
                        where id = %s
                          and takealot_loadsheet_submission_id = ''
                          and status in ('content_queued', 'content_submit_failed', 'queue_failed', 'content_submitting')
                          and stage in ('queued', 'failed', 'submitting')
                          -- The row-level claim is the external POST boundary:
                          -- only an unclaimed or expired submission can call
                          -- Takealot. Duplicate worker tasks get no row back.
                          and (
                            loadsheet_submit_claim_token is null
                            or loadsheet_submit_claim_expires_at is null
                            or loadsheet_submit_claim_expires_at <= now()
                          )
                        returning {self._submission_returning_columns()}
                        """,
                        (task_id, task_id, claim_token, claim_expires_at, submission_id),
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_submission(row) if row else None

    def mark_listing_submission_submit_succeeded(
        self,
        *,
        submission_id: str,
        task_id: str,
        claim_token: str,
        takealot_submission_id: str,
        official_response: dict[str, Any],
        official_status: str = "",
    ) -> dict[str, Any] | None:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set status = 'content_submitted',
                            stage = 'submitted',
                            review_status = 'submitted',
                            official_status = %s,
                            takealot_loadsheet_submission_id = %s,
                            official_response = %s,
                            error_code = null,
                            error_message = null,
                            submitted_at = coalesce(submitted_at, now()),
                            last_checked_at = now(),
                            loadsheet_submit_claim_task_id = null,
                            loadsheet_submit_claim_token = null,
                            loadsheet_submit_claim_expires_at = null,
                            updated_at = now()
                        where id = %s
                          and loadsheet_submit_claim_task_id = %s
                          and loadsheet_submit_claim_token = %s
                          and takealot_loadsheet_submission_id = ''
                        returning {self._submission_returning_columns()}
                        """,
                        (
                            official_status,
                            takealot_submission_id,
                            Jsonb(official_response),
                            submission_id,
                            task_id,
                            claim_token,
                        ),
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_submission(row) if row else None

    def mark_listing_submission_submit_failed(
        self,
        *,
        submission_id: str,
        task_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
        official_response: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        assignments = [
            "status = 'content_submit_failed'",
            "stage = 'failed'",
            "error_code = %s",
            "error_message = %s",
            "last_checked_at = now()",
            "loadsheet_submit_claim_task_id = null",
            "loadsheet_submit_claim_token = null",
            "loadsheet_submit_claim_expires_at = null",
            "updated_at = now()",
        ]
        params: list[Any] = [error_code, error_message]
        if official_response is not None:
            assignments.append("official_response = %s")
            params.append(Jsonb(official_response))
        params.extend([submission_id, task_id, claim_token])
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set {", ".join(assignments)}
                        where id = %s
                          and loadsheet_submit_claim_task_id = %s
                          and loadsheet_submit_claim_token = %s
                          and takealot_loadsheet_submission_id = ''
                        returning {self._submission_returning_columns()}
                        """,
                        params,
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_submission(row) if row else None

    def update_listing_submission_official_response(
        self,
        *,
        submission_id: str,
        takealot_submission_id: str,
        official_response: dict[str, Any],
        official_status: str = "",
    ) -> dict[str, Any]:
        # This duplicate-submit path only persists the already-known Takealot
        # submission id/response. It must not demote an offer that was finalized
        # while a stale worker was still running.
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set status = case
                              when takealot_offer_id <> '' or finalized_at is not null or status = 'offer_submitted'
                                then 'offer_submitted'
                              else 'content_submitted'
                            end,
                            stage = case
                              when takealot_offer_id <> '' or finalized_at is not null or status = 'offer_submitted'
                                then 'offer_submitted'
                              else 'submitted'
                            end,
                            review_status = case
                              when takealot_offer_id <> '' or finalized_at is not null or status = 'offer_submitted'
                                then 'approved'
                              when review_status = 'approved'
                                then 'approved'
                              else 'submitted'
                            end,
                            official_status = %s,
                            takealot_loadsheet_submission_id = %s,
                            official_response = %s,
                            error_code = null,
                            error_message = null,
                            submitted_at = coalesce(submitted_at, now()),
                            last_checked_at = now(),
                            updated_at = now()
                        where id = %s
                        returning {self._submission_returning_columns()}
                        """,
                        (
                            official_status,
                            takealot_submission_id,
                            Jsonb(official_response),
                            submission_id,
                        ),
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        if row is None:
            raise ListingCatalogUnavailable("Listing submission not found")
        return self._normalize_submission(row)

    def list_submissions_due_status_sync(
        self,
        *,
        store_id: str,
        tenant_id: str | None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        filters = [
            "store_id = %s",
            "takealot_loadsheet_submission_id <> ''",
            "review_status in ('submitted', 'under_review', 'unknown', 'partial')",
        ]
        params: list[Any] = [store_id]
        if tenant_id:
            filters.append("tenant_id = %s")
            params.append(tenant_id)
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    rows = cursor.execute(
                        f"""
                        select {self._submission_returning_columns()}
                        from listing_submissions
                        where {" and ".join(filters)}
                        order by
                          case when last_status_sync_at is null then 0 else 1 end,
                          last_status_sync_at asc,
                          created_at asc
                        limit %s
                        """,
                        [*params, limit],
                    ).fetchall()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return [self._normalize_submission(row) for row in rows]

    def update_listing_submission_review_status(
        self,
        *,
        submission_id: str,
        status: str,
        stage: str,
        review_status: str,
        official_status: str,
        official_response: dict[str, Any],
    ) -> dict[str, Any]:
        # Status polling is eventually consistent. Once a submission has an
        # Offer id/finalized_at, or has already reached approved, stale pending
        # reads must not regress the local terminal state.
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set status = case
                              when takealot_offer_id <> '' or finalized_at is not null or status = 'offer_submitted'
                                then 'offer_submitted'
                              when review_status = 'approved' and %s in ('submitted', 'under_review', 'unknown')
                                then status
                              else %s
                            end,
                            stage = case
                              when takealot_offer_id <> '' or finalized_at is not null or status = 'offer_submitted'
                                then 'offer_submitted'
                              when review_status = 'approved' and %s in ('submitted', 'under_review', 'unknown')
                                then stage
                              else %s
                            end,
                            review_status = case
                              when takealot_offer_id <> '' or finalized_at is not null or status = 'offer_submitted'
                                then 'approved'
                              when review_status = 'approved' and %s in ('submitted', 'under_review', 'unknown')
                                then review_status
                              else %s
                            end,
                            official_status = %s,
                            official_response = %s,
                            error_code = null,
                            error_message = null,
                            last_checked_at = now(),
                            last_status_sync_at = now(),
                            updated_at = now()
                        where id = %s
                        returning {self._submission_returning_columns()}
                        """,
                        (
                            review_status,
                            status,
                            review_status,
                            stage,
                            review_status,
                            review_status,
                            official_status,
                            Jsonb(official_response),
                            submission_id,
                        ),
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        if row is None:
            raise ListingCatalogUnavailable("Listing submission not found")
        return self._normalize_submission(row)

    def record_listing_submission_error(
        self,
        *,
        submission_id: str,
        error_code: str,
        error_message: str,
        status: str | None = None,
        stage: str | None = None,
        official_response: dict[str, Any] | None = None,
        offer_error_message: str | None = None,
        last_status_sync_at: bool = False,
    ) -> dict[str, Any]:
        changes: dict[str, Any] = {
            "error_code": error_code,
            "error_message": error_message,
            "last_checked_at": "now()",
        }
        if status is not None:
            changes["status"] = status
        if stage is not None:
            changes["stage"] = stage
        if official_response is not None:
            changes["official_response"] = Jsonb(official_response)
        if offer_error_message is not None:
            changes["offer_error_message"] = offer_error_message
        if last_status_sync_at:
            changes["last_status_sync_at"] = "now()"
        return self._update_submission(submission_id, **changes)

    def mark_listing_submission_offer_finalizing(
        self,
        *,
        submission_id: str,
        task_id: str,
        claim_token: str,
        claim_expires_at: datetime,
    ) -> dict[str, Any] | None:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set status = 'offer_submitting',
                            stage = 'offer_submitting',
                            offer_finalize_claim_task_id = %s,
                            offer_finalize_claim_token = %s,
                            offer_finalize_claim_expires_at = %s,
                            offer_error_message = null,
                            error_code = null,
                            error_message = null,
                            last_checked_at = now(),
                            updated_at = now()
                        where id = %s
                          -- This claim is the Offer API side-effect boundary:
                          -- only one approved, unfinished row may call
                          -- create_or_update_offer. Active offer_submitting
                          -- rows are skipped; expired claims can be reclaimed.
                          and review_status = 'approved'
                          and takealot_offer_id = ''
                          and finalized_at is null
                          and (
                            status not in ('offer_submitting', 'offer_submitted')
                            or (
                              status = 'offer_submitting'
                              and offer_finalize_claim_expires_at is not null
                              and offer_finalize_claim_expires_at <= now()
                            )
                          )
                          and (
                            offer_finalize_claim_token is null
                            or offer_finalize_claim_expires_at is null
                            or offer_finalize_claim_expires_at <= now()
                          )
                        returning {self._submission_returning_columns()}
                        """,
                        (task_id, claim_token, claim_expires_at, submission_id),
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_submission(row) if row else None

    def mark_listing_submission_offer_finalized(
        self,
        *,
        submission_id: str,
        task_id: str,
        claim_token: str,
        takealot_offer_id: str,
        listing_id: str | None,
        platform_product_id: str | None,
        official_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set status = 'offer_submitted',
                            stage = 'offer_submitted',
                            review_status = 'approved',
                            takealot_offer_id = %s,
                            listing_id = %s,
                            platform_product_id = %s,
                            official_response = %s,
                            offer_error_message = null,
                            error_code = null,
                            error_message = null,
                            finalized_at = coalesce(finalized_at, now()),
                            last_checked_at = now(),
                            offer_finalize_claim_task_id = null,
                            offer_finalize_claim_token = null,
                            offer_finalize_claim_expires_at = null,
                            updated_at = now()
                        where id = %s
                          and offer_finalize_claim_task_id = %s
                          and offer_finalize_claim_token = %s
                          and takealot_offer_id = ''
                          and finalized_at is null
                        returning {self._submission_returning_columns()}
                        """,
                        (
                            takealot_offer_id,
                            listing_id,
                            platform_product_id,
                            Jsonb(official_response),
                            submission_id,
                            task_id,
                            claim_token,
                        ),
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_submission(row) if row else None

    def mark_listing_submission_offer_failed(
        self,
        *,
        submission_id: str,
        task_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
        official_response: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        assignments = [
            "status = 'offer_failed'",
            "stage = 'offer_failed'",
            "offer_error_message = %s",
            "error_code = %s",
            "error_message = %s",
            "last_checked_at = now()",
            "offer_finalize_claim_task_id = null",
            "offer_finalize_claim_token = null",
            "offer_finalize_claim_expires_at = null",
            "updated_at = now()",
        ]
        params: list[Any] = [error_message, error_code, error_message]
        if official_response is not None:
            assignments.append("official_response = %s")
            params.append(Jsonb(official_response))
        params.extend([submission_id, task_id, claim_token])
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set {", ".join(assignments)}
                        where id = %s
                          and offer_finalize_claim_task_id = %s
                          and offer_finalize_claim_token = %s
                          and takealot_offer_id = ''
                          and finalized_at is null
                        returning {self._submission_returning_columns()}
                        """,
                        params,
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_submission(row) if row else None

    def attach_loadsheet_asset_to_submission(
        self,
        *,
        asset_id: str,
        submission_id: str,
    ) -> dict[str, Any]:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        """
                        update listing_assets
                        set submission_id = %s,
                            updated_at = now()
                        where id = %s
                          and asset_type = 'loadsheet'
                        returning
                          id::text,
                          tenant_id::text,
                          store_id::text,
                          submission_id::text,
                          asset_type,
                          source,
                          original_file_name,
                          file_name,
                          storage_path,
                          public_url,
                          external_url,
                          content_type,
                          size_bytes,
                          checksum_sha256,
                          width,
                          height,
                          sort_order,
                          validation_status,
                          validation_errors,
                          raw_payload,
                          created_at,
                          updated_at
                        """,
                        (submission_id, asset_id),
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        if row is None:
            raise ListingCatalogUnavailable("Generated loadsheet asset not found")
        return self._normalize_asset(row)

    def get_loadsheet_asset_for_submission(self, submission_id: str) -> dict[str, Any] | None:
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        """
                        select
                          id::text,
                          tenant_id::text,
                          store_id::text,
                          submission_id::text,
                          asset_type,
                          source,
                          original_file_name,
                          file_name,
                          storage_path,
                          public_url,
                          external_url,
                          content_type,
                          size_bytes,
                          checksum_sha256,
                          width,
                          height,
                          sort_order,
                          validation_status,
                          validation_errors,
                          raw_payload,
                          created_at,
                          updated_at
                        from listing_assets
                        where submission_id = %s
                          and asset_type = 'loadsheet'
                        order by created_at desc
                        limit 1
                        """,
                        (submission_id,),
                    ).fetchone()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        return self._normalize_asset(row) if row else None

    def _search_category_embeddings_pgvector(
        self,
        cursor: Any,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_dimensions: int,
        top_k: int,
    ) -> list[dict[str, Any]]:
        vector_literal = self._vector_literal(query_vector)
        # pgvector is the recommended path for large catalogs. The JSONB
        # fallback is intentionally exhaustive, not capped, so correctness does
        # not depend on where a category sorts alphabetically.
        rows = cursor.execute(
            f"""
            with ranked as (
              select
                e.category_id,
                e.embedding_model,
                e.embedding_dimensions,
                e.embedding_hash,
                e.embedding_text,
                1 - (e.embedding_vector_pg <=> %s::vector) as vector_similarity,
                row_number() over(order by e.embedding_vector_pg <=> %s::vector) as vector_rank
              from takealot_category_embeddings e
              where e.embedding_model = %s
                and e.embedding_dimensions = %s
                and e.embedding_vector_pg is not null
              order by e.embedding_vector_pg <=> %s::vector
              limit %s
            )
            {self._category_select_sql(
                extra_columns="""
                  , r.vector_similarity
                  , r.vector_rank
                  , r.embedding_model as vector_embedding_model
                  , r.embedding_dimensions as vector_embedding_dimensions
                  , r.embedding_hash as vector_embedding_hash
                """
            )}
            join ranked r on r.category_id = c.category_id
            order by r.vector_rank asc
            """,
            (
                vector_literal,
                vector_literal,
                embedding_model,
                embedding_dimensions,
                vector_literal,
                top_k,
            ),
        ).fetchall()
        return [self._normalize_category(row) for row in rows]

    def _search_category_embeddings_json(
        self,
        cursor: Any,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_dimensions: int,
        top_k: int,
    ) -> list[dict[str, Any]]:
        scored: list[tuple[float, dict[str, Any]]] = []
        scanned_count = 0
        last_path = ""
        last_category_id = -1
        last_row_id = ""
        while True:
            # pgvector is the recommended path. JSONB fallback is slower, but
            # it pages through every embedding row so category recall is never
            # silently capped at an arbitrary row count.
            rows = cursor.execute(
                f"""
                {self._category_select_sql(
                    extra_columns="""
                      , e.embedding_vector
                      , e.embedding_model as vector_embedding_model
                      , e.embedding_dimensions as vector_embedding_dimensions
                      , e.embedding_hash as vector_embedding_hash
                    """
                )}
                join takealot_category_embeddings e on e.category_id = c.category_id
                where e.embedding_model = %s
                  and e.embedding_dimensions = %s
                  and jsonb_array_length(e.embedding_vector) = %s
                  and (coalesce(c.path_en, ''), c.category_id, c.id::text) > (%s, %s, %s)
                order by coalesce(c.path_en, '') asc, c.category_id asc, c.id::text asc
                limit %s
                """,
                (
                    embedding_model,
                    embedding_dimensions,
                    embedding_dimensions,
                    last_path,
                    last_category_id,
                    last_row_id,
                    JSON_EMBEDDING_FALLBACK_PAGE_SIZE,
                ),
            ).fetchall()
            if not rows:
                break
            scanned_count += len(rows)
            for row in rows:
                embedding_vector = self._json_vector(row.get("embedding_vector"))
                if len(embedding_vector) != embedding_dimensions:
                    continue
                similarity = self._cosine_similarity(query_vector, embedding_vector)
                if similarity is None:
                    continue
                row["vector_similarity"] = similarity
                scored.append((similarity, self._normalize_category(row)))
            last_row = rows[-1]
            last_path = str(last_row.get("path_en") or "")
            last_category_id = int(last_row.get("category_id") or 0)
            last_row_id = str(last_row.get("id") or "")
        scored.sort(key=lambda item: item[0], reverse=True)
        result: list[dict[str, Any]] = []
        warning = None
        if scanned_count > JSON_EMBEDDING_FALLBACK_WARNING_THRESHOLD:
            warning = (
                f"pgvector is unavailable; JSONB embedding fallback scanned {scanned_count} rows. "
                "Install pgvector for faster category recall."
            )
        for rank, (_, category) in enumerate(scored[:top_k], start=1):
            category["vector_rank"] = rank
            if warning:
                category["vector_fallback_warning"] = warning
            result.append(category)
        return result

    def _update_submission(self, submission_id: str, **changes: Any) -> dict[str, Any]:
        if not changes:
            item = self.get_listing_submission(submission_id)
            if item is None:
                raise ListingCatalogUnavailable("Listing submission not found")
            return item
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in changes.items():
            if value == "now()":
                assignments.append(f"{key} = now()")
            else:
                assignments.append(f"{key} = %s")
                params.append(value)
        params.append(submission_id)
        try:
            with get_db_session() as connection:
                with connection.cursor() as cursor:
                    row = cursor.execute(
                        f"""
                        update listing_submissions
                        set {", ".join(assignments)},
                            updated_at = now()
                        where id = %s
                        returning {self._submission_returning_columns()}
                        """,
                        params,
                    ).fetchone()
                connection.commit()
        except (PsycopgError, RuntimeError, TimeoutError) as exc:
            raise ListingCatalogUnavailable() from exc
        if row is None:
            raise ListingCatalogUnavailable("Listing submission not found")
        return self._normalize_submission(row)

    @staticmethod
    def _has_rows(cursor: Any, table_name: str) -> bool:
        row = cursor.execute(f"select exists(select 1 from {table_name} limit 1) as has_rows").fetchone()
        return bool(row and row["has_rows"])

    @staticmethod
    def _table_exists(cursor: Any, table_name: str) -> bool:
        row = cursor.execute("select to_regclass(%s) is not null as exists", (table_name,)).fetchone()
        return bool(row and row["exists"])

    @staticmethod
    def _embedding_vector_pg_available(cursor: Any) -> bool:
        row = cursor.execute(
            """
            select exists (
              select 1
              from information_schema.columns
              where table_name = 'takealot_category_embeddings'
                and column_name = 'embedding_vector_pg'
            ) as has_column
            """
        ).fetchone()
        return bool(row and row["has_column"])

    @staticmethod
    def _normalize_vector(vector: list[float]) -> list[float]:
        normalized: list[float] = []
        for value in vector:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                normalized.append(round(number, 8))
        return normalized

    @staticmethod
    def _json_vector(value: Any) -> list[float]:
        if not isinstance(value, list):
            return []
        return ListingCatalogRepository._normalize_vector(value)

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(str(float(value)) for value in vector) + "]"

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float | None:
        if len(left) != len(right) or not left:
            return None
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm <= 0 or right_norm <= 0:
            return None
        return round(dot / (left_norm * right_norm), 6)

    @staticmethod
    def _submission_returning_columns() -> str:
        return """
          id::text,
          tenant_id::text,
          store_id::text,
          listing_id::text,
          platform_product_id,
          source_job_id::text,
          processing_task_id::text,
          idempotency_key,
          platform,
          sku,
          barcode,
          title,
          subtitle,
          description,
          whats_in_the_box,
          category_id,
          takealot_category_row_id::text,
          category_path,
          brand_id,
          brand_name,
          selling_price,
          rrp,
          stock_quantity,
          minimum_leadtime_days,
          seller_warehouse_id,
          length_cm,
          width_cm,
          height_cm,
          weight_kg,
          image_urls,
          dynamic_attributes,
          content_payload,
          loadsheet_payload,
          official_response,
          official_status,
          takealot_offer_id,
          takealot_loadsheet_submission_id,
          status,
          stage,
          review_status,
          error_code,
          error_message,
          offer_error_message,
          loadsheet_submit_claim_task_id::text,
          loadsheet_submit_claim_token,
          loadsheet_submit_claim_expires_at,
          offer_finalize_claim_task_id::text,
          offer_finalize_claim_token,
          offer_finalize_claim_expires_at,
          submitted_at,
          last_checked_at,
          last_status_sync_at,
          finalized_at,
          created_at,
          updated_at
        """

    @staticmethod
    def _category_select_sql(*, extra_columns: str = "") -> str:
        return f"""
            select
              c.id::text as id,
              c.category_id,
              c.division,
              c.department,
              c.main_category_id,
              c.main_category_name,
              c.lowest_category_name,
              c.lowest_category_raw,
              c.path_en,
              c.path_zh,
              c.min_required_images,
              c.compliance_certificates,
              c.image_requirement_texts,
              coalesce(t.required_attributes, c.required_attributes, '[]'::jsonb) as required_attributes,
              coalesce(t.optional_attributes, c.optional_attributes, '[]'::jsonb) as optional_attributes,
              t.template_key as loadsheet_template_key,
              (t.template_key is not null) as has_loadsheet_template_cache,
              coalesce(t.template_id, c.loadsheet_template_id) as loadsheet_template_id,
              coalesce(t.template_name, c.loadsheet_template_name, '') as loadsheet_template_name,
              c.raw_payload
              {extra_columns}
            from takealot_categories c
            left join lateral (
              select
                template_id,
                template_name,
                template_key,
                required_attributes,
                optional_attributes
              from takealot_loadsheet_template_cache
              where category_id = c.category_id
              order by fetched_at desc nulls last, updated_at desc
              limit 1
            ) t on true
        """

    @staticmethod
    def _category_where(query_text: str) -> tuple[str, list[Any]]:
        if not query_text:
            return "", []
        pattern = f"%{query_text.lower()}%"
        return (
            """
            where c.category_id::text = %s
               or c.search_text ilike %s
               or c.lowest_category_name ilike %s
               or c.main_category_name ilike %s
               or c.department ilike %s
               or c.division ilike %s
               or c.path_en ilike %s
               or c.path_zh ilike %s
            """,
            [query_text, pattern, pattern, pattern, pattern, pattern, pattern, pattern],
        )

    @staticmethod
    def _category_recall_where(terms: list[str]) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        for term in terms:
            pattern = f"%{term}%"
            conditions.append(
                """
                (
                  c.category_id::text = %s
                  or c.search_text ilike %s
                  or c.lowest_category_name ilike %s
                  or c.main_category_name ilike %s
                  or c.department ilike %s
                  or c.division ilike %s
                  or c.path_en ilike %s
                  or c.path_zh ilike %s
                )
                """
            )
            params.extend([term, pattern, pattern, pattern, pattern, pattern, pattern, pattern])
        return "where " + " or ".join(conditions), params

    @staticmethod
    def _category_recall_rank_sql(terms: list[str]) -> str:
        rank_parts: list[str] = []
        for _ in terms:
            rank_parts.append(
                """
                case
                  when c.category_id::text = %s then 120
                  when lower(c.lowest_category_name) = %s then 100
                  when lower(c.lowest_category_name) like %s then 88
                  when lower(c.path_en) like %s then 72
                  when lower(c.search_text) like %s then 60
                  else 0
                end
                """
            )
        return "(" + " + ".join(rank_parts) + ") desc,"

    @staticmethod
    def _category_recall_rank_params(terms: list[str]) -> list[Any]:
        params: list[Any] = []
        for term in terms:
            normalized = term.lower()
            params.extend([term, normalized, f"{normalized}%", f"%{normalized}%", f"%{normalized}%"])
        return params

    @staticmethod
    def _category_fuzzy_score_sql(terms: list[str]) -> tuple[str, list[Any]]:
        score_parts: list[str] = []
        params: list[Any] = []
        for term in terms:
            normalized = term.lower()
            score_parts.append(
                """
                greatest(
                  similarity(lower(c.lowest_category_name), %s),
                  similarity(lower(c.main_category_name), %s),
                  similarity(lower(c.path_en), %s),
                  word_similarity(%s, lower(c.search_text))
                )
                """
            )
            params.extend([normalized, normalized, normalized, normalized])
        return "greatest(" + ", ".join(score_parts) + ")", params

    @staticmethod
    def _category_order_sql(query_text: str) -> str:
        if not query_text:
            return """
                order by
                  c.division asc,
                  c.department asc,
                  c.main_category_name asc,
                  c.lowest_category_name asc
            """
        return """
            order by
              case
                when c.category_id::text = %s then 0
                when lower(c.lowest_category_name) = %s then 1
                when lower(c.main_category_name) = %s then 2
                when c.lowest_category_name ilike %s then 3
                else 4
              end,
              c.min_required_images desc,
              c.path_en asc
        """

    @staticmethod
    def _category_order_params(query_text: str) -> list[Any]:
        if not query_text:
            return []
        normalized = query_text.lower()
        return [query_text, normalized, normalized, f"{query_text}%"]

    @staticmethod
    def _brand_where(query_text: str) -> tuple[str, list[Any]]:
        if not query_text:
            return "", []
        pattern = f"%{query_text.lower()}%"
        return (
            """
            where b.brand_id = %s
               or b.search_text ilike %s
               or b.brand_name ilike %s
            """,
            [query_text, pattern, pattern],
        )

    @staticmethod
    def _brand_order_sql(query_text: str) -> str:
        if not query_text:
            return "order by b.brand_name asc"
        return """
            order by
              case
                when b.brand_id = %s then 0
                when lower(b.brand_name) = %s then 1
                when b.brand_name ilike %s then 2
                else 3
              end,
              b.brand_name asc
        """

    @staticmethod
    def _brand_order_params(query_text: str) -> list[Any]:
        if not query_text:
            return []
        normalized = query_text.lower()
        return [query_text, normalized, f"{query_text}%"]

    @staticmethod
    def _dedupe_terms(terms: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized_terms: list[str] = []
        for term in terms:
            normalized = str(term or "").strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_terms.append(normalized)
        return normalized_terms[:32]

    @classmethod
    def _normalize_category(
        cls,
        row: dict[str, Any],
        *,
        query_text: str = "",
        include_raw: bool = False,
    ) -> dict[str, Any]:
        required_attributes = cls._json_list(row.get("required_attributes"))
        optional_attributes = cls._json_list(row.get("optional_attributes"))
        has_template_cache = bool(row.get("has_loadsheet_template_cache"))
        attributes_ready = bool(required_attributes or optional_attributes)
        if attributes_ready:
            attribute_source = "template_cache" if has_template_cache else "catalog"
            attribute_message = None
        else:
            attribute_source = "missing"
            attribute_message = (
                "当前类目库只有类目、图片和证书要求，尚未同步 Takealot loadsheet 模板字段；"
                "同步模板后会自动显示必填属性和选填属性。"
            )
        item = {
            "id": str(row["id"]),
            "category_id": int(row["category_id"]),
            "division": row.get("division") or "",
            "department": row.get("department") or "",
            "main_category_id": int(row.get("main_category_id") or 0),
            "main_category_name": row.get("main_category_name") or "",
            "lowest_category_name": row.get("lowest_category_name") or "",
            "lowest_category_raw": row.get("lowest_category_raw") or "",
            "path_en": row.get("path_en") or "",
            "path_zh": row.get("path_zh") or "",
            "min_required_images": int(row.get("min_required_images") or 0),
            "compliance_certificates": cls._json_list(row.get("compliance_certificates")),
            "image_requirement_texts": cls._json_list(row.get("image_requirement_texts")),
            "required_attributes": required_attributes,
            "optional_attributes": optional_attributes,
            "loadsheet_template_key": row.get("loadsheet_template_key"),
            "loadsheet_template_id": row.get("loadsheet_template_id"),
            "loadsheet_template_name": row.get("loadsheet_template_name") or "",
            "attributes_ready": attributes_ready,
            "attribute_source": attribute_source,
            "attribute_message": attribute_message,
            "translation_source": "catalog" if row.get("path_zh") else "rules",
            "match_score": cls._category_score(row, query_text),
            "source": "catalog",
        }
        if "matching_variants" in row:
            item["matching_variants"] = int(row.get("matching_variants") or 1)
        if "existing_embedding_hash" in row:
            item["existing_embedding_hash"] = row.get("existing_embedding_hash")
            item["existing_embedding_model"] = row.get("existing_embedding_model")
            item["existing_embedding_dimensions"] = row.get("existing_embedding_dimensions")
        if "vector_similarity" in row:
            item["vector_similarity"] = cls._float_or_none(row.get("vector_similarity"))
            item["vector_rank"] = int(row.get("vector_rank") or 0)
            item["vector_embedding_model"] = row.get("vector_embedding_model")
            item["vector_embedding_dimensions"] = row.get("vector_embedding_dimensions")
            item["vector_embedding_hash"] = row.get("vector_embedding_hash")
        if "fuzzy_score" in row:
            item["fuzzy_score"] = cls._float_or_none(row.get("fuzzy_score"))
        if include_raw:
            item["raw_payload"] = row.get("raw_payload")
        return item

    @classmethod
    def _normalize_brand(cls, row: dict[str, Any], *, query_text: str = "") -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "brand_id": row.get("brand_id") or "",
            "brand_name": row.get("brand_name") or "",
            "match_score": cls._brand_score(row, query_text),
            "source": "catalog",
        }

    @classmethod
    def _normalize_submission(cls, row: dict[str, Any]) -> dict[str, Any]:
        weight_kg = row.get("weight_kg")
        weight_g = None
        if weight_kg is not None:
            try:
                weight_g = round(float(weight_kg) * 1000, 2)
            except (TypeError, ValueError):
                weight_g = None
        return {
            "id": str(row["id"]),
            "submission_id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "store_id": str(row["store_id"]),
            "listing_id": str(row["listing_id"]) if row.get("listing_id") else None,
            "platform_product_id": row.get("platform_product_id"),
            "source_job_id": str(row["source_job_id"]) if row.get("source_job_id") else None,
            "processing_task_id": str(row["processing_task_id"]) if row.get("processing_task_id") else None,
            "task_id": str(row["processing_task_id"]) if row.get("processing_task_id") else None,
            "idempotency_key": row.get("idempotency_key"),
            "platform": row.get("platform") or "takealot",
            "sku": row.get("sku") or "",
            "barcode": row.get("barcode") or "",
            "title": row.get("title") or "",
            "subtitle": row.get("subtitle") or "",
            "description": row.get("description") or "",
            "whats_in_the_box": row.get("whats_in_the_box") or "",
            "category_id": int(row.get("category_id") or 0),
            "takealot_category_row_id": str(row["takealot_category_row_id"]) if row.get("takealot_category_row_id") else None,
            "category_path": row.get("category_path") or "",
            "brand_id": row.get("brand_id") or "",
            "brand_name": row.get("brand_name") or "",
            "selling_price": cls._float_or_none(row.get("selling_price")),
            "rrp": cls._float_or_none(row.get("rrp")),
            "stock_quantity": int(row.get("stock_quantity") or 0),
            "minimum_leadtime_days": int(row.get("minimum_leadtime_days") or 0),
            "seller_warehouse_id": row.get("seller_warehouse_id") or "",
            "length_cm": cls._float_or_none(row.get("length_cm")),
            "width_cm": cls._float_or_none(row.get("width_cm")),
            "height_cm": cls._float_or_none(row.get("height_cm")),
            "weight_g": weight_g,
            "image_urls": cls._json_list(row.get("image_urls")),
            "dynamic_attributes": row.get("dynamic_attributes") if isinstance(row.get("dynamic_attributes"), dict) else {},
            "content_payload": row.get("content_payload") if isinstance(row.get("content_payload"), dict) else {},
            "loadsheet_payload": row.get("loadsheet_payload") if isinstance(row.get("loadsheet_payload"), dict) else {},
            "official_response": row.get("official_response") if isinstance(row.get("official_response"), dict) else {},
            "official_status": row.get("official_status") or "",
            "takealot_offer_id": row.get("takealot_offer_id") or "",
            "takealot_submission_id": row.get("takealot_loadsheet_submission_id") or "",
            "status": row.get("status") or "",
            "stage": row.get("stage") or "",
            "review_status": row.get("review_status") or "",
            "error_code": row.get("error_code"),
            "error_message": row.get("error_message"),
            "offer_error_message": row.get("offer_error_message"),
            "loadsheet_submit_claim_task_id": str(row["loadsheet_submit_claim_task_id"]) if row.get("loadsheet_submit_claim_task_id") else None,
            "loadsheet_submit_claim_token": row.get("loadsheet_submit_claim_token"),
            "loadsheet_submit_claim_expires_at": row.get("loadsheet_submit_claim_expires_at"),
            "offer_finalize_claim_task_id": str(row["offer_finalize_claim_task_id"]) if row.get("offer_finalize_claim_task_id") else None,
            "offer_finalize_claim_token": row.get("offer_finalize_claim_token"),
            "offer_finalize_claim_expires_at": row.get("offer_finalize_claim_expires_at"),
            "submitted_at": row.get("submitted_at"),
            "last_checked_at": row.get("last_checked_at"),
            "last_status_sync_at": row.get("last_status_sync_at"),
            "finalized_at": row.get("finalized_at"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _category_score(row: dict[str, Any], query_text: str) -> float | None:
        if not query_text:
            return None
        normalized = query_text.lower()
        if str(row.get("category_id")) == query_text:
            return 1.0
        if (row.get("lowest_category_name") or "").lower() == normalized:
            return 0.95
        if (row.get("main_category_name") or "").lower() == normalized:
            return 0.9
        if normalized in (row.get("lowest_category_name") or "").lower():
            return 0.82
        if normalized in (row.get("path_en") or "").lower():
            return 0.76
        return 0.6

    @staticmethod
    def _brand_score(row: dict[str, Any], query_text: str) -> float | None:
        if not query_text:
            return None
        normalized = query_text.lower()
        if (row.get("brand_id") or "") == query_text:
            return 1.0
        if (row.get("brand_name") or "").lower() == normalized:
            return 0.95
        if normalized in (row.get("brand_name") or "").lower():
            return 0.8
        return 0.6

    @classmethod
    def _normalize_asset(cls, row: dict[str, Any]) -> dict[str, Any]:
        raw_payload = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]) if row.get("tenant_id") else None,
            "store_id": str(row["store_id"]) if row.get("store_id") else None,
            "submission_id": str(row["submission_id"]) if row.get("submission_id") else None,
            "asset_type": row.get("asset_type") or "image",
            "source": row.get("source") or "upload",
            "original_file_name": row.get("original_file_name"),
            "file_name": row.get("file_name"),
            "storage_path": row.get("storage_path"),
            "public_url": row.get("public_url"),
            "external_url": row.get("external_url"),
            "content_type": row.get("content_type"),
            "size_bytes": int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
            "checksum_sha256": row.get("checksum_sha256"),
            "width": int(row["width"]) if row.get("width") is not None else None,
            "height": int(row["height"]) if row.get("height") is not None else None,
            "sort_order": int(row.get("sort_order") or 0),
            "validation_status": row.get("validation_status") or "pending",
            "validation_errors": cls._json_list(row.get("validation_errors")),
            "warnings": cls._json_list(raw_payload.get("warnings")),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
