"""Chrome extension API router — auth, status, pricing, profit, actions."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select

from app.api.deps import ActiveUser, DbSession, RedisConn
from app.models.extension import ExtensionAction
from app.models.product import BidProduct
from app.schemas.extension import (
    ExtensionAuthorizeCodeResponse,
    ExtensionListHistoryResponse,
    ExtensionListNowRequest,
    ExtensionListNowResponse,
    ExtensionRedeemCodeRequest,
    ExtensionRedeemCodeResponse,
)
from app.services import extension_service

router = APIRouter(prefix="/api/extension", tags=["extension"])

_LIST_NOW_PENDING_STATUSES = ("queued", "dispatching", "processing", "running")
_PUBLIC_ERROR_MESSAGES = {
    "INVALID_BARCODE": "条码无效，请检查后重试。",
    "STORE_NOT_FOUND": "关联店铺不存在，请检查店铺配置。",
    "STORE_INACTIVE": "店铺已停用，暂时无法上架。",
    "STORE_CREDENTIALS_INVALID": "店铺凭证异常，请在 ERP 中检查后重试。",
    "INVALID_PRICE": "价格无效，请重新计算后再试。",
    "OFFER_CREATE_FAILED": "创建 Takealot 商品失败，请稍后重试。",
    "OFFER_CREATE_REJECTED": "Takealot 拒绝了本次上架，请检查商品信息后重试。",
}


# ---------------------------------------------------------------------------
# Dependency: authenticate via Bearer token (extension-specific, not JWT)
# ---------------------------------------------------------------------------

async def _get_extension_user(
    request: Request,
    db: DbSession,
):
    """Extract Bearer token from extension request and resolve the user."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing extension token")

    raw_token = auth_header[7:]
    token = await extension_service.verify_token(db, raw_token)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired extension token")

    from app.services import auth_service
    user = await auth_service.get_user_by_id(db, token.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _json_text(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _public_error_message(error_code: str | None, error_msg: str | None, status: str | None) -> str:
    code = str(error_code or "").strip()
    if code:
        return _PUBLIC_ERROR_MESSAGES.get(code, "操作失败，请在 ERP 中查看详情。")
    if str(status or "").strip().lower() == "failed" or str(error_msg or "").strip():
        return "操作失败，请在 ERP 中查看详情。"
    return ""


async def _find_inflight_list_now_action(
    db: DbSession,
    user_id: int,
    store_id: int,
    plid: str,
) -> ExtensionAction | None:
    result = await db.execute(
        select(ExtensionAction)
        .where(
            ExtensionAction.user_id == user_id,
            ExtensionAction.store_id == store_id,
            ExtensionAction.plid == plid,
            ExtensionAction.action_status.in_(_LIST_NOW_PENDING_STATUSES),
        )
        .order_by(ExtensionAction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _find_listed_bid_product(
    db: DbSession,
    store_id: int,
    plid: str,
    barcode: str,
) -> BidProduct | None:
    filters = [BidProduct.plid == plid]
    if barcode:
        filters.append(BidProduct.barcode == barcode)

    result = await db.execute(
        select(BidProduct)
        .where(
            BidProduct.store_binding_id == store_id,
            or_(*filters),
        )
        .order_by(BidProduct.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _enqueue_extension_list_now(action_id: int):
    from app.tasks.extension_tasks import process_extension_list_now

    return process_extension_list_now.delay(action_id)


# ---------------------------------------------------------------------------
# 1. Authorize page — user visits from browser to issue extension token
# ---------------------------------------------------------------------------

@router.get("/authorize", response_class=HTMLResponse)
async def authorize_page():
    """Legacy auth page is intentionally disabled to avoid bearer token exposure."""
    raise HTTPException(status_code=410, detail="该授权方式已下线，请使用 /extension/authorize 页面完成扩展授权")


@router.post("/authorize-api", response_model=ExtensionAuthorizeCodeResponse)
async def authorize_api(user: ActiveUser, redis: RedisConn):
    """SPA authorization bootstrap — returns a short-lived auth code only."""
    auth_code, expires_at = await extension_service.issue_authorization_code(redis, user.id)
    return {"ok": True, "auth_code": auth_code, "expires_at": expires_at}


@router.post("/redeem-code", response_model=ExtensionRedeemCodeResponse)
async def redeem_code(
    body: ExtensionRedeemCodeRequest,
    db: DbSession,
    redis: RedisConn,
):
    payload = await extension_service.redeem_authorization_code(db, redis, body.auth_code)
    if not payload:
        raise HTTPException(status_code=401, detail="授权码无效或已过期")
    return {
        "ok": True,
        "token": payload["token"],
        "expires_at": payload["expires_at"],
    }


# ---------------------------------------------------------------------------
# 2. Status — extension popup shows store list + basic info
# ---------------------------------------------------------------------------

@router.get("/status")
async def extension_status(
    db: DbSession,
    user=Depends(_get_extension_user),
):
    """Return stores list and basic stats for extension popup."""
    payload = await extension_service.build_status(db, user.id)
    return {"ok": True, **payload}


# ---------------------------------------------------------------------------
# 3. Pricing config — extension needs commission/fx/freight rates
# ---------------------------------------------------------------------------

@router.get("/pricing-config")
async def pricing_config(
    db: DbSession,
    store_id: int = Query(...),
    user=Depends(_get_extension_user),
):
    config = await extension_service.get_pricing_config(db, store_id, user.id)
    if not config:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return {"ok": True, "config": config}


# ---------------------------------------------------------------------------
# 4. Calculate profit — inline profit display in extension
# ---------------------------------------------------------------------------

@router.post("/calculate-profit")
async def calculate_profit(
    body: dict,
    db: DbSession,
    user=Depends(_get_extension_user),
):
    from app.config import get_settings
    settings = get_settings()

    result = extension_service.calculate_profit_for_extension(
        selling_price_zar=float(body.get("selling_price_zar", 0)),
        purchase_price_cny=float(body.get("purchase_price_cny", 0)),
        weight_kg=float(body.get("weight_kg", settings.default_weight_kg)),
        length_cm=float(body.get("length_cm", 0)),
        width_cm=float(body.get("width_cm", 0)),
        height_cm=float(body.get("height_cm", 0)),
        air_freight_cny_per_kg=float(body.get("air_freight_cny_per_kg", settings.freight_rate_cny_per_kg)),
        operation_fee_cny=float(body.get("operation_fee_cny", 0)),
        commission_rate=float(body.get("commission_rate", settings.commission_rate)),
        vat_rate=float(body.get("vat_rate", settings.vat_rate)),
        fx_rate=float(body.get("fx_rate", settings.fx_zar_to_cny)),
    )
    return result


# ---------------------------------------------------------------------------
# 5. List-now — trigger immediate listing from extension
# ---------------------------------------------------------------------------

@router.post("/list-now", response_model=ExtensionListNowResponse)
async def list_now(
    body: ExtensionListNowRequest,
    db: DbSession,
    user=Depends(_get_extension_user),
):
    """Record a list-now action from extension and enqueue listing task."""
    store_id = int(body.store_id)
    plid = body.plid.strip()
    barcode = body.barcode.strip()
    if not plid:
        raise HTTPException(status_code=400, detail="store_id and plid are required")

    status = await extension_service.build_status(db, user.id)
    store_ids = [s["id"] for s in status.get("stores", [])]
    if store_id not in store_ids:
        raise HTTPException(status_code=403, detail="无权操作此店铺")

    inflight_action = await _find_inflight_list_now_action(db, user.id, store_id, plid)
    if inflight_action:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "ALREADY_PENDING",
                "message": "同一商品的一键上架请求已在队列中",
            },
        )

    listed_product = await _find_listed_bid_product(db, store_id, plid, barcode)
    if listed_product:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "ALREADY_LISTED",
                "message": "该商品已在本店铺商品中存在",
            },
        )

    action = await extension_service.log_action(
        db,
        user_id=user.id,
        store_id=store_id,
        action_type="list_now",
        plid=plid,
        page_url=body.page_url,
        title=body.title,
        image_url=body.image_url,
        barcode=barcode,
        brand_name=body.brand_name,
        buybox_price_zar=body.buybox_price_zar,
        page_price_zar=body.page_price_zar,
        target_price_zar=body.target_price_zar,
        offer_id=body.offer_id,
        pricing_snapshot_json=body.pricing_snapshot_json
        or json.dumps(body.pricing_snapshot, ensure_ascii=False),
        raw_json=_json_text(body.raw_json)
        or json.dumps(body.model_dump(exclude={"raw_json"}, exclude_none=True), ensure_ascii=False),
    )

    action.action_status = "queued"
    action.error_code = ""
    action.error_msg = ""
    await db.commit()

    task = _enqueue_extension_list_now(action.id)
    task_id = str(getattr(task, "id", "") or "")
    if task_id:
        action.task_id = task_id
        await db.commit()

    return ExtensionListNowResponse(
        ok=True,
        action_id=action.id,
        status=action.action_status,
        message="一键上架请求已进入队列",
        task_id=task_id,
    )


# ---------------------------------------------------------------------------
# 6. List history — extension shows recent actions
# ---------------------------------------------------------------------------

@router.get("/list-history", response_model=ExtensionListHistoryResponse)
async def list_history(
    db: DbSession,
    limit: int = Query(50, ge=1, le=200),
    user=Depends(_get_extension_user),
):
    actions = await extension_service.list_actions(db, user.id, limit)

    items = []
    for a in actions:
        items.append({
            "id": a.id,
            "action_type": a.action_type,
            "plid": a.plid or "",
            "title": a.title or "",
            "image_url": a.image_url or "",
            "buybox_price_zar": a.buybox_price_zar or 0,
            "offer_id": a.offer_id or "",
            "status": a.action_status or "",
            "error_code": a.error_code or "",
            "error_msg": _public_error_message(a.error_code, a.error_msg, a.action_status),
            "task_id": a.task_id or "",
            "created_at": str(a.created_at) if a.created_at else None,
        })

    return {"ok": True, "actions": items}
