from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.modules.auth.dependencies import require_roles

from .schemas import DashboardContextResponse, DashboardSummaryResponse
from .service import DashboardService

router = APIRouter(tags=["dashboard"])
service = DashboardService()
DashboardReader = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin", "operator", "warehouse")),
]


@router.get("/api/v1/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(current_user: DashboardReader):
    return service.get_summary(current_user)


@router.get("/api/v1/dashboard/context", response_model=DashboardContextResponse)
def get_dashboard_context(current_user: DashboardReader):
    return service.get_context(current_user)
