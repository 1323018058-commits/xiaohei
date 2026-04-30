from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from src.platform.settings.base import settings

from .schemas import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PhoneVerificationCodeRequest,
    PhoneVerificationCodeResponse,
    RegisterRequest,
    SessionInfoResponse,
)
from .service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])
service = AuthService()


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response):
    session_token, result = await service.login(payload)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        max_age=settings.session_max_age_seconds,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return result


@router.post("/register/send-code", response_model=PhoneVerificationCodeResponse)
async def send_register_code(payload: PhoneVerificationCodeRequest):
    return await service.send_registration_code(payload)


@router.post("/register", response_model=LoginResponse)
async def register(payload: RegisterRequest, response: Response):
    session_token, result = await service.register(payload)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        max_age=settings.session_max_age_seconds,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return result


@router.post("/logout", response_model=LogoutResponse)
def logout(
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
):
    result = service.logout(session_token)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite="lax",
    )
    return result


@router.get("/me", response_model=SessionInfoResponse)
def me(
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
):
    return service.me(session_token)
