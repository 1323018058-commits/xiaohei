"""Chrome extension API Pydantic schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtensionListNowRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    store_id: int = Field(..., ge=1)
    plid: str = Field(..., min_length=1)
    page_url: str = ""
    title: str = ""
    image_url: str = ""
    barcode: str = ""
    brand_name: str = ""
    buybox_price_zar: float = 0
    page_price_zar: float = 0
    target_price_zar: float = 0
    offer_id: str = ""
    pricing_snapshot_json: str = ""
    pricing_snapshot: dict[str, Any] = Field(default_factory=dict)
    raw_json: Any = None


class ExtensionAuthorizeCodeResponse(BaseModel):
    ok: bool = True
    auth_code: str
    expires_at: str


class ExtensionRedeemCodeRequest(BaseModel):
    auth_code: str = Field(..., min_length=1)


class ExtensionRedeemCodeResponse(BaseModel):
    ok: bool = True
    token: str
    expires_at: str


class ExtensionListNowResponse(BaseModel):
    ok: bool = True
    action_id: int
    status: str
    message: str
    task_id: str = ""


class ExtensionListHistoryItem(BaseModel):
    id: int
    action_type: str
    plid: str
    title: str = ""
    image_url: str = ""
    buybox_price_zar: float = 0
    offer_id: str = ""
    status: str = ""
    error_code: str = ""
    error_msg: str = ""
    task_id: str = ""
    created_at: str | None = None


class ExtensionListHistoryResponse(BaseModel):
    ok: bool = True
    actions: list[ExtensionListHistoryItem]
