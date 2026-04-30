from typing import Annotated, Any

from fastapi import Cookie, Depends, HTTPException, status

from src.platform.settings.base import settings

from .repo import auth_repository


def get_current_user(
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, Any]:
    user = auth_repository.get_session_user(session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或会话已过期",
        )
    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def require_roles(*allowed_roles: str):
    def dependency(current_user: CurrentUser) -> dict[str, Any]:
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user

    return dependency
