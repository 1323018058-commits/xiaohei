import re
import time
from typing import Any

import httpx

from fastapi import HTTPException, status

from src.modules.admin.service import get_request_id
from src.modules.common.dev_state import app_state
from src.modules.common.tenant_scope import require_tenant_access
from src.modules.store.adapters import AdapterAuthError, AdapterCredentials, TakealotAdapter
from src.platform.settings.base import settings

from .engine import (
    BUYBOX_FETCH_BACKOFF_SECONDS,
    BUYBOX_FETCH_RETRIES,
    calculate_cycle_limit,
    decide_reprice,
    is_retryable_buybox_error,
    next_check_at,
    subscription_weight,
    utcnow,
)
from .schemas import (
    BiddingCycleItemResponse,
    BiddingCycleRequest,
    BiddingCycleResponse,
    BiddingRuleListResponse,
    BiddingRuleLogListResponse,
    BiddingRuleResponse,
    BiddingStoreStatusResponse,
    BulkImportBiddingRuleItem,
    BulkImportBiddingRuleResponse,
    UpdateBiddingRuleRequest,
)


DETAIL_URL = "https://api.takealot.com/rest/v-1-16-0/product-details/{identifier}"
PUBLIC_HEADERS = {
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class BiddingService:
    def status(
        self,
        *,
        actor: dict[str, Any],
        store_id: str,
    ) -> BiddingStoreStatusResponse:
        store = self._require_store(store_id, actor)
        return self._to_store_status_response(
            store=store,
            summary=self._store_summary(store_id),
            runtime=self._store_runtime(store_id),
        )

    def start_store(
        self,
        *,
        actor: dict[str, Any],
        store_id: str,
        request_headers: dict[str, str],
    ) -> BiddingStoreStatusResponse:
        store = self._require_store(store_id, actor)
        runtime = self._update_store_runtime(
            store_id=store_id,
            is_running=True,
            last_started_at=utcnow(),
        )
        self._append_store_runtime_audit(
            store=store,
            actor=actor,
            request_headers=request_headers,
            action="START_AUTOBID_STORE",
            label="Start automatic bidding worker for store",
            after={"is_running": True},
        )
        return self._to_store_status_response(
            store=store,
            summary=self._store_summary(store_id),
            runtime=runtime or self._store_runtime(store_id),
        )

    def stop_store(
        self,
        *,
        actor: dict[str, Any],
        store_id: str,
        request_headers: dict[str, str],
    ) -> BiddingStoreStatusResponse:
        store = self._require_store(store_id, actor)
        runtime = self._update_store_runtime(
            store_id=store_id,
            is_running=False,
            last_stopped_at=utcnow(),
        )
        self._append_store_runtime_audit(
            store=store,
            actor=actor,
            request_headers=request_headers,
            action="STOP_AUTOBID_STORE",
            label="Pause automatic bidding worker for store",
            after={"is_running": False},
        )
        return self._to_store_status_response(
            store=store,
            summary=self._store_summary(store_id),
            runtime=runtime or self._store_runtime(store_id),
        )

    def list_rules(
        self,
        *,
        actor: dict[str, Any],
        store_id: str,
        sku_query: str | None = None,
    ) -> BiddingRuleListResponse:
        self._require_store(store_id, actor)
        return BiddingRuleListResponse(
            rules=[
                self._to_rule_response(rule)
                for rule in app_state.list_bidding_rules(
                    store_id=store_id,
                    sku_query=sku_query,
                )
            ]
        )

    def list_log(
        self,
        *,
        actor: dict[str, Any],
        store_id: str,
    ) -> BiddingRuleLogListResponse:
        self._require_store(store_id, actor)
        rules = app_state.list_bidding_rules(store_id=store_id)
        rules.sort(
            key=lambda item: item.get("last_reprice_at") or item.get("updated_at"),
            reverse=True,
        )
        return BiddingRuleLogListResponse(
            rules=[self._to_rule_response(rule) for rule in rules[:200]]
        )

    def run_cycle(
        self,
        *,
        actor: dict[str, Any],
        store_id: str,
        payload: BiddingCycleRequest,
        request_headers: dict[str, str],
        cycle_source: str = "manual",
    ) -> BiddingCycleResponse:
        store = self._require_store(store_id, actor)
        plan = self._store_plan(store)
        limit = min(payload.limit, self._cycle_limit(plan))
        effective_dry_run = payload.dry_run or not settings.autobid_real_write_enabled
        candidate_loader = getattr(app_state, "list_bidding_cycle_candidates", None)
        if candidate_loader is None:
            candidates = []
        else:
            candidates = candidate_loader(
                store_id=store_id,
                limit=limit,
                now=utcnow(),
            )

        items: list[BiddingCycleItemResponse] = []
        for candidate in candidates:
            item = self._process_cycle_candidate(
                store=store,
                plan=plan,
                rule=candidate["rule"],
                listing=candidate.get("listing"),
                dry_run=effective_dry_run,
                actor=actor,
                request_headers=request_headers,
            )
            items.append(item)

        response = BiddingCycleResponse(
            store_id=store_id,
            dry_run=effective_dry_run,
            real_write_enabled=settings.autobid_real_write_enabled,
            processed_count=len(items),
            suggested_count=sum(1 for item in items if item.suggested_price is not None),
            applied_count=sum(1 for item in items if item.applied_price is not None),
            skipped_count=sum(1 for item in items if item.status == "skipped"),
            failed_count=sum(1 for item in items if item.status == "failed"),
            items=items,
        )
        cycle_updates: dict[str, Any] = {
            "last_cycle_summary": {
                "source": cycle_source,
                "dry_run": response.dry_run,
                "processed_count": response.processed_count,
                "suggested_count": response.suggested_count,
                "applied_count": response.applied_count,
                "skipped_count": response.skipped_count,
                "failed_count": response.failed_count,
            },
        }
        if cycle_source == "worker":
            cycle_updates["last_worker_cycle_at"] = utcnow()
        else:
            cycle_updates["last_manual_cycle_at"] = utcnow()
        self._update_store_runtime(store_id=store_id, **cycle_updates)
        return response

    def process_due_store_cycles(
        self,
        *,
        dry_run: bool = True,
        limit_per_store: int | None = None,
    ) -> list[dict[str, Any]]:
        actor = {
            "id": None,
            "role": "super_admin",
            "tenant_id": None,
        }
        cycle_summaries: list[dict[str, Any]] = []
        remaining_budget = max(1, int(settings.autobid_worker_global_cycle_limit))
        eligible_stores: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for store in self._eligible_bidding_stores():
            runtime = self._store_runtime(store["id"])
            if not runtime.get("is_running"):
                continue
            eligible_stores.append((store, runtime))
        eligible_stores.sort(
            key=lambda item: (
                item[1].get("last_worker_cycle_at") is not None,
                item[1].get("last_worker_cycle_at") or utcnow(),
            )
        )

        for store, _runtime in eligible_stores:
            if remaining_budget <= 0:
                break
            summary_getter = getattr(app_state, "bidding_runtime_summary", None)
            if summary_getter is None:
                continue
            runtime_summary = summary_getter(store_id=store["id"])
            due_rule_count = int(runtime_summary.get("due_rule_count") or 0)
            if due_rule_count <= 0:
                continue
            requested_limit = min(
                remaining_budget,
                500,
                due_rule_count,
                max(1, int(limit_per_store or settings.autobid_cycle_default_limit)),
            )
            try:
                result = self.run_cycle(
                    actor=actor,
                    store_id=store["id"],
                    payload=BiddingCycleRequest(dry_run=dry_run, limit=requested_limit),
                    request_headers={},
                    cycle_source="worker",
                )
                remaining_budget -= max(1, result.processed_count)
                cycle_summaries.append(
                    {
                        "store_id": result.store_id,
                        "status": "succeeded",
                        "dry_run": result.dry_run,
                        "processed_count": result.processed_count,
                        "suggested_count": result.suggested_count,
                        "applied_count": result.applied_count,
                        "skipped_count": result.skipped_count,
                        "failed_count": result.failed_count,
                    }
                )
            except Exception as exc:
                remaining_budget -= max(1, requested_limit)
                cycle_summaries.append(
                    {
                        "store_id": store["id"],
                        "status": "failed",
                        "dry_run": dry_run,
                        "processed_count": 0,
                        "suggested_count": 0,
                        "applied_count": 0,
                        "skipped_count": 0,
                        "failed_count": 1,
                        "error": str(exc)[:500],
                    }
                )
        return cycle_summaries

    def update_rule(
        self,
        *,
        rule_id: str,
        payload: UpdateBiddingRuleRequest,
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> BiddingRuleResponse:
        before = self._require_rule(rule_id, actor)
        changes = payload.model_dump(exclude_unset=True)
        if "floor_price" in changes:
            self._validate_floor_price(changes["floor_price"])

        effective_is_active = changes.get("is_active", before.get("is_active"))
        if effective_is_active:
            effective_floor_price = changes.get("floor_price", before.get("floor_price"))
            self._validate_required_floor_price(effective_floor_price)

        updated = app_state.update_bidding_rule(rule_id, **changes)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bidding rule not found",
            )
        if "floor_price" in changes and before["floor_price"] != updated["floor_price"]:
            self._append_floor_price_audit(
                rule=updated,
                actor=actor,
                request_headers=request_headers,
                old_price=before["floor_price"],
                new_price=updated["floor_price"],
                reason="single rule edit",
            )
        return self._to_rule_response(updated)

    def bulk_import(
        self,
        *,
        store_id: str,
        items: list[BulkImportBiddingRuleItem],
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> BulkImportBiddingRuleResponse:
        self._require_store(store_id, actor)
        imported_rules: list[dict[str, Any]] = []
        created_count = 0
        updated_count = 0
        existing_rules = {
            rule["sku"]: rule
            for rule in app_state.list_bidding_rules(store_id=store_id)
        }
        valid_listing_by_sku = self._valid_bidding_listing_by_sku(store_id)
        invalid_skus: list[str] = []
        disabled_skus: list[str] = []

        for item in items:
            self._validate_required_floor_price(item.floor_price)
            listing = valid_listing_by_sku.get(item.sku)
            if listing is None:
                exact_listing = self._find_listing_by_sku(store_id, item.sku)
                if exact_listing is None:
                    invalid_skus.append(item.sku)
                else:
                    disabled_skus.append(item.sku)

        if invalid_skus or disabled_skus:
            problems: list[str] = []
            if invalid_skus:
                problems.append(f"未同步到当前店铺商品：{', '.join(invalid_skus[:8])}")
            if disabled_skus:
                problems.append(f"不是可竞价商品：{', '.join(disabled_skus[:8])}")
            if len(invalid_skus) > 8 or len(disabled_skus) > 8:
                problems.append("其余 SKU 请检查导入文件")
            raise ValueError("导入失败，存在无法匹配的 SKU。" + "；".join(problems))

        for item in items:
            existing_rule = existing_rules.get(item.sku)
            listing = valid_listing_by_sku[item.sku]
            rule, before = app_state.upsert_bidding_rule(
                store_id=store_id,
                sku=item.sku,
                listing_id=listing["id"],
                floor_price=item.floor_price,
                strategy_type="manual",
                is_active=bool(existing_rule.get("is_active")) if existing_rule else False,
            )
            existing_rules[item.sku] = rule
            imported_rules.append(rule)
            if before is None:
                created_count += 1
            else:
                updated_count += 1
            if before is None or before["floor_price"] != rule["floor_price"]:
                self._append_floor_price_audit(
                    rule=rule,
                    actor=actor,
                    request_headers=request_headers,
                    old_price=before["floor_price"] if before else None,
                    new_price=rule["floor_price"],
                    reason="bulk floor price import",
                )

        return BulkImportBiddingRuleResponse(
            imported_count=len(imported_rules),
            created_count=created_count,
            updated_count=updated_count,
            rules=[self._to_rule_response(rule) for rule in imported_rules],
        )

    def upsert_rule_from_guardrail(
        self,
        *,
        store_id: str,
        sku: str,
        listing_id: str | None,
        floor_price: float,
        actor: dict[str, Any],
        request_id: str,
        reason: str,
    ) -> dict[str, Any]:
        store = self._require_store(store_id, actor)
        self._validate_floor_price(floor_price)
        rule, before = app_state.upsert_bidding_rule(
            store_id=store_id,
            sku=sku,
            listing_id=listing_id,
            floor_price=floor_price,
            strategy_type="guarded",
            is_active=True,
        )
        if before is None or before["floor_price"] != rule["floor_price"]:
            app_state.append_audit(
                request_id=request_id,
                tenant_id=store["tenant_id"],
                store_id=store_id,
                actor_user_id=actor.get("id"),
                actor_role=actor.get("role"),
                action="UPSERT_BIDDING_RULE_FROM_GUARDRAIL",
                action_label="Hydrate bidding rule from protected floor",
                risk_level="high",
                target_type="bidding_rule",
                target_id=rule["id"],
                target_label=rule["sku"],
                before={"floor_price": before["floor_price"] if before else None},
                after={"floor_price": rule["floor_price"], "listing_id": rule["listing_id"]},
                reason=reason,
                result="success",
                task_id=None,
                metadata={
                    "source": "guardrail",
                    "operator_id": actor.get("id"),
                    "details": {
                        "old_price": before["floor_price"] if before else None,
                        "new_price": rule["floor_price"],
                    },
                },
            )
        return rule

    def _process_cycle_candidate(
        self,
        *,
        store: dict[str, Any],
        plan: str | None,
        rule: dict[str, Any],
        listing: dict[str, Any] | None,
        dry_run: bool,
        actor: dict[str, Any],
        request_headers: dict[str, str],
    ) -> BiddingCycleItemResponse:
        del request_headers
        now = utcnow()
        offer_id = self._extract_offer_id(rule, listing)
        plid = self._extract_plid(listing)
        tsin = self._extract_tsin(listing)
        current_price = self._numeric(listing.get("platform_price") if listing else None)
        floor_price = self._numeric(rule.get("floor_price"))

        if not listing:
            return self._skip_rule(
                rule=rule,
                plan=plan,
                offer_id=offer_id,
                plid=plid,
                tsin=tsin,
                reason="listing_missing",
                message="SKU has no synced listing",
                dry_run=dry_run,
                floor_price=floor_price,
            )
        if not offer_id:
            return self._skip_rule(
                rule=rule,
                plan=plan,
                offer_id=None,
                plid=plid,
                tsin=tsin,
                reason="missing_offer_id",
                message="Listing has no offer_id",
                dry_run=dry_run,
                current_price=current_price,
                floor_price=floor_price,
            )

        if not tsin:
            listing = self._hydrate_listing_identity(
                store=store,
                listing=listing,
                offer_id=offer_id,
            )
            plid = self._extract_plid(listing) or plid
            tsin = self._extract_tsin(listing) or tsin
            current_price = self._numeric(listing.get("platform_price") if listing else None)

        if not plid:
            return self._skip_rule(
                rule=rule,
                plan=plan,
                offer_id=offer_id,
                plid=None,
                tsin=tsin,
                reason="missing_plid",
                message="Listing has no PLID",
                dry_run=dry_run,
                current_price=current_price,
                floor_price=floor_price,
            )
        if current_price is None or current_price <= 0 or floor_price is None or floor_price <= 0:
            return self._skip_rule(
                rule=rule,
                plan=plan,
                offer_id=offer_id,
                plid=plid,
                tsin=tsin,
                reason="missing_price",
                message="Current price or floor price is missing",
                dry_run=dry_run,
                current_price=current_price,
                floor_price=floor_price,
            )

        variant_hint = self._extract_variant_hint(listing)
        detail = self._fetch_buybox_with_retry(
            plid=plid,
            tsin=tsin,
            variant_hint=variant_hint,
        )
        if not detail.get("ok"):
            fail_count = int(rule.get("buybox_fetch_fail_count") or 0) + 1
            error = str(detail.get("error") or "BuyBox refresh failed")[:500]
            retryable = is_retryable_buybox_error(detail)
            status_value = "retrying" if retryable else "blocked"
            self._update_runtime(
                rule["id"],
                buybox_fetch_fail_count=fail_count,
                buybox_last_error=error,
                buybox_status=status_value,
                repricing_blocked_reason="" if retryable else "buybox_refresh_failed",
                last_action="buybox_refresh_failed",
                last_cycle_dry_run=dry_run,
                last_cycle_error=error,
                next_check_at=next_check_at(
                    last_action="buybox_refresh_failed",
                    plan=plan,
                    fail_count=fail_count,
                    now=now,
                ),
                buybox_next_retry_at=next_check_at(
                    last_action="buybox_refresh_failed",
                    plan=plan,
                    fail_count=fail_count,
                    now=now,
                ),
            )
            return BiddingCycleItemResponse(
                rule_id=rule["id"],
                sku=rule["sku"],
                offer_id=offer_id,
                plid=plid,
                action="buybox_refresh_failed",
                current_price=current_price,
                floor_price=floor_price,
                dry_run=dry_run,
                status="failed" if retryable else "skipped",
                reason=error,
            )

        buybox = self._parse_buybox_detail(
            detail["payload"],
            offer_id=offer_id,
            tsin=tsin,
            detail_identifier=detail.get("identifier"),
            variant_matched=bool(detail.get("variant_matched")),
            current_price=current_price,
        )
        if not buybox["trusted"]:
            return self._skip_rule(
                rule=rule,
                plan=plan,
                offer_id=offer_id,
                plid=plid,
                tsin=tsin,
                reason="offer_match_untrusted",
                message="Offer id/TSIN was not found in fresh BuyBox detail",
                dry_run=dry_run,
                current_price=current_price,
                floor_price=floor_price,
                buybox_price=buybox["buybox_price"],
                next_offer_price=buybox["next_offer_price"],
            )
        if buybox["buybox_price"] is None:
            return self._skip_rule(
                rule=rule,
                plan=plan,
                offer_id=offer_id,
                plid=plid,
                tsin=tsin,
                reason="missing_buybox_price",
                message="Fresh BuyBox has no usable price",
                dry_run=dry_run,
                current_price=current_price,
                floor_price=floor_price,
            )

        if not buybox["ownership_known"] and buybox["buybox_price"] >= current_price:
            action, suggested_price = "unchanged", None
        else:
            action, suggested_price = decide_reprice(
                current=current_price,
                floor=floor_price,
                buybox=buybox["buybox_price"],
                owns_buybox=buybox["owns_buybox"],
                next_offer_price=buybox["next_offer_price"],
            )
        last_decision = {
            "action": action,
            "current_price": current_price,
            "floor_price": floor_price,
            "buybox_price": buybox["buybox_price"],
            "next_offer_price": buybox["next_offer_price"],
            "owns_buybox": buybox["owns_buybox"],
            "ownership_known": buybox["ownership_known"],
            "offer_id": offer_id,
            "plid": plid,
            "tsin": tsin,
            "detail_identifier": detail.get("identifier"),
            "variant_hint": variant_hint,
            "variant_url": detail.get("variant_url"),
            "matched_ids": sorted(buybox["matched_ids"]),
            "dry_run": dry_run,
        }
        runtime_updates = {
            "buybox_fetch_fail_count": 0,
            "buybox_last_error": "",
            "buybox_last_success_at": now,
            "buybox_next_retry_at": None,
            "buybox_status": "fresh",
            "repricing_blocked_reason": "",
            "last_action": action,
            "last_reprice_at": now,
            "last_suggested_price": suggested_price,
            "last_applied_price": None,
            "last_buybox_price": buybox["buybox_price"],
            "last_next_offer_price": buybox["next_offer_price"],
            "last_cycle_dry_run": dry_run,
            "last_cycle_error": "",
            "last_decision": last_decision,
            "next_check_at": next_check_at(last_action=action, plan=plan, now=now),
        }

        applied_price: float | None = None
        status_value = "suggested" if suggested_price is not None else "skipped"
        reason = "" if suggested_price is not None else "No price change needed"
        if suggested_price is not None and not dry_run:
            try:
                self._apply_offer_price(
                    store=store,
                    listing=listing,
                    offer_id=offer_id,
                    new_price=suggested_price,
                )
                applied_price = float(suggested_price)
                runtime_updates["last_applied_price"] = applied_price
                runtime_updates["last_cycle_error"] = ""
                status_value = "applied"
                reason = ""
                try:
                    self._append_reprice_audit(
                        store=store,
                        rule=rule,
                        actor=actor,
                        old_price=current_price,
                        new_price=applied_price,
                        decision=last_decision,
                    )
                except Exception as audit_exc:
                    audit_error = str(audit_exc)[:300]
                    last_decision["audit_error"] = audit_error
                    runtime_updates["last_cycle_error"] = f"audit_log_failed_after_apply: {audit_error}"
            except Exception as exc:
                runtime_updates["last_action"] = "api_error"
                runtime_updates["last_cycle_error"] = str(exc)[:500]
                runtime_updates["next_check_at"] = next_check_at(
                    last_action="api_error",
                    plan=plan,
                    fail_count=1,
                    now=now,
                )
                status_value = "failed"
                reason = str(exc)

        self._update_runtime(rule["id"], **runtime_updates)
        return BiddingCycleItemResponse(
            rule_id=rule["id"],
            sku=rule["sku"],
            offer_id=offer_id,
            plid=plid,
            action=action,
            current_price=current_price,
            floor_price=floor_price,
            buybox_price=buybox["buybox_price"],
            next_offer_price=buybox["next_offer_price"],
            suggested_price=float(suggested_price) if suggested_price is not None else None,
            applied_price=applied_price,
            owns_buybox=buybox["owns_buybox"],
            dry_run=dry_run,
            status=status_value,
            reason=reason,
        )

    def _skip_rule(
        self,
        *,
        rule: dict[str, Any],
        plan: str | None,
        offer_id: str | None,
        plid: str | None,
        tsin: str | None,
        reason: str,
        message: str,
        dry_run: bool,
        current_price: float | None = None,
        floor_price: float | None = None,
        buybox_price: float | None = None,
        next_offer_price: float | None = None,
    ) -> BiddingCycleItemResponse:
        now = utcnow()
        self._update_runtime(
            rule["id"],
            buybox_status="blocked" if reason in {"missing_plid", "missing_offer_id", "offer_match_untrusted"} else "idle",
            repricing_blocked_reason=reason,
            last_action=reason,
            last_reprice_at=now,
            last_suggested_price=None,
            last_applied_price=None,
            last_buybox_price=buybox_price,
            last_next_offer_price=next_offer_price,
            last_cycle_dry_run=dry_run,
            last_cycle_error=message,
            last_decision={
                "action": reason,
                "offer_id": offer_id,
                "plid": plid,
                "tsin": tsin,
                "reason": message,
                "dry_run": dry_run,
            },
            next_check_at=next_check_at(last_action=reason, plan=plan, fail_count=1, now=now),
        )
        return BiddingCycleItemResponse(
            rule_id=rule["id"],
            sku=rule["sku"],
            offer_id=offer_id,
            plid=plid,
            action=reason,
            current_price=current_price,
            floor_price=floor_price,
            buybox_price=buybox_price,
            next_offer_price=next_offer_price,
            dry_run=dry_run,
            status="skipped",
            reason=message,
        )

    def _fetch_buybox_with_retry(
        self,
        *,
        plid: str,
        tsin: str | None,
        variant_hint: str | None,
    ) -> dict[str, Any]:
        identifiers = self._detail_identifiers(plid=plid, tsin=tsin)
        if not identifiers:
            return {"ok": False, "error": "Empty PLID/TSIN", "attempts": 0}

        last_result: dict[str, Any] = {}
        with httpx.Client(
            headers=PUBLIC_HEADERS,
            timeout=settings.autobid_buybox_timeout_seconds,
            follow_redirects=True,
        ) as client:
            for identifier in identifiers:
                for attempt in range(1, BUYBOX_FETCH_RETRIES + 1):
                    try:
                        response = client.get(DETAIL_URL.format(identifier=identifier))
                        if response.status_code == 200:
                            payload = response.json()
                            if isinstance(payload, dict) and payload.get("buybox"):
                                variant_payload = self._fetch_variant_payload(
                                    client=client,
                                    payload=payload,
                                    variant_hint=variant_hint,
                                )
                                if variant_payload:
                                    return {
                                        "ok": True,
                                        "payload": variant_payload["payload"],
                                        "attempts": attempt,
                                        "identifier": identifier,
                                        "variant_url": variant_payload["url"],
                                        "variant_matched": True,
                                    }
                                return {
                                    "ok": True,
                                    "payload": payload,
                                    "attempts": attempt,
                                    "identifier": identifier,
                                    "variant_matched": not self._is_summary_buybox(payload),
                                }
                            last_result = {
                                "ok": False,
                                "status_code": response.status_code,
                                "error": "BuyBox payload missing",
                                "attempts": attempt,
                                "identifier": identifier,
                            }
                        else:
                            last_result = {
                                "ok": False,
                                "status_code": response.status_code,
                                "error": f"HTTP {response.status_code}: {response.text[:300]}",
                                "attempts": attempt,
                                "identifier": identifier,
                            }
                    except (httpx.HTTPError, ValueError) as exc:
                        last_result = {
                            "ok": False,
                            "error": str(exc),
                            "attempts": attempt,
                            "identifier": identifier,
                        }
                    if not is_retryable_buybox_error(last_result):
                        break
                    time.sleep(BUYBOX_FETCH_BACKOFF_SECONDS * attempt)
                if is_retryable_buybox_error(last_result):
                    return last_result
        return last_result or {"ok": False, "error": "BuyBox refresh failed", "attempts": 0}

    def _fetch_variant_payload(
        self,
        *,
        client: httpx.Client,
        payload: dict[str, Any],
        variant_hint: str | None,
    ) -> dict[str, Any] | None:
        if not self._is_summary_buybox(payload):
            return None
        variant_url = self._variant_detail_url(payload=payload, variant_hint=variant_hint)
        if not variant_url:
            return None
        try:
            response = client.get(variant_url)
            if response.status_code != 200:
                return None
            variant_payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(variant_payload, dict) or not variant_payload.get("buybox"):
            return None
        if self._is_summary_buybox(variant_payload):
            return None
        return {"payload": variant_payload, "url": variant_url}

    def _variant_detail_url(
        self,
        *,
        payload: dict[str, Any],
        variant_hint: str | None,
    ) -> str | None:
        hint = self._normalize_variant_text(variant_hint)
        if not hint:
            return None
        variants = payload.get("variants")
        if not isinstance(variants, dict):
            return None
        selectors = variants.get("selectors")
        if not isinstance(selectors, list):
            return None
        for selector in selectors:
            if not isinstance(selector, dict):
                continue
            options = selector.get("options")
            if not isinstance(options, list):
                continue
            for option in options:
                if not isinstance(option, dict):
                    continue
                value = option.get("value")
                names: list[Any] = []
                if isinstance(value, dict):
                    names.extend([value.get("name"), value.get("value")])
                names.extend([option.get("name"), option.get("id")])
                if any(self._variant_text_matches(hint, name) for name in names):
                    href = option.get("href")
                    return str(href).strip() if href else None
        return None

    @staticmethod
    def _is_summary_buybox(payload: dict[str, Any]) -> bool:
        buybox = payload.get("buybox")
        if not isinstance(buybox, dict):
            return False
        return str(buybox.get("buybox_items_type") or "").strip().lower() == "summary"

    @classmethod
    def _variant_text_matches(cls, normalized_hint: str, value: Any) -> bool:
        option = cls._normalize_variant_text(value)
        if not option:
            return False
        if option == normalized_hint:
            return True
        return len(option) >= 3 and (option in normalized_hint or normalized_hint in option)

    def _parse_buybox_detail(
        self,
        payload: dict[str, Any],
        *,
        offer_id: str,
        tsin: str | None,
        detail_identifier: str | None,
        variant_matched: bool,
        current_price: float,
    ) -> dict[str, Any]:
        offers = self._public_offers(payload)
        selected = next((offer for offer in offers if offer["selected"]), None)
        offer_match_ids = self._listing_offer_match_ids(offer_id=offer_id)
        matched = [offer for offer in offers if self._offer_matches(offer, offer_match_ids)]
        matched_ids = set().union(
            *(offer.get("ids", set()) & offer_match_ids for offer in matched)
        ) if matched else set()
        buybox_price = selected["price"] if selected else None
        owns_buybox = bool(selected and self._offer_matches(selected, offer_match_ids))
        explicit_tsin_matched = self._payload_matches_tsin(
            payload=payload,
            tsin=tsin,
            detail_identifier=detail_identifier,
        )
        prices = [
            offer["price"]
            for offer in offers
            if offer["price"] is not None and offer["price"] > current_price
        ]
        return {
            "trusted": bool(matched or variant_matched or explicit_tsin_matched),
            "ownership_known": bool(matched),
            "owns_buybox": owns_buybox,
            "buybox_price": buybox_price,
            "next_offer_price": min(prices) if prices else None,
            "matched_ids": matched_ids,
        }

    def _public_offers(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        offers: list[dict[str, Any]] = []
        buybox = payload.get("buybox") if isinstance(payload.get("buybox"), dict) else {}
        buybox_items = buybox.get("items")
        if isinstance(buybox_items, list):
            for item in buybox_items:
                if isinstance(item, dict):
                    offers.append(self._public_offer_row(item, selected=bool(item.get("is_selected"))))

        other_offers = payload.get("other_offers") if isinstance(payload.get("other_offers"), dict) else {}
        conditions = other_offers.get("conditions")
        if isinstance(conditions, list):
            for condition in conditions:
                if not isinstance(condition, dict):
                    continue
                items = condition.get("items")
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            offers.append(self._public_offer_row(item, selected=False))
        return offers

    def _public_offer_row(self, item: dict[str, Any], *, selected: bool) -> dict[str, Any]:
        return {
            "selected": selected,
            "price": self._numeric(
                item.get("price")
                if item.get("price") not in (None, 0)
                else item.get("listing_price")
            ),
            "ids": self._public_offer_ids(item),
        }

    def _public_offer_ids(self, item: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for value in (
            item.get("offer_id"),
            item.get("offerId"),
            item.get("sku"),
            item.get("id"),
            item.get("product_id"),
            item.get("listing_id"),
        ):
            self._add_match_id(ids, value)

        for key in ("offer", "seller_offer", "offer_detail", "listing"):
            nested = item.get(key)
            if not isinstance(nested, dict):
                continue
            for value in (
                nested.get("offer_id"),
                nested.get("offerId"),
                nested.get("sku"),
                nested.get("id"),
                nested.get("product_id"),
                nested.get("listing_id"),
            ):
                self._add_match_id(ids, value)
        return ids

    @classmethod
    def _listing_offer_match_ids(cls, *, offer_id: str) -> set[str]:
        ids: set[str] = set()
        cls._add_match_id(ids, offer_id)
        return ids

    @staticmethod
    def _add_match_id(ids: set[str], value: Any) -> None:
        if value in (None, ""):
            return
        text = str(value).strip()
        if text:
            ids.add(text)

    @staticmethod
    def _offer_matches(offer: dict[str, Any], match_ids: set[str]) -> bool:
        return bool(match_ids and offer.get("ids", set()) & match_ids)

    def _hydrate_listing_identity(
        self,
        *,
        store: dict[str, Any],
        listing: dict[str, Any] | None,
        offer_id: str,
    ) -> dict[str, Any] | None:
        if not listing:
            return listing
        credentials_payload = app_state.get_store_credentials(store["id"])
        if not credentials_payload:
            return listing
        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=credentials_payload.get("api_key", ""),
            api_secret=credentials_payload.get("api_secret", ""),
        )
        if not credentials.api_key or not credentials.api_secret:
            return listing

        try:
            offer = TakealotAdapter(credentials).get_offer(offer_id)
        except Exception:
            return listing
        if not offer:
            return listing

        raw_payload = listing.get("raw_payload")
        merged_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        merged_payload.update({key: value for key, value in offer.items() if value is not None})

        updater = getattr(app_state, "update_store_listing", None)
        listing_id = listing.get("id")
        if updater is None or not listing_id:
            return {**listing, "raw_payload": merged_payload}
        updated = updater(
            store_id=store["id"],
            listing_id=listing_id,
            platform_price=self._numeric(offer.get("selling_price")),
            raw_payload=merged_payload,
        )
        return updated or {**listing, "raw_payload": merged_payload}

    def _apply_offer_price(
        self,
        *,
        store: dict[str, Any],
        listing: dict[str, Any],
        offer_id: str,
        new_price: int,
    ) -> None:
        credentials_payload = app_state.get_store_credentials(store["id"])
        if not credentials_payload:
            raise AdapterAuthError("Store credentials unavailable")
        credentials = AdapterCredentials(
            platform=store["platform"],
            api_key=credentials_payload.get("api_key", ""),
            api_secret=credentials_payload.get("api_secret", ""),
        )
        if not credentials.api_key or not credentials.api_secret:
            raise AdapterAuthError("Store credentials unavailable")
        adapter = TakealotAdapter(credentials)
        adapter.update_offer_price(
            offer_id=offer_id,
            selling_price=new_price,
            barcode=self._extract_barcode(listing),
        )

    def _append_reprice_audit(
        self,
        *,
        store: dict[str, Any],
        rule: dict[str, Any],
        actor: dict[str, Any],
        old_price: float,
        new_price: float,
        decision: dict[str, Any],
    ) -> None:
        app_state.append_audit(
            request_id=f"autobid-{rule['id']}-{int(time.time())}",
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=actor.get("id"),
            actor_role=actor.get("role"),
            action="AUTOBID_REPRICE",
            action_label="Apply automatic bid price",
            risk_level="critical",
            target_type="bidding_rule",
            target_id=rule["id"],
            target_label=rule["sku"],
            before={"price": old_price},
            after={"price": new_price},
            reason="Automatic repricing after fresh BuyBox refresh",
            result="success",
            task_id=None,
            metadata={"decision": decision},
        )

    @staticmethod
    def _append_store_runtime_audit(
        *,
        store: dict[str, Any],
        actor: dict[str, Any],
        request_headers: dict[str, str],
        action: str,
        label: str,
        after: dict[str, Any],
    ) -> None:
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=actor.get("id"),
            actor_role=actor.get("role"),
            action=action,
            action_label=label,
            risk_level="high",
            target_type="store",
            target_id=store["id"],
            target_label=store["name"],
            before=None,
            after=after,
            reason="Operator changed automatic bidding runtime state",
            result="success",
            task_id=None,
            metadata={"operator_id": actor.get("id")},
        )

    def _store_plan(self, store: dict[str, Any]) -> str | None:
        entitlement_getter = getattr(app_state, "get_tenant_entitlement", None)
        if entitlement_getter is None:
            return None
        entitlement = entitlement_getter(store["tenant_id"])
        return entitlement.get("plan")

    def _cycle_limit(self, plan: str | None) -> int:
        stores = [
            store
            for store in self._eligible_bidding_stores()
        ]
        weighted_limit = calculate_cycle_limit(
            subscription_weight(plan),
            len(stores),
        )
        return min(max(1, settings.autobid_cycle_default_limit), weighted_limit)

    def _store_summary(self, store_id: str) -> dict[str, int]:
        summary_getter = getattr(app_state, "bidding_runtime_summary", None)
        if summary_getter is not None:
            return summary_getter(store_id=store_id)
        rules = app_state.list_bidding_rules(store_id=store_id)
        return {
            "active_rule_count": sum(1 for rule in rules if rule.get("is_active")),
            "due_rule_count": sum(1 for rule in rules if rule.get("is_active")),
            "blocked_count": sum(1 for rule in rules if rule.get("buybox_status") == "blocked"),
            "retrying_count": sum(1 for rule in rules if rule.get("buybox_status") == "retrying"),
            "fresh_count": sum(1 for rule in rules if rule.get("buybox_status") == "fresh"),
            "won_buybox_count": sum(1 for rule in rules if self._summary_rule_owns_buybox(rule)),
            "lost_buybox_count": sum(1 for rule in rules if self._summary_rule_lost_buybox(rule)),
            "alert_count": sum(1 for rule in rules if self._summary_rule_has_alert(rule)),
        }

    @staticmethod
    def _summary_rule_owns_buybox(rule: dict[str, Any]) -> bool:
        decision = rule.get("last_decision")
        return bool(rule.get("is_active") and isinstance(decision, dict) and decision.get("owns_buybox") is True)

    @classmethod
    def _summary_rule_lost_buybox(cls, rule: dict[str, Any]) -> bool:
        return bool(
            rule.get("is_active")
            and rule.get("last_buybox_price") is not None
            and not cls._summary_rule_owns_buybox(rule)
        )

    @classmethod
    def _summary_rule_has_alert(cls, rule: dict[str, Any]) -> bool:
        if not rule.get("is_active"):
            return False
        if rule.get("buybox_status") == "blocked":
            return True
        if rule.get("last_cycle_error") or rule.get("repricing_blocked_reason"):
            return True
        if rule.get("last_action") == "floor":
            return True
        floor_price = cls._numeric(rule.get("floor_price"))
        buybox_price = cls._numeric(rule.get("last_buybox_price"))
        return bool(
            floor_price is not None
            and buybox_price is not None
            and buybox_price < floor_price
            and not cls._summary_rule_owns_buybox(rule)
        )

    @staticmethod
    def _store_runtime(store_id: str) -> dict[str, Any]:
        getter = getattr(app_state, "get_bidding_store_runtime_state", None)
        if getter is None:
            return {
                "store_id": store_id,
                "is_running": False,
                "last_started_at": None,
                "last_stopped_at": None,
                "last_manual_cycle_at": None,
                "last_worker_cycle_at": None,
                "last_cycle_summary": None,
            }
        return getter(store_id)

    @staticmethod
    def _update_store_runtime(store_id: str, **changes: Any) -> dict[str, Any] | None:
        updater = getattr(app_state, "update_bidding_store_runtime_state", None)
        if updater is None:
            return None
        return updater(store_id, **changes)

    @staticmethod
    def _to_store_status_response(
        *,
        store: dict[str, Any],
        summary: dict[str, int],
        runtime: dict[str, Any],
    ) -> BiddingStoreStatusResponse:
        return BiddingStoreStatusResponse(
            store_id=store["id"],
            is_running=bool(runtime.get("is_running")),
            active_rule_count=summary["active_rule_count"],
            due_rule_count=summary["due_rule_count"],
            blocked_count=summary["blocked_count"],
            retrying_count=summary["retrying_count"],
            fresh_count=summary["fresh_count"],
            won_buybox_count=summary.get("won_buybox_count", 0),
            lost_buybox_count=summary.get("lost_buybox_count", 0),
            alert_count=summary.get("alert_count", 0),
            dry_run_default=True,
            real_write_enabled=settings.autobid_real_write_enabled,
            worker_enabled=settings.autobid_worker_enabled,
            worker_cycle_limit=settings.autobid_worker_cycle_limit,
            last_started_at=runtime.get("last_started_at"),
            last_stopped_at=runtime.get("last_stopped_at"),
            last_manual_cycle_at=runtime.get("last_manual_cycle_at"),
            last_worker_cycle_at=runtime.get("last_worker_cycle_at"),
            last_cycle_summary=runtime.get("last_cycle_summary"),
        )

    @staticmethod
    def _eligible_bidding_stores() -> list[dict[str, Any]]:
        return [
            store
            for store in app_state.list_stores()
            if store.get("status") == "active"
            and store.get("platform") == "takealot"
        ]

    def _extract_offer_id(
        self,
        rule: dict[str, Any],
        listing: dict[str, Any] | None,
    ) -> str | None:
        if listing and listing.get("external_listing_id"):
            return str(listing["external_listing_id"])
        raw_payload = listing.get("raw_payload") if listing else None
        value = self._first_nested_value(
            raw_payload,
            "offer_id",
            "offerId",
            "listing_id",
            "id",
        )
        if value not in (None, ""):
            return str(value)
        return str(rule["listing_id"]) if rule.get("listing_id") else None

    def _extract_plid(self, listing: dict[str, Any] | None) -> str | None:
        if not listing:
            return None
        for value in (
            listing.get("platform_product_id"),
            self._first_nested_value(
                listing.get("raw_payload"),
                "productline_id",
                "productlineId",
                "product_line_id",
                "plid",
                "product_id",
            ),
        ):
            plid = self._normalize_plid(value)
            if plid:
                return plid
        return None

    def _extract_tsin(self, listing: dict[str, Any] | None) -> str | None:
        if not listing:
            return None
        raw_payload = listing.get("raw_payload")
        if not isinstance(raw_payload, dict):
            return None

        candidates = [
            raw_payload.get("tsin_id"),
            raw_payload.get("tsinId"),
            raw_payload.get("takealot_tsin"),
            raw_payload.get("takealotTsin"),
        ]
        nested_tsin = raw_payload.get("tsin")
        if isinstance(nested_tsin, dict):
            candidates.extend(
                [
                    nested_tsin.get("id"),
                    nested_tsin.get("tsin_id"),
                    nested_tsin.get("tsinId"),
                ]
            )

        for value in candidates:
            tsin = self._normalize_tsin(value)
            if tsin:
                return tsin
        return None

    def _extract_variant_hint(self, listing: dict[str, Any] | None) -> str | None:
        if not listing:
            return None
        raw_payload = listing.get("raw_payload")
        raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
        for key in (
            "variant",
            "variant_name",
            "variantName",
            "colour_variant",
            "color_variant",
            "colour",
            "color",
            "size",
        ):
            value = raw_payload.get(key)
            if value not in (None, "") and not isinstance(value, (dict, list)):
                return str(value).strip()

        title = str(raw_payload.get("title") or listing.get("title") or "").strip()
        if " - " not in title:
            return None
        suffix = title.rsplit(" - ", 1)[-1].strip()
        return suffix or None

    def _extract_barcode(self, listing: dict[str, Any]) -> str | None:
        value = self._first_nested_value(
            listing.get("raw_payload"),
            "barcode",
            "gtin",
            "ean",
            "isbn",
        )
        return str(value).strip() if value not in (None, "") else None

    @staticmethod
    def _normalize_plid(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        match = re.search(r"(PLID)?(\d+)", text, flags=re.I)
        if not match:
            return None
        return f"PLID{match.group(2)}"

    @staticmethod
    def _normalize_tsin(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        match = re.search(r"TSIN\s*(\d+)", text, flags=re.I)
        if match:
            return f"TSIN{match.group(1)}"
        if re.fullmatch(r"\d+", text):
            return f"TSIN{text}"
        return None

    @staticmethod
    def _normalize_variant_text(value: Any) -> str:
        if value in (None, ""):
            return ""
        return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())

    def _detail_identifiers(self, *, plid: str | None, tsin: str | None) -> list[str]:
        identifiers: list[str] = []
        for value in (self._normalize_tsin(tsin), self._normalize_plid(plid)):
            if value and value not in identifiers:
                identifiers.append(value)
        return identifiers

    def _payload_matches_tsin(
        self,
        *,
        payload: dict[str, Any],
        tsin: str | None,
        detail_identifier: str | None,
    ) -> bool:
        normalized_tsin = self._normalize_tsin(tsin)
        if not normalized_tsin:
            return False

        del detail_identifier
        candidates: list[Any] = [
            payload.get("meta_identifier"),
            payload.get("tsin"),
            payload.get("tsin_id"),
        ]
        buybox = payload.get("buybox")
        if isinstance(buybox, dict):
            candidates.extend([buybox.get("tsin"), buybox.get("tsin_id")])

        return any(self._normalize_tsin(value) == normalized_tsin for value in candidates)

    def _first_nested_value(self, value: Any, *keys: str) -> Any:
        if isinstance(value, dict):
            for key in keys:
                if value.get(key) not in (None, ""):
                    return value[key]
            for nested in value.values():
                found = self._first_nested_value(nested, *keys)
                if found not in (None, ""):
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._first_nested_value(item, *keys)
                if found not in (None, ""):
                    return found
        return None

    @staticmethod
    def _numeric(value: Any) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            value = value.replace("R", "").replace(",", "").strip()
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _update_runtime(rule_id: str, **changes: Any) -> dict[str, Any] | None:
        updater = getattr(app_state, "update_bidding_rule_runtime", None)
        if updater is None:
            return None
        return updater(rule_id, **changes)

    @staticmethod
    def _validate_floor_price(floor_price: float | None) -> None:
        if floor_price is not None and floor_price <= 0:
            raise ValueError("floor_price must be greater than 0")

    @classmethod
    def _validate_required_floor_price(cls, floor_price: float | None) -> None:
        cls._validate_floor_price(floor_price)
        if floor_price is None:
            raise ValueError("floor_price is required")

    @staticmethod
    def _valid_bidding_listing_by_sku(store_id: str) -> dict[str, dict[str, Any]]:
        return {
            listing["sku"]: listing
            for listing in app_state.list_store_listings(
                store_id=store_id,
                status_group="buyable",
                limit=None,
            )
        }

    @staticmethod
    def _find_listing_by_sku(store_id: str, sku: str) -> dict[str, Any] | None:
        return next(
            (
                listing
                for listing in app_state.list_store_listings(
                    store_id=store_id,
                    sku_query=sku,
                    limit=None,
                )
                if listing["sku"] == sku
            ),
            None,
        )

    @staticmethod
    def _require_store(
        store_id: str,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        store = app_state.get_store(store_id)
        if store is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found",
            )
        require_tenant_access(actor, store["tenant_id"], detail="Store not found")
        return store

    def _require_rule(
        self,
        rule_id: str,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        rule = app_state.get_bidding_rule(rule_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bidding rule not found",
            )
        self._require_store(rule["store_id"], actor)
        return rule

    @staticmethod
    def _append_floor_price_audit(
        *,
        rule: dict[str, Any],
        actor: dict[str, Any],
        request_headers: dict[str, str],
        old_price: float | None,
        new_price: float | None,
        reason: str,
    ) -> None:
        details = {
            "old_price": old_price,
            "new_price": new_price,
        }
        store = app_state.get_store(rule["store_id"])
        app_state.append_audit(
            request_id=get_request_id(request_headers),
            tenant_id=store["tenant_id"] if store is not None else actor["tenant_id"],
            store_id=rule["store_id"],
            actor_user_id=actor["id"],
            actor_role=actor["role"],
            action="UPDATE_BIDDING_RULE",
            action_label="Update bidding floor price",
            risk_level="critical",
            target_type="bidding_rule",
            target_id=rule["id"],
            target_label=rule["sku"],
            before={"floor_price": old_price},
            after={"floor_price": new_price},
            reason=reason,
            result="success",
            task_id=None,
            metadata={
                "operator_id": actor["id"],
                "details": details,
            },
        )

    @staticmethod
    def _to_rule_response(rule: dict[str, Any]) -> BiddingRuleResponse:
        return BiddingRuleResponse(
            rule_id=rule["id"],
            store_id=rule["store_id"],
            sku=rule["sku"],
            listing_id=rule["listing_id"],
            floor_price=rule["floor_price"],
            strategy_type=rule["strategy_type"],
            is_active=rule["is_active"],
            next_check_at=rule.get("next_check_at"),
            buybox_fetch_fail_count=int(rule.get("buybox_fetch_fail_count") or 0),
            buybox_last_error=rule.get("buybox_last_error") or "",
            buybox_last_success_at=rule.get("buybox_last_success_at"),
            buybox_next_retry_at=rule.get("buybox_next_retry_at"),
            buybox_status=rule.get("buybox_status") or "idle",
            repricing_blocked_reason=rule.get("repricing_blocked_reason") or "",
            last_action=rule.get("last_action") or "",
            last_reprice_at=rule.get("last_reprice_at"),
            last_suggested_price=rule.get("last_suggested_price"),
            last_applied_price=rule.get("last_applied_price"),
            last_buybox_price=rule.get("last_buybox_price"),
            last_next_offer_price=rule.get("last_next_offer_price"),
            last_cycle_dry_run=bool(rule.get("last_cycle_dry_run", True)),
            last_cycle_error=rule.get("last_cycle_error") or "",
            last_decision=rule.get("last_decision"),
            version=rule["version"],
            created_at=rule["created_at"],
            updated_at=rule["updated_at"],
        )
