from __future__ import annotations


ORDER_STATUS_PREPARING = "preparing"
ORDER_STATUS_SHIPPED = "shipped"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUS_RETURNED = "returned"
ORDER_STATUS_UNKNOWN = "unknown"

ORDER_STATUS_LABELS = {
    ORDER_STATUS_PREPARING: "Preparing",
    ORDER_STATUS_SHIPPED: "Shipped",
    ORDER_STATUS_CANCELLED: "Cancelled",
    ORDER_STATUS_RETURNED: "Returned",
    ORDER_STATUS_UNKNOWN: "Unknown",
}


def normalize_takealot_order_status(raw_status: str | None) -> str:
    status = (raw_status or "").strip().lower()
    if not status:
        return ORDER_STATUS_UNKNOWN
    if "cancel" in status:
        return ORDER_STATUS_CANCELLED
    if "return" in status or "refund" in status:
        return ORDER_STATUS_RETURNED
    if "ship" in status or "delivered" in status or "complete" in status:
        return ORDER_STATUS_SHIPPED
    if (
        "prepar" in status
        or "customer" in status
        or "collect" in status
        or "ready" in status
        or "lead time" in status
        or status.startswith("new")
    ):
        return ORDER_STATUS_PREPARING
    return ORDER_STATUS_UNKNOWN
