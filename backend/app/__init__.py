"""ProfitLens v3 — FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.security_headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    settings = get_settings()
    settings.output_dir.mkdir(exist_ok=True)
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ProfitLens ERP",
        description="Takealot Cross-border E-commerce ERP System",
        version="3.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # --- Middleware (order matters: last added = first executed) ---
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-CSRF-Token"],
    )

    # --- Include API routers ---
    from app.api import (
        admin, auth, bids, cnexpress, dashboard, dropship,
        extension, library, listings, notifications, products,
        profit, stores, warehouse, webhooks,
    )

    app.include_router(auth.router)
    app.include_router(stores.router)
    app.include_router(admin.router)
    app.include_router(bids.router)
    app.include_router(products.router)
    app.include_router(listings.router)
    app.include_router(dropship.router)
    app.include_router(library.router)
    app.include_router(cnexpress.router)
    app.include_router(warehouse.router)
    app.include_router(notifications.router)
    app.include_router(dashboard.router)
    app.include_router(profit.router)
    app.include_router(extension.router)
    app.include_router(webhooks.router)

    # --- Health check ---
    @app.get("/api/health", tags=["system"])
    async def health_check():
        return {"status": "ok", "version": "3.0.0"}

    return app
