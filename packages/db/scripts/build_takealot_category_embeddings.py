from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.listing.category_matcher import CategoryMatcher  # noqa: E402
from src.modules.listing.embedding_service import ListingEmbeddingService  # noqa: E402
from src.modules.listing.repository import ListingCatalogRepository, ListingCatalogUnavailable  # noqa: E402


def chunks(values: list[dict[str, Any]], size: int) -> Any:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def build_pending_categories(
    *,
    repository: ListingCatalogRepository,
    embedding_service: ListingEmbeddingService,
    limit: int,
    force: bool,
) -> tuple[list[dict[str, Any]], int]:
    categories = repository.get_categories_missing_embeddings(
        embedding_model=embedding_service.model,
        embedding_dimensions=embedding_service.dimensions,
        limit=limit,
        include_existing=True,
    )
    pending: list[dict[str, Any]] = []
    skipped_unchanged = 0
    for category in categories:
        embedding_text = CategoryMatcher.category_embedding_text(category)
        embedding_hash = embedding_service.text_hash(embedding_text)
        if not force and category.get("existing_embedding_hash") == embedding_hash:
            skipped_unchanged += 1
            continue
        pending.append(
            {
                "category": category,
                "embedding_text": embedding_text,
                "embedding_hash": embedding_hash,
            }
        )
    return pending, skipped_unchanged


def run(args: argparse.Namespace) -> dict[str, Any]:
    repository = ListingCatalogRepository()
    embedding_service = ListingEmbeddingService()
    pending, skipped_unchanged = build_pending_categories(
        repository=repository,
        embedding_service=embedding_service,
        limit=args.limit,
        force=args.force,
    )
    summary: dict[str, Any] = {
        "dry_run": args.dry_run,
        "embedding_model": embedding_service.model,
        "embedding_dimensions": embedding_service.dimensions,
        "candidate_count": len(pending) + skipped_unchanged,
        "pending_count": len(pending),
        "skipped_unchanged": skipped_unchanged,
        "upserted": 0,
        "failed": 0,
    }
    if args.dry_run:
        summary["sample_category_ids"] = [item["category"]["category_id"] for item in pending[:10]]
        return summary
    if pending and not embedding_service.enabled:
        summary["message"] = "embedding disabled"
        summary["upserted"] = 0
        summary["failed"] = len(pending)
        return summary

    for batch in chunks(pending, max(1, args.batch_size)):
        vectors = embedding_service.embed_texts([item["embedding_text"] for item in batch])
        if len(vectors) != len(batch):
            summary["failed"] += len(batch)
            continue
        for item, vector in zip(batch, vectors, strict=True):
            category = item["category"]
            repository.upsert_category_embedding(
                category_id=int(category["category_id"]),
                embedding_model=embedding_service.model,
                embedding_dimensions=embedding_service.dimensions,
                embedding_text=item["embedding_text"],
                embedding_vector=embedding_service.normalize_vector(vector),
                embedding_hash=item["embedding_hash"],
            )
            summary["upserted"] += 1
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local Takealot category embeddings.")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    try:
        summary = run(parse_args())
    except ListingCatalogUnavailable as exc:
        print(
            json.dumps(
                {
                    "passed": False,
                    "message": "PostgreSQL unavailable",
                    "detail": exc.message,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from exc
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("message") == "embedding disabled" or summary.get("failed"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
