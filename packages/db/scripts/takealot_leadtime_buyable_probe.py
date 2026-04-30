from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.store.adapters.base import AdapterCredentials  # noqa: E402
from src.modules.store.adapters.takealot import TakealotAdapter  # noqa: E402


def _credentials() -> AdapterCredentials:
    api_key = os.environ.get("XH_TAKEALOT_API_KEY", "").strip()
    api_secret = os.environ.get("XH_TAKEALOT_API_SECRET", "").strip() or "takealot-api-secret-placeholder"
    if not api_key:
        raise SystemExit("Missing XH_TAKEALOT_API_KEY")
    return AdapterCredentials(platform="takealot", api_key=api_key, api_secret=api_secret)


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }


def _poll_batch(client: httpx.Client, headers: dict[str, str], batch_id: int, poll_seconds: int, max_polls: int) -> dict[str, object]:
    last_payload: dict[str, object] = {"batch_id": batch_id, "status": "unknown"}
    for _ in range(max(1, max_polls)):
        response = client.get(f"/offers/batch/{batch_id}", headers=headers)
        response.raise_for_status()
        payload = response.json()
        last_payload = payload if isinstance(payload, dict) else {"raw": payload}
        if str(last_payload.get("status") or "").lower() in {"success", "failed"}:
            return last_payload
        time.sleep(max(1, poll_seconds))
    return last_payload


def _offer_by_barcode(client: httpx.Client, headers: dict[str, str], barcode: str) -> dict[str, object] | None:
    response = client.get(f"/offers/by_barcode/{barcode}", headers=headers)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"raw": payload}


def _variants(args: argparse.Namespace) -> list[tuple[str, dict[str, object]]]:
    base = {
        "barcode": args.barcode,
        "sku": args.sku,
        "selling_price": max(0, int(round(args.selling_price))),
        "leadtime_days": args.leadtime_days,
    }
    variants: list[tuple[str, dict[str, object]]] = [
        ("baseline", dict(base)),
        ("reenable", {**base, "status_action": "Re-enable"}),
    ]
    if args.merchant_warehouse_id is not None and args.quantity is not None:
        variants.append(
            (
                "leadtime_stock",
                {
                    **base,
                    "status_action": "Re-enable",
                    "leadtime_stock": [
                        {
                            "merchant_warehouse_id": args.merchant_warehouse_id,
                            "quantity": max(1, int(args.quantity)),
                        }
                    ],
                },
            )
        )
    return variants


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe which official leadtime batch payload turns an offer buyable")
    parser.add_argument("--barcode", required=True)
    parser.add_argument("--sku", required=True)
    parser.add_argument("--selling-price", required=True, type=float)
    parser.add_argument("--leadtime-days", required=True, type=int)
    parser.add_argument("--merchant-warehouse-id", type=int, default=None)
    parser.add_argument("--quantity", type=int, default=None)
    parser.add_argument("--poll-seconds", type=int, default=3)
    parser.add_argument("--max-polls", type=int, default=8)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually submit each probe variant to the live Takealot batch endpoint.",
    )
    args = parser.parse_args()

    variants = _variants(args)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "barcode": args.barcode,
                    "variants": [{"name": name, "payload": payload} for name, payload in variants],
                },
                ensure_ascii=False,
            )
        )
        return

    credentials = _credentials()
    adapter = TakealotAdapter(credentials)
    seller = adapter.get_seller_profile()
    headers = _headers(credentials.api_key)
    results: list[dict[str, object]] = []

    with httpx.Client(base_url=adapter.base_url, timeout=30) as client:
        for name, payload in variants:
            response = client.post("/offers/batch", headers=headers, json={"offers": [payload]})
            response.raise_for_status()
            batch = response.json()
            batch_payload = batch if isinstance(batch, dict) else {"raw": batch}
            batch_id = int(batch_payload["batch_id"])
            final_batch = _poll_batch(client, headers, batch_id, args.poll_seconds, args.max_polls)
            offer = _offer_by_barcode(client, headers, args.barcode)
            results.append(
                {
                    "variant": name,
                    "submitted_payload": payload,
                    "batch_id": batch_id,
                    "batch_status": final_batch.get("status"),
                    "batch_payload": final_batch,
                    "offer": offer,
                }
            )

    print(
        json.dumps(
            {
                "mode": "execute",
                "seller_display_name": seller.get("display_name"),
                "leadtime_enabled": seller.get("leadtime_enabled"),
                "leadtime_details": seller.get("leadtime_details"),
                "results": results,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
