from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import Cookie, Depends, Header, HTTPException, status

from src.modules.auth.repo import auth_repository
from src.platform.settings.base import settings
from src.modules.common.dev_state import app_state


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def get_extension_user(
    authorization: Annotated[str | None, Header()] = None,
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, Any]:
    bearer = _bearer_token(authorization)
    if bearer:
        token_hash = hashlib.sha256(bearer.encode("utf-8")).hexdigest()
        token_record = app_state.get_extension_auth_token(token_hash)
        if token_record is not None:
            user = app_state.get_user(token_record["user_id"])
            if user is not None:
                user["extension_store_id"] = token_record.get("store_id")
                app_state.touch_extension_auth_token(token_hash)
                return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired extension token",
        )

    user = auth_repository.get_session_user(session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或会话已过期",
        )
    return user


ExtensionUser = Annotated[dict[str, Any], Depends(get_extension_user)]
