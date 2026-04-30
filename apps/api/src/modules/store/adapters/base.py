from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable


class AdapterError(Exception):
    """Base platform adapter error."""


class AdapterAuthError(AdapterError):
    """Platform rejected the stored credentials."""


class AdapterTemporaryError(AdapterError):
    """Platform is temporarily unavailable or rate limited."""


@dataclass(frozen=True)
class AdapterCredentials:
    platform: str
    api_key: str
    api_secret: str


@dataclass(frozen=True)
class ListingSnapshot:
    external_listing_id: str
    sku: str
    title: str
    platform_product_id: str | None = None
    platform_price: float | None = None
    stock_quantity: int | None = None
    currency: str = "USD"
    sync_status: str = "synced"
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderItemSnapshot:
    external_order_item_id: str
    sku: str
    title: str | None = None
    quantity: int = 1
    unit_price: float | None = None
    status: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderSnapshot:
    external_order_id: str
    order_number: str | None
    status: str
    fulfillment_status: str | None = None
    total_amount: float | None = None
    currency: str = "ZAR"
    placed_at: Any | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    items: list[OrderItemSnapshot] = field(default_factory=list)


class BaseAdapter(ABC):
    def __init__(self, credentials: AdapterCredentials) -> None:
        self.credentials = credentials

    def validate_credentials(self) -> dict[str, Any]:
        return {"status": "valid"}

    @abstractmethod
    def fetch_listings(
        self,
        heartbeat: Callable[[dict[str, Any] | None], None] | None = None,
        *,
        include_stock_details: bool = True,
    ) -> list[ListingSnapshot]:
        raise NotImplementedError

    def fetch_orders(
        self,
        heartbeat: Callable[[dict[str, Any] | None], None] | None = None,
        *,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> list[OrderSnapshot]:
        raise NotImplementedError

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
        raise NotImplementedError

    def update_offer_price(
        self,
        *,
        offer_id: str,
        selling_price: float,
        sku: str | None = None,
        barcode: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

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
        if selling_price is None and seller_stock is None and seller_stock_enabled is None:
            return {}
        if seller_stock is not None or seller_stock_enabled is not None:
            raise NotImplementedError
        if selling_price is None:
            return {}
        return self.update_offer_price(
            offer_id=offer_id,
            selling_price=selling_price,
            sku=sku,
            barcode=barcode,
        )

    def get_seller_profile(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_primary_seller_warehouse_id(self) -> int | None:
        raise NotImplementedError

    def get_offer_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def get_offer_batch_status(self, batch_id: int) -> dict[str, Any]:
        raise NotImplementedError
