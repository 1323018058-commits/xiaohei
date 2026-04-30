import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[5] / ".env"


def _load_root_env() -> None:
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_root_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XH_", extra="ignore")

    app_name: str = "xiaohei-erp"
    database_url: str | None = None
    db_bootstrap_demo_data: bool = True
    session_cookie_name: str = "erp_session"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 28800
    demo_username: str = "admin"
    demo_password: str = "admin123"
    demo_user_id: str = "demo-user"
    demo_role: str = "super_admin"
    demo_subscription_status: str = "active"
    store_credential_encryption_key: str = "xiaohei-erp-dev-store-credential-key"
    takealot_api_base_url: str = "https://marketplace-api.takealot.com/v1"
    takealot_catalog_base_url: str = "https://seller-api.takealot.com"
    takealot_catalog_email: str | None = None
    takealot_catalog_password: str | None = None
    takealot_catalog_api_key: str | None = None
    extension_token_ttl_seconds: int = 604800
    extension_listing_default_quantity: int = 1
    extension_listing_default_leadtime_days: int = 3
    takealot_leadtime_merchant_warehouse_id: int | None = None
    takealot_webhook_secret: str | None = None
    takealot_webhook_public_url: str | None = None
    takealot_webhook_store_id: str | None = None
    platform_api_timeout_seconds: float = 15.0
    takealot_order_page_limit: int = 10
    takealot_order_max_pages: int = 50
    takealot_order_sync_lookback_days: int = 30
    takealot_order_sync_fallback_chunk_days: int = 7
    takealot_order_auto_sync_interval_minutes: int = 30
    takealot_order_auto_sync_batch_size: int = 50
    autobid_real_write_enabled: bool = False
    autobid_cycle_default_limit: int = 50
    autobid_worker_enabled: bool = True
    autobid_worker_cycle_limit: int = 2
    autobid_worker_global_cycle_limit: int = 120
    autobid_buybox_timeout_seconds: float = 10.0
    db_pool_max_size: int = 50
    db_pool_max_overflow: int = 100
    db_pool_timeout_seconds: int = 30
    db_connect_timeout_seconds: int = 10
    db_slow_checkout_probe_ms: int = 250
    db_pool_healthcheck_idle_seconds: int = 15
    dashboard_business_timezone: str = "Africa/Johannesburg"
    dashboard_viewer_timezone: str = "Asia/Shanghai"
    dashboard_order_sync_stale_minutes: int = 60
    dashboard_zar_cny_rate: float = 0.42
    worker_poll_interval_seconds: float = 2.0
    worker_log_dir: str = "reports/runtime"
    worker_stale_task_after_seconds: int = 300
    worker_stale_recovery_limit: int = 20
    alert_output_dir: str = "reports/alerts"
    alert_webhook_url: str | None = None
    listing_file_storage_dir: str = "reports/listing-loadsheets"


settings = Settings()
