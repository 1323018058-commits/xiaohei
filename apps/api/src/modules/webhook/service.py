from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from fastapi import HTTPException, status
from starlette.datastructures import Headers

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state
from src.modules.extension.service import sync_guardrails_for_listing
from src.modules.store.adapters.takealot import TakealotAdapter
from src.platform.settings.base import settings

from .schemas import TakealotWebhookAck


TAKEALOT_WEBHOOK_TASK_TYPE = "TAKEALOT_WEBHOOK_PROCESS"
TAKEALOT_WEBHOOK_QUEUE = "takealot-webhooks"
TAKEALOT_WEBHOOK_SOURCE_ID = "takealot-webhook"


class TakealotWebhookService:
    def receive(
        self,
        *,
        headers: Headers,
        body: bytes,
        received_url: str,
    ) -> TakealotWebhookAck:
        event_type = self._required_header(headers, "x-takealot-event")
        delivery_id = self._required_header(headers, "x-takealot-delivery")
        signature = self._required_header(headers, "x-takealot-signature")
        content_type = headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Takealot webhooks must use application/json",
            )

        payload = self._decode_payload(body)
        self._verify_signature(
            signature=signature,
            body=body,
            payload=payload,
            received_url=received_url,
        )

        existing = self._find_existing_task(delivery_id)
        if existing is not None:
            return TakealotWebhookAck(
                accepted=True,
                duplicate=True,
                task_id=existing["id"],
                delivery_id=delivery_id,
                event_type=event_type,
            )

        task = app_state.create_task(
            task_type=TAKEALOT_WEBHOOK_TASK_TYPE,
            domain="webhook",
            queue_name=TAKEALOT_WEBHOOK_QUEUE,
            actor_user_id=ADMIN_USER_ID,
            actor_role="system",
            tenant_id=DEMO_TENANT_ID,
            store_id=None,
            target_type="takealot_webhook",
            target_id=delivery_id,
            request_id=delivery_id,
            label=f"Takealot webhook: {event_type}",
            next_action="Process Takealot webhook payload",
        )
        app_state.add_task_event(
            task_id=task["id"],
            event_type="webhook.received",
            from_status="queued",
            to_status="queued",
            stage="received",
            message=f"Takealot webhook delivery {delivery_id} accepted",
            details={
                "delivery_id": delivery_id,
                "event_type": event_type,
                "payload": payload,
            },
            source="webhook",
            source_id=TAKEALOT_WEBHOOK_SOURCE_ID,
        )
        app_state.append_audit(
            request_id=delivery_id,
            tenant_id=DEMO_TENANT_ID,
            store_id=None,
            actor_user_id=None,
            actor_role=None,
            action="takealot.webhook.receive",
            action_label="Receive Takealot webhook",
            risk_level="low",
            target_type="takealot_webhook",
            target_id=delivery_id,
            target_label=event_type,
            before=None,
            after={"task_id": task["id"], "event_type": event_type},
            reason="Verified Takealot webhook signature",
            result="success",
            task_id=task["id"],
            metadata={"delivery_id": delivery_id, "event_type": event_type},
        )
        return TakealotWebhookAck(
            accepted=True,
            duplicate=False,
            task_id=task["id"],
            delivery_id=delivery_id,
            event_type=event_type,
        )

    def process_queued_webhook_tasks(self) -> list[dict[str, Any]]:
        claimed_tasks = app_state.claim_queued_tasks(
            {TAKEALOT_WEBHOOK_TASK_TYPE},
            worker_id=TAKEALOT_WEBHOOK_SOURCE_ID,
        )
        return [self.process_webhook_task(task["id"]) for task in claimed_tasks]

    def process_webhook_task(self, task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None or task["task_type"] != TAKEALOT_WEBHOOK_TASK_TYPE:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Takealot webhook task not found",
            )
        if task["status"] == "cancelled" or task["cancel_requested_at"]:
            return task
        started_at = self._now()
        app_state.update_task(
            task_id,
            status="running",
            stage="processing",
            progress_percent=50,
            progress_current=0,
            progress_total=1,
            started_at=started_at,
            last_heartbeat_at=started_at,
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.started",
            from_status=task["status"],
            to_status="running",
            stage="processing",
            message="Takealot webhook processing started",
            details=None,
            source="worker",
            source_id=TAKEALOT_WEBHOOK_SOURCE_ID,
        )
        if self._task_cancel_requested(task_id):
            return self._mark_task_cancelled(task_id)
        result = self._apply_webhook_payload(task_id)
        finished_at = self._now()
        updated = app_state.update_task(
            task_id,
            status="succeeded",
            stage=result["stage"],
            progress_percent=100,
            progress_current=1,
            progress_total=1,
            finished_at=finished_at,
            last_heartbeat_at=finished_at,
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="task.succeeded",
            from_status="running",
            to_status="succeeded",
            stage=result["stage"],
            message=result["message"],
            details=result,
            source="worker",
            source_id=TAKEALOT_WEBHOOK_SOURCE_ID,
        )
        return updated

    def _apply_webhook_payload(self, task_id: str) -> dict[str, Any]:
        webhook_event = self._received_event(task_id)
        if webhook_event is None:
            return {
                "stage": "stored",
                "message": "Takealot webhook payload stored without received event metadata",
                "applied": False,
                "reason": "missing_webhook_received_event",
            }

        details = webhook_event.get("details") or {}
        event_type = str(details.get("event_type") or "")
        payload = details.get("payload")
        if not isinstance(payload, dict):
            return {
                "stage": "stored",
                "message": "Takealot webhook payload stored without JSON object payload",
                "applied": False,
                "event_type": event_type,
                "reason": "non_object_payload",
            }

        event_key = self._event_key(event_type)
        if event_key not in {"offercreated", "offerupdated"}:
            order_snapshot = self._order_snapshot_from_webhook(event_type, payload)
            if order_snapshot is not None:
                store = self._resolve_store()
                if store is None:
                    return {
                        "stage": "needs_mapping",
                        "message": f"Takealot webhook {event_type} stored; configure XH_TAKEALOT_WEBHOOK_STORE_ID to update orders",
                        "applied": False,
                        "event_type": event_type,
                        "reason": "store_mapping_missing",
                    }

                from src.modules.orders.service import OrderService

                order = OrderService()._upsert_order(store, order_snapshot)
                app_state.add_task_event(
                    task_id=task_id,
                    event_type="webhook.order_upserted",
                    from_status="running",
                    to_status="running",
                    stage="applying",
                    message=f"Updated order {order['external_order_id']} from Takealot webhook",
                    details={
                        "store_id": store["id"],
                        "order_id": order["id"],
                        "external_order_id": order["external_order_id"],
                        "event_type": event_type,
                    },
                    source="worker",
                    source_id=TAKEALOT_WEBHOOK_SOURCE_ID,
                )
                app_state.append_audit(
                    request_id=task_id,
                    tenant_id=store["tenant_id"],
                    store_id=store["id"],
                    actor_user_id=None,
                    actor_role=None,
                    action="takealot.webhook.order_upsert",
                    action_label="Apply Takealot webhook to order",
                    risk_level="low",
                    target_type="order",
                    target_id=order["id"],
                    target_label=order["external_order_id"],
                    before=None,
                    after={
                        "external_order_id": order["external_order_id"],
                        "status": order["status"],
                        "total_amount": order["total_amount"],
                    },
                    reason=f"Takealot webhook {event_type}",
                    result="success",
                    task_id=task_id,
                    metadata={"event_type": event_type},
                )
                app_state.update_task(task_id, store_id=store["id"], target_type="order", target_id=order["id"])
                return {
                    "stage": "applied",
                    "message": f"Takealot webhook {event_type} applied to order {order['external_order_id']}",
                    "applied": True,
                    "event_type": event_type,
                    "store_id": store["id"],
                    "order_id": order["id"],
                    "external_order_id": order["external_order_id"],
                }

            return {
                "stage": "stored",
                "message": f"Takealot webhook {event_type} stored for downstream reconciliation",
                "applied": False,
                "event_type": event_type,
                "reason": "event_not_listing_mutation",
            }

        store = self._resolve_store()
        if store is None:
            return {
                "stage": "needs_mapping",
                "message": f"Takealot webhook {event_type} stored; configure XH_TAKEALOT_WEBHOOK_STORE_ID to update listings",
                "applied": False,
                "event_type": event_type,
                "reason": "store_mapping_missing",
            }

        listing_payload = self._listing_payload_from_webhook(
            store_id=store["id"],
            event_type=event_type,
            payload=payload,
        )
        if listing_payload is None:
            return {
                "stage": "stored",
                "message": f"Takealot webhook {event_type} stored; listing payload did not include enough identifiers",
                "applied": False,
                "event_type": event_type,
                "store_id": store["id"],
                "reason": "listing_identifier_missing",
            }

        listing = app_state.upsert_store_listing(**listing_payload)
        sync_guardrails_for_listing(
            listing=listing,
            request_id=task_id,
            actor=None,
        )
        app_state.add_task_event(
            task_id=task_id,
            event_type="webhook.listing_upserted",
            from_status="running",
            to_status="running",
            stage="applying",
            message=f"Updated listing {listing['sku']} from Takealot webhook",
            details={
                "store_id": store["id"],
                "listing_id": listing["id"],
                "external_listing_id": listing["external_listing_id"],
                "sku": listing["sku"],
                "event_type": event_type,
            },
            source="worker",
            source_id=TAKEALOT_WEBHOOK_SOURCE_ID,
        )
        app_state.append_audit(
            request_id=task_id,
            tenant_id=store["tenant_id"],
            store_id=store["id"],
            actor_user_id=None,
            actor_role=None,
            action="takealot.webhook.listing_upsert",
            action_label="Apply Takealot webhook to listing",
            risk_level="low",
            target_type="listing",
            target_id=listing["id"],
            target_label=listing["sku"],
            before=None,
            after={
                "external_listing_id": listing["external_listing_id"],
                "sku": listing["sku"],
                "platform_price": listing["platform_price"],
                "stock_quantity": listing["stock_quantity"],
            },
            reason=f"Takealot webhook {event_type}",
            result="success",
            task_id=task_id,
            metadata={"event_type": event_type},
        )
        app_state.update_task(task_id, store_id=store["id"], target_type="listing", target_id=listing["id"])
        return {
            "stage": "applied",
            "message": f"Takealot webhook {event_type} applied to listing {listing['sku']}",
            "applied": True,
            "event_type": event_type,
            "store_id": store["id"],
            "listing_id": listing["id"],
            "external_listing_id": listing["external_listing_id"],
            "sku": listing["sku"],
        }

    def _order_snapshot_from_webhook(
        self,
        event_type: str,
        payload: dict[str, Any],
    ):
        sale_payloads = self._sales_payloads_from_webhook(event_type, payload)
        if not sale_payloads:
            return None
        snapshots = TakealotAdapter._sales_to_orders(sale_payloads)
        return snapshots[0] if snapshots else None

    def _sales_payloads_from_webhook(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        sale = payload.get("sale") if isinstance(payload.get("sale"), dict) else {}
        order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        offer = payload.get("offer") if isinstance(payload.get("offer"), dict) else {}
        values_changed = payload.get("values_changed") if isinstance(payload.get("values_changed"), dict) else {}
        base = {
            **sale,
            **order,
            **data,
            **offer,
            **payload,
            **self._normalized_values_changed(values_changed),
        }
        line_items = self._line_items_from_webhook(payload)
        if not line_items:
            sale_payload = self._sales_payload_from_merged(event_type, base)
            return [sale_payload] if sale_payload is not None else []

        sale_payloads: list[dict[str, Any]] = []
        for line_item in line_items:
            line_values_changed = (
                line_item.get("values_changed")
                if isinstance(line_item.get("values_changed"), dict)
                else {}
            )
            line_offer = line_item.get("offer") if isinstance(line_item.get("offer"), dict) else {}
            line = {
                **line_offer,
                **line_item,
                **self._normalized_values_changed(line_values_changed),
            }
            if len(line_items) > 1 and not self._has_price_field(line):
                continue
            sale_payload = self._sales_payload_from_merged(
                event_type,
                {**base, **line},
            )
            if sale_payload is not None:
                sale_payloads.append(sale_payload)
        return sale_payloads

    @staticmethod
    def _line_items_from_webhook(payload: dict[str, Any]) -> list[dict[str, Any]]:
        line_items: list[dict[str, Any]] = []
        for key in ["sales", "items", "order_items", "orderItems", "lines", "order_lines", "orderLines", "offers"]:
            value = payload.get(key)
            if isinstance(value, list):
                line_items.extend(item for item in value if isinstance(item, dict))
        return line_items

    def _sales_payload_from_merged(
        self,
        event_type: str,
        merged: dict[str, Any],
    ) -> dict[str, Any] | None:

        order_id = self._string_value(
            self._first_present(merged, "order_id", "orderId", "order_number", "orderNumber")
        )
        selling_price = self._float_value(
            self._first_present(
                merged,
                "selling_price",
                "sellingPrice",
                "total_selling_price",
                "totalSellingPrice",
                "price",
            )
        )
        if not order_id or selling_price is None:
            return None

        sku = self._string_value(
            self._first_present(merged, "sku", "merchant_sku", "merchantSku", "offer_sku")
        )
        offer_id = self._string_value(
            self._first_present(merged, "offer_id", "offerId", "listing_id", "listingId")
        )
        order_item_id = self._string_value(
            self._first_present(merged, "order_item_id", "orderItemId", "sale_id", "saleId", "line_id", "lineId")
        )
        if not order_item_id:
            order_item_id = f"{order_id}-{sku or offer_id or 'item'}"

        return {
            "order_id": order_id,
            "order_item_id": order_item_id,
            "order_date": self._first_present(
                merged,
                "order_date",
                "orderDate",
                "created_at",
                "createdAt",
                "sale_date",
                "saleDate",
                "event_date",
                "eventDate",
                "event_timestamp_utc",
                "eventTimestampUtc",
            ),
            "sale_status": self._string_value(
                self._first_present(merged, "sale_status", "saleStatus", "status", fallback=event_type)
            ),
            "offer_id": offer_id,
            "sku": sku,
            "title": self._string_value(
                self._first_present(merged, "title", "product_title", "productTitle", "name", fallback=sku)
            ),
            "selling_price": selling_price,
            "quantity": self._first_present(merged, "quantity", "qty", "quantity_sold", "quantitySold", fallback=1),
            "currency": self._string_value(self._first_present(merged, "currency", fallback="ZAR")),
            "raw_webhook_event_type": event_type,
        }

    @staticmethod
    def _has_price_field(payload: dict[str, Any]) -> bool:
        return any(
            key in payload and payload[key] not in (None, "")
            for key in [
                "selling_price",
                "sellingPrice",
                "total_selling_price",
                "totalSellingPrice",
                "price",
            ]
        )

    @staticmethod
    def _received_event(task_id: str) -> dict[str, Any] | None:
        for event in app_state.list_task_events(task_id):
            if event["event_type"] == "webhook.received":
                return event
        return None

    @staticmethod
    def _event_key(event_type: str) -> str:
        return "".join(character for character in event_type.lower() if character.isalnum())

    @staticmethod
    def _resolve_store() -> dict[str, Any] | None:
        if settings.takealot_webhook_store_id:
            return app_state.get_store(settings.takealot_webhook_store_id)
        active_takealot_stores = [
            store
            for store in app_state.list_stores()
            if store["platform"] == "takealot" and store["status"] == "active"
        ]
        if len(active_takealot_stores) == 1:
            return active_takealot_stores[0]
        return None

    def _listing_payload_from_webhook(
        self,
        *,
        store_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        offer = payload.get("offer") if isinstance(payload.get("offer"), dict) else {}
        values_changed = payload.get("values_changed") if isinstance(payload.get("values_changed"), dict) else {}
        merged = {**offer, **payload, **self._normalized_values_changed(values_changed)}
        external_listing_id = self._string_value(
            merged.get("offer_id")
            or merged.get("id")
        )
        if not external_listing_id:
            return None

        existing = self._find_listing(store_id, external_listing_id)
        sku = self._string_value(
            merged.get("merchant_sku")
            or merged.get("sku")
            or (existing or {}).get("sku")
            or external_listing_id
        )
        title = self._string_value(
            merged.get("product_title")
            or merged.get("title")
            or (existing or {}).get("title")
            or sku
        )
        if not sku or not title:
            return None

        platform_price = self._float_value(
            self._first_present(
                merged,
                "selling_price",
                "price",
                "total_selling_price",
                fallback=(existing or {}).get("platform_price"),
            )
        )
        stock_quantity = self._stock_quantity(
            merged.get("merchant_warehouse_stock")
            or merged.get("leadtime_stock")
            or merged.get("seller_warehouse_stock")
        )
        if stock_quantity is None:
            stock_quantity = (existing or {}).get("stock_quantity")

        return {
            "store_id": store_id,
            "external_listing_id": external_listing_id,
            "platform_product_id": self._string_value(
                merged.get("productline_id")
                or merged.get("productlineId")
                or merged.get("tsin_id")
                or merged.get("tsinId")
                or merged.get("tsin")
                or (existing or {}).get("platform_product_id")
            ),
            "sku": sku,
            "title": title,
            "platform_price": platform_price,
            "stock_quantity": stock_quantity,
            "currency": str((existing or {}).get("currency") or "ZAR"),
            "sync_status": "webhook_synced",
            "raw_payload": {
                "source": "takealot_webhook",
                "event_type": event_type,
                "payload": payload,
            },
        }

    @staticmethod
    def _normalized_values_changed(values_changed: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in values_changed.items():
            if isinstance(value, dict):
                normalized[key] = TakealotWebhookService._first_present(
                    value,
                    "new",
                    "value",
                    "current",
                )
            else:
                normalized[key] = value
        return normalized

    @staticmethod
    def _first_present(payload: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return fallback

    @staticmethod
    def _find_listing(store_id: str, external_listing_id: str) -> dict[str, Any] | None:
        for listing in app_state.list_store_listings(store_id=store_id):
            if listing["external_listing_id"] == external_listing_id:
                return listing
        return None

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _float_value(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _stock_quantity(value: Any) -> int | None:
        if value in (None, ""):
            return None
        if isinstance(value, list):
            total = 0
            found = False
            for item in value:
                if not isinstance(item, dict):
                    continue
                quantity = item.get("quantity_available")
                if quantity is None:
                    continue
                try:
                    total += max(0, int(float(quantity)))
                    found = True
                except (TypeError, ValueError):
                    continue
            return total if found else None
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _now():
        from datetime import UTC, datetime

        return datetime.now(UTC)

    @staticmethod
    def _required_header(headers: Headers, name: str) -> str:
        value = headers.get(name)
        if not value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing {name} header",
            )
        return value

    @staticmethod
    def _decode_payload(body: bytes) -> Any:
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON webhook payload",
            ) from exc

    def _verify_signature(
        self,
        *,
        signature: str,
        body: bytes,
        payload: Any,
        received_url: str,
    ) -> None:
        secret = settings.takealot_webhook_secret
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Takealot webhook secret is not configured",
            )

        webhook_url = (settings.takealot_webhook_public_url or received_url).strip()
        body_text = body.decode("utf-8")
        candidates = {
            self._signature_for(webhook_url, body_text, secret),
            self._signature_for(webhook_url, json.dumps(payload), secret),
            self._signature_for(
                webhook_url,
                json.dumps(payload, separators=(",", ":")),
                secret,
            ),
        }
        if not any(hmac.compare_digest(signature, candidate) for candidate in candidates):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Takealot webhook signature",
            )

    @staticmethod
    def _signature_for(webhook_url: str, payload_text: str, secret: str) -> str:
        hmac_data = webhook_url + payload_text
        digest = hmac.new(
            secret.encode(),
            hmac_data.encode(),
            hashlib.sha256,
        ).hexdigest()
        return base64.b64encode(digest.encode()).decode()

    @staticmethod
    def _find_existing_task(delivery_id: str) -> dict[str, Any] | None:
        for task in app_state.list_tasks():
            if (
                task["task_type"] == TAKEALOT_WEBHOOK_TASK_TYPE
                and task["request_id"] == delivery_id
            ):
                return task
        return None

    @staticmethod
    def _task_cancel_requested(task_id: str) -> bool:
        task = app_state.get_task(task_id)
        return bool(task and (task["status"] == "cancelled" or task["cancel_requested_at"]))

    @staticmethod
    def _mark_task_cancelled(task_id: str) -> dict[str, Any]:
        task = app_state.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Takealot webhook task not found",
            )
        if task["status"] == "cancelled":
            return task
        cancelled_at = TakealotWebhookService._now()
        return app_state.update_task(
            task_id,
            status="cancelled",
            stage="cancelled",
            finished_at=cancelled_at,
            last_heartbeat_at=cancelled_at,
            next_retry_at=None,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code="TASK_CANCELLED",
            error_msg=task["cancel_reason"] or "Task cancelled",
        )
