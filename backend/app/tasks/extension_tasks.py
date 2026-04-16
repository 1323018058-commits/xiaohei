"""Celery tasks for Chrome extension one-click listing actions."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from app.models.extension import ExtensionAction
from app.models.store import StoreBinding
from app.services.takealot_api import TakealotSellerAPI
from app.tasks.celery_app import celery_app
from app.utils.encryption import decrypt
from app.database import task_db_session

logger = logging.getLogger(__name__)

DEFAULT_LEADTIME_DAYS = 14
BARCODE_RE = re.compile(r"^\d{8,14}$")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _normalize_barcode(value: str | None) -> str:
    return re.sub(r"[\s-]+", "", str(value or "").strip())


def _is_valid_barcode(value: str | None) -> bool:
    return bool(BARCODE_RE.fullmatch(_normalize_barcode(value)))


def _derive_sku(action: ExtensionAction) -> str:
    plid = str(action.plid or "").strip()
    if plid:
        return plid
    return f"EXT-{action.id}"


def _derive_pricing(action: ExtensionAction) -> tuple[int, int]:
    target_price = float(action.target_price_zar or 0)
    page_price = float(action.page_price_zar or 0)
    selling_price = target_price if target_price > 0 else page_price
    rrp = max(page_price, target_price)
    return int(round(selling_price)), int(round(rrp))


def _extract_offer_id(payload) -> str:
    if not isinstance(payload, dict):
        return ""

    candidates = [
        payload.get("offer_id"),
        payload.get("id"),
    ]

    nested_offer = payload.get("offer")
    if isinstance(nested_offer, dict):
        candidates.extend([nested_offer.get("offer_id"), nested_offer.get("id")])

    for key in ("offers", "results", "items"):
        entries = payload.get(key)
        if isinstance(entries, list) and entries:
            first = entries[0]
            if isinstance(first, dict):
                candidates.extend([first.get("offer_id"), first.get("id")])

    for candidate in candidates:
        offer_id = str(candidate or "").strip()
        if offer_id:
            return offer_id
    return ""


async def _set_action_status(
    db,
    action: ExtensionAction,
    *,
    status: str,
    error_code: str = "",
    error_msg: str = "",
    offer_id: str | None = None,
    raw_json: str | None = None,
) -> None:
    action.action_status = status
    action.error_code = error_code
    action.error_msg = error_msg
    if offer_id is not None:
        action.offer_id = offer_id
    if raw_json is not None:
        action.raw_json = raw_json
    await db.commit()


async def _process_extension_list_now(action_id: int) -> dict:
    async with task_db_session() as db:
        action = await db.get(ExtensionAction, action_id)
        if not action:
            return {"ok": False, "error": "extension action not found"}

        existing_offer_id = str(action.offer_id or "").strip()
        if action.action_status == "submitted" or existing_offer_id:
            return {
                "ok": True,
                "action_id": action_id,
                "status": action.action_status or "submitted",
                "offer_id": existing_offer_id,
            }

        await _set_action_status(db, action, status="processing", error_code="", error_msg="")

        barcode = _normalize_barcode(action.barcode)
        if not _is_valid_barcode(barcode):
            await _set_action_status(
                db,
                action,
                status="failed",
                error_code="INVALID_BARCODE",
                error_msg="条码无效，必须是 8 到 14 位数字",
            )
            return {"ok": False, "action_id": action_id, "error": "invalid barcode"}

        store = await db.get(StoreBinding, action.store_id)
        if not store:
            await _set_action_status(
                db,
                action,
                status="failed",
                error_code="STORE_NOT_FOUND",
                error_msg="关联店铺不存在，无法创建 Takealot 商品",
            )
            return {"ok": False, "action_id": action_id, "error": "store not found"}

        if getattr(store, "is_active", 1) != 1:
            await _set_action_status(
                db,
                action,
                status="failed",
                error_code="STORE_INACTIVE",
                error_msg="关联店铺已停用，无法创建 Takealot 商品",
            )
            return {"ok": False, "action_id": action_id, "error": "store inactive"}

        try:
            api_key = decrypt(store.api_key)
            api_secret = decrypt(getattr(store, "api_secret", "") or "")
        except Exception as exc:  # pragma: no cover - defensive guard
            await _set_action_status(
                db,
                action,
                status="failed",
                error_code="STORE_CREDENTIALS_INVALID",
                error_msg=f"店铺凭证解密失败: {exc}",
            )
            return {"ok": False, "action_id": action_id, "error": "store credentials invalid"}

        selling_price, rrp = _derive_pricing(action)
        if selling_price <= 0:
            await _set_action_status(
                db,
                action,
                status="failed",
                error_code="INVALID_PRICE",
                error_msg="缺少有效的 target_price_zar / page_price_zar，无法创建报价",
            )
            return {"ok": False, "action_id": action_id, "error": "invalid price"}

        api = TakealotSellerAPI(api_key, api_secret)
        sku = _derive_sku(action)

        try:
            remote_response = await api.create_offer_by_barcode(
                barcode=barcode,
                sku=sku,
                selling_price=selling_price,
                rrp=rrp,
                leadtime_days=DEFAULT_LEADTIME_DAYS,
            )
        except Exception as exc:
            await _set_action_status(
                db,
                action,
                status="failed",
                error_code="OFFER_CREATE_FAILED",
                error_msg=f"创建 Takealot 商品失败: {exc}",
                raw_json=json.dumps({"error": str(exc)}, ensure_ascii=False),
            )
            return {"ok": False, "action_id": action_id, "error": "offer create failed"}

        raw_json = json.dumps(remote_response, ensure_ascii=False, default=str)
        offer_id = _extract_offer_id(remote_response)

        if not offer_id and any(remote_response.get(key) for key in ("errors", "validation_errors")):
            await _set_action_status(
                db,
                action,
                status="failed",
                error_code="OFFER_CREATE_REJECTED",
                error_msg="Takealot 返回校验错误，商品未创建",
                raw_json=raw_json,
            )
            return {"ok": False, "action_id": action_id, "error": "offer rejected"}

        await _set_action_status(
            db,
            action,
            status="submitted",
            error_code="",
            error_msg="",
            offer_id=offer_id or None,
            raw_json=raw_json,
        )
        return {
            "ok": True,
            "action_id": action_id,
            "status": "submitted",
            "offer_id": offer_id,
        }


@celery_app.task(name="app.tasks.extension_tasks.process_extension_list_now")
def process_extension_list_now(action_id: int):
    return _run_async(_process_extension_list_now(action_id))
