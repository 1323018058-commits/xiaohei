from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Guarded real Takealot offer create/update script")
    parser.add_argument("--barcode", required=True)
    parser.add_argument("--sku", required=True)
    parser.add_argument("--selling-price", required=True, type=float)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--minimum-leadtime-days", type=int, default=3)
    parser.add_argument("--poll-seconds", type=int, default=3)
    parser.add_argument("--max-polls", type=int, default=10)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call the live Takealot API. Without this flag the script only prints the planned payload.",
    )
    args = parser.parse_args()

    payload = {
        "barcode": args.barcode,
        "sku": args.sku,
        "selling_price": args.selling_price,
        "quantity": max(1, args.quantity),
        "minimum_leadtime_days": max(1, args.minimum_leadtime_days),
    }

    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "message": "Add --execute to call live Takealot POST /offers or PATCH /offers/by_barcode/{barcode}.",
                    "payload": payload,
                },
                ensure_ascii=False,
            )
        )
        return

    adapter = TakealotAdapter(_credentials())
    result = adapter.create_or_update_offer(
        barcode=args.barcode,
        sku=args.sku,
        selling_price=args.selling_price,
        quantity=max(1, args.quantity),
        minimum_leadtime_days=max(1, args.minimum_leadtime_days),
    )
    if result.get("batch_id") and result.get("batch_status") not in {"success", "failed"}:
        batch_id = int(result["batch_id"])
        for _ in range(max(1, args.max_polls)):
            time.sleep(max(1, args.poll_seconds))
            batch_status = adapter.get_offer_batch_status(batch_id)
            result["batch_status"] = batch_status.get("status")
            result["batch_status_payload"] = batch_status
            if batch_status.get("status") in {"success", "failed"}:
                refreshed_offer = adapter.get_offer_by_barcode(args.barcode)
                if refreshed_offer is not None:
                    result = {
                        **refreshed_offer,
                        "batch_id": batch_id,
                        "batch_status": batch_status.get("status"),
                        "batch_status_payload": batch_status,
                    }
                break
    print(
        json.dumps(
            {
                "mode": "execute",
                "barcode": args.barcode,
                "sku": args.sku,
                "result": result,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
