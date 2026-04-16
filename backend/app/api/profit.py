"""Profit calculator API router."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ActiveUser
from app.config import get_settings

router = APIRouter(prefix="/api/profit", tags=["profit"])


@router.post("/calculate")
async def calculate_profit(body: dict, user: ActiveUser):
    """Calculate profit margins for a product.

    Uses the same formula as the original profit_screen.py.
    """
    settings = get_settings()

    selling_price_zar = float(body.get("selling_price_zar", 0))
    cost_cny = float(body.get("cost_cny", 0))
    weight_kg = float(body.get("weight_kg", settings.default_weight_kg))
    commission_rate = float(body.get("commission_rate", settings.commission_rate))
    vat_rate = float(body.get("vat_rate", settings.vat_rate))
    fx_rate = float(body.get("fx_rate", settings.fx_zar_to_cny))
    freight_rate = float(body.get("freight_rate", settings.freight_rate_cny_per_kg))

    if selling_price_zar <= 0:
        return {"ok": False, "error": "售价必须大于0"}

    # Costs
    cost_zar = cost_cny / fx_rate if fx_rate > 0 else 0
    freight_cny = weight_kg * freight_rate
    freight_zar = freight_cny / fx_rate if fx_rate > 0 else 0
    commission_zar = selling_price_zar * commission_rate
    vat_zar = selling_price_zar * vat_rate / (1 + vat_rate)

    total_cost_zar = cost_zar + freight_zar + commission_zar + vat_zar
    profit_zar = selling_price_zar - total_cost_zar
    margin_rate = (profit_zar / selling_price_zar * 100) if selling_price_zar > 0 else 0

    # Suggested price for target margin
    target_margin = float(body.get("target_margin", settings.target_margin_rate))
    if target_margin < 1:
        target_margin *= 100  # Convert to percentage

    suggested_price = 0
    denominator = 1 - commission_rate - vat_rate / (1 + vat_rate) - target_margin / 100
    if denominator > 0:
        suggested_price = (cost_zar + freight_zar) / denominator

    return {
        "ok": True,
        "selling_price_zar": round(selling_price_zar, 2),
        "cost_cny": round(cost_cny, 2),
        "cost_zar": round(cost_zar, 2),
        "freight_cny": round(freight_cny, 2),
        "freight_zar": round(freight_zar, 2),
        "commission_zar": round(commission_zar, 2),
        "vat_zar": round(vat_zar, 2),
        "total_cost_zar": round(total_cost_zar, 2),
        "profit_zar": round(profit_zar, 2),
        "margin_rate": round(margin_rate, 2),
        "suggested_price_zar": round(suggested_price, 2),
        "fx_rate": fx_rate,
        "weight_kg": weight_kg,
    }
