from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    from playwright.sync_api import Page, Response, sync_playwright
except Exception as exc:  # pragma: no cover - dependency guard for operator machines.
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

INTERESTING_KEYWORDS = (
    "shipment",
    "shipments",
    "leadtime",
    "lead-time",
    "lead_time",
    "purchase-order",
    "purchase_order",
    "orders",
    "order",
    "po",
    "fulfil",
    "fulfill",
    "delivery",
    "label",
    "sales",
)
NOISE_HOST_KEYWORDS = (
    "google-analytics",
    "googletagmanager",
    "hotjar",
    "intercom",
    "segment",
    "sentry",
    "newrelic",
    "datadog",
    "doubleclick",
    "facebook",
    "clarity",
    "cloudflareinsights",
)
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-csrf-token",
    "x-xsrf-token",
    "csrf-token",
    "x-auth-token",
}
SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|apikey|api_key|api-key|authorization|auth|cookie|"
    r"session|signature|csrf|xsrf|jwt|code)",
    re.IGNORECASE,
)
ID_SEGMENT_RE = re.compile(
    r"^(\d{3,}|[0-9a-f]{16,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def _timestamp() -> str:
    return dt.datetime.now(dt.UTC).astimezone().strftime("%Y%m%d-%H%M%S")


def _mask(value: Any, keep: int = 4) -> str:
    text = "" if value is None else str(value)
    if not text:
        return ""
    if len(text) <= keep * 2:
        return "***"
    return f"{text[:keep]}***{text[-keep:]}"


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_RE.search(key))


def _redact_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<max-depth>"
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            if _is_sensitive_key(str(key)):
                redacted[str(key)] = "***"
            else:
                redacted[str(key)] = _redact_json(child, depth=depth + 1)
        return redacted
    if isinstance(value, list):
        return [_redact_json(child, depth=depth + 1) for child in value[:5]]
    if isinstance(value, str):
        if not value:
            return ""
        return f"<string len={len(value)} sha256={_stable_hash(value)}>"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    return type(value).__name__


def _json_shape(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<max-depth>"
    if isinstance(value, dict):
        return {str(key): _json_shape(child, depth=depth + 1) for key, child in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [_json_shape(value[0], depth=depth + 1)]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key in SENSITIVE_HEADER_NAMES or _is_sensitive_key(lower_key):
            safe[key] = "***"
        elif lower_key in {"referer", "origin"}:
            safe[key] = _redact_url(value)
        elif lower_key in {"content-type", "accept", "cache-control"}:
            safe[key] = value
    return safe


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    query_items: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        query_items.append((key, "***" if _is_sensitive_key(key) else value))
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query_items, doseq=True),
            "",
        )
    )


