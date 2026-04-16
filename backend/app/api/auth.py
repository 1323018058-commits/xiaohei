"""Auth API router — register, login, logout, me, activate, refresh, send-code."""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ActiveUser, CurrentUser, DbSession, RedisConn
from app.schemas.auth import (
    ActivateRequest,
    ActivateResponse,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    SendCodeRequest,
    SendCodeResponse,
    TokenResponse,
    UserInfo,
)
from app.schemas.common import OkResponse
from app.services import auth_service, email_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(body: SendCodeRequest, db: DbSession, redis: RedisConn):
    """Send a verification code to the given email address."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    # Check if email is already registered
    existing = await auth_service.get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    result = await email_service.send_verification_code(redis, email)
    if not result["ok"]:
        raise HTTPException(status_code=429, detail=result["error"])

    return SendCodeResponse(ok=True, expire_minutes=result["expire_minutes"])


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest, db: DbSession, redis: RedisConn):
    email = body.email.strip().lower()

    # Validate email format
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    # Verify email code
    code_valid = await email_service.verify_code(redis, email, body.email_code.strip())
    if not code_valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    # Check username uniqueness
    existing = await auth_service.get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # Check email uniqueness
    existing_email = await auth_service.get_user_by_email(db, email)
    if existing_email:
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    user = await auth_service.create_user(db, body.username, body.password, email=email)
    access_token = auth_service.create_access_token(user.id, user.username, user.role)
    refresh_token = auth_service.create_refresh_token(user.id)
    await auth_service.store_refresh_token(redis, user.id, refresh_token)

    return RegisterResponse(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        activated=False,
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: DbSession, redis: RedisConn):
    user = await auth_service.get_user_by_username(db, body.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    loop = asyncio.get_event_loop()
    valid = await loop.run_in_executor(None, auth_service.verify_password, body.password, user.password_hash)
    if not valid:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    access_token = auth_service.create_access_token(user.id, user.username, user.role)
    refresh_token = auth_service.create_refresh_token(user.id)
    await auth_service.store_refresh_token(redis, user.id, refresh_token)

    activated = auth_service.is_user_active(user)
    activated_until = (
        user.activated_until.strftime("%Y-%m-%d %H:%M:%S")
        if user.activated_until
        else None
    )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        username=user.username,
        role=user.role,
        activated=activated,
        activated_until=activated_until,
    )


@router.post("/logout", response_model=OkResponse)
async def logout(user: CurrentUser, redis: RedisConn):
    await auth_service.revoke_all_user_tokens(redis, user.id)
    return OkResponse()


@router.get("/me", response_model=UserInfo)
async def me(user: CurrentUser):
    activated = auth_service.is_user_active(user)
    activated_until = (
        user.activated_until.strftime("%Y-%m-%d %H:%M:%S")
        if user.activated_until
        else None
    )
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        activated=activated,
        activated_until=activated_until,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: DbSession, redis: RedisConn):
    try:
        payload = auth_service.decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token 无效")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token 类型错误")

    user_id = int(payload.get("sub", 0))
    if not await auth_service.is_refresh_token_valid(redis, user_id, body.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh token 已失效")

    user = await auth_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    # Rotate: revoke old, issue new pair
    await auth_service.revoke_refresh_token(redis, user_id, body.refresh_token)
    new_access = auth_service.create_access_token(user.id, user.username, user.role)
    new_refresh = auth_service.create_refresh_token(user.id)
    await auth_service.store_refresh_token(redis, user.id, new_refresh)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/activate", response_model=ActivateResponse)
async def activate(body: ActivateRequest, user: CurrentUser, db: DbSession):
    result = await auth_service.activate_license(db, user.id, body.key.strip().upper())
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return ActivateResponse(ok=True, activated_until=result["activated_until"])
