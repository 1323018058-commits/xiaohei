"""CN Express API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ActiveUser, DbSession
from app.services.cnexpress_service import CnExpressClient
from app.models.cnexpress import CnexpressAccount

from sqlalchemy import select

router = APIRouter(prefix="/api/cnexpress", tags=["cnexpress"])


def _mask_token(token: str) -> str:
    """Mask token for display: show first 4 and last 4 chars."""
    t = str(token or "")
    if len(t) <= 8:
        return "*" * len(t)
    return t[:4] + "*" * (len(t) - 8) + t[-4:]


def _account_to_dict(account, token_raw: str = "") -> dict:
    """Convert account model to safe dict (no raw secrets)."""
    return {
        "id": account.id,
        "account_username": account.account_username or "",
        "customer_id": account.customer_id or "",
        "login_name": account.login_name or "",
        "token_masked": _mask_token(token_raw),
        "token_present": bool(token_raw),
        "password_present": bool(account.account_password),
        "is_active": account.is_active,
        "created_at": str(account.created_at) if account.created_at else None,
        "updated_at": str(account.updated_at) if account.updated_at else None,
    }


async def _get_client(db, user_id: int) -> CnExpressClient:
    """Get CN Express client with user's saved token."""
    result = await db.execute(
        select(CnexpressAccount).where(CnexpressAccount.user_id == user_id)
    )
    account = result.scalar_one_or_none()
    if not account or not account.token:
        raise HTTPException(status_code=400, detail="未绑定 CN Express 账户，请先在「账号设置」中登录嘉鸿账号")

    from app.utils.encryption import decrypt
    token = decrypt(account.token)
    return CnExpressClient(token=token)


# ---------------------------------------------------------------------------
# Account binding
# ---------------------------------------------------------------------------

@router.get("/account")
async def get_account(user: ActiveUser, db: DbSession):
    """Get current user's CNExpress account info (masked)."""
    result = await db.execute(
        select(CnexpressAccount).where(CnexpressAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()
    if not account:
        return {"ok": True, "account": None, "bound": False}

    from app.utils.encryption import decrypt
    try:
        token_raw = decrypt(account.token) if account.token else ""
    except Exception:
        token_raw = ""

    return {"ok": True, "account": _account_to_dict(account, token_raw), "bound": bool(token_raw)}


@router.post("/account")
async def save_account(user: ActiveUser, db: DbSession, body: dict):
    """Save/update CNExpress account config (manual token mode)."""
    from app.utils.encryption import encrypt

    token = str(body.get("token") or "").strip()
    username = str(body.get("account_username") or "").strip()
    password = str(body.get("account_password") or "").strip()
    customer_id = str(body.get("customer_id") or "").strip()
    login_name = str(body.get("login_name") or "").strip()

    result = await db.execute(
        select(CnexpressAccount).where(CnexpressAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()

    if account:
        # Preserve existing values if not provided
        if not token:
            token = ""
            from app.utils.encryption import decrypt
            try:
                token = decrypt(account.token) if account.token else ""
            except Exception:
                pass
        if not username:
            username = account.account_username or ""
        if not password:
            password = ""
            from app.utils.encryption import decrypt as dec2
            try:
                password = dec2(account.account_password) if account.account_password else ""
            except Exception:
                pass

        account.token = encrypt(token) if token else ""
        account.account_username = username
        account.account_password = encrypt(password) if password else ""
        account.customer_id = customer_id or account.customer_id
        account.login_name = login_name or account.login_name
    else:
        account = CnexpressAccount(
            user_id=user.id,
            token=encrypt(token) if token else "",
            account_username=username,
            account_password=encrypt(password) if password else "",
            customer_id=customer_id,
            login_name=login_name,
        )
        db.add(account)

    await db.flush()
    await db.commit()
    return {"ok": True, "account": _account_to_dict(account, token)}


@router.post("/account/login")
async def login_account(user: ActiveUser, db: DbSession, body: dict):
    """Login to CNExpress with username/password, auto-save token."""
    from app.utils.encryption import encrypt

    username = str(body.get("account_username") or body.get("username") or "").strip()
    password = str(body.get("account_password") or body.get("password") or "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="账号和密码不能为空")

    client = CnExpressClient(token="")
    try:
        payload = await client.login({
            "username": username,
            "password": password,
            "client": "new_customer",
        })
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"嘉鸿登录失败: {exc}")

    if not payload or not payload.get("code"):
        msg = (payload or {}).get("msg") or "嘉鸿登录失败"
        raise HTTPException(status_code=400, detail=msg)

    data = payload.get("data") or {}
    userinfo = data.get("userinfo") or {}
    token = str(data.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="登录成功但未返回 token")

    customer_id = str(
        userinfo.get("relation_id") or userinfo.get("customer_id") or ""
    ).strip()
    login_name = str(
        userinfo.get("nickname") or userinfo.get("username") or ""
    ).strip()

    # Upsert account
    result = await db.execute(
        select(CnexpressAccount).where(CnexpressAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()

    if account:
        account.token = encrypt(token)
        account.account_username = username
        account.account_password = encrypt(password)
        account.customer_id = customer_id or account.customer_id
        account.login_name = login_name or account.login_name
    else:
        account = CnexpressAccount(
            user_id=user.id,
            token=encrypt(token),
            account_username=username,
            account_password=encrypt(password),
            customer_id=customer_id,
            login_name=login_name,
        )
        db.add(account)

    await db.flush()
    await db.commit()

    return {
        "ok": True,
        "account": _account_to_dict(account, token),
        "userinfo": userinfo,
    }


@router.get("/warehouses")
async def list_warehouses(user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.list_warehouses()
    return {"ok": True, "data": data}


@router.get("/lines")
async def list_lines(user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.list_lines()
    return {"ok": True, "data": data}


@router.get("/orders")
async def list_orders(
    user: ActiveUser, db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    client = await _get_client(db, user.id)
    data = await client.list_orders(params={"page": page, "pageSize": page_size})
    return {"ok": True, "data": data}


@router.get("/orders/{order_no}")
async def order_detail(order_no: str, user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.get_order_detail(params={"order_no": order_no})
    return {"ok": True, "data": data}


@router.post("/orders")
async def create_order(body: dict, user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.create_order(body)
    return {"ok": True, "data": data}


@router.post("/orders/cancel")
async def cancel_order(body: dict, user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.cancel_order(body)
    return {"ok": True, "data": data}


@router.post("/labels")
async def print_label(body: dict, user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.print_label(body)
    return {"ok": True, "data": data}


@router.get("/wallet")
async def wallet_info(user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.get_wallet_info()
    return {"ok": True, "data": data}


@router.post("/wallet/details")
async def wallet_details(body: dict, user: ActiveUser, db: DbSession):
    client = await _get_client(db, user.id)
    data = await client.list_wallet_details(body)
    return {"ok": True, "data": data}


@router.get("/tracking/{order_no}")
async def tracking(order_no: str):
    client = CnExpressClient()  # No auth needed for tracking
    data = await client.get_tracking(order_no)
    return {"ok": True, "data": data}
