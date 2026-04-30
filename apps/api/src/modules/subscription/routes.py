from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.dependencies import require_roles

from .schemas import RedeemActivationCardRequest, RedeemActivationCardResponse, TenantUsageResponse
from .service import subscription_service


router = APIRouter(prefix="/admin/api", tags=["subscriptions"])
public_router = APIRouter(prefix="/api/subscription", tags=["subscription"])
TenantAdmin = Annotated[
    dict[str, Any],
    Depends(require_roles("super_admin", "tenant_admin")),
]


@router.get("/tenant/usage", response_model=TenantUsageResponse)
def get_tenant_usage(current_user: TenantAdmin, tenant_id: str | None = None):
    return subscription_service.get_tenant_usage(current_user, tenant_id)


@public_router.post("/redeem-card", response_model=RedeemActivationCardResponse)
def redeem_activation_card(
    payload: RedeemActivationCardRequest,
    current_user: CurrentUser,
):
    return subscription_service.redeem_activation_card(current_user, payload.code)
