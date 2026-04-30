from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

import httpx

from src.platform.settings.base import settings


class TakealotCatalogClient:
    _token_lock = Lock()
    _cached_api_key: str | None = None
    _cached_api_key_expires_at: datetime | None = None

    def __init__(self) -> None:
        self.base_url = settings.takealot_catalog_base_url.rstrip("/")
        self.timeout = settings.platform_api_timeout_seconds

    def is_configured(self) -> bool:
        return bool(
            settings.takealot_catalog_api_key
            or (settings.takealot_catalog_email and settings.takealot_catalog_password)
        )

    def fetch_product_detail(self, plid: str) -> dict[str, Any] | None:
        api_key = self._get_api_key()
        if not api_key:
            return None
        clean_plid = str(plid or "").removeprefix("PLID").removeprefix("plid").strip()
        product_ids = [clean_plid, f"PLID{clean_plid}"] if clean_plid else []
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                for product_id in product_ids:
                    response = client.get(
                        f"/1/catalogue/mpv/{product_id}",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Accept": "application/json",
                        },
                    )
                    if response.status_code in {401, 403}:
                        self._forget_cached_api_key()
                        return None
                    if response.status_code >= 400:
                        continue
                    payload = response.json()
                    if isinstance(payload, dict):
                        return payload
            return None
        except Exception:
            return None

    def _get_api_key(self) -> str | None:
        if settings.takealot_catalog_api_key:
            return settings.takealot_catalog_api_key

        if not settings.takealot_catalog_email or not settings.takealot_catalog_password:
            return None

        now = datetime.now(UTC)
        with self._token_lock:
            if (
                self._cached_api_key
                and self._cached_api_key_expires_at is not None
                and self._cached_api_key_expires_at > now
            ):
                return self._cached_api_key

            try:
                with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                    response = client.post(
                        "/v1/login",
                        json={
                            "email": settings.takealot_catalog_email,
                            "password": settings.takealot_catalog_password,
                        },
                    )
                response.raise_for_status()
                payload = response.json()
                api_key = payload.get("api_key") if isinstance(payload, dict) else None
                if not api_key:
                    return None
                self._cached_api_key = str(api_key)
                self._cached_api_key_expires_at = now + timedelta(minutes=50)
                return self._cached_api_key
            except Exception:
                self._cached_api_key = None
                self._cached_api_key_expires_at = None
                return None

    def _forget_cached_api_key(self) -> None:
        with self._token_lock:
            self._cached_api_key = None
            self._cached_api_key_expires_at = None


catalog_client = TakealotCatalogClient()
