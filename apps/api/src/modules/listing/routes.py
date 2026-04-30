from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from src.modules.auth.dependencies import require_roles, require_writable_feature_roles

from .schemas import ListingJobListResponse, ListingJobResponse
from .service import ListingService

router = APIRouter(prefix="/api/listing", tags=["listing"])
service = ListingService()
ListingReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator")),
]
ListingWriter = Annotated[
    dict[str, Any],
    Depends(require_writable_feature_roles("listing", "super_admin", "tenant_admin", "operator")),
]


@router.get("/jobs", response_model=ListingJobListResponse)
def list_jobs(
    current_user: ListingReader,
    store_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    return service.list_jobs(current_user, store_id=store_id, status_filter=status)


@router.get("/jobs/{job_id}", response_model=ListingJobResponse)
def get_job(job_id: str, current_user: ListingReader):
    return service.get_job(job_id, current_user)


@router.post("/jobs/{job_id}/refresh-status", response_model=ListingJobResponse)
def refresh_job_status(job_id: str, current_user: ListingWriter):
    return service.refresh_job_status(job_id, current_user)
