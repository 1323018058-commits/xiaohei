from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import time

from src.modules.bidding.service import BiddingService
from src.modules.common.dev_state import app_state
from src.modules.extension.service import ExtensionService
from src.modules.listing.service import ListingService
from src.modules.orders.service import OrderService
from src.modules.store.service import StoreService
from src.modules.webhook.service import TakealotWebhookService
from src.platform.alerting.service import alert_service
from src.platform.settings.base import settings


WORKER_ID = "api-worker"
RECOVERABLE_TASK_TYPES = {
    "SYNC_STORE_LISTINGS",
    "store.sync.full",
    "store.credentials.validate",
    "SYNC_TAKEALOT_ORDERS",
    "TAKEALOT_WEBHOOK_PROCESS",
    "EXTENSION_LIST_NOW",
    "PROCESS_LISTING_JOB",
}


def drain_once(
    store_service: StoreService | None = None,
    extension_service: ExtensionService | None = None,
    listing_service: ListingService | None = None,
    order_service: OrderService | None = None,
    webhook_service: TakealotWebhookService | None = None,
    bidding_service: BiddingService | None = None,
    *,
    emit: bool = True,
    recover_stale: bool = True,
) -> dict[str, object]:
    store_worker = store_service or StoreService()
    extension_worker = extension_service or ExtensionService()
    listing_worker = listing_service or ListingService()
    order_worker = order_service or OrderService()
    webhook_worker = webhook_service or TakealotWebhookService()
    bidding_worker = bidding_service or BiddingService()
    recovered_tasks = recover_stale_tasks() if recover_stale else []
    scheduled_store_reconcile_tasks = store_worker.enqueue_due_daily_reconciliation()
    scheduled_order_tasks = order_worker.enqueue_due_order_sync_tasks()
    processed_tasks = [
        *store_worker.process_queued_store_tasks(),
        *extension_worker.process_queued_extension_tasks(),
        *listing_worker.process_queued_listing_tasks(),
        *order_worker.process_queued_order_tasks(),
        *webhook_worker.process_queued_webhook_tasks(),
    ]
    bidding_cycles = (
        bidding_worker.process_due_store_cycles(
            dry_run=not settings.autobid_real_write_enabled,
            limit_per_store=settings.autobid_worker_cycle_limit,
        )
        if settings.autobid_worker_enabled
        else []
    )
    failed_tasks = [
        task
        for task in [*recovered_tasks, *processed_tasks]
        if task.get("status") in {"failed", "failed_final", "dead_letter", "timed_out"}
    ]
    if recovered_tasks:
        emit_worker_alert(
            event="worker_stale_task_recovered",
            severity="warning",
            message=f"Recovered {len(recovered_tasks)} stale worker task(s)",
            tasks=recovered_tasks,
        )
    if failed_tasks:
        emit_worker_alert(
            event="worker_task_failure",
            severity="critical",
            message=f"{len(failed_tasks)} worker task(s) failed",
            tasks=failed_tasks,
        )
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "worker_id": WORKER_ID,
        "recovered_count": len(recovered_tasks),
        "scheduled_store_reconcile_count": len(scheduled_store_reconcile_tasks),
        "scheduled_order_sync_count": len(scheduled_order_tasks),
        "processed_count": len(processed_tasks),
        "failed_count": len(failed_tasks),
        "bidding_cycle_count": len(bidding_cycles),
        "bidding_processed_count": sum(
            int(cycle.get("processed_count") or 0)
            for cycle in bidding_cycles
        ),
        "bidding_suggested_count": sum(
            int(cycle.get("suggested_count") or 0)
            for cycle in bidding_cycles
        ),
        "bidding_failed_count": sum(
            int(cycle.get("failed_count") or 0)
            for cycle in bidding_cycles
        ),
        "scheduled_order_sync_tasks": [
            summarize_task(task)
            for task in scheduled_order_tasks
        ],
        "scheduled_store_reconcile_tasks": [
            summarize_task(task)
            for task in scheduled_store_reconcile_tasks
        ],
        "recovered_tasks": [
            summarize_task(task)
            for task in recovered_tasks
        ],
        "tasks": [
            summarize_task(task)
            for task in processed_tasks
        ],
        "bidding_cycles": bidding_cycles,
    }
    if emit:
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def recover_stale_tasks() -> list[dict[str, object]]:
    recover = getattr(app_state, "recover_stale_tasks", None)
    if recover is None:
        return []
    return recover(
        RECOVERABLE_TASK_TYPES,
        stale_after_seconds=settings.worker_stale_task_after_seconds,
        worker_id=WORKER_ID,
        limit=settings.worker_stale_recovery_limit,
    )


def summarize_task(task: dict[str, object]) -> dict[str, object]:
    return {
        "task_id": task["id"],
        "task_type": task["task_type"],
        "status": task["status"],
        "stage": task["stage"],
        "error_code": task["error_code"],
        "store_id": task.get("store_id"),
    }


def emit_worker_alert(
    *,
    event: str,
    severity: str,
    message: str,
    tasks: list[dict[str, object]],
) -> dict[str, object]:
    return alert_service.emit(
        event=event,
        severity=severity,
        message=message,
        source="apps/api/worker_main.py",
        summary={
            "task_count": len(tasks),
            "statuses": sorted({str(task.get("status")) for task in tasks}),
        },
        details={
            "tasks": [summarize_task(task) for task in tasks],
        },
    )


def run_worker_loop(
    poll_interval_seconds: float,
    idle_log_interval_seconds: float,
) -> None:
    store_service = StoreService()
    extension_service = ExtensionService()
    listing_service = ListingService()
    order_service = OrderService()
    webhook_service = TakealotWebhookService()
    bidding_service = BiddingService()
    last_idle_log_at = 0.0
    while True:
        summary = drain_once(
            store_service,
            extension_service,
            listing_service,
            order_service,
            webhook_service,
            bidding_service,
            emit=False,
        )
        current_time = time.monotonic()
        should_log_idle = (
            idle_log_interval_seconds <= 0
            or current_time - last_idle_log_at >= idle_log_interval_seconds
        )
        if (
            summary["processed_count"]
            or summary["recovered_count"]
            or summary["scheduled_store_reconcile_count"]
            or summary["bidding_cycle_count"]
            or should_log_idle
        ):
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            if not summary["processed_count"] and not summary["recovered_count"]:
                last_idle_log_at = current_time
        time.sleep(poll_interval_seconds)


def main(argv: list[str] | None = None) -> dict[str, object] | None:
    parser = argparse.ArgumentParser(description="Xiaohei ERP store worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain queued store tasks once and exit",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=settings.worker_poll_interval_seconds,
        help="Polling interval in seconds for loop mode",
    )
    parser.add_argument(
        "--idle-log-interval",
        type=float,
        default=60.0,
        help="Minimum seconds between idle heartbeat logs in loop mode",
    )
    parser.add_argument(
        "--no-stale-recovery",
        action="store_true",
        help="Skip stale running task recovery in --once mode",
    )
    args = parser.parse_args(argv)

    if args.once:
        return drain_once(recover_stale=not args.no_stale_recovery)

    try:
        run_worker_loop(args.poll_interval, args.idle_log_interval)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped"}, ensure_ascii=False), flush=True)
    return None


if __name__ == "__main__":
    main()
