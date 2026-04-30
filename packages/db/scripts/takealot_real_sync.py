from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
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
    return {"x-request-id": f"takealot-real-sync-{label}"}


def _find_store_id(name: str) -> str | None:
    for store in app_state.list_stores():
        if store["name"] == name:
            return store["id"]
    return None


def _sync_adapter_factory(
    store: dict[str, object],
    credentials: AdapterCredentials,
) -> BaseAdapter:
    del store
    max_pages = int(os.environ.get("XH_TAKEALOT_SYNC_MAX_PAGES", DEFAULT_SYNC_MAX_PAGES))
    page_limit = int(os.environ.get("XH_TAKEALOT_SYNC_PAGE_LIMIT", DEFAULT_SYNC_PAGE_LIMIT))
    return TakealotAdapter(
        credentials,
        max_pages=max_pages,
        page_limit=page_limit,
    )


def _prepare_store(
    service: StoreService,
    *,
    store_name: str,
    api_key: str,
    api_secret: str,
) -> str:
    store_id = _find_store_id(store_name)
    if store_id is None:
        detail = service.create_store(
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

    validation_task = service.update_credentials(
        store_id,
        api_key,
        api_secret,
        "Real Takealot credential validation",
        _actor(),
        _request_headers("validate"),
    )
    validation_result = service.process_store_task(validation_task.task_id)
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

    service = StoreService()
    store_id = _prepare_store(
        service,
        store_name=store_name,
        api_key=api_key,
        api_secret=api_secret,
    )

    sync_task = service.sync_store(
        store_id,
        _actor(),
        _request_headers("sync"),
        reason="Real Takealot listing sync pilot",
        force=True,
    )
    sync_result = service.process_sync_task(
        sync_task.task_id,
        adapter_factory=_sync_adapter_factory,
    )
    task_events = app_state.list_task_events(sync_task.task_id)
    synced_listing_count = 0
    for event in task_events:
        details = event.get("details") or {}
        if event.get("event_type") in {"task.progress", "task.succeeded"}:
            synced_listing_count = int(details.get("listing_count") or synced_listing_count)
    listings = service.list_store_listings(store_id, _actor()).listings
    first_listing = listings[0] if listings else None

    result = {
        "store_id": store_id,
        "store_name": store_name,
        "sync_task_id": sync_task.task_id,
        "sync_status": sync_result["status"],
        "sync_error_code": sync_result.get("error_code"),
        "sync_error_msg": sync_result.get("error_msg"),
        "synced_listing_count": synced_listing_count,
        "listing_count": len(listings),
        "first_listing": {
            "sku": first_listing.sku,
            "title": first_listing.title,
            "platform_price": first_listing.platform_price,
            "stock_quantity": first_listing.stock_quantity,
            "currency": first_listing.currency,
        }
        if first_listing
        else None,
    }
    print(json.dumps(result, ensure_ascii=False))

    if sync_result["status"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
