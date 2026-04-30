from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.modules.listing.category_matcher import CategoryMatcher  # noqa: E402
from src.modules.listing.repository import ListingCatalogUnavailable  # noqa: E402
from src.modules.listing.service import ListingService  # noqa: E402


MATCH_SAMPLES = {
    "手机壳": "手机壳",
    "鱼竿": "鱼竿",
    "吊床": "吊床",
    "露营灯": "灯具",
    "电动牙刷": "电动牙刷",
    "蓝牙耳机": "耳机",
    "花盆": "花盆",
    "哑铃": "哑铃",
    "宠物垫": "宠物",
    "奶瓶加热器": "奶瓶",
    "厨房收纳盒": "食物收纳",
    "车载手机支架": "手机支架",
    "充电宝": "充电宝",
    "手机膜": "保护膜",
    "瑜伽垫": "瑜伽",
    "弹力带": "弹力带",
}

SEARCH_SAMPLES = {
    "手机壳": "Mobile Phone Cases",
    "蓝牙耳机": "Headsets",
    "充电宝": "Power Banks",
    "厨房收纳盒": "Food Storage Containers",
    "哑铃": "Dumbbells",
    "手机膜": "Screen Protectors",
    "咖啡机": "Coffee Machines",
    "雨伞": "Umbrellas",
    "玩具车": "Toy Cars",
    "窗帘": "Curtains & Drapes",
    "打印机": "Printers",
    "沙发套": "Couch Covers & Protectors",
}


class FakeCategoryAiService:
    enabled = True

    def extract_category_intent(self, description: str) -> list[str]:
        if "咖啡机" in description:
            return [
                "coffee machines",
                "coffee machine",
                "hot drink machines",
                "espresso machine",
            ]
        if "空气炸锅" in description:
            return ["air fryer", "air fryers", "fryers", "kitchen appliances"]
        if "猫砂盆" in description:
            return ["cat litter box", "cat litter boxes", "litter boxes", "cat supplies", "pets"]
        return []

    def rerank_category_candidates(self, *, description: str, candidates: list[dict]) -> list[int]:
        if "咖啡机" in description:
            preferred = [
                int(candidate["category_id"])
                for candidate in candidates
                if "coffee machines" in str(candidate.get("path_en") or "").lower()
            ]
            return preferred
        if "空气炸锅" in description:
            return [
                int(candidate["category_id"])
                for candidate in candidates
                if "air fryers" in str(candidate.get("path_en") or "").lower()
            ]
        if "猫砂盆" in description:
            return [
                int(candidate["category_id"])
                for candidate in candidates
                if "cat litter boxes" in str(candidate.get("path_en") or "").lower()
            ]
        return []

    def translate_category_paths(self, paths: list[str]) -> dict[str, str]:
        translations: dict[str, str] = {}
        for path in paths:
            if "Coffee Machines" in path:
                translations[path] = "家居 > 小家电 > 厨房电器 > 热饮机 > 咖啡机"
            elif "Air Fryers" in path:
                translations[path] = "家居 > 小家电 > 厨房电器 > 空气炸锅"
            elif "Cat Litter Boxes" in path:
                translations[path] = "家庭 > 宠物 > 猫用品 > 猫砂盆"
        return translations


def dump_item(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


def main() -> None:
    matcher = CategoryMatcher(ai_service=FakeCategoryAiService())  # type: ignore[arg-type]
    service = ListingService(category_matcher=matcher)
    records: list[dict] = []
    search_records: list[dict] = []
    failed = False

    for description, expected_path_zh in MATCH_SAMPLES.items():
        try:
            result = matcher.match(description=description, limit=5, use_ai=False)
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

        if not result.catalog_ready:
            print(
                json.dumps(
                    {
                        "passed": False,
                        "message": "需要导入 Takealot 类目库",
                        "description": description,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(1)

        suggestions = result.suggestions
        top = suggestions[0] if suggestions else None
        sample_passed = bool(
            top
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
                "top": top,
                "suggestion_count": len(suggestions),
            }
        )

    actor = {"role": "super_admin", "tenant_id": "smoke"}
    for query, expected_path_en in SEARCH_SAMPLES.items():
        response = service.search_categories(actor, query=query, page=1, page_size=5)
        items = [dump_item(item) for item in response.items]
        top = items[0] if items else None
        sample_passed = bool(top and expected_path_en.lower() in str(top.get("path_en") or "").lower())
        if not sample_passed:
            failed = True
        search_records.append(
            {
                "query": query,
                "expected_path_en": expected_path_en,
                "passed": sample_passed,
                "top": top,
                "suggestion_count": len(items),
            }
        )

    ai_matcher = matcher
    ai_service = service
    ai_response = ai_service.search_categories(actor, query="咖啡机", page=1, page_size=5)
    ai_items = [dump_item(item) for item in ai_response.items]
    ai_top = ai_items[0] if ai_items else None
    ai_sample_passed = bool(
        ai_top
        and "Coffee Machines" in str(ai_top.get("path_en") or "")
        and ai_top.get("translation_source") == "ai"
    )
    if not ai_sample_passed:
        failed = True
    search_records.append(
        {
            "query": "咖啡机",
            "expected_path_en": "Coffee Machines",
            "passed": ai_sample_passed,
            "top": ai_top,
            "suggestion_count": len(ai_items),
            "source": "fake_ai_semantic_recall",
        }
    )

    for query, expected_path_en in {
        "空气炸锅": "Air Fryers",
        "猫砂盆": "Cat Litter Boxes",
    }.items():
        response = ai_service.search_categories(actor, query=query, page=1, page_size=5)
        items = [dump_item(item) for item in response.items]
        top = items[0] if items else None
        sample_passed = bool(top and expected_path_en.lower() in str(top.get("path_en") or "").lower())
        if not sample_passed:
            failed = True
        search_records.append(
            {
                "query": query,
                "expected_path_en": expected_path_en,
                "passed": sample_passed,
                "top": top,
                "suggestion_count": len(items),
                "source": "fake_ai_generic_chinese_recall",
            }
        )

    print(
        json.dumps(
            {
                "passed": not failed,
                "samples": records,
                "search_samples": search_records,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
