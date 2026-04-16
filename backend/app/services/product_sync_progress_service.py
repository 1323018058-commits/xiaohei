"""Product sync progress helpers (Redis-backed)."""
from __future__ import annotations

from datetime import datetime
import json

from app.config import get_settings


class SyncTaskMissing(RuntimeError):
    """Raised when the product sync task module is unavailable."""


DEFAULT_PROGRESS_SCOPE = "default"
DEFAULT_LOCK_SCOPE = "store_products"


def default_progress_payload() -> dict:
    return {"running": False, "stage": "idle"}


def _normalize_scope(scope: str | None, *, fallback: str) -> str:
    value = str(scope or "").strip()
    return value or fallback


def _lock_key(store_id: int, lock_scope: str | None = None) -> str:
    scope = _normalize_scope(lock_scope, fallback=DEFAULT_LOCK_SCOPE)
    return f"product_sync_lock:{scope}:{store_id}"


def _progress_key(store_id: int, scope: str | None = None) -> str:
    progress_scope = _normalize_scope(scope, fallback=DEFAULT_PROGRESS_SCOPE)
    return f"product_sync_progress:{progress_scope}:{store_id}"


async def try_acquire_sync(redis, store_id: int, *, owner: str, lock_scope: str | None = None) -> bool:
    settings = get_settings()
    acquired = await redis.set(
        _lock_key(store_id, lock_scope),
        owner,
        ex=settings.product_sync_progress_ttl_seconds,
        nx=True,
    )
    return bool(acquired)


async def get_sync_owner(redis, store_id: int, *, lock_scope: str | None = None) -> str:
    raw = await redis.get(_lock_key(store_id, lock_scope))
    return str(raw or "").strip()


async def release_sync(redis, store_id: int, *, lock_scope: str | None = None) -> None:
    await redis.delete(_lock_key(store_id, lock_scope))


async def get_progress(redis, store_id: int, *, scope: str | None = None) -> dict:
    raw = await redis.get(_progress_key(store_id, scope))
    if not raw:
        return default_progress_payload()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default_progress_payload()
    if "running" not in payload:
        payload["running"] = True
    if "stage" not in payload:
        payload["stage"] = "idle"
    return payload


async def set_progress(redis, store_id: int, *, scope: str | None = None, **fields) -> None:
    settings = get_settings()
    current = await get_progress(redis, store_id, scope=scope)
    current.update(fields)
    if "running" not in fields:
        current["running"] = True
    now = datetime.utcnow().isoformat()
    current["updated_at"] = now
    if current.get("running") and not current.get("started_at"):
        current["started_at"] = now
    await redis.setex(
        _progress_key(store_id, scope),
        settings.product_sync_progress_ttl_seconds,
        json.dumps(current, default=str),
    )


async def clear_progress(
    redis,
    store_id: int,
    *,
    scope: str | None = None,
    lock_scope: str | None = None,
    result: str = "done",
    **fields,
) -> None:
    settings = get_settings()
    current = await get_progress(redis, store_id, scope=scope)
    current.update(fields)
    current["running"] = False
    current["result"] = result
    now = datetime.utcnow().isoformat()
    current["updated_at"] = now
    if not current.get("finished_at"):
        current["finished_at"] = now
    if "stage" not in fields:
        current["stage"] = result
    await redis.setex(
        _progress_key(store_id, scope),
        settings.product_sync_progress_ttl_seconds,
        json.dumps(current, default=str),
    )
    await release_sync(redis, store_id, lock_scope=lock_scope)


async def enqueue_sync(
    redis,
    store_id: int,
    *,
    task_importer,
    task_args: tuple | None = None,
    task_kwargs: dict | None = None,
    progress_scope: str | None = None,
    lock_scope: str | None = None,
    queued_message: str = "任务已提交，等待同步开始...",
    conflict_message: str = "另一同步任务正在运行，请稍后再试",
) -> dict:
    scope = _normalize_scope(progress_scope, fallback=DEFAULT_PROGRESS_SCOPE)
    shared_lock_scope = _normalize_scope(lock_scope, fallback=DEFAULT_LOCK_SCOPE)
    acquired = await try_acquire_sync(
        redis,
        store_id,
        owner=scope,
        lock_scope=shared_lock_scope,
    )
    if not acquired:
        owner = await get_sync_owner(redis, store_id, lock_scope=shared_lock_scope)
        if owner == scope:
            progress = await get_progress(redis, store_id, scope=scope)
            progress["running"] = True
            return {"ok": False, "running": True, **progress}
        return {
            "ok": False,
            "running": False,
            "stage": "blocked",
            "message": conflict_message,
        }

    await set_progress(
        redis,
        store_id,
        scope=scope,
        stage="queued",
        message=queued_message,
    )
    try:
        task_func = task_importer()
    except ImportError as exc:
        await clear_progress(
            redis,
            store_id,
            scope=scope,
            lock_scope=shared_lock_scope,
            result="missing_task",
            stage="error",
            message="同步任务未就绪",
        )
        raise SyncTaskMissing("product sync task missing") from exc

    task = task_func.delay(store_id, *(task_args or ()), **(task_kwargs or {}))
    return {"ok": True, "async": True, "task_id": task.id, "stage": "queued"}
