from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Python Playwright is required. Run: python -m pip install playwright && "
        "python -m playwright install chromium"
    ) from exc


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "XiaoheiERP" / "takealot-portal-profile"
)
DEFAULT_PORTAL_URL = os.environ.get("XH_TAKEALOT_PORTAL_URL", "https://seller.takealot.com")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply leadtime buyable patch via logged-in Seller Portal browser session")
    parser.add_argument("--offer-id", required=True, type=int)
    parser.add_argument("--leadtime-days", required=True, type=int)
    parser.add_argument("--merchant-warehouse-id", required=True, type=int)
    parser.add_argument("--quantity", required=True, type=int)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--portal-url", default=DEFAULT_PORTAL_URL)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually send the PATCH requests using the current logged-in seller portal session",
    )
    args = parser.parse_args()

    payloads = [
        {
            "step": "leadtime_days",
            "body": {
                "leadtime_days": max(1, args.leadtime_days),
            },
        },
        {
            "step": "leadtime_stock_reenable",
            "body": {
                "leadtime_stock": [
                    {
                        "merchant_warehouse_id": args.merchant_warehouse_id,
                        "quantity": max(1, args.quantity),
                    }
                ],
                "status_action": "Re-enable",
            },
        },
    ]

    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "offer_id": args.offer_id,
                    "payloads": payloads,
                },
                ensure_ascii=False,
            )
        )
        return

    target_url = f"https://seller-api.takealot.com/v2/offers/offer/{args.offer_id}"

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            headless=False,
        )
        page = context.new_page()
        page.goto(args.portal_url, wait_until="domcontentloaded")
        results = []
        for item in payloads:
            result = page.evaluate(
                """async ({ url, body }) => {
                    const authRaw = localStorage.getItem('usr_st_auth');
                    const auth = authRaw ? JSON.parse(authRaw) : null;
                    const token = auth?.api_key || null;
                    if (!token) {
                      return { status: 0, body: { message: "Missing usr_st_auth.api_key in localStorage" } };
                    }
                    const response = await fetch(url, {
                      method: "PATCH",
                      credentials: "include",
                      headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/plain, */*"
                      },
                      body: JSON.stringify(body)
                    });
                    const text = await response.text();
                    let data = null;
                    try {
                      data = text ? JSON.parse(text) : null;
                    } catch (_) {
                      data = { raw: text };
                    }
                    return {
                      status: response.status,
                      body: data,
                    };
                }""",
                {"url": target_url, "body": item["body"]},
            )
            results.append({"step": item["step"], **result})
        context.close()

    print(
        json.dumps(
            {
                "mode": "execute",
                "offer_id": args.offer_id,
                "results": results,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
