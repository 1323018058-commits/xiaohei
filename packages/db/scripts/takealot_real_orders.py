from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
from src.modules.orders.service import OrderService  # noqa: E402
from src.modules.store.adapters.base import AdapterCredentials, BaseAdapter  # noqa: E402
from src.modules.store.adapters.takealot import TakealotAdapter  # noqa: E402
from src.modules.store.service import StoreService  # noqa: E402


DEFAULT_STORE_NAME = "Takealot Pilot Store"
DEFAULT_SYNC_MAX_PAGES = 1
DEFAULT_SYNC_PAGE_LIMIT = 10


def _credential_from_env() -> tuple[str, str]:
    api_key = os.environ.get("XH_TAKEALOT_API_KEY", "").strip()
    api_secret = os.environ.get("XH_TAKEALOT_API_SECRET", "").strip()
    if not api_secret:
        api_secret = "takealot-api-secret-placeholder"
    if not api_key:
        raise SystemExit(
            "Missing XH_TAKEALOT_API_KEY. Set it in .env or the shell environment; "
            "the script never prints the key."
        )
    return api_key, api_secret


def _actor() -> dict[str, str]:
    return {
        "id": ADMIN_USER_ID,
        "role": "super_admin",
        "tenant_id": DEMO_TENANT_ID,
    }


def _request_headers(label: str) -> dict[str, str]:
    return {"x-request-id": f"takealot-real-orders-{label}"}


def _find_store_id(name: str) -> str | None:
    for store in app_state.list_stores():
        if store["name"] == name:
            return store["id"]
    return None


def _order_adapter_factory(
    store: dict[str, object],
    credentials: AdapterCredentials,
) -> BaseAdapter:
    del store
    max_pages = int(os.environ.get("XH_TAKEALOT_ORDER_MAX_PAGES", DEFAULT_SYNC_MAX_PAGES))
    page_limit = int(os.environ.get("XH_TAKEALOT_ORDER_PAGE_LIMIT", DEFAULT_SYNC_PAGE_LIMIT))
    return TakealotAdapter(
        credentials,
        max_pages=max_pages,
        page_limit=page_limit,
    )


def _prepare_store(
    store_service: StoreService,
    *,
    store_name: str,
    api_key: str,
    api_secret: str,
) -> str:
    store_id = _find_store_id(store_name)
    if store_id is None:
        detail = store_service.create_store(
            {
                "name": store_name,
                "platform": "takealot",
                "api_key": api_key,
                "api_secret": api_secret,
                "status": "active",
            },
            _actor(),
            _request_headers("create"),
        )
        store_id = detail.store_id

    validation_task = store_service.update_credentials(
        store_id,
        api_key,
        api_secret,
        "Real Takealot credential validation before order sync",
        _actor(),
        _request_headers("validate"),
    )
    validation_result = store_service.process_store_task(validation_task.task_id)
    if validation_result["status"] != "succeeded":
        print(
            json.dumps(
                {
                    "store_id": store_id,
                    "validation_task_id": validation_task.task_id,
                    "validation_status": validation_result["status"],
                    "error_code": validation_result.get("error_code"),
                    "error_msg": validation_result.get("error_msg"),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)
    return store_id


def main() -> None:
    api_key, api_secret = _credential_from_env()
    store_name = os.environ.get("XH_TAKEALOT_REAL_STORE_NAME", DEFAULT_STORE_NAME).strip()
    if not store_name:
        store_name = DEFAULT_STORE_NAME

    store_service = StoreService()
    order_service = OrderService()
    store_id = _prepare_store(
        store_service,
        store_name=store_name,
        api_key=api_key,
        api_secret=api_secret,
    )

    sync_task = order_service.sync_store_orders(
        store_id,
        _actor(),
        _request_headers("sync"),
        reason="Real Takealot /sales order sync pilot",
        force=True,
    )
    sync_result = order_service.process_order_sync_task(
        sync_task.task_id,
        adapter_factory=_order_adapter_factory,
    )
    orders = order_service.list_orders(
        _actor(),
        store_id=store_id,
    ).orders
    first_order = orders[0] if orders else None
    first_order_detail = (
        order_service.get_order(first_order.order_id, _actor()) if first_order else None
    )

    result = {
        "store_id": store_id,
        "store_name": store_name,
        "sync_task_id": sync_task.task_id,
        "sync_status": sync_result["status"],
        "sync_error_code": sync_result.get("error_code"),
        "sync_error_msg": sync_result.get("error_msg"),
        "order_count": len(orders),
        "first_order": {
            "external_order_id": first_order.external_order_id,
            "status": first_order.status,
            "fulfillment_status": first_order.fulfillment_status,
            "total_amount": first_order.total_amount,
            "currency": first_order.currency,
            "item_count": first_order.item_count,
        }
        if first_order
        else None,
        "first_order_items": len(first_order_detail.items) if first_order_detail else 0,
    }
    print(json.dumps(result, ensure_ascii=False))

    if sync_result["status"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
