from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["XH_DATABASE_URL"] = ""

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state
from src.modules.store.adapters.base import (
    AdapterAuthError,
    AdapterCredentials,
    AdapterTemporaryError,
    BaseAdapter,
    ListingSnapshot,
)
from src.modules.store.service import StoreService, SYNC_STORE_LISTINGS_TASK_TYPE


class SuccessAdapter(BaseAdapter):
    def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
        if heartbeat is not None:
            heartbeat({"page_number": 1, "page_item_count": 1, "listing_count": 1})
        return [
            ListingSnapshot(
                external_listing_id="mock-success-001",
                sku="MOCK-SUCCESS-001",
                title="Mock Success Listing",
                platform_price=42.0,
                stock_quantity=7,
                currency="ZAR",
                raw_payload={"mock": "success"},
            )
        ]


class AuthFailureAdapter(BaseAdapter):
    def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
        raise AdapterAuthError("mock platform 401")


class TemporaryFailureAdapter(BaseAdapter):
    def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
        raise AdapterTemporaryError("mock platform 503")


def adapter_factory(
    store: dict[str, object],
    credentials: AdapterCredentials,
) -> BaseAdapter:
    name = str(store["name"])
    if "401" in name:
        return AuthFailureAdapter(credentials)
    if "503" in name:
        return TemporaryFailureAdapter(credentials)
    return SuccessAdapter(credentials)


def main() -> None:
    service = StoreService()
    app_state.create_store(
        {
            "name": "Mock 401 Store",
            "platform": "takealot",
            "status": "active",
            "api_key": "mock-401-key",
            "api_secret": "mock-401-secret",
            "masked_api_key": "mock********401",
            "api_key_status": "configured",
            "credential_status": "configured",
            "feature_policies": {
                "bidding_enabled": False,
                "listing_enabled": True,
                "sync_enabled": True,
            },
        }
    )
    app_state.create_store(
        {
            "name": "Mock 503 Store",
            "platform": "takealot",
            "status": "active",
            "api_key": "mock-503-key",
            "api_secret": "mock-503-secret",
            "masked_api_key": "mock********503",
            "api_key_status": "configured",
            "credential_status": "configured",
            "feature_policies": {
                "bidding_enabled": False,
                "listing_enabled": True,
                "sync_enabled": True,
            },
        }
    )

    task = app_state.create_task(
        task_type=SYNC_STORE_LISTINGS_TASK_TYPE,
        domain="store",
        queue_name="store-sync",
        actor_user_id=ADMIN_USER_ID,
        actor_role="super_admin",
        tenant_id=DEMO_TENANT_ID,
        store_id=None,
        target_type="store",
        target_id=None,
        request_id="mock-store-sync-failures",
        label="Mock all-store listing sync",
        next_action="Run mock adapters",
    )
    processed = service.process_sync_task(
        task["id"],
        adapter_factory=adapter_factory,
    )
    events = app_state.list_task_events(task["id"])
    failure_events = [
        event for event in events if event["event_type"] == "task.store_failed"
    ]
    sync_audits = [
        audit
        for audit in app_state.list_audits()
        if audit["task_id"] == task["id"] and audit["action"] == "store.sync.worker"
    ]

    assert processed["status"] == "partial", processed
    assert len(failure_events) == 2, failure_events
    assert any(audit["result"] == "success" for audit in sync_audits), sync_audits
    assert sum(1 for audit in sync_audits if audit["result"] == "failed") == 2, sync_audits

    retry_store = app_state.create_store(
        {
            "name": "Mock Retry 503 Store",
            "platform": "takealot",
            "status": "active",
            "api_key": "mock-retry-503-key",
            "api_secret": "mock-retry-503-secret",
            "masked_api_key": "mock********retry",
            "api_key_status": "configured",
            "credential_status": "configured",
            "feature_policies": {
                "bidding_enabled": False,
                "listing_enabled": True,
                "sync_enabled": True,
            },
        }
    )
    retry_task = app_state.create_task(
        task_type=SYNC_STORE_LISTINGS_TASK_TYPE,
        domain="store",
        queue_name="store-sync",
        actor_user_id=ADMIN_USER_ID,
        actor_role="super_admin",
        tenant_id=DEMO_TENANT_ID,
        store_id=retry_store["id"],
        target_type="store",
        target_id=retry_store["id"],
        request_id="mock-store-sync-retry",
        label="Mock retry listing sync",
        next_action="Run temporary-failure adapter",
    )
    retry_result = service.process_sync_task(
        retry_task["id"],
        adapter_factory=adapter_factory,
    )
    retry_events = app_state.list_task_events(retry_task["id"])

    assert retry_result["status"] == "waiting_retry", retry_result
    assert retry_result["next_retry_at"] is not None, retry_result
    assert any(
        event["event_type"] == "task.retry_scheduled"
        for event in retry_events
    ), retry_events

    app_state.update_task(
        retry_task["id"],
        next_retry_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    claimed_retry = app_state.claim_queued_tasks(
        {SYNC_STORE_LISTINGS_TASK_TYPE},
        worker_id="mock-retry-worker",
        limit=10,
    )
    retry_claimed = any(claimed["id"] == retry_task["id"] for claimed in claimed_retry)
    assert retry_claimed, claimed_retry

    print(
        json.dumps(
            {
                "task_id": task["id"],
                "status": processed["status"],
                "failure_event_count": len(failure_events),
                "audit_count": len(sync_audits),
                "retry_task_id": retry_task["id"],
                "retry_status": retry_result["status"],
                "retry_claimed": retry_claimed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
