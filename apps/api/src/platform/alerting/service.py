from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.platform.settings.base import settings


logger = logging.getLogger(__name__)


class AlertService:
    def emit(
        self,
        *,
        event: str,
        severity: str,
        message: str,
        source: str,
        details: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        generated_at = datetime.now(UTC).isoformat()
        payload = {
            "event": event,
            "severity": severity,
            "generated_at": generated_at,
            "source": source,
            "message": message,
            "summary": summary,
            "details": details,
        }
        alert_path = self._write_local_alert(event, generated_at, payload)
        webhook_status = self._deliver_webhook(payload)
        return {
            "path": str(alert_path),
            "webhook_status": webhook_status,
            "generated_at": generated_at,
        }

    def _write_local_alert(
        self,
        event: str,
        generated_at: str,
        payload: dict[str, Any],
    ) -> Path:
        alert_dir = self._resolve_dir(settings.alert_output_dir)
        alert_dir.mkdir(parents=True, exist_ok=True)
        timestamp = generated_at.replace(":", "").replace("-", "")
        safe_event = event.replace(".", "-").replace("/", "-")
        path = alert_dir / f"{safe_event}-{timestamp}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _deliver_webhook(self, payload: dict[str, Any]) -> str:
        webhook_url = (settings.alert_webhook_url or "").strip()
        if not webhook_url:
            return "skipped"
        try:
            httpx.post(
                webhook_url,
                json=payload,
                timeout=10.0,
            ).raise_for_status()
        except Exception as exc:
            logger.warning("alert_webhook_delivery_failed error=%s", exc)
            return "failed"
        return "delivered"

    @staticmethod
    def _resolve_dir(path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return Path.cwd() / path


alert_service = AlertService()
