from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


BUYBOX_FETCH_RETRIES = 3
BUYBOX_FETCH_BACKOFF_SECONDS = 1.0
GLOBAL_BUYBOX_BUDGET_PER_MINUTE = 3000
STORE_BUYBOX_BUDGET_PER_MINUTE = 120
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def utcnow() -> datetime:
    return datetime.now(UTC)


def subscription_weight(plan: str | None) -> int:
    normalized = str(plan or "").strip().lower()
    if normalized in {"quarterly", "season", "seasonal", "scale", "war-room", "季付"}:
        return 3
    return 1


def calculate_cycle_limit(store_weight: int, active_store_count: int) -> int:
    active_store_count = max(1, active_store_count)
    fair_share = GLOBAL_BUYBOX_BUDGET_PER_MINUTE // active_store_count
    weighted = fair_share * max(1, store_weight)
    return max(20, min(STORE_BUYBOX_BUDGET_PER_MINUTE, weighted))


def next_check_delay_minutes(
    last_action: str | None,
    plan: str | None,
    fail_count: int = 0,
) -> int:
    if fail_count <= 0:
        if subscription_weight(plan) >= 3:
            return 15 if last_action in {"raised", "lowered", "floor"} else 30
        return 30 if last_action in {"raised", "lowered", "floor"} else 60

    if fail_count == 1:
        return 5
    if fail_count == 2:
        return 15
    if fail_count == 3:
        return 60
    return 360


def next_check_at(
    *,
    last_action: str | None,
    plan: str | None,
    fail_count: int = 0,
    now: datetime | None = None,
) -> datetime:
    base = now or utcnow()
    return base + timedelta(
        minutes=next_check_delay_minutes(last_action, plan, fail_count)
    )


def is_retryable_buybox_error(result: dict[str, Any]) -> bool:
    status_code = result.get("status_code")
    if status_code in RETRYABLE_STATUS_CODES:
        return True
    if status_code in {400, 404}:
        return False

    error = str(result.get("error") or "").lower()
    if not error:
        return False
    if "not found" in error or "empty plid" in error:
        return False
    if any(f"http {code}" in error for code in RETRYABLE_STATUS_CODES):
        return True
    return any(
        marker in error
        for marker in ("timeout", "timed out", "connection", "network", "rate limit")
    )


def decide_reprice(
    *,
    current: float,
    floor: float,
    buybox: float,
    owns_buybox: bool,
    next_offer_price: float | None = None,
) -> tuple[str, int | None]:
    if current <= 0 or floor <= 0 or buybox <= 0:
        return "unchanged", None

    if current < floor:
        return "floor", int(floor)

    if owns_buybox:
        if next_offer_price and next_offer_price > current:
            candidate = int(next_offer_price) - 1
            if candidate > current and candidate >= floor:
                return "raised", candidate
        return "unchanged", None

    if buybox < current:
        candidate = int(buybox) - 1
        if candidate <= 0:
            return "unchanged", None
        if candidate < floor:
            return "floor", int(floor)
        return "lowered", candidate

    if buybox == current:
        candidate = int(current) - 1
        if candidate >= floor and candidate > 0:
            return "lowered", candidate
        return "unchanged", None

    candidate = int(buybox) - 1
    if candidate > current and candidate >= floor:
        return "raised", candidate
    return "unchanged", None
