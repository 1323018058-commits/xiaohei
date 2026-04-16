from app.tasks.celery_app import celery_app
from app.config import get_settings


def test_periodic_bid_product_sync_runs_every_30_minutes():
    schedule = celery_app.conf.beat_schedule["sync-buyable-bid-products"]
    assert schedule["task"] == "app.tasks.bid_tasks.sync_buyable_bid_products"
    assert schedule["schedule"] == 1800.0


def test_periodic_library_auto_scrape_runs_every_12_hours():
    schedule = celery_app.conf.beat_schedule["library-auto-replenish"]
    assert schedule["task"] == "app.tasks.scrape_tasks.enqueue_auto_library_scrape"
    assert schedule["schedule"] == 43200.0


def test_periodic_library_auto_scrape_defaults_to_full_price_slices():
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.library_auto_scrape_max_per_cat == 0


def test_celery_visibility_timeout_is_configured_for_long_scrapes():
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.celery_visibility_timeout_seconds == 86400
    assert celery_app.conf.broker_transport_options["visibility_timeout"] == 86400
    assert celery_app.conf.result_backend_transport_options["visibility_timeout"] == 86400
