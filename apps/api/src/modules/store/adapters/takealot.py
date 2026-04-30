from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from src.platform.settings.base import settings

from .base import (
    AdapterError,
    AdapterAuthError,
    AdapterCredentials,
    AdapterTemporaryError,
    BaseAdapter,
    ListingSnapshot,
    OrderItemSnapshot,
    OrderSnapshot,
)


class TakealotAdapter(BaseAdapter):
    SELLER_STOCK_CHUNK_SIZE = 100

    def __init__(
        self,
        credentials: AdapterCredentials,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        page_limit: int = 1000,
        max_pages: int = 100,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(credentials)
        self.base_url = (base_url or settings.takealot_api_base_url).rstrip("/")
        self.timeout = timeout or settings.platform_api_timeout_seconds
        self.page_limit = max(1, min(page_limit, 1000))
        self.max_pages = max(1, max_pages)
        self.transport = transport

    def validate_credentials(self) -> dict[str, Any]:
        return self.get_seller_profile()

    def get_seller_profile(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            "/seller",
            params=[
                ("fields", "seller_id"),
                ("fields", "display_name"),
                ("fields", "seller_status_id"),
                ("fields", "date_added"),
                ("fields", "leadtime_enabled"),
                ("fields", "account_verified"),
                ("fields", "disable_listing_enabled"),
                ("fields", "registration_complete"),
                ("fields", "on_vacation"),
                ("expands", "warehouses"),
                ("expands", "leadtime_details"),
            ],
            headers=self._headers(),
        )
        return _offer_payload_from_response(response)

    def get_primary_seller_warehouse_id(self) -> int | None:
        return self._get_primary_seller_warehouse_id()

    def get_offer_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        return self._get_offer_by_barcode(barcode)

    def get_offer(self, offer_id: str) -> dict[str, Any] | None:
        return self._get_offer(offer_id)

    def get_offer_batch_status(self, batch_id: int) -> dict[str, Any]:
        return self._get_offer_batch_status(batch_id)

    def fetch_listings(
        self,
        heartbeat=None,
        *,
        include_stock_details: bool = True,
    ) -> list[ListingSnapshot]:
        snapshots: list[ListingSnapshot] = []
        continuation_token: str | None = None
        for page_number in range(1, self.max_pages + 1):
            params: list[tuple[str, Any]] = [
                ("limit", self.page_limit),
                ("fields", "offer_id"),
                ("fields", "sku"),
                ("fields", "tsin_id"),
                ("fields", "productline_id"),
                ("fields", "selling_price"),
                ("fields", "status"),
                ("fields", "title"),
                ("fields", "product_label"),
                ("fields", "rrp"),
                ("fields", "barcode"),
                ("fields", "image_url"),
                ("fields", "conversion_percentage_30_days"),
                ("fields", "conversion_percentage_previous_30_days"),
                ("fields", "page_views_30_days"),
                ("fields", "quantity_returned_30_days"),
                ("fields", "benchmark_price"),
                ("fields", "total_wishlist"),
                ("fields", "wishlist_30_days"),
                ("fields", "listing_quality"),
                ("fields", "width_cm"),
                ("fields", "length_cm"),
                ("fields", "height_cm"),
                ("fields", "weight_grams"),
                ("expands", "takealot_warehouse_stock"),
            ]
            if continuation_token:
                params.append(("continuation_token", continuation_token))

            response = self._request(
                "GET",
                "/offers",
                params=params,
                headers=self._headers(),
            )

            data = response.json()
            items = self._extract_items(data)
            if include_stock_details:
                self._hydrate_seller_warehouse_stock(items)
                self._hydrate_leadtime_stock(items)
            snapshots.extend(self._to_snapshot(item) for item in items)
            if heartbeat is not None:
                heartbeat(
                    {
                        "page_number": page_number,
                        "page_item_count": len(items),
                        "listing_count": len(snapshots),
                    }
                )
            continuation_token = str(data.get("continuation_token") or "") if isinstance(data, dict) else ""
            if not continuation_token:
                break
        return snapshots

    def fetch_orders(
        self,
        heartbeat=None,
        *,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> list[OrderSnapshot]:
        sales: list[dict[str, Any]] = []
        continuation_token: str | None = None
        order_date_start = _date_filter_value(start_date)
        order_date_end = _date_filter_value(end_date)
        effective_limit = min(self.page_limit, 100)
        for page_number in range(1, self.max_pages + 1):
            params: list[tuple[str, Any]] = [
                ("limit", effective_limit),
                ("fields", "order_item_id"),
                ("fields", "order_id"),
                ("fields", "order_date"),
                ("fields", "sale_status"),
                ("fields", "offer_id"),
                ("fields", "sku"),
                ("fields", "selling_price"),
                ("fields", "quantity"),
                ("fields", "total_fees"),
                ("fields", "sales_region"),
                ("fields", "stock_source_region"),
            ]
            if order_date_start:
                params.append(("order_date__gte", order_date_start))
            if order_date_end:
                params.append(("order_date__lte", order_date_end))
            if continuation_token:
                params.append(("continuation_token", continuation_token))

            response = self._request(
                "GET",
                "/sales",
                params=params,
                headers=self._headers(),
            )
            data = response.json()
            items = self._extract_items(data)
            sales.extend(items)
            if heartbeat is not None:
                heartbeat(
                    {
                        "page_number": page_number,
                        "page_item_count": len(items),
                        "sale_count": len(sales),
                        "order_date_start": order_date_start,
                        "order_date_end": order_date_end,
                    }
                )
            continuation_token = str(data.get("continuation_token") or "") if isinstance(data, dict) else ""
            if not continuation_token or len(items) < effective_limit:
                break
        return self._sales_to_orders(sales)

    def create_or_update_offer(
        self,
        *,
        barcode: str,
        sku: str,
        selling_price: float,
        rrp: float | None = None,
        quantity: int | None,
        minimum_leadtime_days: int,
        leadtime_merchant_warehouse_id: int | None = None,
    ) -> dict[str, Any]:
        existing = self._get_offer_by_barcode(barcode)
        seller_profile = self.get_seller_profile()
        warehouse_id = self._extract_primary_seller_warehouse_id(seller_profile)
        minimum_leadtime_days = self._normalize_minimum_leadtime_days(
            seller_profile,
            minimum_leadtime_days,
        )
        normalized_selling_price = max(0, int(round(float(selling_price))))
        body: dict[str, Any] = {
            "sku": sku,
            "selling_price": normalized_selling_price,
        }
        if rrp is not None:
            body["rrp"] = max(0, int(round(float(rrp))))
        if warehouse_id is not None:
            if quantity is not None:
                body["seller_warehouse_stock"] = [
                    {
                        "seller_warehouse_id": warehouse_id,
                        "quantity_available": max(1, int(quantity)),
                    }
                ]
        else:
            body["minimum_leadtime_days"] = max(1, int(minimum_leadtime_days))

        if warehouse_id is None:
            response = self._request(
                "POST",
                "/offers/batch",
                headers=self._headers(),
                json_body={
                    "offers": [
                        {
                            "barcode": barcode,
                            "sku": sku,
                            "selling_price": normalized_selling_price,
                            "leadtime_days": max(1, int(minimum_leadtime_days)),
                            **(
                                {
                                    "leadtime_stock": [
                                        {
                                            "merchant_warehouse_id": leadtime_merchant_warehouse_id or settings.takealot_leadtime_merchant_warehouse_id,
                                            "quantity": max(1, int(quantity)),
                                        }
                                    ],
                                    "status_action": "Re-enable",
                                }
                                if quantity is not None and (leadtime_merchant_warehouse_id or settings.takealot_leadtime_merchant_warehouse_id) is not None
                                else {}
                            ),
                        }
                    ]
                },
            )
            batch_payload = response.json()
            if not isinstance(batch_payload, dict):
                return {"raw": batch_payload}
            batch_id = batch_payload.get("batch_id")
            if batch_id:
                batch_status = self._get_offer_batch_status(int(batch_id))
                refreshed_offer = self._get_offer_by_barcode(barcode)
                if refreshed_offer is not None:
                    refreshed_offer["batch_id"] = batch_id
                    refreshed_offer["batch_status"] = batch_status.get("status")
                    refreshed_offer["batch_status_payload"] = batch_status
                    return refreshed_offer
                return {
                    **batch_payload,
                    "batch_status": batch_status.get("status"),
                    "batch_status_payload": batch_status,
                    "barcode": barcode,
                    "sku": sku,
                    "selling_price": normalized_selling_price,
                }
        elif existing is not None:
            response = self._request(
                "PATCH",
                _offer_update_path(
                    offer_id=str(existing.get("offer_id") or ""),
                    sku=sku,
                    barcode=barcode,
                ),
                headers=self._headers(),
                json_body=body,
            )
        else:
            response = self._request(
                "POST",
                "/offers",
                headers=self._headers(),
                json_body={"barcode": barcode, **body},
            )
        return _offer_payload_from_response(response)

    def update_offer_price(
        self,
        *,
        offer_id: str,
        selling_price: float,
        sku: str | None = None,
        barcode: str | None = None,
    ) -> dict[str, Any]:
        normalized_selling_price = max(0, int(round(float(selling_price))))
        path = _offer_update_path(offer_id=offer_id, sku=sku, barcode=barcode)
        response = self._request(
            "PATCH",
            path,
            headers=self._headers(),
            json_body={"selling_price": normalized_selling_price},
        )
        payload = response.json()
        return payload if isinstance(payload, dict) else {"raw": payload}

    def update_offer(
        self,
        *,
        offer_id: str,
        selling_price: float | None = None,
        seller_stock: int | None = None,
        seller_stock_enabled: bool | None = None,
        seller_warehouse_id: int | None = None,
        leadtime_merchant_warehouse_id: int | None = None,
        sku: str | None = None,
        barcode: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if selling_price is not None:
            body["selling_price"] = max(0, int(round(float(selling_price))))
        if seller_stock is not None or seller_stock_enabled is not None:
            warehouse_id = (
                seller_warehouse_id
                or leadtime_merchant_warehouse_id
                or settings.takealot_leadtime_merchant_warehouse_id
                or self._get_primary_seller_warehouse_id()
            )
            if warehouse_id is None:
                raise AdapterError("Seller warehouse unavailable for stock update")
            body["seller_warehouse_stock"] = [
                {
                    "seller_warehouse_id": int(warehouse_id),
                    "quantity_available": 0 if seller_stock is None else max(0, int(seller_stock)),
                }
            ]
        if not body:
            return {}

        path = _offer_update_path(offer_id=offer_id, sku=sku, barcode=barcode)
        response = self._request(
            "PATCH",
            path,
            headers=self._headers(),
            json_body=body,
        )
        return _offer_payload_from_response(response)

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.credentials.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Xiaohei-ERP/1.0",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = client.request(
                    method,
                    path,
                    params=params,
                    headers=headers,
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise AdapterTemporaryError(f"Takealot request failed: {exc}") from exc

        if allow_not_found and response.status_code == 404:
            return response
        if response.status_code in {401, 403}:
            content_type = response.headers.get("content-type", "").lower()
            cf_mitigated = response.headers.get("cf-mitigated", "").lower()
            response_preview = response.text[:400]
            if (
                cf_mitigated == "challenge"
                or "text/html" in content_type
                or "just a moment" in response_preview.lower()
                or "cloudflare" in response_preview.lower()
            ):
                raise AdapterTemporaryError(
                    f"Takealot temporary challenge: {response.status_code} {response_preview}"
                )
            raise AdapterAuthError(
                f"Takealot credential rejected: {response.status_code} {response_preview}"
            )
        if response.status_code >= 500 or response.status_code == 429:
            raise AdapterTemporaryError(
                f"Takealot temporary failure: {response.status_code} {response.text[:400]}"
            )
        if response.status_code >= 400:
            raise AdapterError(
                f"Takealot request failed: {response.status_code} {response.text[:400]}"
            )
        return response

    def _get_offer_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            f"/offers/by_barcode/{_path_segment(barcode)}",
            headers=self._headers(),
            allow_not_found=True,
        )
        if response.status_code == 404:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def _get_offer(self, offer_id: str) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            f"/offers/{_path_segment(offer_id)}",
            params=[
                ("fields", "offer_id"),
                ("fields", "sku"),
                ("fields", "tsin_id"),
                ("fields", "productline_id"),
                ("fields", "selling_price"),
                ("fields", "status"),
                ("fields", "title"),
                ("fields", "product_label"),
                ("fields", "barcode"),
            ],
            headers=self._headers(),
            allow_not_found=True,
        )
        if response.status_code == 404:
            return None
        return _offer_payload_from_response(response)

    def _get_offer_batch_status(self, batch_id: int) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/offers/batch/{batch_id}",
            headers=self._headers(),
        )
        payload = response.json()
        return payload if isinstance(payload, dict) else {"raw": payload}

    def _get_primary_seller_warehouse_id(self) -> int | None:
        payload = self.get_seller_profile()
        return self._extract_primary_seller_warehouse_id(payload)

    @staticmethod
    def _extract_primary_seller_warehouse_id(payload: dict[str, Any] | None) -> int | None:
        if not isinstance(payload, dict):
            return None
        warehouses = payload.get("warehouses")
        if not isinstance(warehouses, list) or not warehouses:
            return None
        first = warehouses[0]
        if not isinstance(first, dict):
            return None
        warehouse_id = first.get("seller_warehouse_id")
        try:
            return int(warehouse_id) if warehouse_id is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_minimum_leadtime_days(
        payload: dict[str, Any] | None,
        requested_days: int,
    ) -> int:
        normalized = max(1, int(requested_days))
        if not isinstance(payload, dict):
            return normalized
        details = payload.get("leadtime_details")
        if not isinstance(details, list) or not details:
            return normalized
        min_candidates: list[int] = []
        max_candidates: list[int] = []
        for item in details:
            if not isinstance(item, dict):
                continue
            try:
                if item.get("min_days") is not None:
                    min_candidates.append(int(item["min_days"]))
                if item.get("max_days") is not None:
                    max_candidates.append(int(item["max_days"]))
            except (TypeError, ValueError):
                continue
        if min_candidates:
            normalized = max(normalized, min(min_candidates))
        if max_candidates:
            normalized = min(normalized, max(max_candidates))
        return normalized

    @staticmethod
    def _extract_items(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        items = (
            data.get("offers")
            or data.get("listings")
            or data.get("sales")
            or data.get("items")
            or data.get("results")
            or []
        )
        return [item for item in items if isinstance(item, dict)]

    def _hydrate_seller_warehouse_stock(self, items: list[dict[str, Any]]) -> None:
        offer_ids = [
            item.get("offer_id")
            for item in items
            if item.get("offer_id") not in (None, "")
        ]
        for index in range(0, len(offer_ids), self.SELLER_STOCK_CHUNK_SIZE):
            chunk = offer_ids[index:index + self.SELLER_STOCK_CHUNK_SIZE]
            params: list[tuple[str, Any]] = [
                ("limit", len(chunk)),
                ("fields", "offer_id"),
                ("expands", "seller_warehouse_stock"),
                *[("offer_id__in", offer_id) for offer_id in chunk],
            ]
            try:
                response = self._request(
                    "GET",
                    "/offers",
                    params=params,
                    headers=self._headers(),
                )
            except AdapterError:
                continue
            seller_items = self._extract_items(response.json())
            seller_stock_by_offer_id = {
                str(item["offer_id"]): item.get("seller_warehouse_stock")
                for item in seller_items
                if item.get("offer_id") not in (None, "")
                and item.get("seller_warehouse_stock") is not None
            }
            for item in items:
                seller_stock = seller_stock_by_offer_id.get(str(item.get("offer_id")))
                if seller_stock is not None:
                    item["seller_warehouse_stock"] = seller_stock

    def _hydrate_leadtime_stock(self, items: list[dict[str, Any]]) -> None:
        offer_ids = [
            item.get("offer_id")
            for item in items
            if item.get("offer_id") not in (None, "")
        ]
        for index in range(0, len(offer_ids), self.SELLER_STOCK_CHUNK_SIZE):
            chunk = offer_ids[index:index + self.SELLER_STOCK_CHUNK_SIZE]
            params: list[tuple[str, Any]] = [
                ("limit", len(chunk)),
                ("fields", "offer_id"),
                ("fields", "leadtime_days"),
                ("expands", "leadtime_stock"),
                *[("offer_id__in", offer_id) for offer_id in chunk],
            ]
            try:
                response = self._request(
                    "GET",
                    "/offers",
                    params=params,
                    headers=self._headers(),
                )
            except AdapterError:
                continue
            leadtime_items = self._extract_items(response.json())
            leadtime_by_offer_id = {
                str(item["offer_id"]): item
                for item in leadtime_items
                if item.get("offer_id") not in (None, "")
            }
            for item in items:
                leadtime = leadtime_by_offer_id.get(str(item.get("offer_id")))
                if leadtime is None:
                    continue
                if "leadtime_days" in leadtime:
                    item["leadtime_days"] = leadtime.get("leadtime_days")
                if "leadtime_stock" in leadtime:
                    item["leadtime_stock"] = leadtime.get("leadtime_stock")

    @staticmethod
    def _to_snapshot(item: dict[str, Any]) -> ListingSnapshot:
        sku = str(item.get("merchant_sku") or item.get("sku") or item.get("seller_sku") or item.get("offer_id") or "")
        external_id = str(
            item.get("offer_id")
            or item.get("listing_id")
            or item.get("id")
            or item.get("tsin_id")
            or sku
        )
        title = str(
            item.get("title")
            or item.get("name")
            or _nested_text(item.get("tsin"), "title")
            or _nested_text(item.get("tsin"), "name")
            or item.get("product_label")
            or sku
        )
        price = _first_present(item, "selling_price", "price", "rrp")
        stock = _stock_quantity(item)
        return ListingSnapshot(
            external_listing_id=external_id or sku,
            sku=sku or external_id,
            title=title,
            platform_product_id=_string_or_none(
                item.get("productline_id")
                or item.get("productlineId")
                or item.get("product_line_id")
            ),
            platform_price=_to_float(price),
            stock_quantity=_to_int(stock),
            currency=str(item.get("currency") or "ZAR"),
            raw_payload=item,
        )

    @staticmethod
    def _sales_to_orders(sales: list[dict[str, Any]]) -> list[OrderSnapshot]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for sale in sales:
            external_order_id = str(sale.get("order_id") or "")
            if not external_order_id:
                continue
            grouped.setdefault(external_order_id, []).append(sale)

        snapshots: list[OrderSnapshot] = []
        for external_order_id, order_sales in grouped.items():
            first_sale = order_sales[0]
            items = [TakealotAdapter._sale_to_item(sale) for sale in order_sales]
            total_amount = sum(
                (item.unit_price or 0) * item.quantity
                for item in items
            )
            status = str(first_sale.get("sale_status") or "unknown")
            snapshots.append(
                OrderSnapshot(
                    external_order_id=external_order_id,
                    order_number=external_order_id,
                    status=status,
                    fulfillment_status=status,
                    total_amount=total_amount,
                    currency=str(first_sale.get("currency") or "ZAR"),
                    placed_at=_to_datetime(first_sale.get("order_date")),
                    raw_payload={
                        "source": "takealot_sales",
                        "sales": order_sales,
                    },
                    items=items,
                )
            )
        snapshots.sort(
            key=lambda item: item.placed_at.timestamp() if item.placed_at else 0,
            reverse=True,
        )
        return snapshots

    @staticmethod
    def _sale_to_item(sale: dict[str, Any]) -> OrderItemSnapshot:
        sku = str(sale.get("sku") or sale.get("offer_id") or sale.get("order_item_id") or "")
        quantity = _to_positive_int(sale.get("quantity")) or 1
        line_total = _to_float(sale.get("selling_price"))
        # Takealot /sales exposes selling_price as the line total, not unit price.
        unit_price = line_total / quantity if line_total is not None else None
        return OrderItemSnapshot(
            external_order_item_id=str(sale.get("order_item_id") or sku),
            sku=sku,
            title=str(sale.get("title") or sale.get("product_title") or sku) if sku else None,
            quantity=quantity,
            unit_price=unit_price,
            status=str(sale.get("sale_status") or "") or None,
            raw_payload=sale,
        )


def _offer_payload_from_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    if isinstance(payload, dict):
        offer = payload.get("offer")
        if isinstance(offer, dict):
            return offer
        return payload
    return {"raw": payload}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_filter_value(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _to_positive_int(value: Any) -> int | None:
    number = _to_int(value)
    if number is None:
        return None
    return max(1, number)


def _to_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _nested_text(value: Any, key: str) -> str | None:
    if isinstance(value, dict) and value.get(key) is not None:
        return str(value[key])
    return None


def _stock_quantity(item: dict[str, Any]) -> Any:
    direct_stock = _first_present(
        item,
        "total_takealot_stock",
        "stock_at_takealot_total",
        "takealot_stock_quantity",
    )
    if direct_stock is not None:
        return direct_stock

    total = 0
    found_stock = False
    values = item.get("takealot_warehouse_stock")
    if not isinstance(values, list):
        return None
    for value in values:
        if not isinstance(value, dict):
            continue
        quantity = _to_int(value.get("quantity_available"))
        if quantity is not None:
            total += quantity
            found_stock = True
    return total if found_stock else None


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _path_segment(value: Any) -> str:
    return quote(str(value).strip(), safe="")


def _is_offer_id(value: Any) -> bool:
    text = str(value or "").strip()
    return text.isdigit() and int(text) > 0


def _offer_update_path(
    *,
    offer_id: str,
    sku: str | None = None,
    barcode: str | None = None,
) -> str:
    if _is_offer_id(offer_id):
        return f"/offers/{_path_segment(offer_id)}"
    if sku and sku.strip():
        return f"/offers/by_sku/{_path_segment(sku)}"
    if barcode and barcode.strip():
        return f"/offers/by_barcode/{_path_segment(barcode)}"
    return f"/offers/{_path_segment(offer_id)}"
