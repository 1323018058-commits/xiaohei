from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
from src.modules.store.service import StoreService  # noqa: E402


def _actor() -> dict[str, str]:
    return {
        "id": ADMIN_USER_ID,
        "role": "super_admin",
        "tenant_id": DEMO_TENANT_ID,
    }


def main() -> None:
    service = StoreService()
    task = service.reconcile_active_stores(
        _actor(),
        {"x-request-id": "takealot-reconcile"},
        reason="Scheduled Takealot /offers reconciliation",
    )
    result = service.process_sync_task(task.task_id)
    task_events = app_state.list_task_events(task.task_id)
    listing_count = 0
    failed_store_count = 0
    for event in task_events:
        details = event.get("details") or {}
        if event.get("event_type") == "task.succeeded":
            listing_count = int(details.get("listing_count") or listing_count)
            failed_store_count = int(details.get("failed_store_count") or failed_store_count)

    print(
        json.dumps(
            {
                "task_id": task.task_id,
                "status": result["status"],
                "stage": result["stage"],
                "error_code": result.get("error_code"),
                "error_msg": result.get("error_msg"),
                "listing_count": listing_count,
                "failed_store_count": failed_store_count,
            },
            ensure_ascii=False,
        )
    )
    if result["status"] not in {"succeeded", "partial"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
