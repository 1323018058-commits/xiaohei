from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

os.environ["XH_DATABASE_URL"] = ""
os.environ["XH_TAKEALOT_WEBHOOK_SECRET"] = "test-secret"
os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"] = "https://erp.example.com/api/v1/webhooks/takealot"

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import app_state  # noqa: E402
from src.modules.webhook.service import TakealotWebhookService  # noqa: E402
from src.platform.settings.base import settings  # noqa: E402


def _signature(payload_text: str) -> str:
    hmac_data = os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"] + payload_text
    digest = hmac.new(
        os.environ["XH_TAKEALOT_WEBHOOK_SECRET"].encode(),
        hmac_data.encode(),
        hashlib.sha256,
    ).hexdigest()
    return base64.b64encode(digest.encode()).decode()


def main() -> None:
    service = TakealotWebhookService()
    store = app_state.create_store(
        {
            "name": "Webhook Mock Store",
            "platform": "takealot",
            "status": "active",
            "api_key": "mock-api-key",
            "api_secret": "mock-api-secret",
            "masked_api_key": "mock********key",
            "api_key_status": "valid",
            "credential_status": "valid",
        }
    )
    settings.takealot_webhook_store_id = store["id"]
    payload = {
        "seller_id": 29897844,
        "offer_id": 101,
        "merchant_sku": "TL-WEBHOOK-001",
        "tsin_id": 990101,
        "gtin": "6000000000101",
        "selling_price": 199,
        "merchant_warehouse_stock": [
            {"warehouse_id": 1, "name": "CPT", "quantity_available": 2},
            {"warehouse_id": 2, "name": "JHB", "quantity_available": 3},
        ],
        "batch_id": None,
    }
    body_text = json.dumps(payload)
    headers = {
        "content-type": "application/json",
        "x-takealot-event": "Offer Created",
        "x-takealot-delivery": "delivery-001",
        "x-takealot-signature": _signature(body_text),
    }
    ack = service.receive(
        headers=headers,
        body=body_text.encode(),
        received_url=os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"],
    )
    duplicate_ack = service.receive(
        headers=headers,
        body=body_text.encode(),
        received_url=os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"],
    )
    processed = service.process_queued_webhook_tasks()
    events = app_state.list_task_events(ack.task_id)
    listings = app_state.list_store_listings(store_id=store["id"])

    assert ack.accepted is True
    assert ack.duplicate is False
    assert duplicate_ack.duplicate is True
    assert len(processed) == 1, processed
    assert processed[0]["status"] == "succeeded", processed
    assert processed[0]["stage"] == "applied", processed
    assert any(event["event_type"] == "webhook.received" for event in events), events
    assert any(event["event_type"] == "webhook.listing_upserted" for event in events), events
    assert len(listings) == 1, listings
    assert listings[0]["external_listing_id"] == "101", listings
    assert listings[0]["sku"] == "TL-WEBHOOK-001", listings
    assert listings[0]["platform_product_id"] == "990101", listings
    assert listings[0]["platform_price"] == 199.0, listings
    assert listings[0]["stock_quantity"] == 5, listings

    update_payload = {
        "seller_id": 29897844,
        "offer_id": 101,
        "values_changed": {
            "selling_price": 249,
            "merchant_warehouse_stock": [
                {"warehouse_id": 1, "name": "CPT", "quantity_available": 7},
            ],
        },
        "batch_id": None,
    }
    update_body_text = json.dumps(update_payload)
    update_ack = service.receive(
        headers={
            "content-type": "application/json",
            "x-takealot-event": "Offer Updated",
            "x-takealot-delivery": "delivery-002",
            "x-takealot-signature": _signature(update_body_text),
        },
        body=update_body_text.encode(),
        received_url=os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"],
    )
    update_processed = service.process_queued_webhook_tasks()
    updated_listings = app_state.list_store_listings(store_id=store["id"])

    assert update_ack.accepted is True
    assert update_ack.duplicate is False
    assert len(update_processed) == 1, update_processed
    assert update_processed[0]["stage"] == "applied", update_processed
    assert len(updated_listings) == 1, updated_listings
    assert updated_listings[0]["sku"] == "TL-WEBHOOK-001", updated_listings
    assert updated_listings[0]["platform_price"] == 249.0, updated_listings
    assert updated_listings[0]["stock_quantity"] == 7, updated_listings

    order_payload = {
        "order_id": "WEBHOOK-ORDER-001",
        "order_item_id": "WEBHOOK-ORDER-001-1",
        "order_date": "2026-04-26T10:15:00Z",
        "sale_status": "Shipped",
        "sku": "TL-WEBHOOK-ORDER-001",
        "product_title": "Webhook Order Product",
        "selling_price": 300,
        "quantity": 2,
        "currency": "ZAR",
    }
    order_body_text = json.dumps(order_payload)
    order_ack = service.receive(
        headers={
            "content-type": "application/json",
            "x-takealot-event": "Sales Status Changed",
            "x-takealot-delivery": "delivery-003",
            "x-takealot-signature": _signature(order_body_text),
        },
        body=order_body_text.encode(),
        received_url=os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"],
    )
    order_processed = service.process_queued_webhook_tasks()
    orders = app_state.list_orders(store_id=store["id"])
    webhook_orders = [order for order in orders if order["external_order_id"] == "WEBHOOK-ORDER-001"]
    assert order_ack.accepted is True
    assert order_ack.duplicate is False
    assert len(order_processed) == 1, order_processed
    assert order_processed[0]["stage"] == "applied", order_processed
    assert len(webhook_orders) == 1, orders
    assert webhook_orders[0]["status"] == "shipped", webhook_orders
    assert webhook_orders[0]["total_amount"] == 300.0, webhook_orders
    order_items = app_state.list_order_items(webhook_orders[0]["id"])
    assert len(order_items) == 1, order_items
    assert order_items[0]["quantity"] == 2, order_items
    assert order_items[0]["unit_price"] == 150.0, order_items

    leadtime_payload = {
        "order_id": "WEBHOOK-LEADTIME-001",
        "order_item_id": "WEBHOOK-LEADTIME-001-1",
        "offer": {
            "offer_id": 202,
            "sku": "TL-WEBHOOK-LT-001",
            "barcode": "6000000000202",
            "leadtime_stock": [
                {
                    "warehouse": {"warehouse_id": 1, "name": "CPT"},
                    "quantity_available": 3,
                },
            ],
        },
        "warehouse": "CPT",
        "total_selling_price": 300,
        "event_date": "2026-04-26T11:15:00Z",
        "facility": "CPT",
    }
    leadtime_body_text = json.dumps(leadtime_payload)
    leadtime_ack = service.receive(
        headers={
            "content-type": "application/json",
            "x-takealot-event": "New Leadtime Order",
            "x-takealot-delivery": "delivery-004",
            "x-takealot-signature": _signature(leadtime_body_text),
        },
        body=leadtime_body_text.encode(),
        received_url=os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"],
    )
    leadtime_processed = service.process_queued_webhook_tasks()
    leadtime_orders = [
        order
        for order in app_state.list_orders(store_id=store["id"])
        if order["external_order_id"] == "WEBHOOK-LEADTIME-001"
    ]
    assert leadtime_ack.accepted is True
    assert leadtime_ack.duplicate is False
    assert len(leadtime_processed) == 1, leadtime_processed
    assert leadtime_processed[0]["stage"] == "applied", leadtime_processed
    assert len(leadtime_orders) == 1, leadtime_orders
    assert leadtime_orders[0]["total_amount"] == 300.0, leadtime_orders
    leadtime_items = app_state.list_order_items(leadtime_orders[0]["id"])
    assert len(leadtime_items) == 1, leadtime_items
    assert sum(item["quantity"] for item in leadtime_items) == 1, leadtime_items
    assert leadtime_items[0]["sku"] == "TL-WEBHOOK-LT-001", leadtime_items
    assert leadtime_items[0]["unit_price"] == 300.0, leadtime_items

    dropship_payload = {
        "order_id": "WEBHOOK-DROPSHIP-001",
        "ready_for_collect_due_date": "2026-04-28",
        "acceptance_due_date": "2026-04-27",
        "merchant_warehouse": {"warehouse_id": 7, "name": "Merchant Main"},
        "event_date": "2026-04-26T12:15:00Z",
        "offers": [
            {
                "offer": {
                    "offer_id": 303,
                    "sku": "TL-WEBHOOK-DS-001",
                    "barcode": "6000000000303",
                    "leadtime_stock": [{"warehouse_id": 7, "quantity_available": 4}],
                },
                "total_selling_price": 125,
                "quantity": 1,
            },
            {
                "offer": {
                    "offer_id": 304,
                    "sku": "TL-WEBHOOK-DS-002",
                    "barcode": "6000000000304",
                    "leadtime_stock": [{"warehouse_id": 7, "quantity_available": 4}],
                },
                "total_selling_price": 250,
                "quantity": 2,
            },
        ],
    }
    dropship_body_text = json.dumps(dropship_payload)
    dropship_ack = service.receive(
        headers={
            "content-type": "application/json",
            "x-takealot-event": "New Drop Ship Order",
            "x-takealot-delivery": "delivery-005",
            "x-takealot-signature": _signature(dropship_body_text),
        },
        body=dropship_body_text.encode(),
        received_url=os.environ["XH_TAKEALOT_WEBHOOK_PUBLIC_URL"],
    )
    dropship_processed = service.process_queued_webhook_tasks()
    dropship_orders = [
        order
        for order in app_state.list_orders(store_id=store["id"])
        if order["external_order_id"] == "WEBHOOK-DROPSHIP-001"
    ]
    assert dropship_ack.accepted is True
    assert dropship_ack.duplicate is False
    assert len(dropship_processed) == 1, dropship_processed
    assert dropship_processed[0]["stage"] == "applied", dropship_processed
    assert len(dropship_orders) == 1, dropship_orders
    assert dropship_orders[0]["total_amount"] == 375.0, dropship_orders
    dropship_items = app_state.list_order_items(dropship_orders[0]["id"])
    assert len(dropship_items) == 2, dropship_items
    assert sum(item["quantity"] for item in dropship_items) == 3, dropship_items

    print(
        json.dumps(
            {
                "task_id": ack.task_id,
                "duplicate_task_id": duplicate_ack.task_id,
                "processed_count": len(processed),
                "event_count": len(events),
                "update_task_id": update_ack.task_id,
                "update_processed_count": len(update_processed),
                "listing_count": len(updated_listings),
                "sku": updated_listings[0]["sku"],
                "platform_price": updated_listings[0]["platform_price"],
                "stock_quantity": updated_listings[0]["stock_quantity"],
                "order_task_id": order_ack.task_id,
                "webhook_order_id": webhook_orders[0]["external_order_id"],
                "webhook_order_total": webhook_orders[0]["total_amount"],
                "leadtime_order_task_id": leadtime_ack.task_id,
                "leadtime_order_total": leadtime_orders[0]["total_amount"],
                "leadtime_item_count": len(leadtime_items),
                "dropship_order_task_id": dropship_ack.task_id,
                "dropship_order_total": dropship_orders[0]["total_amount"],
                "dropship_item_count": len(dropship_items),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
