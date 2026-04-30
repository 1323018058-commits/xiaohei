from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.modules.auth.dependencies import require_roles

from .schemas import TenantUsageResponse
from .service import subscription_service


router = APIRouter(prefix="/admin/api", tags=["subscriptions"])
TenantAdmin = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin")),
]


@router.get("/tenant/usage", response_model=TenantUsageResponse)
def get_tenant_usage(current_user: TenantAdmin, tenant_id: str | None = None):
    return subscription_service.get_tenant_usage(current_user, tenant_id)
