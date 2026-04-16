"""Extension service — token management, status building, profit calc for Chrome extension."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extension import ExtensionAction, ExtensionAuthToken
from app.models.store import StoreBinding
from app.services import store_service
from app.services.takealot_api import TakealotSellerAPI
from app.utils.encryption import decrypt

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_DAYS = 90
AUTH_CODE_TTL_SECONDS = 120
AUTH_CODE_REDIS_PREFIX = "extension:auth_code"


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _auth_code_key(raw_code: str) -> str:
    digest = hashlib.sha256(raw_code.encode()).hexdigest()
    return f"{AUTH_CODE_REDIS_PREFIX}:{digest}"


async def issue_token(db: AsyncSession, user_id: int) -> str:
    """Issue a new extension auth token, revoking any previous ones."""
    # Revoke existing
    await db.execute(
        delete(ExtensionAuthToken).where(ExtensionAuthToken.user_id == user_id)
    )

    raw_token = secrets.token_urlsafe(48)
    token = ExtensionAuthToken(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        token_name="takealot_extension",
        expires_at=datetime.utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS),
    )
    db.add(token)
    await db.flush()
    return raw_token


async def issue_authorization_code(redis, user_id: int) -> tuple[str, str]:
    """Issue a short-lived one-time auth code for extension bootstrap."""
    raw_code = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=AUTH_CODE_TTL_SECONDS)
    payload = json.dumps({"user_id": user_id})
    await redis.setex(_auth_code_key(raw_code), AUTH_CODE_TTL_SECONDS, payload)
    return raw_code, expires_at.isoformat()


async def redeem_authorization_code(db: AsyncSession, redis, raw_code: str) -> dict | None:
    """Redeem a one-time auth code into a long-lived extension token."""
    code = str(raw_code or "").strip()
    if not code:
        return None

    key = _auth_code_key(code)
    payload = None
    getdel = getattr(redis, "getdel", None)
    if callable(getdel):
        payload = await getdel(key)
    else:
        payload = await redis.get(key)
        if payload:
            await redis.delete(key)

    if not payload:
        return None

    try:
        data = json.loads(payload)
        user_id = int(data.get("user_id", 0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if user_id <= 0:
        return None

    raw_token = await issue_token(db, user_id)
    expires_at = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS)
    return {
        "token": raw_token,
        "expires_at": expires_at.isoformat(),
        "user_id": user_id,
    }


async def verify_token(db: AsyncSession, raw_token: str) -> ExtensionAuthToken | None:
    """Verify an extension token and update last_used_at."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(ExtensionAuthToken).where(
            ExtensionAuthToken.token_hash == token_hash,
            ExtensionAuthToken.expires_at > datetime.utcnow(),
        )
    )
    token = result.scalar_one_or_none()
    if token:
        token.last_used_at = datetime.utcnow()
        await db.flush()
    return token


