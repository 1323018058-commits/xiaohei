from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
REPORT_ROOT = ROOT / "reports" / "takealot-portal"

sys.path.insert(0, str(API_ROOT))

from src.modules.common.dev_state import ADMIN_USER_ID, DEMO_TENANT_ID, app_state  # noqa: E402
from src.platform.db.session import get_db_session  # noqa: E402
from src.platform.settings.base import settings  # noqa: E402


def _actor() -> dict[str, str]:
    return {
        "id": ADMIN_USER_ID,
        "role": "super_admin",
        "tenant_id": DEMO_TENANT_ID,
    }


def _request_headers(label: str) -> dict[str, str]:
    return {"x-request-id": f"takealot-import-leadtime-warehouse-{label}"}


def _find_latest_report() -> Path:
    reports = sorted(REPORT_ROOT.glob("offer-write-probe-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        raise SystemExit("No offer-write-probe report found")
    return reports[0]


def _extract_warehouse_id(report: dict) -> int:
    for record in report.get("records", []):
        body = record.get("body")
        if not isinstance(body, dict):
            continue
        leadtime_stock = body.get("leadtime_stock")
        if not isinstance(leadtime_stock, list) or not leadtime_stock:
            continue
        first = leadtime_stock[0]
        if not isinstance(first, dict):
            continue
        warehouse_id = first.get("merchant_warehouse_id")
        if warehouse_id is not None:
            return int(warehouse_id)
    raise SystemExit("No merchant_warehouse_id found in report")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import hidden leadtime merchant warehouse id from probe report")
    parser.add_argument("--store-name", required=True)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else _find_latest_report()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    merchant_warehouse_id = _extract_warehouse_id(report)

    store_id = None
    for store in app_state.list_stores():
        if store["name"] == args.store_name:
            store_id = store["id"]
            break
    if store_id is None:
        raise SystemExit(f"Store not found: {args.store_name}")

    with get_db_session() as connection:
        with connection.cursor() as cursor:
            row = cursor.execute(
                """
                select pgp_sym_decrypt(dearmor(api_key_encrypted), %s) as payload
                from store_credentials
                where store_id = %s
                """,
                (settings.store_credential_encryption_key, store_id),
            ).fetchone()
            if row is None or not row["payload"]:
                raise SystemExit(f"Store credentials not found for store_id={store_id}")
            payload = json.loads(row["payload"])
            payload["leadtime_merchant_warehouse_id"] = merchant_warehouse_id
            cursor.execute(
                """
                update store_credentials
                set api_key_encrypted = armor(pgp_sym_encrypt(%s, %s)),
                    updated_at = now()
                where store_id = %s
                """,
                (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                    settings.store_credential_encryption_key,
                    store_id,
                ),
            )
        connection.commit()

    print(
        json.dumps(
            {
                "store_name": args.store_name,
                "store_id": store_id,
                "merchant_warehouse_id": merchant_warehouse_id,
                "report_path": str(report_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
