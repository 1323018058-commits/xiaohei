from datetime import datetime

from pydantic import BaseModel


class DashboardChartPoint(BaseModel):
    date: str
    sales: float
    volume: int


class DashboardOrderDataStatus(BaseModel):
    last_order_sync_at: datetime | None
    latest_order_sync_at: datetime | None
    latest_order_sync_status: str | None
    latest_order_sync_error_code: str | None
    latest_order_sync_error_msg: str | None
    newest_order_at: datetime | None
    stale_after_minutes: int
    is_stale: bool
    message: str


class DashboardContextResponse(BaseModel):
    business_timezone: str
    viewer_timezone: str
    business_now: datetime
    viewer_now: datetime
    plan_name: str | None
    subscription_status: str | None
    zar_cny_rate: float


class DashboardSummaryResponse(BaseModel):
    business_timezone: str
    viewer_timezone: str
    business_date: str
    business_now: datetime
    viewer_now: datetime
    plan_name: str | None
    subscription_status: str | None
    zar_cny_rate: float
    business_day_start_utc: datetime
    business_day_end_utc: datetime
    today_order_count: int
    today_sales_quantity: int
    today_sales_total: float
    today_listing_success_count: int
    today_listing_failed_count: int
    chart_7d: list[DashboardChartPoint]
    chart_30d: list[DashboardChartPoint]
    order_data_status: DashboardOrderDataStatus
