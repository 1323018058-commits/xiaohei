"""Admin API router — user management, license management, system health."""
from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.models.user import LicenseKey, User
from app.models.store import StoreBinding
from app.schemas.admin import (
    AdminStats,
    LicenseGenerateRequest,
    LicenseGenerateResponse,
    LicenseListItem,
    SystemHealthComponent,
    SystemHealthResponse,
    UserListItem,
)
from app.schemas.common import OkResponse
from app.services import auth_service, store_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AdminStats)
async def admin_stats(admin: AdminUser, db: DbSession):
    now = datetime.utcnow()

    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    active_users = (await db.execute(
        select(func.count()).select_from(User).where(
            (User.role == "admin") | (User.activated_until > now)
        )
    )).scalar_one()
    total_keys = (await db.execute(select(func.count()).select_from(LicenseKey))).scalar_one()
    unused_keys = (await db.execute(
        select(func.count()).select_from(LicenseKey).where(LicenseKey.is_used == 0)
    )).scalar_one()

    return AdminStats(
        total_users=total_users,
        active_users=active_users,
        total_keys=total_keys,
        unused_keys=unused_keys,
    )


# ---------------------------------------------------------------------------
# System Health
# ---------------------------------------------------------------------------

@router.get("/system-health", response_model=SystemHealthResponse)
async def admin_system_health(admin: AdminUser, db: DbSession):
    active_stores = await store_service.count_active_stores(db)

    components = [
        SystemHealthComponent(name="Database", level="healthy", detail="PostgreSQL 连接正常"),
        SystemHealthComponent(name="Active Stores", level="healthy" if active_stores > 0 else "warning",
                              detail=f"{active_stores} 个活跃店铺"),
    ]

    metrics = {
        "active_stores": active_stores,
    }

    return SystemHealthResponse(metrics=metrics, components=components)


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@router.get("/users")
async def admin_list_users(admin: AdminUser, db: DbSession):
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()

    now = datetime.utcnow()
    items = []
    for u in users:
        activated = auth_service.is_user_active(u)

        # Count stores
        store_result = await db.execute(
            select(func.count()).select_from(StoreBinding).where(
                StoreBinding.user_id == u.id, StoreBinding.is_active == 1,
            )
        )
        store_count = store_result.scalar_one()

        items.append(UserListItem(
            id=u.id,
            username=u.username,
            role=u.role,
            activated=activated,
            activated_until=u.activated_until.strftime("%Y-%m-%d %H:%M:%S") if u.activated_until else None,
            store_count=store_count,
            created_at=u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else None,
        ))

    return {"ok": True, "users": [item.model_dump() for item in items]}


@router.post("/users/{user_id}/toggle", response_model=OkResponse)
async def admin_toggle_user(user_id: int, admin: AdminUser, db: DbSession):
    user = await auth_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="不能禁用管理员")

    now = datetime.utcnow()
    if user.activated_until and user.activated_until > now:
        # Deactivate by setting activated_until to now
        user.activated_until = now
    else:
        # Reactivate for 30 days
        user.activated_until = now + timedelta(days=30)
    await db.flush()

    return OkResponse()


# ---------------------------------------------------------------------------
# License Management
# ---------------------------------------------------------------------------

@router.get("/licenses")
async def admin_list_licenses(
    admin: AdminUser, db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    offset = (page - 1) * page_size
    total = (await db.execute(select(func.count()).select_from(LicenseKey))).scalar_one()
    result = await db.execute(
        select(LicenseKey).order_by(LicenseKey.id.desc()).offset(offset).limit(page_size)
    )
    keys = result.scalars().all()

    items = []
    for k in keys:
        items.append(LicenseListItem(
            id=k.id,
            key=k.key,
            days=k.days,
            batch_name=k.batch_name,
            is_used=k.is_used,
            used_by=k.used_by,
            used_at=k.used_at.strftime("%Y-%m-%d %H:%M:%S") if k.used_at else None,
            created_at=k.created_at.strftime("%Y-%m-%d %H:%M:%S") if k.created_at else None,
        ))

    return {
        "ok": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "licenses": [item.model_dump() for item in items],
    }


@router.post("/licenses/generate", response_model=LicenseGenerateResponse)
async def admin_generate_licenses(body: LicenseGenerateRequest, admin: AdminUser, db: DbSession):
    keys: list[str] = []
    for _ in range(body.count):
        key = secrets.token_hex(16).upper()
        # Format: XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
        formatted = "-".join(key[i:i+4] for i in range(0, len(key), 4))
        license_key = LicenseKey(
            key=formatted,
            days=body.days,
            batch_name=body.batch_name or None,
        )
        db.add(license_key)
        keys.append(formatted)

    await db.flush()
    return LicenseGenerateResponse(count=len(keys), keys=keys)


@router.get("/licenses/export")
async def admin_export_licenses(admin: AdminUser, db: DbSession):
    result = await db.execute(
        select(LicenseKey).where(LicenseKey.is_used == 0).order_by(LicenseKey.id)
    )
    keys = result.scalars().all()

    output = io.StringIO()
    # UTF-8 BOM for Excel compatibility
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["激活码", "天数", "批次", "创建时间"])
    for k in keys:
        writer.writerow([
            k.key,
            k.days,
            k.batch_name or "",
            k.created_at.strftime("%Y-%m-%d %H:%M:%S") if k.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=unused_licenses.csv"},
    )
