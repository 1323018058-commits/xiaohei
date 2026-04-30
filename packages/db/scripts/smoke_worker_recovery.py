from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["XH_DATABASE_URL"] = ""
os.environ["XH_ALERT_OUTPUT_DIR"] = "reports/test-alerts"

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from worker_main import drain_once  # noqa: E402
from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
from src.modules.store.service import SYNC_STORE_LISTINGS_TASK_TYPE  # noqa: E402
from src.platform.settings.base import settings  # noqa: E402


def main() -> None:
    alert_dir = ROOT / "reports" / "test-alerts"
    alert_dir.mkdir(parents=True, exist_ok=True)
    before_alerts = {path.name for path in alert_dir.glob("*.json")}

    task = app_state.create_task(
        task_type=SYNC_STORE_LISTINGS_TASK_TYPE,
        domain="store",
        queue_name="store-sync",
        actor_user_id=ADMIN_USER_ID,
        actor_role="super_admin",
        tenant_id=DEMO_TENANT_ID,
        store_id=None,
        target_type="store_collection",
        target_id="stale-smoke",
        request_id="smoke-worker-recovery",
        label="Smoke stale worker recovery",
        next_action="Recover stale running task",
    )
    stale_heartbeat = datetime.now(UTC) - timedelta(seconds=30)
    app_state.update_task(
        task["id"],
        status="running",
        stage="syncing",
        attempt_count=1,
        max_retries=3,
        retryable=True,
        started_at=stale_heartbeat,
        last_heartbeat_at=stale_heartbeat,
        lease_owner="stale-worker",
        lease_token="stale-lease",
        lease_expires_at=stale_heartbeat,
    )

    previous_stale_after = settings.worker_stale_task_after_seconds
    previous_alert_dir = settings.alert_output_dir
    settings.worker_stale_task_after_seconds = 1
    settings.alert_output_dir = str(alert_dir)
    try:
        summary = drain_once(emit=False)
    finally:
        settings.worker_stale_task_after_seconds = previous_stale_after
        settings.alert_output_dir = previous_alert_dir

    recovered = app_state.get_task(task["id"])
    events = app_state.list_task_events(task["id"])
    after_alerts = {path.name for path in alert_dir.glob("*.json")}
    new_alerts = sorted(after_alerts - before_alerts)

    assert summary["recovered_count"] >= 1, summary
    assert recovered["status"] == "waiting_retry", recovered
    assert recovered["next_retry_at"] is not None, recovered
    assert any(event["event_type"] == "task.recovered_stale" for event in events), events
    assert any(name.startswith("worker_stale_task_recovered") for name in new_alerts), new_alerts

    print(
        json.dumps(
            {
                "task_id": task["id"],
                "status": recovered["status"],
                "recovered_count": summary["recovered_count"],
                "alert_count": len(new_alerts),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