async def revoke_token(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        delete(ExtensionAuthToken).where(ExtensionAuthToken.user_id == user_id)
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Status for extension popup
# ---------------------------------------------------------------------------

async def build_status(db: AsyncSession, user_id: int) -> dict:
    """Build status payload for extension popup — stores list + basic stats."""
    from app.services import auth_service
    user = await auth_service.get_user_by_id(db, user_id)

    stores = await store_service.list_stores(db, user_id)
    store_list = []
    for s in stores:
        store_list.append({
            "id": s.id,
            "name": s.store_name or s.store_alias or f"Store #{s.id}",
            "offer_count": s.offer_count or 0,
            "api_key_status": s.api_key_status or "",
        })

    active_store = store_list[0] if store_list else None

    return {
        "user": {"id": user_id, "name": user.username if user else "用户"},
        "store": active_store,
        "store_count": len(store_list),
        "stores": store_list,
    }


# ---------------------------------------------------------------------------
# Pricing config for extension
# ---------------------------------------------------------------------------

async def get_pricing_config(db: AsyncSession, store_id: int, user_id: int) -> dict | None:
    """Get store pricing config (commission, fx rate, etc) for extension."""
    store = await store_service.get_store(db, store_id, user_id)
    if not store:
        return None

    from app.config import get_settings
    settings = get_settings()

    return {
        "store_id": store.id,
        "store_name": store.store_name or "",
        "commission_rate": settings.commission_rate,
        "vat_rate": settings.vat_rate,
        "fx_rate": settings.fx_zar_to_cny,
        "freight_rate": settings.freight_rate_cny_per_kg,
        "default_weight_kg": settings.default_weight_kg,
        "target_margin": settings.target_margin_rate,
        "default_air_freight_cny_per_kg": settings.freight_rate_cny_per_kg,
        "default_operation_fee_cny": 20.0,
        "exchange_rate_zar_to_cny": settings.fx_zar_to_cny,
        "notes": {
            "operation_fee_hint": "JHB:20 / CPT / DBN:30",
            "size_weight_rule": "体积重 = 长 × 宽 × 高 / 6000",
        },
    }


# ---------------------------------------------------------------------------
# Profit calculator for extension
# ---------------------------------------------------------------------------

def calculate_profit_for_extension(
    selling_price_zar: float,
    purchase_price_cny: float,
    weight_kg: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    air_freight_cny_per_kg: float,
    operation_fee_cny: float,
    commission_rate: float,
    vat_rate: float,
    fx_rate: float,
) -> dict:
    """Detailed profit calculation matching content.js expected fields."""
    if selling_price_zar <= 0:
        return {"ok": False, "error": "售价必须大于0"}

    # 1. Chargeable weight = max(actual, volumetric)
    vol_weight = (length_cm * width_cm * height_cm) / 6000 if (length_cm > 0 and width_cm > 0 and height_cm > 0) else 0
    chargeable_weight = max(weight_kg, vol_weight)

    # 2. Air freight cost
    air_freight_cny = chargeable_weight * air_freight_cny_per_kg
    air_freight_zar = air_freight_cny / fx_rate if fx_rate > 0 else 0

    # 3. Takealot commission + VAT
    commission_zar = selling_price_zar * commission_rate
    vat_zar = selling_price_zar * vat_rate / (1 + vat_rate)

    # 4. Withdrawal + FX loss (estimated 3.5% of selling price)
    withdrawal_fx_rate = 0.035
    withdrawal_fx_loss_zar = selling_price_zar * withdrawal_fx_rate

    # 5. Last mile fee (Takealot fulfillment, estimated based on weight)
    last_mile_fee_zar = 45.0 if chargeable_weight <= 5 else 45.0 + (chargeable_weight - 5) * 5
    last_mile_vat_zar = last_mile_fee_zar * 0.15

    # 6. Total cost in ZAR
    cost_zar = purchase_price_cny / fx_rate if fx_rate > 0 else 0
    operation_fee_zar = operation_fee_cny / fx_rate if fx_rate > 0 else 0
    total_cost_zar = cost_zar + air_freight_zar + operation_fee_zar + commission_zar + vat_zar + withdrawal_fx_loss_zar + last_mile_fee_zar + last_mile_vat_zar

    # 7. Profit in ZAR and CNY
    profit_zar = selling_price_zar - total_cost_zar
    profit_cny = profit_zar * fx_rate if fx_rate > 0 else 0
    profit_rate_pct = (profit_zar / selling_price_zar * 100) if selling_price_zar > 0 else 0

    # 8. Recommended prices for target margins (10%, 30%)
    def _reco_price(target_pct: float) -> float:
        """Calculate minimum selling price for a given target profit margin."""
        base_cost = cost_zar + air_freight_zar + operation_fee_zar + last_mile_fee_zar + last_mile_vat_zar
        denom = 1 - commission_rate - vat_rate / (1 + vat_rate) - withdrawal_fx_rate - target_pct / 100
        return base_cost / denom if denom > 0 else 0

    reco_10 = _reco_price(10)
    reco_30 = _reco_price(30)

    return {
        "ok": True,
        "result": {
            "chargeable_weight_kg": round(chargeable_weight, 2),
            "air_profit_rate_pct": round(profit_rate_pct, 2),
            "air_profit_cny": round(profit_cny, 2),
            "air_freight_zar": round(air_freight_zar, 2),
            "withdrawal_fx_loss_zar": round(withdrawal_fx_loss_zar, 2),
            "recommended_price_10pct": round(reco_10, 2),
            "recommended_price_30pct": round(reco_30, 2),
            "last_mile_fee_zar": round(last_mile_fee_zar, 2),
            "last_mile_vat_zar": round(last_mile_vat_zar, 2),
        },
    }


# ---------------------------------------------------------------------------
# Action logging (list-now, list-history)
# ---------------------------------------------------------------------------

async def log_action(
    db: AsyncSession,
    user_id: int,
    store_id: int,
    action_type: str,
    plid: str,
    **kwargs: str | float,
) -> ExtensionAction:
    """Log an extension action (e.g. list-now click)."""
    action = ExtensionAction(
        user_id=user_id,
        store_id=store_id,
        action_type=action_type,
        plid=plid,
        page_url=str(kwargs.get("page_url", "")),
        title=str(kwargs.get("title", "")),
        image_url=str(kwargs.get("image_url", "")),
        barcode=str(kwargs.get("barcode", "")),
        brand_name=str(kwargs.get("brand_name", "")),
        buybox_price_zar=float(kwargs.get("buybox_price_zar", 0)),
        page_price_zar=float(kwargs.get("page_price_zar", 0)),
        target_price_zar=float(kwargs.get("target_price_zar", 0)),
        offer_id=str(kwargs.get("offer_id", "")),
        pricing_snapshot_json=str(kwargs.get("pricing_snapshot_json", "")),
        raw_json=str(kwargs.get("raw_json", "")),
    )
    db.add(action)
    await db.flush()
    return action


async def list_actions(
    db: AsyncSession, user_id: int, limit: int = 50,
) -> list[ExtensionAction]:
    result = await db.execute(
        select(ExtensionAction)
        .where(ExtensionAction.user_id == user_id)
        .order_by(ExtensionAction.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
