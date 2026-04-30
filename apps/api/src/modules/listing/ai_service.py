from __future__ import annotations

import json
import os
from typing import Any

import httpx


DASHSCOPE_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_COMPAT_BASE_URL = "https://api.openai.com/v1"

CATEGORY_TRANSLATION_GLOSSARY: dict[str, str] = {
    "home": "家居",
    "family": "家庭",
    "baby": "母婴",
    "personal & lifestyle": "个人与生活方式",
    "consumer electronics": "电子产品",
    "office & business": "办公与商业",
    "small appliances": "小家电",
    "kitchen appliances": "厨房电器",
    "beauty": "美妆个护",
    "hair care": "护发",
    "computer components": "电脑组件",
    "input devices": "输入设备",
}


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


class ListingAiService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else _first_env("XH_AI_API_KEY", "DASHSCOPE_API_KEY", "AI_API_KEY")
        )
        self.model = model if model is not None else _first_env("XH_AI_MODEL", "DASHSCOPE_MODEL", "AI_MODEL") or "qwen-plus"
        self.api_base_url = (
            api_base_url
            if api_base_url is not None
            else _first_env("XH_AI_API_BASE_URL", "DASHSCOPE_API_BASE_URL", "AI_API_BASE_URL")
            or self._default_base_url(self.model)
        )
        if timeout_seconds is None:
            try:
                timeout_seconds = float(os.getenv("XH_AI_TIMEOUT_SECONDS", "8"))
            except ValueError:
                timeout_seconds = 8.0
        self.timeout_seconds = max(1.0, timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.api_base_url and self.model)

    def extract_category_intent(self, description: str) -> list[str]:
        if not self.enabled:
            return []
        payload = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a Takealot category recall assistant. The user may write Chinese or English. "
                        "Your job is to translate the product into English search terms for a local category catalog; "
                        "you must not choose or invent category_id values. Return strict JSON with keys: "
                        "intent_keywords, product_terms, category_terms, path_hints, avoid_terms. "
                        "Always return several concrete English product nouns, singular and plural forms, and likely "
                        "marketplace shelf terms even when the original input is short or only Chinese. "
                        "Use concrete product nouns in product_terms, for example 哑铃 -> dumbbells/free weights; "
                        "Also include marketplace synonyms and broader shelf terms when useful, for example "
                        "air fryer -> air fryer, air fryers, fryers, kitchen appliances; "
                        "cat litter box -> cat litter box, litter boxes, cat supplies, pets. "
                        "keep broad words like health, accessories, home, fitness out of product_terms unless needed. "
                        "Use avoid_terms for misleading nearby categories, for example dumbbells should avoid supplements."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"product_description": description},
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        terms: list[str] = []
        for key in ("intent_keywords", "product_terms", "category_terms", "path_hints"):
            values = payload.get(key)
            if isinstance(values, list):
                terms.extend(str(value).strip() for value in values if str(value).strip())
        avoid_terms = payload.get("avoid_terms")
        if isinstance(avoid_terms, list):
            terms.extend(f"avoid:{str(value).strip()}" for value in avoid_terms if str(value).strip())
        return terms

    def translate_category_paths(self, paths: list[str]) -> dict[str, str]:
        if not self.enabled:
            return {}
        clean_paths = []
        seen = set()
        for path in paths:
            clean_path = str(path or "").strip()
            if not clean_path or clean_path in seen:
                continue
            seen.add(clean_path)
            clean_paths.append(clean_path)
        if not clean_paths:
            return {}

        payload = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Translate Takealot category paths from English into precise Simplified Chinese. "
                        "Only translate the text. Preserve the category hierarchy with ' > ' separators, "
                        "keep numbers and product acronyms such as USB, 3D, TV, DVD unchanged, and do not add category IDs. "
                        "Use marketplace category meanings: Home means 家居, not 首页; Baby means 母婴. "
                        "Return strict JSON with a translations array of objects: path_en, path_zh."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"paths": clean_paths},
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        rows = payload.get("translations")
        if not isinstance(rows, list):
            return {}
        result: dict[str, str] = {}
        allowed_paths = set(clean_paths)
        for row in rows:
            if not isinstance(row, dict):
                continue
            path_en = str(row.get("path_en") or "").strip()
            path_zh = str(row.get("path_zh") or "").strip()
            path_zh = self._apply_category_translation_glossary(path_en, path_zh)
            if path_en not in allowed_paths or not self._looks_like_category_translation(path_en, path_zh):
                continue
            result[path_en] = path_zh
        return result

    def rerank_category_candidates(
        self,
        *,
        description: str,
        candidates: list[dict[str, Any]],
    ) -> list[int]:
        if not self.enabled or not candidates:
            return []
        allowed_ids = [int(candidate["category_id"]) for candidate in candidates if candidate.get("category_id")]
        allowed_set = set(allowed_ids)
        payload = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Rerank Takealot category candidates for the product. "
                        "You may only return category_id values present in the candidate list. "
                        "Never invent a category_id. Return JSON with ranked_category_ids."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "product_description": description,
                            "allowed_category_ids": allowed_ids,
                            "candidates": [
                                {
                                    "category_id": candidate.get("category_id"),
                                    "path_en": candidate.get("path_en"),
                                    "path_zh": candidate.get("path_zh"),
                                    "lowest_category_name": candidate.get("lowest_category_name"),
                                }
                                for candidate in candidates[:20]
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        ranked_values = payload.get("ranked_category_ids")
        if not isinstance(ranked_values, list):
            return []
        ranked_ids: list[int] = []
        for value in ranked_values:
            try:
                category_id = int(value)
            except (TypeError, ValueError):
                continue
            if category_id in allowed_set and category_id not in ranked_ids:
                ranked_ids.append(category_id)
        return ranked_ids

    def generate_listing_content(
        self,
        *,
        product_description: str,
        category: dict[str, Any],
        brand_name: str,
        allowed_attributes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        payload = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You generate Takealot marketplace listing drafts. "
                        "Return strict JSON only. Do not include markdown. "
                        "Never change category_id. Use English for title, subtitle, description, and whats_in_the_box. "
                        "Write buyer-facing retail copy from the supplied product facts: a clear searchable title, "
                        "a concise subtitle, and a polished selling description with practical benefits and use cases. "
                        "Do not return HTML. Do not exaggerate benefits. "
                        "Do not invent certifications, materials, warranties, compatibility, or Takealot promises. "
                        "whats_in_the_box must contain one item per line in the exact format '<quantity> x <Product Name>'. "
                        "Dimensions and weight must be realistic positive numbers. "
                        "dynamic_attributes may only use keys from allowed_attributes. "
                        "If an allowed attribute has options, choose only one of those option values."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "required_json_shape": {
                                "category_id": category.get("category_id"),
                                "title": "string",
                                "subtitle": "string",
                                "description": "plain English text without HTML",
                                "whats_in_the_box": "1 x Product Name",
                                "length_cm": "positive number",
                                "width_cm": "positive number",
                                "height_cm": "positive number",
                                "weight_g": "positive integer",
                                "dynamic_attributes": [
                                    {
                                        "key": "allowed attribute key",
                                        "value": "value allowed by attribute definition",
                                    }
                                ],
                            },
                            "product_description": product_description,
                            "brand_name": brand_name,
                            "copy_guidance": {
                                "title": "Search-friendly English marketplace title using brand/product/type/key specs from product_description only.",
                                "subtitle": "Short sales line highlighting the most useful confirmed benefit.",
                                "description": "Plain English retail copy, 2-4 short paragraphs or sentences, based only on confirmed facts.",
                            },
                            "category": {
                                "category_id": category.get("category_id"),
                                "path_en": category.get("path_en"),
                                "path_zh": category.get("path_zh"),
                                "lowest_category_name": category.get("lowest_category_name"),
                                "min_required_images": category.get("min_required_images"),
                                "compliance_certificates": category.get("compliance_certificates"),
                            },
                            "allowed_attributes": allowed_attributes,
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        )
        return payload

    def _chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.enabled:
            return {}
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self._chat_completions_url(),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                body = response.json()
        except Exception:
            return {}

        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices or not isinstance(choices, list):
            return {}
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            return {}
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _chat_completions_url(self) -> str:
        base_url = self.api_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    @staticmethod
    def _looks_like_category_translation(path_en: str, path_zh: str) -> bool:
        if not path_en or not path_zh or len(path_zh) > 1024:
            return False
        # Keep the hierarchy depth identical; AI can translate words, but it
        # must not reshape the official Takealot category path shown underneath.
        if path_en.count(">") != path_zh.count(">"):
            return False
        return any("\u4e00" <= char <= "\u9fff" for char in path_zh)

    @staticmethod
    def _apply_category_translation_glossary(path_en: str, path_zh: str) -> str:
        en_segments = [segment.strip() for segment in path_en.split(">")]
        zh_segments = [segment.strip() for segment in path_zh.split(">")]
        if len(en_segments) != len(zh_segments):
            return path_zh
        for index, segment in enumerate(en_segments):
            forced = CATEGORY_TRANSLATION_GLOSSARY.get(segment.lower())
            if forced:
                zh_segments[index] = forced
        return " > ".join(zh_segments)

    @staticmethod
    def _default_base_url(model: str) -> str:
        normalized = str(model or "").strip().lower()
        # Qwen-family models are served through DashScope's OpenAI-compatible
        # endpoint. Callers can still override this with XH_AI_API_BASE_URL.
        if os.getenv("DASHSCOPE_API_KEY") or normalized.startswith(("qwen", "qwq", "qvq")):
            return DASHSCOPE_COMPAT_BASE_URL
        return OPENAI_COMPAT_BASE_URL