def _route_signature(method: str, url: str) -> str:
    parsed = urlparse(url)
    segments = []
    for segment in parsed.path.strip("/").split("/"):
        if not segment:
            continue
        segments.append("{id}" if ID_SEGMENT_RE.match(segment) else segment)
    query_keys = sorted(key for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
    query_suffix = f"?{','.join(query_keys)}" if query_keys else ""
    return f"{method.upper()} {parsed.netloc}/{'/'.join(segments)}{query_suffix}"


def _is_noise_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(keyword in host for keyword in NOISE_HOST_KEYWORDS)


def _is_interesting_url(url: str) -> bool:
    lowered = url.lower()
    return any(keyword in lowered for keyword in INTERESTING_KEYWORDS)


def _should_capture(url: str, method: str, resource_type: str, capture_all: bool) -> bool:
    if _is_noise_host(url):
        return False
    if capture_all:
        return True
    if method.upper() != "GET":
        return True
    if resource_type in {"xhr", "fetch"}:
        return True
    return _is_interesting_url(url)


def _body_summary(post_data: str | None, headers: dict[str, str]) -> dict[str, Any] | None:
    if post_data is None:
        return None
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    byte_count = len(post_data.encode("utf-8", errors="ignore"))
    if "application/json" in content_type:
        try:
            data = json.loads(post_data)
        except json.JSONDecodeError:
            return {"kind": "json-invalid", "bytes": byte_count}
        return {
            "kind": "json",
            "bytes": byte_count,
            "shape": _json_shape(data),
            "redacted_preview": _redact_json(data),
        }
    if "application/x-www-form-urlencoded" in content_type:
        fields = []
        for key, value in parse_qsl(post_data, keep_blank_values=True):
            fields.append({"key": key, "value": "***" if _is_sensitive_key(key) else _mask(value)})
        return {"kind": "form", "bytes": byte_count, "fields": fields}
    if byte_count <= 512 and not SENSITIVE_KEY_RE.search(post_data):
        return {"kind": "text", "bytes": byte_count, "preview": post_data[:512]}
    return {"kind": "opaque", "bytes": byte_count, "preview": "<omitted>"}


def _response_shape(response: Response, max_bytes: int) -> dict[str, Any] | None:
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return None
    content_length = response.headers.get("content-length")
    try:
        if content_length and int(content_length) > max_bytes:
            return {"kind": "json", "omitted": f"content-length>{max_bytes}"}
    except ValueError:
        pass
    try:
        data = response.json()
    except Exception:
        return None
    return {"kind": "json", "shape": _json_shape(data)}


def _scan_dom(page: Page) -> list[dict[str, Any]]:
    keywords = [keyword.lower() for keyword in INTERESTING_KEYWORDS] + [
        "draft",
        "confirmed",
        "confirm",
        "book",
        "mark shipped",
        "add orders",
        "qty sending",
        "lead time",
        "warehouse",
    ]
    script = """
    (keywords) => {
      const nodes = Array.from(document.querySelectorAll(
        'button,a,[role="button"],input,select,textarea,[data-testid],[aria-label]'
      ));
      return nodes.slice(0, 1500).map((node) => {
        const rawText = (node.innerText || node.value || node.getAttribute('aria-label') || '').trim();
        const text = rawText.replace(/\\s+/g, ' ').slice(0, 160);
        const attrs = {};
        for (const name of ['type', 'href', 'name', 'id', 'data-testid', 'aria-label', 'disabled']) {
          const value = node.getAttribute && node.getAttribute(name);
          if (value) attrs[name] = String(value).slice(0, 180);
        }
        const className = typeof node.className === 'string' ? node.className.slice(0, 180) : '';
        const haystack = `${text} ${JSON.stringify(attrs)} ${className}`.toLowerCase();
        const matched = keywords.filter((keyword) => haystack.includes(keyword));
        if (!matched.length) return null;
        return {
          tag: node.tagName.toLowerCase(),
          text,
          attrs,
          className,
          matched
        };
      }).filter(Boolean).slice(0, 200);
    }
    """
    try:
        return page.evaluate(script, keywords)
    except Exception as exc:
        return [{"error": str(exc)}]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_summary(
    path: Path,
    *,
    portal_url: str,
    output_dir: Path,
    records: list[dict[str, Any]],
    dom_matches: list[dict[str, Any]],
    screenshot_path: Path | None,
) -> None:
    endpoint_counts: dict[str, int] = {}
    write_routes: set[str] = set()
    read_routes: set[str] = set()
    for record in records:
        route = record["route"]
        endpoint_counts[route] = endpoint_counts.get(route, 0) + 1
        if record["method"] == "GET":
            read_routes.add(route)
        else:
            write_routes.add(route)

    interesting_writes = [route for route in sorted(write_routes) if _is_interesting_url(route)]
    interesting_reads = [route for route in sorted(read_routes) if _is_interesting_url(route)]

    lines = [
        "# Takealot Seller Portal Probe",
        "",
        f"- Portal URL: `{portal_url}`",
        f"- Output: `{output_dir}`",
        f"- Captured network records: `{len(records)}`",
        f"- DOM affordance matches: `{len(dom_matches)}`",
        f"- Screenshot: `{screenshot_path.name if screenshot_path else 'disabled'}`",
        "",
        "## Candidate Write Endpoints",
    ]
    if interesting_writes:
        lines.extend(f"- `{route}`" for route in interesting_writes[:40])
    else:
        lines.append("- 暂未发现 shipment/order 相关写接口；请在 Portal 中手动打开对应页面但不要提交。")

    lines.extend(["", "## Candidate Read Endpoints"])
    if interesting_reads:
        lines.extend(f"- `{route}`" for route in interesting_reads[:60])
    else:
        lines.append("- 暂未发现 shipment/order 相关读接口。")

    lines.extend(["", "## Top Captured Routes"])
    for route, count in sorted(endpoint_counts.items(), key=lambda item: item[1], reverse=True)[:30]:
        lines.append(f"- `{count}x` `{route}`")

    lines.extend(
        [
            "",
            "## Safety Notes",
            "- 脚本不会自动点击、提交、确认、发货或改动 Takealot 数据。",
            "- `network.json` 已脱敏 Cookie、Authorization、Token、Password、API Key 等字段。",
            "- 首轮建议只登录并浏览 Leadtime Orders、Draft Shipments、Confirmed Shipments、PO detail。",
            "- 如果要捕获确认/新增/移除的真实写接口，必须先准备测试 PO，并由人工确认风险。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Non-destructive Takealot Seller Portal network probe."
    )
    parser.add_argument("--url", default=DEFAULT_PORTAL_URL, help="Seller Portal URL to open.")
    parser.add_argument(
        "--output-dir",
        default=str(REPORT_ROOT),
        help="Directory where timestamped reports are written.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Persistent browser profile directory. Keep outside the repo because it stores cookies.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Seconds to keep the browser open. 0 waits for Enter in the terminal.",
    )
    parser.add_argument("--headless", action="store_true", help="Run Chromium headless.")
    parser.add_argument(
        "--capture-all",
        action="store_true",
        help="Capture all non-noise browser requests, not just XHR/fetch/interesting URLs.",
    )
    parser.add_argument(
        "--no-response-shapes",
        action="store_true",
        help="Disable JSON response schema capture.",
    )
    parser.add_argument(
        "--max-response-bytes",
        type=int,
        default=250_000,
        help="Maximum JSON response size considered for schema extraction.",
    )
    parser.add_argument("--no-screenshot", action="store_true", help="Skip final screenshot capture.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_dir = Path(args.output_dir) / f"portal-probe-{_timestamp()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    pending: dict[int, dict[str, Any]] = {}

    print("Takealot Portal Probe starting.")
    print(f"Portal: {args.url}")
    print(f"Report: {output_dir}")
    print(f"Browser profile: {profile_dir}")
    print("安全提示：只浏览页面；首轮不要点击 Confirm / Book / Save / Mark Shipped。")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=args.headless,
            viewport={"width": 1440, "height": 1000},
            accept_downloads=False,
        )
        page = context.pages[0] if context.pages else context.new_page()

        def on_request(request: Any) -> None:
            if not _should_capture(
                request.url,
                request.method,
                request.resource_type,
                args.capture_all,
            ):
                return
            now = time.perf_counter()
            safe_headers = _redact_headers(request.headers)
            record = {
                "id": id(request),
                "started_at": dt.datetime.now(dt.UTC).isoformat(),
                "method": request.method,
                "url": _redact_url(request.url),
                "route": _route_signature(request.method, request.url),
                "resource_type": request.resource_type,
                "request_headers": safe_headers,
                "request_body": _body_summary(request.post_data, request.headers),
                "status": None,
                "response_headers": {},
                "response_shape": None,
                "duration_ms": None,
                "failure": None,
            }
            pending[id(request)] = {"record": record, "start": now}
            records.append(record)

        def finish_request(request: Any, failure: str | None = None) -> None:
            pending_item = pending.pop(id(request), None)
            if pending_item is None:
                return
            record = pending_item["record"]
            record["duration_ms"] = round((time.perf_counter() - pending_item["start"]) * 1000, 2)
            record["failure"] = failure

        def on_response(response: Response) -> None:
            pending_item = pending.get(id(response.request))
            if pending_item is None:
                return
            record = pending_item["record"]
            record["status"] = response.status
            record["response_headers"] = _redact_headers(response.headers)
            if not args.no_response_shapes:
                record["response_shape"] = _response_shape(response, args.max_response_bytes)

        context.on("request", on_request)
        context.on("response", on_response)
        context.on("requestfinished", lambda request: finish_request(request))
        context.on("requestfailed", lambda request: finish_request(request, request.failure or "failed"))

        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        print("浏览器已打开。请登录 Takealot Seller Portal，并浏览以下页面：")
        print("1) Leadtime Orders")
        print("2) Draft Shipments")
        print("3) Confirmed Shipments")
        print("4) 任意 PO / Shipment detail")
        if args.duration > 0:
            print(f"将等待 {args.duration} 秒后自动收尾。")
            time.sleep(args.duration)
        else:
            input("完成浏览后回到终端按 Enter 收尾...")

        dom_matches = _scan_dom(page)
        screenshot_path = None
        if not args.no_screenshot:
            screenshot_path = output_dir / "final-page.png"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception as exc:
                print(f"Screenshot skipped: {exc}")
                screenshot_path = None

        context.close()

    unique_routes = sorted({record["route"] for record in records})
    endpoints = [
        {
            "route": route,
            "count": sum(1 for record in records if record["route"] == route),
            "methods": sorted({record["method"] for record in records if record["route"] == route}),
            "sample_statuses": sorted(
                {
                    str(record["status"])
                    for record in records
                    if record["route"] == route and record["status"] is not None
                }
            )[:10],
            "interesting": _is_interesting_url(route),
        }
        for route in unique_routes
    ]

    _write_json(output_dir / "network.json", records)
    _write_json(output_dir / "endpoints.json", endpoints)
    _write_json(output_dir / "dom-affordances.json", dom_matches)
    _write_summary(
        output_dir / "summary.md",
        portal_url=args.url,
        output_dir=output_dir,
        records=records,
        dom_matches=dom_matches,
        screenshot_path=screenshot_path,
    )

    print("Probe complete.")
    print(f"Summary: {output_dir / 'summary.md'}")
    print(f"Network: {output_dir / 'network.json'}")
    print(f"DOM: {output_dir / 'dom-affordances.json'}")


if __name__ == "__main__":
    main()
