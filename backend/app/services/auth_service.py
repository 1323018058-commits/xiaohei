"""Auth service — user CRUD, password hashing, JWT token management."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User, LicenseKey


# ---------------------------------------------------------------------------
# Password hashing — PBKDF2-SHA256, compatible with ProfitLens v2 format
# Format: "{hex_salt}${hex_dk}" with 260,000 iterations
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, dk_hex = stored_hash.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, username: str, role: str) -> str:
    settings = get_settings()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int) -> str:
    settings = get_settings()
    expire = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": secrets.token_urlsafe(32),
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


async def store_refresh_token(redis: aioredis.Redis, user_id: int, token: str) -> None:
    """Store refresh token in Redis with TTL."""
    settings = get_settings()
    ttl = settings.jwt_refresh_token_expire_days * 86400
    key = f"refresh_token:{user_id}:{token}"
    await redis.setex(key, ttl, "1")


async def revoke_refresh_token(redis: aioredis.Redis, user_id: int, token: str) -> None:
    key = f"refresh_token:{user_id}:{token}"
    await redis.delete(key)


async def is_refresh_token_valid(redis: aioredis.Redis, user_id: int, token: str) -> bool:
    key = f"refresh_token:{user_id}:{token}"
    return await redis.exists(key) > 0


async def revoke_all_user_tokens(redis: aioredis.Redis, user_id: int) -> None:
    """Revoke all refresh tokens for a user."""
    pattern = f"refresh_token:{user_id}:*"
    async for key in redis.scan_iter(match=pattern, count=100):
        await redis.delete(key)


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------

def is_user_active(user: User) -> bool:
    if user.role == "admin":
        return True
    if not user.activated_until:
        return False
    return user.activated_until > datetime.utcnow()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, username: str, password: str, email: str = "", role: str = "user") -> User:
    loop = asyncio.get_event_loop()
    pw_hash = await loop.run_in_executor(None, hash_password, password)
    user = User(
        username=username,
        email=email or None,
        password_hash=pw_hash,
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def activate_license(db: AsyncSession, user_id: int, key: str) -> dict:
    """Activate a license key for a user. Returns result dict."""
    result = await db.execute(
        select(LicenseKey).where(LicenseKey.key == key, LicenseKey.is_used == 0)
    )
    license_key = result.scalar_one_or_none()
    if not license_key:
        return {"ok": False, "error": "激活码无效或已被使用"}

    user = await get_user_by_id(db, user_id)
    if not user:
        return {"ok": False, "error": "用户不存在"}

    now = datetime.utcnow()
    current_until = user.activated_until if user.activated_until and user.activated_until > now else now
    new_until = current_until + timedelta(days=license_key.days)

    user.activated_until = new_until
    user.license_key = key

    license_key.is_used = 1
    license_key.used_by = user_id
    license_key.used_at = now

    await db.flush()
    return {
        "ok": True,
        "activated_until": new_until.strftime("%Y-%m-%d %H:%M:%S"),
    }
