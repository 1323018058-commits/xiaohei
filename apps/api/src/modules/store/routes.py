from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from src.modules.auth.dependencies import require_roles

from .schemas import (
    CreateStoreRequest,
    StoreCredentialValidationResponse,
    StoreDeleteResponse,
    StoreDetail,
    StoreListingListResponse,
    StoreListingMetricListResponse,
    StoreListingResponse,
    StoreListResponse,
    StoreSyncRequest,
    StoreSyncTaskListResponse,
    TaskCreatedResponse,
    UpdateStoreListingRequest,
    UpdateStoreCredentialsRequest,
    UpdateStoreRequest,
)
from .service import StoreService

router = APIRouter(tags=["stores"])
service = StoreService()
StoreReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator")),
]
StoreAdmin = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin")),
]
StoreSuperAdmin = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin")),
]


@router.get("/api/stores", response_model=StoreListResponse, include_in_schema=False)
@router.get("/api/v1/stores", response_model=StoreListResponse)
def list_stores(current_user: StoreReader):
    return service.list_stores(current_user)


@router.post("/api/stores", response_model=StoreDetail, include_in_schema=False)
@router.post("/api/v1/stores", response_model=StoreDetail)
def create_store(payload: CreateStoreRequest, request: Request, current_user: StoreAdmin):
    return service.create_store(payload.model_dump(), current_user, request.headers)


@router.post(
    "/api/stores/sync/reconcile",
    response_model=TaskCreatedResponse,
    include_in_schema=False,
)
@router.post("/api/v1/stores/sync/reconcile", response_model=TaskCreatedResponse)
def reconcile_active_stores(
    payload: StoreSyncRequest,
    request: Request,
    current_user: StoreSuperAdmin,
):
    return service.reconcile_active_stores(
        current_user,
        request.headers,
        reason=payload.reason,
    )


@router.get("/api/stores/{store_id}", response_model=StoreDetail, include_in_schema=False)
@router.get("/api/v1/stores/{store_id}", response_model=StoreDetail)
def get_store(store_id: str, current_user: StoreReader):
    return service.get_store(store_id, current_user)


@router.delete("/api/stores/{store_id}", response_model=StoreDeleteResponse, include_in_schema=False)
@router.delete("/api/v1/stores/{store_id}", response_model=StoreDeleteResponse)
def delete_store(store_id: str, request: Request, current_user: StoreAdmin):
    return service.delete_store(store_id, current_user, request.headers)


@router.get("/api/stores/{store_id}/listings", response_model=StoreListingListResponse, include_in_schema=False)
@router.get("/api/v1/stores/{store_id}/listings", response_model=StoreListingListResponse)
def list_store_listings(
    store_id: str,
    current_user: StoreReader,
    sku: str | None = Query(default=None, max_length=128),
    q: str | None = Query(default=None, max_length=128),
    status_group: str | None = Query(default=None, max_length=32),
    bidding_filter: str | None = Query(default=None, max_length=32),
    sort_by: str | None = Query(default=None, max_length=32),
    sort_dir: str | None = Query(default=None, max_length=8),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return service.list_store_listings(
        store_id,
        current_user,
        sku_query=sku,
        query=q,
        status_group=status_group,
        bidding_filter=bidding_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/v1/stores/{store_id}/listing-metrics",
    response_model=StoreListingMetricListResponse,
)
def list_store_listing_metrics(
    store_id: str,
    current_user: StoreReader,
    sku: list[str] | None = Query(default=None, max_length=128),
):
    return service.list_store_listing_metrics(store_id, current_user, sku_filter=sku)


@router.patch(
    "/api/v1/stores/{store_id}/listings/{listing_id}",
    response_model=StoreListingResponse,
)
def update_store_listing(
    store_id: str,
    listing_id: str,
    payload: UpdateStoreListingRequest,
    request: Request,
    current_user: StoreReader,
):
    return service.update_store_listing(
        store_id,
        listing_id,
        payload.model_dump(exclude_unset=True),
        current_user,
        request.headers,
    )


@router.post("/api/stores/{store_id}", response_model=StoreDetail, include_in_schema=False)
@router.post("/api/v1/stores/{store_id}", response_model=StoreDetail)
def update_store(
    store_id: str,
    payload: UpdateStoreRequest,
    request: Request,
    current_user: StoreAdmin,
):
    return service.update_store(
        store_id,
        payload.model_dump(exclude_unset=True),
        current_user,
        request.headers,
    )


@router.get(
    "/api/stores/{store_id}/sync-tasks",
    response_model=StoreSyncTaskListResponse,
    include_in_schema=False,
)
@router.get("/api/v1/stores/{store_id}/sync-tasks", response_model=StoreSyncTaskListResponse)
def list_sync_tasks(store_id: str, current_user: StoreReader):
    return service.list_sync_tasks(store_id, current_user)


@router.post(
    "/api/stores/{store_id}/credentials",
    response_model=TaskCreatedResponse,
    include_in_schema=False,
)
@router.post("/api/v1/stores/{store_id}/credentials", response_model=TaskCreatedResponse)
def update_credentials(
    store_id: str,
    payload: UpdateStoreCredentialsRequest,
    request: Request,
    current_user: StoreAdmin,
):
    return service.update_credentials(
        store_id,
        payload.api_key,
        payload.api_secret,
        payload.reason,
        current_user,
        request.headers,
    )


@router.post(
    "/api/stores/{store_id}/credentials/validate",
    response_model=StoreCredentialValidationResponse,
    include_in_schema=False,
)
@router.post(
    "/api/v1/stores/{store_id}/credentials/validate",
    response_model=StoreCredentialValidationResponse,
)
def validate_credentials(
    store_id: str,
    request: Request,
    current_user: StoreAdmin,
):
    return service.validate_credentials(store_id, current_user, request.headers)


@router.post("/api/stores/{store_id}/sync", response_model=TaskCreatedResponse, include_in_schema=False)
@router.post("/api/v1/stores/{store_id}/sync", response_model=TaskCreatedResponse)
def sync_store(
    store_id: str,
    payload: StoreSyncRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: StoreReader,
):
    response = service.sync_store(
        store_id,
        current_user,
        request.headers,
        reason=payload.reason,
        sync_scope=payload.sync_scope,
        force=False,
    )
    background_tasks.add_task(service.process_store_task_safely, response.task_id)
    return response


@router.post("/api/stores/{store_id}/sync/force", response_model=TaskCreatedResponse, include_in_schema=False)
@router.post("/api/v1/stores/{store_id}/sync/force", response_model=TaskCreatedResponse)
def force_sync_store(
    store_id: str,
    payload: StoreSyncRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: StoreAdmin,
):
    response = service.sync_store(
        store_id,
        current_user,
        request.headers,
        reason=payload.reason,
        sync_scope=payload.sync_scope,
        force=True,
    )
    background_tasks.add_task(service.process_store_task_safely, response.task_id)
    return response
