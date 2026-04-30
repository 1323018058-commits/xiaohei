from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.listing.category_matcher import CategoryMatcher  # noqa: E402
from src.modules.listing.embedding_service import ListingEmbeddingService  # noqa: E402
from src.modules.listing.repository import ListingCatalogRepository, ListingCatalogUnavailable  # noqa: E402


SAMPLES = {
    "\u624b\u673a\u58f3": "\u624b\u673a\u58f3",
    "\u9c7c\u7aff": "\u9c7c\u7aff",
    "\u540a\u5e8a": "\u540a\u5e8a",
    "\u9732\u8425\u706f": "\u9732\u8425\u706f",
    "\u7535\u52a8\u7259\u5237": "\u7535\u52a8\u7259\u5237",
}


class FakeEmbeddingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return [dict(row) for row in self._rows]


class FakeEmbeddingCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.page_count = 0

    def execute(self, _sql: str, params: tuple) -> FakeEmbeddingResult:
        last_key = (str(params[3]), int(params[4]), str(params[5]))
        limit = int(params[6])
        page = [
            row
            for row in self._rows
            if (str(row["path_en"]), int(row["category_id"]), str(row["id"])) > last_key
        ][:limit]
        self.page_count += 1
        return FakeEmbeddingResult(page)


def category_row(index: int, vector: list[float]) -> dict:
    return {
        "id": f"id-{index:05d}",
        "category_id": index + 1,
        "division": "Smoke",
        "department": "Smoke",
        "main_category_id": 1,
        "main_category_name": "Smoke",
        "lowest_category_name": f"Smoke {index}",
        "lowest_category_raw": f"Smoke {index}",
        "path_en": f"Smoke > {index:05d}",
        "path_zh": f"Smoke ZH > {index:05d}",
        "min_required_images": 1,
        "compliance_certificates": [],
        "image_requirement_texts": [],
        "required_attributes": [],
        "optional_attributes": [],
        "loadsheet_template_id": "template",
        "loadsheet_template_name": "Template",
        "raw_payload": {},
        "embedding_vector": vector,
        "vector_embedding_model": "smoke-model",
        "vector_embedding_dimensions": 2,
        "vector_embedding_hash": f"hash-{index}",
    }


def run_pure_checks() -> dict[str, bool]:
    repository = ListingCatalogRepository()
    rows = [category_row(index, [0.0, 1.0]) for index in range(10005)]
    rows[-1]["embedding_vector"] = [1.0, 0.0]
    cursor = FakeEmbeddingCursor(rows)
    result = repository._search_category_embeddings_json(
        cursor,
        query_vector=[1.0, 0.0],
        embedding_model="smoke-model",
        embedding_dimensions=2,
        top_k=1,
    )
    return {
        "jsonb_fallback_scans_past_10000": bool(result) and result[0]["category_id"] == 10005,
        "jsonb_fallback_uses_pages": cursor.page_count > 10,
    }


def main() -> None:
    pure_checks = run_pure_checks()
    repository = ListingCatalogRepository()
    embedding_service = ListingEmbeddingService()
    try:
        _, _, catalog_ready = repository.search_categories(query=None, page=1, page_size=1)
    except ListingCatalogUnavailable as exc:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "PostgreSQL unavailable",
                    "detail": exc.message,
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from exc

    if not catalog_ready:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "Takealot category catalog import required",
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)

    matcher = CategoryMatcher(repository=repository, embedding_service=embedding_service)
    if not embedding_service.enabled:
        fallback = matcher.match(description="\u624b\u673a\u58f3", limit=5, use_ai=False)
        passed = bool(fallback.suggestions) and all(pure_checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "message": "embedding disabled; skipped live vector recall",
                    "rule_fallback_available": bool(fallback.suggestions),
                    "embedding_model": embedding_service.model,
                    "embedding_dimensions": embedding_service.dimensions,
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if not passed:
            raise SystemExit(1)
        return

    if not repository.has_category_embeddings(
        embedding_model=embedding_service.model,
        embedding_dimensions=embedding_service.dimensions,
    ):
        fallback = matcher.match(description="\u624b\u673a\u58f3", limit=5, use_ai=False)
        passed = bool(fallback.suggestions) and all(pure_checks.values())
        print(
            json.dumps(
                {
                    "passed": passed,
                    "message": "category embeddings not built; skipped live vector recall",
                    "rule_fallback_available": bool(fallback.suggestions),
                    "embedding_model": embedding_service.model,
                    "embedding_dimensions": embedding_service.dimensions,
                    "embedding_rows": 0,
                    "pure_checks": pure_checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if not passed:
            raise SystemExit(1)
        return

    records: list[dict] = []
    failed = False
    vector_used_any = False
    for description, expected_path_zh in SAMPLES.items():
        result = matcher.match(description=description, limit=5, use_ai=False)
        suggestions = result.suggestions
        top = suggestions[0] if suggestions else None
        vector_used_any = vector_used_any or result.vector_used
        sample_passed = bool(
            result.vector_used
            and top
            and top.get("category_id")
            and expected_path_zh in str(top.get("path_zh") or "")
        )
        if not sample_passed:
            failed = True
        records.append(
            {
                "description": description,
                "expected_path_zh": expected_path_zh,
                "passed": sample_passed,
                "vector_used": result.vector_used,
                "vector_candidates": result.vector_candidates,
                "keyword_candidates": result.keyword_candidates,
                "match_strategy": result.match_strategy,
                "top": top,
            }
        )

    print(
        json.dumps(
            {
                "passed": not failed and vector_used_any,
                "embedding_model": embedding_service.model,
                "embedding_dimensions": embedding_service.dimensions,
                "pure_checks": pure_checks,
                "samples": records,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failed or not vector_used_any or not all(pure_checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
