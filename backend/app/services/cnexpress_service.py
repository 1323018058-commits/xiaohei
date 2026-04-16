"""CN Express logistics service — async port of cnexpress_client.py."""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CNEXPRESS_API_BASE = "https://portal.cnexpressintl.com/api"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 3


class CnExpressClient:
    """Async CN Express International API client."""

    def __init__(self, token: str = "", token_header: str = "Token", base_url: str = CNEXPRESS_API_BASE):
        self.token = token
        self.token_header = token_header
        self.base_url = base_url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        auth_required: bool = True,
    ) -> dict:
        if auth_required and not self.token:
            raise RuntimeError("CN Express token missing")

        url = f"{self.base_url}{path}"
        headers = {}
        if self.token:
            headers[self.token_header] = self.token

        for attempt in range(1, DEFAULT_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.request(
                        method, url, params=params, json=json_body,
                        headers=headers, timeout=DEFAULT_TIMEOUT,
                    )
                    if resp.status_code >= 500 and attempt < DEFAULT_RETRIES:
                        import asyncio
                        await asyncio.sleep(0.8 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    return resp.json() if resp.content else {}
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                if attempt < DEFAULT_RETRIES:
                    import asyncio
                    await asyncio.sleep(0.8 * (attempt + 1))
                    continue
                raise RuntimeError(f"CN Express API error: {exc}") from exc
        return {}

    # -- Auth --
    async def login(self, payload: dict) -> dict:
        return await self._request("POST", "/admin/login", json_body=payload, auth_required=False)

    # -- Warehouses & Lines --
    async def list_warehouses(self) -> dict:
        return await self._request("GET", "/po/warehouseList")

    async def list_lines(self, params: dict | None = None) -> dict:
        return await self._request("GET", "/po/lineList", params=params)

    # -- Orders --
    async def list_orders(self, params: dict | None = None) -> dict:
        return await self._request("GET", "/v3/order/orderList", params=params)

    async def get_order_detail(self, params: dict) -> dict:
        return await self._request("GET", "/v3/order/detailInfo", params=params)

    async def create_order(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/order/createOrder", json_body=payload)

    async def create_fba_order(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/order/createFbaOrder", json_body=payload)

    async def cancel_order(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/order/cancelOrder", json_body=payload)

    async def import_order(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/order/importOrder", json_body=payload)

    async def import_fba_order(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/order/importFBAOrder", json_body=payload)

    # -- Labels --
    async def print_label(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/order/Label", json_body=payload)

    async def print_cn_label(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/order/cnLabel", json_body=payload)

    # -- Wallet --
    async def get_wallet_info(self) -> dict:
        return await self._request("POST", "/po/walletInfo", json_body={"msg": False})

    async def list_wallet_details(self, payload: dict) -> dict:
        payload.setdefault("msg", False)
        return await self._request("POST", "/po/walletDetailsList", json_body=payload)

    async def list_recharge_records(self, payload: dict) -> dict:
        return await self._request("POST", "/emx.recharge/list", json_body=payload)

    # -- Tracking --
    async def get_tracking(self, order_no: str) -> dict:
        return await self._request(
            "POST", "/Official_Website/getShipTrail",
            json_body={"order_no": order_no}, auth_required=False,
        )
