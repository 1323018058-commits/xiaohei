"""Auth-related Pydantic schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=6, max_length=128)
    email: str = Field(..., min_length=5, max_length=200)
    email_code: str = Field(..., min_length=4, max_length=10)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    ok: bool = True
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    username: str
    role: str
    activated: bool
    activated_until: str | None = None


class RegisterResponse(BaseModel):
    ok: bool = True
    user_id: int
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    activated: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ActivateRequest(BaseModel):
    key: str = Field(..., min_length=1)


class ActivateResponse(BaseModel):
    ok: bool
    activated_until: str | None = None
    error: str | None = None


class UserInfo(BaseModel):
    id: int
    username: str
    email: str | None = None
    role: str
    activated: bool
    activated_until: str | None = None


class SendCodeRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)


class SendCodeResponse(BaseModel):
    ok: bool
    expire_minutes: int | None = None
    error: str | None = None
