from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ListingJobResponse(BaseModel):
    job_id: str
    tenant_id: str
    store_id: str
    product_id: str | None
    guardrail_id: str | None
    entry_task_id: str | None
    processing_task_id: str | None
    platform: str
    source: str
    source_ref: str | None
    title: str
    status: str
    stage: str
    note: str | None
    raw_payload: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ListingJobListResponse(BaseModel):
    jobs: list[ListingJobResponse]
