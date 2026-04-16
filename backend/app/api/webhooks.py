"""Takealot Webhook API router — receive, verify HMAC, invalidate caches."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import ActiveUser, DbSession, RedisConn
from app.models.webhook import TakealotWebhookConfig, TakealotWebhookDelivery
from app.services import store_service
from app.utils.encryption import decrypt, encrypt

from sqlalchemy import select

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Get webhook config for a store
# ---------------------------------------------------------------------------

@router.get("/config/{store_id}")
async def get_webhook_config(store_id: int, user: ActiveUser, db: DbSession):
    """Get webhook configuration for a store."""
    store = await store_service.get_store(db, store_id, user.id)
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")

    result = await db.execute(
        select(TakealotWebhookConfig).where(
            TakealotWebhookConfig.store_binding_id == store_id,
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        return {
            "ok": True,
            "config": None,
            "webhook_url": f"/api/webhooks/receive/{store_id}",
        }

    return {
        "ok": True,
        "config": {
            "id": config.id,
            "store_binding_id": config.store_binding_id,
            "active": config.active,
            "has_secret": bool(config.secret),
            "last_delivery_at": str(config.last_delivery_at) if config.last_delivery_at else None,
            "last_event_type": config.last_event_type,
            "last_delivery_status": config.last_delivery_status,
            "created_at": str(config.created_at) if config.created_at else None,
        },
        "webhook_url": f"/api/webhooks/receive/{store_id}",
    }


# ---------------------------------------------------------------------------
# 2. Save webhook config (create or update)
# ---------------------------------------------------------------------------

@router.post("/config/{store_id}")
async def save_webhook_config(
    store_id: int, body: dict, user: ActiveUser, db: DbSession,
):
    """Create or update webhook config for a store."""
    store = await store_service.get_store(db, store_id, user.id)
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在")

    result = await db.execute(
        select(TakealotWebhookConfig).where(
            TakealotWebhookConfig.store_binding_id == store_id,
        )
    )
    config = result.scalar_one_or_none()

    secret = body.get("secret", "")
    active = int(body.get("active", 1))

    if config:
        if secret:
            config.secret = encrypt(secret)
        config.active = active
    else:
        config = TakealotWebhookConfig(
            store_binding_id=store_id,
            secret=encrypt(secret) if secret else "",
            active=active,
        )
        db.add(config)

    await db.flush()
    return {"ok": True, "message": "Webhook 配置已保存"}


# ---------------------------------------------------------------------------
# 3. Receive webhook — public endpoint, no auth, HMAC verification
# ---------------------------------------------------------------------------

@router.post("/receive/{store_id}")
async def receive_webhook(
    store_id: int, request: Request, db: DbSession, redis: RedisConn,
):
    """Receive a webhook delivery from Takealot.

    Verifies HMAC-SHA256 signature, logs delivery, and invalidates relevant caches.
    """
    # Read raw body for HMAC verification
    raw_body = await request.body()
    signature = request.headers.get("X-Takealot-Signature", "")
    delivery_id = request.headers.get("X-Takealot-Delivery-Id", "")
    event_type = request.headers.get("X-Takealot-Event", "")

    # Parse payload
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        payload = {}

    # Check for duplicate delivery
    if delivery_id:
        dup = await db.execute(
            select(TakealotWebhookDelivery).where(
                TakealotWebhookDelivery.delivery_id == delivery_id,
            )
        )
        if dup.scalar_one_or_none():
            return {"ok": True, "message": "已处理", "duplicate": True}

    # Load webhook config
    result = await db.execute(
        select(TakealotWebhookConfig).where(
            TakealotWebhookConfig.store_binding_id == store_id,
        )
    )
    config = result.scalar_one_or_none()

    verified = False

    if config and config.secret:
        # HMAC-SHA256 verification
        try:
            secret = decrypt(config.secret)
            expected = hmac.new(
                secret.encode(), raw_body, hashlib.sha256,
            ).hexdigest()
            verified = hmac.compare_digest(
                signature.lower().replace("sha256=", ""),
                expected,
            )
        except Exception as exc:
            logger.warning("HMAC verification failed for store %d: %s", store_id, exc)
            verified = False

        if not verified:
            delivery = TakealotWebhookDelivery(
                store_binding_id=store_id,
                delivery_id=delivery_id or None,
                event_type=event_type or None,
                signature=signature or None,
                request_url=str(request.url),
                payload_json=json.dumps(payload, ensure_ascii=False),
                verified=0,
                status="rejected",
                error="invalid_signature",
                received_at=datetime.utcnow(),
            )
            db.add(delivery)
            config.last_delivery_at = datetime.utcnow()
            config.last_event_type = event_type or ""
            config.last_delivery_id = delivery_id or ""
            config.last_delivery_status = "rejected"
            await db.flush()
            logger.warning(
                "Webhook signature mismatch for store %d, delivery %s",
                store_id, delivery_id,
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Log delivery
    delivery = TakealotWebhookDelivery(
        store_binding_id=store_id,
        delivery_id=delivery_id or None,
        event_type=event_type or None,
        signature=signature or None,
        request_url=str(request.url),
        payload_json=json.dumps(payload, ensure_ascii=False),
        verified=1 if verified else 0,
        status="received",
        received_at=datetime.utcnow(),
    )
    db.add(delivery)

    # Update config last_delivery fields
    if config:
        config.last_delivery_at = datetime.utcnow()
        config.last_event_type = event_type or ""
        config.last_delivery_id = delivery_id or ""
        config.last_delivery_status = "verified" if verified else "unverified"

    await db.flush()

    # --- Cache invalidation based on event type ---
    try:
        await _invalidate_caches(redis, store_id, event_type)
        delivery.status = "processed"
        delivery.processed_at = datetime.utcnow()
    except Exception as exc:
        logger.error("Cache invalidation failed for store %d: %s", store_id, exc)
        delivery.status = "error"
        delivery.error = str(exc)

    await db.flush()

    return {
        "ok": True,
        "delivery_id": delivery_id,
        "event_type": event_type,
        "verified": verified,
    }


# ---------------------------------------------------------------------------
# Cache invalidation helper
# ---------------------------------------------------------------------------

async def _invalidate_caches(redis, store_id: int, event_type: str) -> None:
    """Delete relevant Redis cache keys when a webhook event arrives."""
    # Pattern: snapshot:* keys for the store's user
    # We scan for keys matching known patterns and delete them
    patterns = []

    if event_type in ("offer.created", "offer.updated", "offer.deleted"):
        patterns.append(f"cache:offers:{store_id}:*")
        patterns.append(f"cache:products:{store_id}:*")
    elif event_type in ("sale.created", "order.created", "order.updated"):
        patterns.append(f"cache:sales:{store_id}:*")
        patterns.append(f"cache:orders:{store_id}:*")
    elif event_type in ("shipment.created", "shipment.updated"):
        patterns.append(f"cache:shipments:{store_id}:*")
    elif event_type in ("finance.statement"):
        patterns.append(f"cache:finance:{store_id}:*")

    # Always invalidate the generic store cache
    patterns.append(f"cache:store:{store_id}:*")

    for pattern in patterns:
        async for key in redis.scan_iter(match=pattern, count=100):
            await redis.delete(key)

    # Also invalidate dashboard snapshots — scan for user's snapshot keys
    # We need to find the user_id for this store, but since this is a webhook
    # endpoint (no user context), we delete all dashboard snapshots that
    # reference this store.
    async for key in redis.scan_iter(match="snapshot:dashboard:*", count=100):
        await redis.delete(key)
