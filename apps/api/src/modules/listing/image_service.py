from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
CONTENT_TYPE_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


@dataclass
class ImageValidationResult:
    valid: bool
    content_type: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    extension: str | None = None
    warnings: list[str] | None = None
    errors: list[str] | None = None


class ListingImageService:
    def __init__(
        self,
        *,
        public_base_url: str | None = None,
        storage_root: Path | None = None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[5]
        self.public_base_url = (
            public_base_url
            if public_base_url is not None
            else os.getenv("XH_LISTING_PUBLIC_BASE_URL", "")
        ).strip()
        self.storage_root = storage_root or (repo_root / "apps" / "web" / "public" / "listing-assets")

    def validate_image_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str | None,
    ) -> ImageValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        size_bytes = len(data)
        extension = self._extension_from_filename(filename)
        detected_content_type = self._detect_content_type(data)
        declared_content_type = (content_type or "").split(";")[0].strip().lower() or None

        if not extension or extension not in ALLOWED_EXTENSIONS:
            errors.append("Unsupported image extension. Allowed formats: jpg, jpeg, png, webp.")
        if declared_content_type and declared_content_type not in ALLOWED_CONTENT_TYPES:
            errors.append("Unsupported image content-type. Allowed types: image/jpeg, image/png, image/webp.")
        if detected_content_type is None:
            errors.append("Image file signature is not a supported jpg, png, or webp image.")
        if size_bytes <= 0:
            errors.append("Image file is empty.")
        if size_bytes > MAX_IMAGE_BYTES:
            errors.append("Image file exceeds 10MB.")
        if detected_content_type and declared_content_type and detected_content_type != declared_content_type:
            warnings.append("Declared content-type does not match detected image signature.")

        return ImageValidationResult(
            valid=not errors,
            content_type=detected_content_type or declared_content_type,
            size_bytes=size_bytes,
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            extension=extension or (EXTENSION_BY_CONTENT_TYPE.get(detected_content_type or "") if detected_content_type else None),
            warnings=warnings,
            errors=errors,
        )

    def save_image_bytes(
        self,
        data: bytes,
        *,
        original_file_name: str,
        content_type: str | None,
    ) -> dict[str, Any]:
        validation = self.validate_image_bytes(
            data,
            filename=original_file_name,
            content_type=content_type,
        )
        if not validation.valid:
            return {
                "valid": False,
                "warnings": validation.warnings or [],
                "errors": validation.errors or [],
            }

        now = datetime.now(UTC)
        date_path = now.strftime("%Y/%m/%d")
        extension = validation.extension or EXTENSION_BY_CONTENT_TYPE.get(validation.content_type or "", "jpg")
        file_name = f"{uuid4().hex}.{extension}"
        target_dir = self.storage_root / date_path
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / file_name
        target_path.write_bytes(data)

        relative_path = f"listing-assets/{date_path}/{file_name}".replace("\\", "/")
        public_url, url_warnings = self.public_url_for(relative_path)
        return {
            "valid": True,
            "asset": {
                "asset_type": "image",
                "source": "upload",
                "original_file_name": original_file_name,
                "file_name": file_name,
                "storage_path": str(target_path),
                "public_url": public_url,
                "external_url": None,
                "content_type": validation.content_type,
                "size_bytes": validation.size_bytes,
                "checksum_sha256": validation.checksum_sha256,
                "width": None,
                "height": None,
                "validation_status": "warning" if url_warnings else "valid",
                "validation_errors": [],
                "raw_payload": {
                    "relative_path": relative_path,
                    "public_base_url_configured": bool(self.public_base_url),
                },
            },
            "warnings": [*(validation.warnings or []), *url_warnings],
            "errors": [],
        }

    def validate_image_url(
        self,
        image_url: str,
        *,
        check_remote: bool = True,
    ) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        parsed = urlparse(image_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {
                "image_url": image_url,
                "valid": False,
                "content_type": None,
                "size_bytes": None,
                "warnings": [],
                "errors": ["image_url must be an http or https URL."],
            }
        if not check_remote:
            return {
                "image_url": image_url,
                "valid": True,
                "content_type": None,
                "size_bytes": None,
                "warnings": ["Remote image accessibility was not checked."],
                "errors": [],
            }

        content_type = None
        size_bytes = None
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                response = client.head(image_url)
                if response.status_code in {405, 403} or not response.headers.get("content-type"):
                    response = client.get(image_url, headers={"Range": "bytes=0-0"})
                if response.status_code >= 400:
                    errors.append(f"Remote image returned HTTP {response.status_code}.")
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower() or None
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit():
                    size_bytes = int(content_length)
        except Exception as exc:
            errors.append(f"Remote image could not be checked: {exc}")

        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            errors.append("Remote URL content-type is not an allowed image type.")
        if not content_type:
            warnings.append("Remote URL did not provide a content-type header.")
        if size_bytes is not None and size_bytes > MAX_IMAGE_BYTES:
            errors.append("Remote image exceeds 10MB.")
        return {
            "image_url": image_url,
            "valid": not errors,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "warnings": warnings,
            "errors": errors,
        }

    def public_url_for(self, relative_path: str) -> tuple[str, list[str]]:
        normalized_path = relative_path.strip().replace("\\", "/").lstrip("/")
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{normalized_path}", []
        return (
            f"/{normalized_path}",
            ["XH_LISTING_PUBLIC_BASE_URL is not configured; Takealot loadsheets need publicly reachable image URLs."],
        )

    @staticmethod
    def is_http_url(value: str | None) -> bool:
        if not value:
            return False
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _extension_from_filename(filename: str) -> str | None:
        match = re.search(r"\.([A-Za-z0-9]+)$", filename or "")
        return match.group(1).lower() if match else None

    @staticmethod
    def _detect_content_type(data: bytes) -> str | None:
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return None
