"""ProfitLens v3 — Celery application configuration.

Celery handles background tasks: store sync, auto-bid cycles, listing jobs,
dropship jobs, scraping, and snapshot refresh.

Queues:
  - default: General tasks (store sync, bid, dashboard)
  - listing: Playwright-heavy listing/dropship jobs (separate worker pool)
  - snapshot: Cache refresh tasks
  - scrape: Product library scraping
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "profitlens",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    broker_transport_options={
        "visibility_timeout": _settings.celery_visibility_timeout_seconds,
    },
    result_backend_transport_options={
        "visibility_timeout": _settings.celery_visibility_timeout_seconds,
    },

    # Results
    result_expires=3600,

    # Queues
    task_default_queue="default",
    task_routes={
        "app.tasks.product_sync_tasks.*": {"queue": "sync"},
        "app.tasks.bid_tasks.run_autobid_cycle": {"queue": "repricing"},
        "app.tasks.listing_tasks.*": {"queue": "listing"},
        "app.tasks.dropship_tasks.*": {"queue": "listing"},
        "app.tasks.scrape_tasks.*": {"queue": "scrape"},
        "app.tasks.snapshot_tasks.*": {"queue": "snapshot"},
    },

    # Beat schedule — periodic tasks
    beat_schedule={
        # Auto-bid cycle every 5 minutes
        "autobid-cycle": {
            "task": "app.tasks.bid_tasks.run_autobid_cycle",
            "schedule": 300.0,
        },
        # Buyable bid products sync every 30 minutes
        "sync-buyable-bid-products": {
            "task": "app.tasks.bid_tasks.sync_buyable_bid_products",
            "schedule": 1800.0,
        },
        # Dashboard snapshot refresh every 2 minutes
        "dashboard-refresh": {
            "task": "app.tasks.snapshot_tasks.refresh_dashboard_snapshots",
            "schedule": 120.0,
        },
        # Library auto scrape every 12 hours
        "library-auto-replenish": {
            "task": "app.tasks.scrape_tasks.enqueue_auto_library_scrape",
            "schedule": float(_settings.library_auto_scrape_interval_seconds),
        },
        # Clean up expired extension tokens daily
        "cleanup-extension-tokens": {
            "task": "app.tasks.store_tasks.cleanup_expired_tokens",
            "schedule": crontab(hour=3, minute=0),
        },
        # Listing job recovery every 10 minutes
        "listing-recovery": {
            "task": "app.tasks.listing_tasks.recover_stale_jobs",
            "schedule": 600.0,
        },
        # Dropship job recovery every 10 minutes
        "dropship-recovery": {
            "task": "app.tasks.dropship_tasks.recover_stale_dropship_jobs",
            "schedule": 600.0,
        },
        # Fulfillment stale draft check every hour
        "fulfillment-stale-check": {
            "task": "app.tasks.warehouse_tasks.check_stale_fulfillment_drafts",
            "schedule": 3600,
        },
    },
)

# Explicitly import all task modules so Celery registers them
celery_app.conf.update(
    include=[
        "app.tasks.product_sync_tasks",
        "app.tasks.bid_tasks",
        "app.tasks.store_tasks",
        "app.tasks.extension_tasks",
        "app.tasks.listing_tasks",
        "app.tasks.dropship_tasks",
        "app.tasks.scrape_tasks",
        "app.tasks.snapshot_tasks",
        "app.tasks.warehouse_tasks",
    ],
)
