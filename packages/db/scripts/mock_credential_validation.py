from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["XH_DATABASE_URL"] = ""

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
from src.modules.store.adapters.base import AdapterAuthError, AdapterCredentials, BaseAdapter, ListingSnapshot  # noqa: E402
from src.modules.store.service import StoreService  # noqa: E402


class ValidCredentialsAdapter(BaseAdapter):
    def validate_credentials(self) -> dict[str, object]:
        return {"account_id": "valid-account"}

    def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
        return []


class InvalidCredentialsAdapter(BaseAdapter):
    def validate_credentials(self) -> dict[str, object]:
        raise AdapterAuthError("mock invalid api key")

    def fetch_listings(self, heartbeat=None) -> list[ListingSnapshot]:
        return []


def adapter_factory(
    store: dict[str, object],
    credentials: AdapterCredentials,
) -> BaseAdapter:
    if credentials.api_key.startswith("valid"):
        return ValidCredentialsAdapter(credentials)
    return InvalidCredentialsAdapter(credentials)


def main() -> None:
    service = StoreService()
    actor = {
        "id": ADMIN_USER_ID,
        "role": "super_admin",
        "tenant_id": DEMO_TENANT_ID,
    }

    valid_store = app_state.create_store(
        {
            "name": "Credential Valid Store",
            "platform": "takealot",
            "status": "active",
            "api_key": "valid-key",
            "api_secret": "valid-secret",
            "masked_api_key": "vali********key",
            "api_key_status": "configured",
            "credential_status": "configured",
        }
    )
    invalid_store = app_state.create_store(
        {
            "name": "Credential Invalid Store",
            "platform": "takealot",
            "status": "active",
            "api_key": "invalid-key",
            "api_secret": "invalid-secret",
            "masked_api_key": "inva********key",
            "api_key_status": "configured",
            "credential_status": "configured",
        }
    )

    valid_task = service.update_credentials(
        valid_store["id"],
        "valid-key",
        "valid-secret",
        "mock validation",
        actor,
        {"x-request-id": "mock-validate-valid"},
    )
    invalid_task = service.update_credentials(
        invalid_store["id"],
        "invalid-key",
        "invalid-secret",
        "mock validation",
        actor,
        {"x-request-id": "mock-validate-invalid"},
    )

    processed_tasks = service.process_queued_store_tasks(adapter_factory=adapter_factory)
    valid_task_state = app_state.get_task(valid_task.task_id)
    invalid_task_state = app_state.get_task(invalid_task.task_id)
    valid_store_state = app_state.get_store(valid_store["id"])
    invalid_store_state = app_state.get_store(invalid_store["id"])

    assert len(processed_tasks) >= 2, processed_tasks
    assert valid_task_state["status"] == "succeeded", valid_task_state
    assert invalid_task_state["status"] == "failed", invalid_task_state
    assert valid_store_state["credential_status"] == "valid", valid_store_state
    assert invalid_store_state["credential_status"] == "expired", invalid_store_state

    print(
        json.dumps(
            {
                "processed_count": len(processed_tasks),
                "valid_task_status": valid_task_state["status"],
                "invalid_task_status": invalid_task_state["status"],
                "valid_store_status": valid_store_state["credential_status"],
                "invalid_store_status": invalid_store_state["credential_status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
