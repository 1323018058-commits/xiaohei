"""Common Pydantic schemas shared across modules."""
from __future__ import annotations

from pydantic import BaseModel


class OkResponse(BaseModel):
    ok: bool = True


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str


class PaginatedMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
