"""FastAPI dependency injection — database sessions, current user, permissions."""
from __future__ import annotations

from typing import Annotated

import jwt
import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, get_redis
from app.models.user import User
from app.services import auth_service

# Re-export for convenience
DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisConn = Annotated[aioredis.Redis, Depends(get_redis)]

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """Extract and validate JWT access token, return the authenticated user."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效")

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 类型错误")

    user_id = int(payload.get("sub", 0))
    user = await auth_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")

    return user


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """Require user to have an active license."""
    if not auth_service.is_user_active(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="License 未激活或已过期",
        )
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限")
    return user


# Type aliases for use as route dependencies
CurrentUser = Annotated[User, Depends(get_current_user)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]
AdminUser = Annotated[User, Depends(get_current_admin)]
