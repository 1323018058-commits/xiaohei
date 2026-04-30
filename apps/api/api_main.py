import logging
from contextlib import asynccontextmanager
from time import perf_counter

import anyio
from fastapi import FastAPI, Request

from src.modules.admin.routes import router as admin_router
from src.modules.auth.routes import router as auth_router
from src.modules.bidding.routes import router as bidding_router
from src.modules.dashboard.routes import router as dashboard_router
from src.modules.extension.routes import router as extension_router
from src.modules.listing.routes import router as listing_router
from src.modules.orders.routes import router as orders_router
from src.modules.selection.routes import router as selection_router
from src.modules.store.routes import router as store_router
from src.modules.subscription.routes import router as subscription_router
from src.modules.tasking.routes import router as task_router
from src.modules.webhook.routes import router as webhook_router
from src.platform.settings.base import settings

logger = logging.getLogger(__name__)
HOT_PATH_PREFIXES = (
    "/api/auth/login",
    "/api/auth/me",
    "/api/v1/dashboard/summary",
    "/api/tasks",
    "/api/v1/orders",
    "/api/v1/selection",
    "/api/v1/stores",
    "/admin/api/tenant/usage",
    "/admin/api/system/health",
)
SLOW_REQUEST_PROBE_MS = 500


@asynccontextmanager
async def lifespan(app: FastAPI):
    limiter = anyio.to_thread.current_default_thread_limiter()
    previous_tokens = limiter.total_tokens
    limiter.total_tokens = 500
    logger.warning(
        "anyio_thread_limiter_configured previous_tokens=%s total_tokens=%s",
        previous_tokens,
        limiter.total_tokens,
    )
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(task_router)
app.include_router(dashboard_router)
app.include_router(store_router)
app.include_router(orders_router)
app.include_router(bidding_router)
app.include_router(selection_router)
app.include_router(extension_router)
app.include_router(listing_router)
app.include_router(subscription_router)
app.include_router(webhook_router)


def _should_probe_request(path: str) -> bool:
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in HOT_PATH_PREFIXES
    )


@app.middleware("http")
async def request_probe(request: Request, call_next):
    path = request.url.path
    if not _should_probe_request(path):
        return await call_next(request)

    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.warning(
            "request_probe_failed method=%s path=%s elapsed_ms=%.2f",
            request.method,
            path,
            elapsed_ms,
        )
        raise

    elapsed_ms = (perf_counter() - started_at) * 1000
    response.headers["x-xh-request-ms"] = f"{elapsed_ms:.2f}"
    if elapsed_ms >= SLOW_REQUEST_PROBE_MS:
        logger.warning(
            "request_probe_slow method=%s path=%s status_code=%s elapsed_ms=%.2f",
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
    return response


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}
