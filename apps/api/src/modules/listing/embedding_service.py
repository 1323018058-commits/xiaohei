from __future__ import annotations

import hashlib
import os
from typing import Any

import httpx


DASHSCOPE_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_COMPAT_BASE_URL = "https://api.openai.com/v1"


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


class ListingEmbeddingService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base_url: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else _first_env("XH_EMBEDDING_API_KEY", "DASHSCOPE_API_KEY", "XH_AI_API_KEY", "AI_API_KEY")
        )
        self.model = model if model is not None else _first_env(
            "XH_EMBEDDING_MODEL",
            "DASHSCOPE_EMBEDDING_MODEL",
            "AI_EMBEDDING_MODEL",
        ) or "text-embedding-v4"
        self.api_base_url = (
            api_base_url
            if api_base_url is not None
            else _first_env(
                "XH_EMBEDDING_API_BASE_URL",
                "XH_AI_API_BASE_URL",
                "DASHSCOPE_API_BASE_URL",
                "AI_API_BASE_URL",
            )
            or self._default_base_url(self.model)
        )
        if dimensions is None:
            try:
                dimensions = int(os.getenv("XH_EMBEDDING_DIMENSIONS", "1024"))
            except ValueError:
                dimensions = 1024
        self.dimensions = max(1, dimensions)
        if timeout_seconds is None:
            try:
                timeout_seconds = float(os.getenv("XH_EMBEDDING_TIMEOUT_SECONDS", "20"))
            except ValueError:
                timeout_seconds = 20.0
        self.timeout_seconds = max(1.0, timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.api_base_url and self.model)

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        inputs = [str(text or "").strip() for text in texts if str(text or "").strip()]
        if not self.enabled or not inputs:
            return []
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self._embeddings_url(),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "input": inputs,
                        "dimensions": self.dimensions,
                    },
                )
                response.raise_for_status()
                body = response.json()
        except Exception:
            return []

        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return []
        vectors_by_index: dict[int, list[float]] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            embedding = row.get("embedding")
            if not isinstance(embedding, list):
                continue
            try:
                vector = [float(value) for value in embedding]
            except (TypeError, ValueError):
                continue
            if len(vector) != self.dimensions:
                continue
            row_index = row.get("index")
            try:
                normalized_index = int(row_index)
            except (TypeError, ValueError):
                normalized_index = index
            vectors_by_index[normalized_index] = vector
        return [vectors_by_index[index] for index in range(len(inputs)) if index in vectors_by_index]

    def _embeddings_url(self) -> str:
        base_url = self.api_base_url.rstrip("/")
        if base_url.endswith("/embeddings"):
            return base_url
        return f"{base_url}/embeddings"

    @staticmethod
    def _default_base_url(model: str) -> str:
        normalized = str(model or "").strip().lower()
        # Alibaba text-embedding-v* models use DashScope's compatible endpoint.
        # pgvector remains the preferred retrieval path after vectors are built.
        if os.getenv("DASHSCOPE_API_KEY") or normalized.startswith(("text-embedding-v", "qwen")):
            return DASHSCOPE_COMPAT_BASE_URL
        return OPENAI_COMPAT_BASE_URL

    @staticmethod
    def text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def normalize_vector(vector: list[float]) -> list[float]:
        return [round(float(value), 8) for value in vector]
