"""AESGCM encryption for sensitive data fields.

Backward-compatible with the original ProfitLens v2 encryption format:
- Encrypted values use the prefix "enc:v1:" followed by base64url-encoded (nonce + ciphertext).
- The encryption key is read from the PROFITLENS_DATA_KEY environment variable
  (32 bytes, either hex-encoded or base64url-encoded).
"""
from __future__ import annotations

import base64
import os
import re
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DATA_KEY_ENV = "PROFITLENS_DATA_KEY"
_ENCRYPTED_VALUE_PREFIX = "enc:v1:"


def _decode_data_key(raw_key: str) -> bytes:
    raw = str(raw_key or "").strip()
    if not raw:
        raise ValueError("empty data key")
    if re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        key = bytes.fromhex(raw)
    else:
        padded = raw + "=" * (-len(raw) % 4)
        key = base64.urlsafe_b64decode(padded.encode("utf-8"))
    if len(key) != 32:
        raise ValueError("data key must decode to exactly 32 bytes")
    return key


def _get_data_key_bytes() -> bytes | None:
    raw = str(os.environ.get(_DATA_KEY_ENV) or "").strip()
    if not raw:
        return None
    return _decode_data_key(raw)


def encryption_ready() -> bool:
    """Return True if encryption key is configured and available."""
    return _get_data_key_bytes() is not None


def is_encrypted(value: str | None) -> bool:
    """Check if a value uses the enc:v1: format."""
    return str(value or "").startswith(_ENCRYPTED_VALUE_PREFIX)


def encrypt(value: str | None, *, force: bool = False) -> str:
    """Encrypt a plaintext value. Returns the value unchanged if no key is configured
    (unless force=True, which raises an error).

    Already-encrypted values are returned as-is.
    """
    raw = str(value or "")
    if not raw:
        return ""
    if is_encrypted(raw):
        return raw

    key = _get_data_key_bytes()
    if not key:
        if force:
            raise RuntimeError(f"{_DATA_KEY_ENV} not configured, cannot encrypt")
        return raw

    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, raw.encode("utf-8"), None)
    payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8").rstrip("=")
    return _ENCRYPTED_VALUE_PREFIX + payload


def decrypt(value: str | None) -> str:
    """Decrypt an enc:v1: value. Returns plaintext values unchanged."""
    raw = str(value or "")
    if not raw or not is_encrypted(raw):
        return raw

    key = _get_data_key_bytes()
    if not key:
        raise RuntimeError(f"Encrypted data found but {_DATA_KEY_ENV} not configured")

    payload = raw[len(_ENCRYPTED_VALUE_PREFIX):]
    padded = payload + "=" * (-len(payload) % 4)
    blob = base64.urlsafe_b64decode(padded.encode("utf-8"))
    if len(blob) <= 12:
        raise ValueError("invalid encrypted payload")

    nonce, ciphertext = blob[:12], blob[12:]
    plain = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plain.decode("utf-8")


def encrypt_dict_fields(data: dict, sensitive_fields: set[str]) -> dict:
    """Encrypt specified fields in a dict. Returns a new dict."""
    result = dict(data or {})
    for field in sensitive_fields:
        if field in result:
            result[field] = encrypt(result.get(field))
    return result


def decrypt_dict_fields(data: dict, sensitive_fields: set[str]) -> dict:
    """Decrypt specified fields in a dict. Returns a new dict."""
    result = dict(data or {})
    for field in sensitive_fields:
        if field in result:
            result[field] = decrypt(result.get(field))
    return result


# Sensitive field sets for each model (same as original system)
STORE_SECRET_FIELDS = {"api_key", "api_secret"}
CNEXPRESS_SECRET_FIELDS = {"token", "account_password"}
WEBHOOK_SECRET_FIELDS = {"secret"}
