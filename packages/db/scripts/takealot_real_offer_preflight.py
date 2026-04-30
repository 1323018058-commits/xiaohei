from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from src.modules.store.adapters.base import AdapterCredentials  # noqa: E402
from src.modules.store.adapters.takealot import TakealotAdapter  # noqa: E402
from src.modules.common.dev_state import app_state  # noqa: E402
from src.platform.settings.base import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight checks for real Takealot official offer create/update")
    parser.add_argument("--barcode", required=True)
    parser.add_argument("--sku", default="XH-PREFLIGHT-001")
    parser.add_argument("--selling-price", type=float, default=299)
    parser.add_argument("--store-name", default=os.environ.get("XH_TAKEALOT_REAL_STORE_NAME", "Takealot Pilot Store"))
    args = parser.parse_args()

    api_key = os.environ.get("XH_TAKEALOT_API_KEY", "").strip()
    api_secret = os.environ.get("XH_TAKEALOT_API_SECRET", "").strip() or "takealot-api-secret-placeholder"

    configured_merchant_warehouse_id = None
    for store in app_state.list_stores():
        if store["name"] == args.store_name:
            credentials = app_state.get_store_credentials(store["id"]) or {}
            configured_merchant_warehouse_id = credentials.get("leadtime_merchant_warehouse_id")
            break

    checks: list[dict[str, object]] = []

    checks.append(
        {
            "name": "database_url",
            "ok": bool(settings.database_url),
            "detail": "XH_DATABASE_URL is configured" if settings.database_url else "XH_DATABASE_URL is missing",
        }
    )
    checks.append(
        {
            "name": "takealot_api_key",
            "ok": bool(api_key),
            "detail": "XH_TAKEALOT_API_KEY is configured" if api_key else "XH_TAKEALOT_API_KEY is missing",
        }
    )

    if not api_key:
        print(json.dumps({"ready": False, "checks": checks}, ensure_ascii=False))
        raise SystemExit(1)

    adapter = TakealotAdapter(
        AdapterCredentials(platform="takealot", api_key=api_key, api_secret=api_secret)
    )

    try:
        seller = adapter.get_seller_profile()
        warehouse_id = adapter.get_primary_seller_warehouse_id()
        existing_offer = adapter.get_offer_by_barcode(args.barcode)
        leadtime_enabled = seller.get("leadtime_enabled") if isinstance(seller, dict) else None
        leadtime_details = seller.get("leadtime_details") if isinstance(seller, dict) else None
        checks.extend(
            [
                {
                    "name": "seller_profile",
                    "ok": True,
                    "detail": str(seller.get("display_name") or seller.get("legal_name") or "seller profile fetched"),
                },
                {
                    "name": "leadtime_mode",
                    "ok": bool(leadtime_enabled) if leadtime_enabled is not None else False,
                    "detail": f"leadtime_enabled={leadtime_enabled}, leadtime_details={leadtime_details}",
                },
                {
                    "name": "leadtime_stock_config",
                    "ok": (configured_merchant_warehouse_id or settings.takealot_leadtime_merchant_warehouse_id) is not None,
                    "detail": (
                        f"merchant_warehouse_id={configured_merchant_warehouse_id or settings.takealot_leadtime_merchant_warehouse_id}; leadtime batch can submit stock and Re-enable"
                        if (configured_merchant_warehouse_id or settings.takealot_leadtime_merchant_warehouse_id) is not None
                        else "XH_TAKEALOT_LEADTIME_MERCHANT_WAREHOUSE_ID missing; leadtime batch will create/update offer but may remain not_buyable"
                    ),
                },
                {
                    "name": "seller_warehouse",
                    "ok": warehouse_id is not None,
                    "detail": f"seller_warehouse_id={warehouse_id}" if warehouse_id is not None else "No seller warehouse returned; create will fall back to leadtime mode",
                },
                {
                    "name": "barcode_offer_state",
                    "ok": True,
                    "detail": (
                        f"Existing offer found for barcode {args.barcode}; live run will PATCH"
                        if existing_offer is not None
                        else f"No offer found for barcode {args.barcode}; live run will POST /offers"
                    ),
                },
            ]
        )
    except Exception as exc:
        checks.append(
            {
                "name": "takealot_connectivity",
                "ok": False,
                "detail": str(exc),
            }
        )
        print(json.dumps({"ready": False, "checks": checks}, ensure_ascii=False))
        raise SystemExit(1)

    ready = all(bool(check["ok"]) for check in checks if check["name"] != "seller_warehouse")
    print(
        json.dumps(
            {
                "ready": ready,
                "barcode": args.barcode,
                "sku": args.sku,
                "selling_price": args.selling_price,
                "checks": checks,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
