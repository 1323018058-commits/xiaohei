from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.modules.common.dev_state import app_state
from src.platform.settings.base import settings

from .schemas import (
    DashboardChartPoint,
    DashboardContextResponse,
    DashboardOrderDataStatus,
    DashboardSummaryResponse,
)


class DashboardService:
    def get_context(self, actor: dict[str, Any]) -> DashboardContextResponse:
        business_timezone = _safe_zone_name(settings.dashboard_business_timezone)
        viewer_timezone = _safe_zone_name(settings.dashboard_viewer_timezone)
        now_utc = datetime.now(UTC)
        actor_entitlement = _safe_entitlement(actor.get("tenant_id"))

        return DashboardContextResponse(
            business_timezone=business_timezone,
            viewer_timezone=viewer_timezone,
            business_now=now_utc.astimezone(ZoneInfo(business_timezone)),
            viewer_now=now_utc.astimezone(ZoneInfo(viewer_timezone)),
            plan_name=actor_entitlement.get("plan_name") if actor_entitlement else None,
            subscription_status=(
                actor_entitlement.get("subscription_status")
                if actor_entitlement
                else actor.get("subscription_status")
            ),
            zar_cny_rate=max(0, float(settings.dashboard_zar_cny_rate)),
        )

    def get_summary(self, actor: dict[str, Any]) -> DashboardSummaryResponse:
        business_timezone = _safe_zone_name(settings.dashboard_business_timezone)
        viewer_timezone = _safe_zone_name(settings.dashboard_viewer_timezone)
        business_zone = ZoneInfo(business_timezone)
        viewer_zone = ZoneInfo(viewer_timezone)
        now_utc = datetime.now(UTC)
        business_now = now_utc.astimezone(business_zone)
        viewer_now = now_utc.astimezone(viewer_zone)
        business_day_start = datetime.combine(
            business_now.date(),
            time.min,
            business_zone,
        ).astimezone(UTC)
        business_day_end = business_day_start + timedelta(days=1)
        chart_30d_start = business_day_start - timedelta(days=29)
        tenant_id = None if actor["role"] == "super_admin" else actor["tenant_id"]
        actor_entitlement = _safe_entitlement(actor.get("tenant_id"))

        metrics = app_state.get_dashboard_metrics(
            tenant_id=tenant_id,
            business_timezone=business_timezone,
            business_day_start=business_day_start,
            business_day_end=business_day_end,
            chart_start=chart_30d_start,
            chart_end=business_day_end,
        )
        chart_30d = _chart_buckets(
            metrics["chart_points"],
            business_day_start=business_day_start,
            days=30,
            business_zone=business_zone,
        )
        chart_7d = chart_30d[-7:]
        stale_after_minutes = max(1, settings.dashboard_order_sync_stale_minutes)
        order_status = _build_order_data_status(
            last_order_sync_at=metrics["last_order_sync_at"],
            latest_order_sync_at=metrics["latest_order_sync_at"],
            latest_order_sync_status=metrics["latest_order_sync_status"],
            latest_order_sync_error_code=metrics["latest_order_sync_error_code"],
            latest_order_sync_error_msg=metrics["latest_order_sync_error_msg"],
            newest_order_at=metrics["newest_order_at"],
            now_utc=now_utc,
            stale_after_minutes=stale_after_minutes,
        )

        return DashboardSummaryResponse(
            business_timezone=business_timezone,
            viewer_timezone=viewer_timezone,
            business_date=business_now.date().isoformat(),
            business_now=business_now,
            viewer_now=viewer_now,
            plan_name=actor_entitlement.get("plan_name") if actor_entitlement else None,
            subscription_status=(
                actor_entitlement.get("subscription_status")
                if actor_entitlement
                else actor.get("subscription_status")
            ),
            zar_cny_rate=max(0, float(settings.dashboard_zar_cny_rate)),
            business_day_start_utc=business_day_start,
            business_day_end_utc=business_day_end,
            today_order_count=int(metrics["today_order_count"]),
            today_sales_quantity=int(metrics["today_sales_quantity"]),
            today_sales_total=float(metrics["today_sales_total"] or 0),
            today_listing_success_count=int(metrics["today_listing_success_count"]),
            today_listing_failed_count=int(metrics["today_listing_failed_count"]),
            chart_7d=[DashboardChartPoint(**point) for point in chart_7d],
            chart_30d=[DashboardChartPoint(**point) for point in chart_30d],
            order_data_status=order_status,
        )


def _safe_zone_name(value: str) -> str:
    try:
        ZoneInfo(value)
        return value
    except ZoneInfoNotFoundError:
        return "UTC"


def _safe_entitlement(tenant_id: str | None) -> dict[str, Any] | None:
    if not tenant_id:
        return None
    try:
        return app_state.get_tenant_entitlement(tenant_id)
    except Exception:
        return None


def _chart_buckets(
    source_points: list[dict[str, Any]],
    *,
    business_day_start: datetime,
    days: int,
    business_zone: ZoneInfo,
) -> list[dict[str, Any]]:
    by_date = {
        str(point["date"]): {
            "sales": float(point["sales"] or 0),
            "volume": int(point["volume"] or 0),
        }
        for point in source_points
    }
    buckets: list[dict[str, Any]] = []

    for offset in range(days - 1, -1, -1):
        current_utc = business_day_start - timedelta(days=offset)
        local_date = current_utc.astimezone(business_zone).date()
        key = local_date.isoformat()
        value = by_date.get(key, {"sales": 0, "volume": 0})
        buckets.append(
            {
                "date": f"{local_date.month:02d}-{local_date.day:02d}",
                "sales": round(float(value["sales"]), 2),
                "volume": int(value["volume"]),
            }
        )

    return buckets


def _build_order_data_status(
    *,
    last_order_sync_at: datetime | None,
    latest_order_sync_at: datetime | None,
    latest_order_sync_status: str | None,
    latest_order_sync_error_code: str | None,
    latest_order_sync_error_msg: str | None,
    newest_order_at: datetime | None,
    now_utc: datetime,
    stale_after_minutes: int,
) -> DashboardOrderDataStatus:
    last_success_is_fresh = (
        last_order_sync_at is not None
        and now_utc - _as_utc(last_order_sync_at) <= timedelta(minutes=stale_after_minutes)
    )
    latest_failed = latest_order_sync_status not in {None, "succeeded"} and (
        last_order_sync_at is None
        or (
            latest_order_sync_at is not None
            and _as_utc(latest_order_sync_at) >= _as_utc(last_order_sync_at)
        )
    )
    is_stale = not last_success_is_fresh

    if last_order_sync_at is None:
        message = "订单数据正在后台初始化，首页会在同步完成后自动更新。"
    elif not is_stale:
        message = "订单数据已按最近一次后台同步统计。"
    elif latest_failed:
        message = "订单数据正在后台重试，首页会在同步完成后自动更新。"
    else:
        message = f"订单数据超过 {stale_after_minutes} 分钟未更新，系统会自动补齐。"

    return DashboardOrderDataStatus(
        last_order_sync_at=last_order_sync_at,
        latest_order_sync_at=latest_order_sync_at,
        latest_order_sync_status=latest_order_sync_status,
        latest_order_sync_error_code=latest_order_sync_error_code,
        latest_order_sync_error_msg=latest_order_sync_error_msg,
        newest_order_at=newest_order_at,
        stale_after_minutes=stale_after_minutes,
        is_stale=is_stale,
        message=message,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
