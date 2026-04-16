"""Takealot Seller API client — async httpx port of store_api.py.

Two external APIs:
  - Seller API:      https://seller-api.takealot.com/v2   (Authorization: Key {api_key})
  - Marketplace API: https://marketplace-api.takealot.com/v1 (X-API-Key: {api_key})
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://seller-api.takealot.com/v2"
MARKETPLACE_API_BASE = "https://marketplace-api.takealot.com/v1"
RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
REQUEST_RETRIES = 4
BASE_RETRY_DELAY = 0.8

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://seller.takealot.com",
    "Referer": "https://seller.takealot.com/",
}


class TakealotSellerAPI:
    """Async wrapper around Takealot's Seller and Marketplace APIs."""

    def __init__(self, api_key: str, api_secret: str = "") -> None:
        self.api_key = api_key
        self.api_secret = api_secret

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict:
        url = f"{API_BASE}{path}"
        headers = {
            **_DEFAULT_HEADERS,
            "Authorization": f"Key {self.api_key}",
        }

        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.request(
                        method,
                        url,
                        params=params,
                        json=body if body else None,
                        headers=headers,
                        timeout=timeout,
                    )

                if resp.status_code in RETRY_STATUS_CODES and attempt < REQUEST_RETRIES:
                    delay = BASE_RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                    logger.warning("Takealot API %s %s → %s, retry %d after %.1fs", method, path, resp.status_code, attempt, delay)
                    await asyncio.sleep(delay)
                    continue

                resp.raise_for_status()
                if not resp.content:
                    return {}
                return resp.json()

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code in RETRY_STATUS_CODES and attempt < REQUEST_RETRIES:
                    delay = BASE_RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                    logger.warning("Takealot API %s %s error: %s, retry %d", method, path, exc, attempt)
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(f"Takealot API 请求失败 ({method} {path}): {exc}") from exc
            except httpx.RequestError as exc:
                if attempt < REQUEST_RETRIES:
                    delay = BASE_RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                    logger.warning("Takealot API %s %s error: %s, retry %d", method, path, exc, attempt)
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(f"Takealot API 请求失败 ({method} {path}): {exc}") from exc

        return {}

    async def _marketplace_request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict:
        url = f"{MARKETPLACE_API_BASE}{path}"
        headers = {
            **_DEFAULT_HEADERS,
            "X-API-Key": self.api_key,
        }

        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.request(
                        method, url, params=params, headers=headers, timeout=timeout,
                    )

                if resp.status_code in RETRY_STATUS_CODES and attempt < REQUEST_RETRIES:
                    delay = BASE_RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                    await asyncio.sleep(delay)
                    continue

                resp.raise_for_status()
                return resp.json() if resp.content else {}

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code in RETRY_STATUS_CODES and attempt < REQUEST_RETRIES:
                    delay = BASE_RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(f"Marketplace API 请求失败 ({method} {path}): {exc}") from exc
            except httpx.RequestError as exc:
                if attempt < REQUEST_RETRIES:
                    delay = BASE_RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(f"Marketplace API 请求失败 ({method} {path}): {exc}") from exc

        return {}

    # ------------------------------------------------------------------
    # Store info
    # ------------------------------------------------------------------

    async def get_store_info(self) -> dict:
        data = await self._request("GET", "/offers", params={"page_size": 1})
        offer_count = data.get("total_results", 0)
        return {"store_name": "Takealot Store", "offer_count": offer_count}

    # ------------------------------------------------------------------
    # Offers & Catalogue
    # ------------------------------------------------------------------

    async def get_offers(self, page: int = 1, page_size: int = 100) -> dict:
        return await self._request("GET", "/offers", params={"page_number": page, "page_size": page_size})

    async def get_marketplace_offer(self, offer_id: str) -> dict:
        return await self._marketplace_request("GET", f"/offers/{offer_id}")

    async def get_all_offers(self) -> list[dict]:
        page, all_offers = 1, []
        while True:
            data = await self.get_offers(page=page, page_size=100)
            items = data.get("offers", data.get("results", []))
            if not items:
                break
            all_offers.extend(items)
            total = data.get("total_results", 0)
            if len(all_offers) >= total:
                break
            page += 1
        return all_offers

    async def get_offer_buybox(self, offer_id: str) -> float | None:
        detail = await self.get_offer_detail(offer_id)
        if not detail:
            detail = await self.get_marketplace_offer(offer_id)
        return detail.get("selling_price") if detail else None

    async def get_offer_detail(self, offer_id: str) -> dict | None:
        requested_offer_id = str(offer_id).strip()
        data = await self._request("GET", "/offers", params={"offer_id": requested_offer_id, "page_size": 1})
        offers = data.get("offers", [])
        for offer in offers:
            if str(offer.get("offer_id", "")).strip() == requested_offer_id:
                return offer

        page = 1
        scanned = 0
        while True:
            page_data = await self.get_offers(page=page, page_size=100)
            page_offers = page_data.get("offers", page_data.get("results", []))
            if not page_offers:
                break
            for offer in page_offers:
                if str(offer.get("offer_id", "")).strip() == requested_offer_id:
                    return offer
            scanned += len(page_offers)
            total = int(page_data.get("total_results", scanned) or scanned)
            if scanned >= total:
                break
            page += 1
        return None

    async def get_offer_media_detail(self, offer_id: str) -> dict:
        errors: list[str] = []
        detail: dict | None = None
        marketplace: dict | None = None
        try:
            detail = await self.get_offer_detail(offer_id)
        except RuntimeError as exc:
            errors.append(str(exc))

        try:
            marketplace = await self.get_marketplace_offer(offer_id)
        except RuntimeError as exc:
            errors.append(str(exc))

        if detail and marketplace:
            merged = dict(marketplace)
            merged.update(detail)
            return merged
        if detail:
            return detail
        if marketplace:
            return marketplace

        if errors:
            return {"_fetch_error": "; ".join(errors), "offer_id": offer_id}

        return {}

    async def update_offer_price(self, offer_id: str, new_price: float) -> tuple[bool, Any]:
        return await self.update_offer_fields(
            offer_id,
            {"selling_price": int(new_price)},
        )

    async def update_offer_fields(self, offer_id: str, fields: dict[str, Any]) -> tuple[bool, Any]:
        payload = {key: value for key, value in fields.items() if value is not None}
        if not payload:
            return False, "没有可更新的字段"
        try:
            resp = await self._request(
                "PATCH",
                f"/offers/offer/ID{offer_id}",
                body=payload,
            )
            validation_errors = resp.get("validation_errors")
            if validation_errors:
                return False, validation_errors
            return True, resp
        except RuntimeError as exc:
            return False, str(exc)

    async def update_offer_leadtime_stock(
        self, offer_id: str, warehouse_id: int, quantity_available: int,
    ) -> tuple[bool, Any]:
        if warehouse_id <= 0:
            return False, "warehouse_id 无效"
        return await self.update_offer_fields(
            offer_id,
            {
                "leadtime_stock": [
                    {"merchant_warehouse_id": warehouse_id, "quantity": quantity_available},
                ],
            },
        )

    async def search_catalogue(
        self, query: str, search_by: str = "title", page_size: int = 50,
    ) -> list[dict]:
        data = await self._request(
            "GET", "/catalogue/mpv/search",
            params={"search": query, "search_by": search_by, "page_size": page_size},
        )
        return data.get("results", [])

    async def create_offer_batch(self, items: list[dict]) -> dict:
        return await self._request("POST", "/offers/batch", body={"items": items})

    async def create_offer_by_barcode(
        self,
        barcode: str,
        sku: str,
        selling_price: int,
        rrp: int,
        leadtime_days: int = 5,
    ) -> dict:
        item = {
            "barcode": barcode,
            "sku": sku,
            "selling_price": selling_price,
            "rrp": rrp,
            "leadtime_days": leadtime_days,
        }
        return await self.create_offer_batch([item])

    # ------------------------------------------------------------------
    # Loadsheet / Product submission
    # ------------------------------------------------------------------

    async def get_loadsheet_templates(self) -> list[dict]:
        data = await self._request("GET", "/loadsheets/templates")
        results: list[dict] = []
        for group in data.get("template_groups", []):
            group_name = group.get("group_name", "")
            for tpl in group.get("templates", []):
                results.append({
                    "template_id": tpl.get("template_id"),
                    "name": tpl.get("name"),
                    "description": tpl.get("description", ""),
                    "group": group_name,
                })
        return results

    async def get_template_schema(self, template_id: int) -> dict:
        return await self._request("GET", f"/loadsheets/templates/json/{template_id}")

    async def download_template_excel(self, template_id: int) -> bytes:
        url = f"{API_BASE}/loadsheets/templates/{template_id}"
        headers = {
            **_DEFAULT_HEADERS,
            "Authorization": f"Key {self.api_key}",
            "Accept": "application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=60.0)
            resp.raise_for_status()
            return resp.content

    async def submit_loadsheet(
        self, template_id: int, excel_bytes: bytes, submission_name: str,
    ) -> dict:
        url = f"{API_BASE}/loadsheets/submissions"
        headers = {
            **_DEFAULT_HEADERS,
            "Authorization": f"Key {self.api_key}",
        }
        files = {"loadsheet": (f"{submission_name}.xlsm", excel_bytes,
                              "application/vnd.ms-excel.sheet.macroEnabled.12")}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, files=files, timeout=120.0)
            resp.raise_for_status()
            return resp.json()

    async def get_submissions(self, page: int = 1, page_size: int = 50) -> dict:
        return await self._request("GET", "/loadsheets/submissions", params={"page_number": page, "page_size": page_size})

    async def get_submission_status(self, submission_id: int) -> dict | None:
        try:
            return await self._request("GET", f"/loadsheets/submissions/{submission_id}")
        except RuntimeError:
            data = await self.get_submissions(page=1, page_size=100)
            for sub in data.get("submissions", []):
                if sub.get("submission_id") == submission_id:
                    return sub
            return None

    # ------------------------------------------------------------------
    # Sales & Finance
    # ------------------------------------------------------------------

    async def get_sales(
        self, page: int = 1, page_size: int = 100,
        start_date: str = "", end_date: str = "",
    ) -> dict:
        params: dict[str, Any] = {"page_number": page, "page_size": page_size}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return await self._request("GET", "/sales", params=params)

    async def get_all_sales(self, start_date: str = "", end_date: str = "") -> list[dict]:
        page, all_items = 1, []
        while True:
            data = await self.get_sales(page=page, page_size=100, start_date=start_date, end_date=end_date)
            items = data.get("sales", data.get("orders", []))
            if not items:
                break
            all_items.extend(items)
            total = data.get("total_results", len(all_items))
            if len(all_items) >= total:
                break
            page += 1
        return all_items

    async def get_sales_orders(
        self,
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        page_size: int = 100,
        **filters: Any,
    ) -> dict:
        params: dict[str, Any] = {"page_number": page, "page_size": page_size}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        for k in ("sku", "product_title", "tsin", "order_id"):
            if k in filters and filters[k]:
                params[k] = filters[k]
        return await self._request("GET", "/sales", params=params)

    async def get_financial_statements(self, page: int = 1, page_size: int = 50) -> dict:
        return await self._request("GET", "/financial/statements", params={"page_number": page, "page_size": page_size})

    async def get_seller_balance(self) -> dict:
        return await self._request("GET", "/seller/balance")

    async def get_seller_balances(self) -> dict:
        return await self._request("GET", "/seller/balances")

    async def get_seller_transactions(
        self,
        date_from: str = "",
        date_to: str = "",
        page: int = 1,
        page_size: int = 100,
        transaction_type_ids: str = "",
    ) -> dict:
        params: dict[str, Any] = {"page_number": page, "page_size": page_size}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if transaction_type_ids:
            params["transaction_type_ids"] = transaction_type_ids
        return await self._request("GET", "/seller/transactions", params=params)

    # ------------------------------------------------------------------
    # Warehouse & Shipments
    # ------------------------------------------------------------------

    async def get_merchant_warehouses(self, validated: bool = True) -> dict:
        params: dict[str, Any] = {}
        if validated:
            params["validated"] = "true"
        return await self._request("GET", "/merchant_warehouses", params=params)

    async def get_shipment_facilities(self) -> dict:
        return await self._request("GET", "/shipment/facilities")

    async def get_shipments(
        self,
        shipment_state: str = "",
        page: int = 1,
        page_size: int = 50,
        **filters: Any,
    ) -> dict:
        params: dict[str, Any] = {"page_number": page, "page_size": page_size}
        if shipment_state:
            params["shipment_state"] = shipment_state
        return await self._request("GET", "/shipments", params=params)

    async def get_shipment_details(self, shipment_id: str, get_po_data: bool = False) -> dict:
        params: dict[str, Any] = {}
        if get_po_data:
            params["get_po_data"] = "true"
        return await self._request("GET", f"/shipment/{shipment_id}/details", params=params)

    async def get_shipment_items(
        self,
        shipment_id: str,
        page: int = 1,
        page_size: int = 100,
        get_po_data: bool = False,
    ) -> dict:
        params: dict[str, Any] = {"page_number": page, "page_size": page_size}
        if get_po_data:
            params["get_po_data"] = "true"
        return await self._request("GET", f"/shipment/{shipment_id}/shipment_items", params=params)

    async def get_leadtime_order_items(
        self, page: int = 1, page_size: int = 100, **filters: Any,
    ) -> dict:
        params: dict[str, Any] = {"page_number": page, "page_size": page_size}
        return await self._request("GET", "/shipment/leadtime_order_items/unattended", params=params)

    async def preview_leadtime_order_items(self, leadtime_order_item_ids: list[int]) -> dict:
        return await self._request(
            "POST",
            "/shipment/leadtime_order_items/add/preview",
            body={"leadtime_order_item_id_list": leadtime_order_item_ids},
        )

    async def create_shipments_review(self, shipment_items: list[dict]) -> dict:
        return await self._request(
            "POST", "/shipment/shipments_review",
            body={"shipment_items": shipment_items},
        )

    async def create_shipment_task_request(
        self, shipment_id: str, task_type_id: int, request_params: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {"task_type_id": task_type_id}
        if request_params:
            body["request_params"] = request_params
        return await self._request("POST", f"/shipment/{shipment_id}/task/request", body=body)

    async def get_shipment_confirm_preview(self, shipment_id: str) -> dict:
        return await self._request("GET", f"/shipment/{shipment_id}/confirm/preview")

    async def get_shipment_task_status(self, task_id: str) -> dict:
        return await self._request("GET", f"/shipment/task/{task_id}/status")

    async def get_shipment_task_result(self, task_id: str) -> dict:
        return await self._request("GET", f"/shipment/task/{task_id}/result")

    async def mark_shipment_shipped(self, shipment_id: str, shipped: bool = True) -> dict:
        return await self._request(
            "PUT", f"/shipment/{shipment_id}/shipped",
            body={"status": "shipped" if shipped else "unshipped"},
        )

    async def update_shipment_reference(self, shipment_id: str, reference: str) -> dict:
        return await self._request(
            "PUT", f"/shipment/{shipment_id}/reference",
            body={"seller_reference": reference},
        )

    async def update_shipment_tracking_info(self, shipment_id: str, tracking_info: dict) -> dict:
        return await self._request(
            "PUT", f"/shipment/{shipment_id}/tracking_info",
            body=tracking_info,
        )
