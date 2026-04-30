from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from src.modules.auth.dependencies import require_roles

from .schemas import (
    CategoryMatchRequest,
    CategoryMatchResponse,
    ListingAiAutopilotRequest,
    ListingAiAutopilotResponse,
    ListingImageRequirementCheckRequest,
    ListingImageRequirementCheckResponse,
    ListingImageUploadResponse,
    ListingImageUrlValidateRequest,
    ListingImageUrlValidateResponse,
    ListingJobListResponse,
    ListingJobResponse,
    ListingFinalizeOfferResponse,
    ListingLoadsheetPreviewRequest,
    ListingLoadsheetPreviewResponse,
    ListingSubmissionCreateRequest,
    ListingSubmissionCreateResponse,
    ListingSubmissionDetailResponse,
    ListingSubmissionListResponse,
    ListingSubmissionSyncResponse,
    TakealotBrandSearchResponse,
    TakealotCategoryRequirementsResponse,
    TakealotCategorySearchResponse,
)
from .service import ListingService

router = APIRouter(prefix="/api/listing", tags=["listing"])
service = ListingService()
ListingReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator")),
]


@router.post("/images", response_model=ListingImageUploadResponse)
def upload_listing_images(
    current_user: ListingReader,
    store_id: str = Form(...),
    submission_id: str | None = Form(default=None),
    files: list[UploadFile] = File(...),
):
    return service.upload_listing_images(
        current_user,
        store_id=store_id,
        submission_id=submission_id,
        files=files,
    )


@router.post("/images/validate-url", response_model=ListingImageUrlValidateResponse)
def validate_listing_image_url(
    request: ListingImageUrlValidateRequest,
    current_user: ListingReader,
):
    return service.validate_listing_image_url(current_user, request)


@router.post("/images/check-requirements", response_model=ListingImageRequirementCheckResponse)
def check_listing_image_requirements(
    request: ListingImageRequirementCheckRequest,
    current_user: ListingReader,
):
    return service.check_listing_image_requirements(current_user, request)


@router.post("/loadsheet/preview", response_model=ListingLoadsheetPreviewResponse)
def preview_listing_loadsheet(
    request: ListingLoadsheetPreviewRequest,
    current_user: ListingReader,
):
    return service.preview_listing_loadsheet(current_user, request)


@router.post("/stores/{store_id}/submissions", response_model=ListingSubmissionCreateResponse)
def create_listing_submission(
    store_id: str,
    request: ListingSubmissionCreateRequest,
    current_user: ListingReader,
    raw_request: Request,
):
    return service.create_listing_submission(
        current_user,
        store_id=store_id,
        request=request,
        request_headers=dict(raw_request.headers),
    )


@router.get("/stores/{store_id}/submissions", response_model=ListingSubmissionListResponse)
def list_listing_submissions(
    store_id: str,
    current_user: ListingReader,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return service.list_listing_submissions(
        current_user,
        store_id=store_id,
        status_filter=status,
        page=page,
        page_size=page_size,
    )


@router.post("/stores/{store_id}/submissions/sync", response_model=ListingSubmissionSyncResponse)
def sync_store_listing_submissions(
    store_id: str,
    current_user: ListingReader,
    raw_request: Request,
):
    return service.sync_store_listing_submissions(
        current_user,
        store_id=store_id,
        request_headers=dict(raw_request.headers),
    )


@router.get("/submissions/{submission_id}", response_model=ListingSubmissionDetailResponse)
def get_listing_submission_detail(
    submission_id: str,
    current_user: ListingReader,
):
    return service.get_listing_submission_detail(current_user, submission_id)


@router.post("/submissions/{submission_id}/sync-status", response_model=ListingSubmissionSyncResponse)
def sync_listing_submission_status(
    submission_id: str,
    current_user: ListingReader,
    raw_request: Request,
):
    return service.sync_listing_submission_status(
        current_user,
        submission_id,
        request_headers=dict(raw_request.headers),
    )


@router.post("/submissions/{submission_id}/finalize-offer", response_model=ListingFinalizeOfferResponse)
def finalize_listing_submission_offer(
    submission_id: str,
    current_user: ListingReader,
    raw_request: Request,
):
    return service.finalize_listing_submission_offer(
        current_user,
        submission_id,
        request_headers=dict(raw_request.headers),
    )


@router.post("/ai/autopilot", response_model=ListingAiAutopilotResponse)
def generate_listing_content(
    request: ListingAiAutopilotRequest,
    current_user: ListingReader,
):
    return service.generate_listing_content(current_user, request)


@router.post("/categories/match", response_model=CategoryMatchResponse)
def match_category(
    request: CategoryMatchRequest,
    current_user: ListingReader,
):
    return service.match_category(current_user, request)


@router.get("/categories/search", response_model=TakealotCategorySearchResponse)
def search_categories(
    current_user: ListingReader,
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return service.search_categories(
        current_user,
        query=q,
        page=page,
        page_size=page_size,
    )


@router.get("/categories/{category_id}/requirements", response_model=TakealotCategoryRequirementsResponse)
def get_category_requirements(
    category_id: int,
    current_user: ListingReader,
):
    return service.get_category_requirements(category_id, current_user)


@router.get("/brands/search", response_model=TakealotBrandSearchResponse)
def search_brands(
    current_user: ListingReader,
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return service.search_brands(
        current_user,
        query=q,
        page=page,
        page_size=page_size,
    )


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
def refresh_job_status(job_id: str, current_user: ListingReader):
    return service.refresh_job_status(job_id, current_user)
