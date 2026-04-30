from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class FeatureFlagResponse(BaseModel):
    feature_key: str
    enabled: bool
    source: str


class AuthUser(BaseModel):
    user_id: str
    username: str
    role: str
    status: str
    subscription_status: str


class SessionInfoResponse(BaseModel):
    user: AuthUser
    roles: list[str]
    feature_flags: list[FeatureFlagResponse]
    subscription_status: str


class LoginResponse(BaseModel):
    success: bool = True
    session: SessionInfoResponse


class LogoutResponse(BaseModel):
    success: bool = True
