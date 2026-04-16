"""Store service — CRUD, sync, health scoring for store bindings."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.store import StoreBinding
from app.models.product import BidProduct
from app.services.takealot_api import TakealotSellerAPI
from app.utils.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def list_stores(db: AsyncSession, user_id: int) -> list[StoreBinding]:
    result = await db.execute(
        select(StoreBinding)
        .where(StoreBinding.user_id == user_id, StoreBinding.is_active == 1)
        .order_by(StoreBinding.id)
    )
    return list(result.scalars().all())


async def get_store(db: AsyncSession, store_id: int, user_id: int) -> StoreBinding | None:
    result = await db.execute(
        select(StoreBinding)
        .where(StoreBinding.id == store_id, StoreBinding.user_id == user_id, StoreBinding.is_active == 1)
    )
    return result.scalar_one_or_none()


async def get_store_admin(db: AsyncSession, store_id: int) -> StoreBinding | None:
    """Admin access — no user_id filter."""
    result = await db.execute(
        select(StoreBinding).where(StoreBinding.id == store_id)
    )
    return result.scalar_one_or_none()


async def create_store(
    db: AsyncSession,
    user_id: int,
    api_key: str,
    api_secret: str = "",
    store_name: str = "",
    takealot_store_id: str = "",
) -> StoreBinding:
    store = StoreBinding(
        user_id=user_id,
        api_key=encrypt(api_key),
        api_secret=encrypt(api_secret) if api_secret else "",
        store_name=store_name,
        takealot_store_id=takealot_store_id,
        is_active=1,
    )
    db.add(store)
    await db.flush()
    return store


async def update_store(
    db: AsyncSession,
    store: StoreBinding,
    **fields: str | int | None,
) -> StoreBinding:
    allowed = {
        "store_alias", "store_name", "notes", "auto_push_price",
        "min_price_90pct", "direct_ship", "api_key_status",
        "unique_id", "takealot_store_id",
    }
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(store, key, value)
    await db.flush()
    return store


async def soft_delete_store(db: AsyncSession, store: StoreBinding) -> None:
    store.is_active = 0
    await db.flush()


async def update_api_credentials(
    db: AsyncSession,
    store: StoreBinding,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> None:
    if api_key is not None:
        store.api_key = encrypt(api_key)
    if api_secret is not None:
        store.api_secret = encrypt(api_secret) if api_secret else ""
    await db.flush()


# ---------------------------------------------------------------------------
# Sync with Takealot
# ---------------------------------------------------------------------------

async def sync_store(db: AsyncSession, store: StoreBinding) -> dict:
    """Call Takealot API to refresh store info (offer count, etc)."""
    raw_key = decrypt(store.api_key)
    api = TakealotSellerAPI(raw_key)

    try:
        info = await api.get_store_info()
        store.offer_count = info.get("offer_count", 0)
        store.last_synced_at = datetime.utcnow()
        store.api_key_status = "有效"
        if info.get("store_name") and not store.store_name:
            store.store_name = info["store_name"]
        await db.flush()
        return {"ok": True, "offer_count": store.offer_count}
    except RuntimeError as exc:
        store.api_key_status = "无效"
        await db.flush()
        return {"ok": False, "error": str(exc)}


def get_takealot_api(store: StoreBinding) -> TakealotSellerAPI:
    """Create a TakealotSellerAPI instance for a store binding."""
    raw_key = decrypt(store.api_key)
    raw_secret = decrypt(store.api_secret) if store.api_secret else ""
    return TakealotSellerAPI(raw_key, raw_secret)


# ---------------------------------------------------------------------------
# Health scoring
# ---------------------------------------------------------------------------

def health_score(store: StoreBinding, bid_error_count: int = 0) -> dict:
    """Compute 0-100 health score for a store.

    Points:
      40 — API key status is valid
      20 — synced within last 2 hours
      20 — offer_count > 0
      20 — zero bid errors
    """
    score = 0
    now = datetime.utcnow()

    if store.api_key_status == "有效":
        score += 40

    if store.last_synced_at:
        age_hours = (now - store.last_synced_at).total_seconds() / 3600
        if age_hours < 2:
            score += 20

    if store.offer_count > 0:
        score += 20

    if bid_error_count == 0:
        score += 20

    if score >= 80:
        level = "healthy"
    elif score >= 55:
        level = "warning"
    else:
        level = "critical"

    return {"score": score, "level": level}


def sync_freshness(last_synced_at: datetime | None) -> str:
    """Return Chinese freshness label."""
    if not last_synced_at:
        return "从未同步"
    now = datetime.utcnow()
    delta = (now - last_synced_at).total_seconds()
    if delta < 120:
        return "刚刚同步"
    if delta < 1800:
        return "30分钟内"
    if delta < 7200:
        return "2小时内"
    if delta < 86400:
        return "今日已同步"
    return "长时间未同步"


# ---------------------------------------------------------------------------
# Aggregation helpers for dashboard / list views
# ---------------------------------------------------------------------------

async def get_store_bid_error_counts(db: AsyncSession, store_ids: list[int]) -> dict[int, int]:
    """Return {store_id: error_count} for given stores."""
    if not store_ids:
        return {}
    result = await db.execute(
        select(BidProduct.store_binding_id, func.count())
        .where(
            BidProduct.store_binding_id.in_(store_ids),
            BidProduct.last_action.isnot(None),
            BidProduct.last_action.like("%error%"),
        )
        .group_by(BidProduct.store_binding_id)
    )
    return dict(result.all())


async def get_store_bid_counts(db: AsyncSession, store_ids: list[int]) -> dict[int, dict]:
    """Return {store_id: {total, active, paused}} for given stores."""
    if not store_ids:
        return {}
    result = await db.execute(
        select(
            BidProduct.store_binding_id,
            func.count().label("total"),
            func.sum(func.cast(BidProduct.auto_bid_enabled == 1, int)).label("active"),
        )
        .where(BidProduct.store_binding_id.in_(store_ids))
        .group_by(BidProduct.store_binding_id)
    )
    out: dict[int, dict] = {}
    for row in result.all():
        sid, total, active = row
        out[sid] = {"total": total, "active": active or 0, "paused": total - (active or 0)}
    return out


async def count_active_stores(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(StoreBinding).where(StoreBinding.is_active == 1)
    )
    return result.scalar_one()
