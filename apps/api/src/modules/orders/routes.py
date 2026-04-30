from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from src.modules.auth.dependencies import require_roles
from src.modules.store.schemas import TaskCreatedResponse

from .schemas import OrderDetail, OrderListResponse, OrderSyncRequest
from .service import OrderService

router = APIRouter(tags=["orders"])
service = OrderService()
OrderReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator", "warehouse")),
]
OrderOperator = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator")),
]


@router.get("/api/v1/orders", response_model=OrderListResponse)
def list_orders(
    current_user: OrderReader,
    store_id: str | None = Query(default=None, min_length=1),
    status: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=128),
):
    return service.list_orders(
        current_user,
        store_id=store_id,
        status_filter=status,
        query=q,
    )


@router.get("/api/v1/orders/{order_id}", response_model=OrderDetail)
def get_order(order_id: str, current_user: OrderReader):
    return service.get_order(order_id, current_user)


@router.post(
    "/api/stores/{store_id}/orders/sync",
    response_model=TaskCreatedResponse,
    include_in_schema=False,
)
@router.post("/api/v1/stores/{store_id}/orders/sync", response_model=TaskCreatedResponse)
def sync_store_orders(
    store_id: str,
    payload: OrderSyncRequest,
    request: Request,
    current_user: OrderOperator,
):
    return service.sync_store_orders(
        store_id,
        current_user,
        request.headers,
        reason=payload.reason,
        force=False,
    )


@router.post(
    "/api/stores/{store_id}/orders/sync/force",
    response_model=TaskCreatedResponse,
    include_in_schema=False,
)
@router.post("/api/v1/stores/{store_id}/orders/sync/force", response_model=TaskCreatedResponse)
def force_sync_store_orders(
    store_id: str,
    payload: OrderSyncRequest,
    request: Request,
    current_user: OrderOperator,
):
    return service.sync_store_orders(
        store_id,
        current_user,
        request.headers,
        reason=payload.reason,
        force=True,
    )
