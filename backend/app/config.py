"""ProfitLens v3 — Application configuration via environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173,http://localhost:8000"

    # --- Database (PostgreSQL) ---
    database_url: str = "postgresql+asyncpg://profitlens:profitlens_dev_2024@localhost:5432/profitlens"
    database_url_sync: str = "postgresql+psycopg2://profitlens:profitlens_dev_2024@localhost:5432/profitlens"
    db_pool_size: int = 40
    db_max_overflow: int = 40
    db_pool_recycle: int = 1800
    db_pool_timeout: int = 10
    db_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Celery ---
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_visibility_timeout_seconds: int = 86400

    # --- Product sync & Redis tuning ---
    product_sync_max_inflight_per_user: int = 2
    product_sync_max_inflight_per_store: int = 1
    product_sync_progress_ttl_seconds: int = 7200
    product_image_enrich_batch_size: int = 100
    redis_max_connections: int = 200
    library_scrape_pending_ttl_seconds: int = 60
    library_scrape_lock_ttl_seconds: int = 7200
    library_auto_scrape_interval_seconds: int = 43200
    library_auto_scrape_user_id: int = 0
    library_auto_scrape_lead_min: int = 7
    library_auto_scrape_lead_max: int = 21
    library_auto_scrape_price_min: float = 0
    library_auto_scrape_price_max: float = 100000
    library_auto_scrape_max_per_cat: int = 0

    # --- JWT Auth ---
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # --- Encryption ---
    profitlens_data_key: str = ""

    # --- Rate Limiting ---
    rate_limit_auth_login: int = 5          # per minute per IP:username
    rate_limit_auth_register: int = 3       # per hour per IP
    rate_limit_api_default: int = 60        # per minute per user

    # --- Takealot / Business ---
    target_margin_rate: float = 0.25
    fx_zar_to_cny: float = 0.41
    commission_rate: float = 0.15
    vat_rate: float = 0.15
    freight_rate_cny_per_kg: float = 79.0
    default_weight_kg: float = 0.50

    # --- External APIs ---
    deepseek_api_key: str = ""
    amazon_886it_api_key: str = ""

    # --- Email (SMTP) ---
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "ProfitLens ERP"
    smtp_use_ssl: bool = True
    email_code_expire_minutes: int = 10

    # --- Paths ---
    output_dir: Path = Path("output")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: str) -> str:
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _ensure_production_secrets(self) -> "Settings":
        if self.environment == "production":
            if not self.secret_key or self.secret_key == "change-me-in-production":
                raise ValueError("SECRET_KEY must be configured for production")
            if not self.profitlens_data_key:
                raise ValueError("PROFITLENS_DATA_KEY must be configured for production")
        return self



@lru_cache
def get_settings() -> Settings:
    return Settings()
