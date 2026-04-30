from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import Error as PlaywrightError
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Python Playwright is required. Run: python -m pip install playwright && "
        "python -m playwright install chromium"
    ) from exc


ROOT = Path(__file__).resolve().parents[3]
REPORT_ROOT = ROOT / "reports" / "takealot-portal"
DEFAULT_PORTAL_URL = os.environ.get("XH_TAKEALOT_PORTAL_URL", "https://seller.takealot.com")
DEFAULT_PROFILE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "XiaoheiERP" / "takealot-portal-profile"
)

TARGET_KEYWORDS = (
    "/offers",
    "leadtime",
    "stock",
    "warehouse",
)


def _timestamp() -> str:
    return dt.datetime.now(dt.UTC).astimezone().strftime("%Y%m%d-%H%M%S")


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in {"content-type", "accept", "origin", "referer"}:
            allowed[key] = value
    return allowed


def _summarize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _summarize_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_summarize_json(item) for item in value[:5]]
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return str(value)


def _is_target_request(url: str, method: str) -> bool:
    lowered = url.lower()
    return method.upper() in {"POST", "PATCH", "PUT"} and any(keyword in lowered for keyword in TARGET_KEYWORDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Focused probe for Takealot Seller Portal offer write requests")
    parser.add_argument("--portal-url", default=DEFAULT_PORTAL_URL)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=180,
        help="How long to keep the browser open for manual interaction",
    )
    args = parser.parse_args()

    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_ROOT / f"offer-write-probe-{_timestamp()}.json"

    records: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            headless=False,
        )
        page = context.new_page()

        def on_request(request) -> None:
            if not _is_target_request(request.url, request.method):
                return
            post_data = request.post_data
            body = None
            if post_data:
                try:
                    body = json.loads(post_data)
                except json.JSONDecodeError:
                    body = {"raw": post_data[:2000]}
            records.append(
                {
                    "kind": "request",
                    "ts": dt.datetime.now(dt.UTC).isoformat(),
                    "method": request.method,
                    "url": request.url,
                    "headers": _safe_headers(dict(request.headers)),
                    "body": _summarize_json(body),
                }
            )

        def on_response(response) -> None:
            request = response.request
            if not _is_target_request(request.url, request.method):
                return
            body = None
            try:
                if "application/json" in (response.headers.get("content-type") or ""):
                    body = response.json()
            except Exception:
                body = None
            records.append(
                {
                    "kind": "response",
                    "ts": dt.datetime.now(dt.UTC).isoformat(),
                    "method": request.method,
                    "url": request.url,
                    "status": response.status,
                    "body": _summarize_json(body),
                }
            )

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            page.goto(args.portal_url, wait_until="domcontentloaded")
            print(
                "\n[Offer Write Probe]\n"
                "1. 确保你已经登录 seller.takealot.com\n"
                "2. 打开 Manage My Offers\n"
                "3. 找到一个已有报价，把 My SoH 改一个数，再改回去\n"
                "4. 把 Leadtime 从 14 days 改到 16 days，再改回去\n"
                "5. 你可以直接关闭窗口；脚本现在会自动保存已抓到的记录\n",
                flush=True,
            )
            page.wait_for_timeout(max(10, args.duration_seconds) * 1000)
        except PlaywrightError:
            pass
        finally:
            try:
                context.close()
            except Exception:
                pass

    report = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "portal_url": args.portal_url,
        "record_count": len(records),
        "records": records,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), "record_count": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
