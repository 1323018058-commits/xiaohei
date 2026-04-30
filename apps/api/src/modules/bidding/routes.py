from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.modules.auth.dependencies import require_roles

from .schemas import (
    BiddingCycleRequest,
    BiddingCycleResponse,
    BiddingRuleListResponse,
    BiddingRuleLogListResponse,
    BiddingRuleResponse,
    BiddingStoreStatusResponse,
    BulkImportBiddingRuleItem,
    BulkImportBiddingRuleResponse,
    UpdateBiddingRuleRequest,
)
from .service import BiddingService

router = APIRouter(prefix="/api/v1/bidding", tags=["bidding"])
service = BiddingService()
BiddingReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator")),
]
BiddingWriter = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator")),
]


@router.get("/rules", response_model=BiddingRuleListResponse)
def list_rules(
    current_user: BiddingReader,
    store_id: str = Query(min_length=1),
    sku: str | None = Query(default=None, max_length=128),
):
    return service.list_rules(actor=current_user, store_id=store_id, sku_query=sku)


@router.get("/stores/{store_id}/status", response_model=BiddingStoreStatusResponse)
def store_status(store_id: str, current_user: BiddingReader):
    return service.status(actor=current_user, store_id=store_id)


@router.post("/stores/{store_id}/start", response_model=BiddingStoreStatusResponse)
def start_store_bidding(
    store_id: str,
    request: Request,
    current_user: BiddingWriter,
):
    return service.start_store(
        actor=current_user,
        store_id=store_id,
        request_headers=request.headers,
    )


@router.post("/stores/{store_id}/stop", response_model=BiddingStoreStatusResponse)
def stop_store_bidding(
    store_id: str,
    request: Request,
    current_user: BiddingWriter,
):
    return service.stop_store(
        actor=current_user,
        store_id=store_id,
        request_headers=request.headers,
    )


@router.get("/stores/{store_id}/log", response_model=BiddingRuleLogListResponse)
def store_log(store_id: str, current_user: BiddingReader):
    return service.list_log(actor=current_user, store_id=store_id)


@router.post("/stores/{store_id}/cycle", response_model=BiddingCycleResponse)
def run_cycle(
    store_id: str,
    payload: BiddingCycleRequest,
    request: Request,
    current_user: BiddingWriter,
):
    return service.run_cycle(
        actor=current_user,
        store_id=store_id,
        payload=payload,
        request_headers=request.headers,
    )


@router.patch("/rules/{rule_id}", response_model=BiddingRuleResponse)
def update_rule(
    rule_id: str,
    payload: UpdateBiddingRuleRequest,
    request: Request,
    current_user: BiddingWriter,
):
    try:
        return service.update_rule(
            rule_id=rule_id,
            payload=payload,
            actor=current_user,
            request_headers=request.headers,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/rules/bulk-import", response_model=BulkImportBiddingRuleResponse)
def bulk_import_rules(
    payload: list[BulkImportBiddingRuleItem],
    request: Request,
    current_user: BiddingWriter,
    store_id: str = Query(min_length=1),
):
    try:
        return service.bulk_import(
            store_id=store_id,
            items=payload,
            actor=current_user,
            request_headers=request.headers,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
