"""Notifications API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DbSession, RedisConn
from app.models.notification import SiteNotification
from app.schemas.common import OkResponse

from sqlalchemy import func, select, update

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: CurrentUser, db: DbSession,
    limit: int = Query(50, ge=1, le=100),
):
    result = await db.execute(
        select(SiteNotification)
        .where(SiteNotification.user_id == user.id)
        .order_by(SiteNotification.created_at.desc())
        .limit(limit)
    )
    notifications = list(result.scalars().all())

    items = []
    for n in notifications:
        items.append({
            "id": n.id,
            "level": n.level,
            "title": n.title,
            "detail": n.body or "",
            "module": n.module or "",
            "is_read": n.is_read,
            "created_at": str(n.created_at) if n.created_at else None,
        })

    return {"ok": True, "notifications": items}


@router.post("/{notif_id}/read", response_model=OkResponse)
async def mark_read(notif_id: int, user: CurrentUser, db: DbSession, redis: RedisConn):
    result = await db.execute(
        select(SiteNotification).where(
            SiteNotification.id == notif_id, SiteNotification.user_id == user.id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="通知不存在")
    notification.is_read = 1
    await db.flush()
    await redis.delete(f"notif_unread:{user.id}")
    return OkResponse()


@router.post("/read_all")
async def mark_all_read(user: CurrentUser, db: DbSession, redis: RedisConn):
    result = await db.execute(
        update(SiteNotification)
        .where(SiteNotification.user_id == user.id, SiteNotification.is_read == 0)
        .values(is_read=1)
    )
    await redis.delete(f"notif_unread:{user.id}")
    return {"ok": True, "updated": result.rowcount}


@router.get("/unread_count")
async def unread_count(user: CurrentUser, db: DbSession, redis: RedisConn):
    # Check Redis cache first (30s TTL)
    cache_key = f"notif_unread:{user.id}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return {"ok": True, "count": int(cached)}

    result = await db.execute(
        select(func.count()).select_from(SiteNotification).where(
            SiteNotification.user_id == user.id, SiteNotification.is_read == 0,
        )
    )
    count = result.scalar_one()
    await redis.setex(cache_key, 30, str(count))
    return {"ok": True, "count": count}
