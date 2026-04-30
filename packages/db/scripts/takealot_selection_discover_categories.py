from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = (
    "https://api.takealot.com/rest/v-1-16-0/"
    "searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout"
)
DEFAULT_CUSTOMER_ID = "-1452878711"
DEFAULT_CLIENT_ID = "413cba4d-fb82-474e-b89b-0dd65cb38d81"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class CategoryNode:
    name: str
    category_ref: str
    department_slug: str
    path: tuple[str, ...]
    count: int | None
    has_children: bool
    depth: int


class RequestBudgetExhausted(RuntimeError):
    pass


class RequestBudget:
    def __init__(self, max_requests: int) -> None:
        self.max_requests = max(0, max_requests)
        self.used = 0
        self.exhausted = False
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        if self.max_requests == 0:
            return True
        async with self._lock:
            if self.used >= self.max_requests:
                self.exhausted = True
                return False
            self.used += 1
            return True


@dataclass
class DiscoveryCheckpoint:
    path: Path | None
    rows: list[dict[str, Any]]
    department_summaries: list[dict[str, Any]]

    @property
    def completed_slugs(self) -> set[str]:
        return {
            str(item["slug"])
            for item in self.department_summaries
            if item.get("slug") and item.get("completed")
        }

    def save(self, *, output_path: str | None = None) -> None:
        if output_path:
            write_csv(Path(output_path), self.rows)
        if self.path is None:
            return
        payload = {
            "rows": self.rows,
            "department_summaries": self.department_summaries,
            "row_count": len(self.rows),
            "saved_at_epoch": time.time(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)


def load_checkpoint(path: Path) -> DiscoveryCheckpoint:
    if not path.exists():
        return DiscoveryCheckpoint(path, [], [])
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    summaries = payload.get("department_summaries") if isinstance(payload, dict) else None
    return DiscoveryCheckpoint(
        path,
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else [],
        [item for item in summaries if isinstance(item, dict)] if isinstance(summaries, list) else [],
    )


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.monotonic()
    args.fetch_count = 0
    args.retry_count = 0
    args.rate_limited_count = 0
    checkpoint = load_checkpoint(Path(args.checkpoint_json)) if args.checkpoint_json else DiscoveryCheckpoint(None, [], [])
    global_request_budget = RequestBudget(args.max_requests)
    headers = {
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=args.concurrency * 2, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, limits=limits, follow_redirects=True) as client:
        departments = await fetch_departments(client, args, request_budget=global_request_budget)
        if args.department:
            wanted = {item.strip() for item in args.department if item.strip()}
            departments = [item for item in departments if item["slug"] in wanted or item["name"] in wanted]
        leaves, department_summaries = await discover_leaves(
            client,
            args,
            departments,
            global_request_budget=global_request_budget,
            checkpoint=checkpoint,
        )

    rows = dedupe_rows(checkpoint.rows + [node_to_row(node) for node in leaves])
    if args.output:
        write_csv(Path(args.output), rows)
    all_department_summaries = dedupe_department_summaries(checkpoint.department_summaries + department_summaries)
    return {
        "department_count": len(departments),
        "leaf_count": len(rows),
        "fetches": args.fetch_count,
        "retries": args.retry_count,
        "rate_limited": args.rate_limited_count,
        "request_limited": global_request_budget.exhausted,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "output": args.output,
        "checkpoint": str(checkpoint.path) if checkpoint.path else None,
        "resumed_department_count": len(checkpoint.completed_slugs),
        "departments": all_department_summaries,
        "sample": rows[: min(5, len(rows))],
    }


async def fetch_departments(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    *,
    request_budget: RequestBudget | None = None,
) -> list[dict[str, Any]]:
    payload = await fetch_payload(client, args, request_budgets=tuple(item for item in (request_budget,) if item))
    departments: list[dict[str, Any]] = []
    for entry in department_entries(payload):
        slug = text_value(entry, "slug")
        name = text_value(entry, "display_value")
        if not slug or not name:
            continue
        departments.append(
            {
                "slug": slug,
                "name": name,
                "value": text_value(entry, "value"),
                "count": integer_value(entry.get("num_docs")),
            }
        )
    return departments


async def discover_leaves(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    departments: list[dict[str, Any]],
    *,
    global_request_budget: RequestBudget,
    checkpoint: DiscoveryCheckpoint,
) -> tuple[list[CategoryNode], list[dict[str, Any]]]:
    leaves: list[CategoryNode] = []
    summaries: list[dict[str, Any]] = []
    completed_slugs = checkpoint.completed_slugs

    for department in departments:
        if department["slug"] in completed_slugs:
            continue
        current_leaf_count = len(checkpoint.rows) + len(leaves)
        if args.limit and current_leaf_count >= args.limit:
            break
        if global_request_budget.exhausted:
            break
        remaining_limit = args.limit - current_leaf_count if args.limit else 0
        if args.limit_per_department:
            remaining_limit = (
                min(remaining_limit, args.limit_per_department)
                if remaining_limit
                else args.limit_per_department
            )
        before_fetches = args.fetch_count
        department_leaves, request_limited, time_limited, depth_limited = await discover_department_leaves(
            client,
            args,
            department,
            remaining_limit=remaining_limit,
            global_request_budget=global_request_budget,
        )
        leaves.extend(department_leaves)
        limit_limited = bool(remaining_limit and len(department_leaves) >= remaining_limit)
        completed = not request_limited and not time_limited and not depth_limited and not limit_limited
        summary = {
            "slug": department["slug"],
            "name": department["name"],
            "leaf_count": len(department_leaves),
            "fetches": args.fetch_count - before_fetches,
            "request_limited": request_limited,
            "time_limited": time_limited,
            "depth_limited": depth_limited,
            "limit_limited": limit_limited,
            "completed": completed,
        }
        if completed:
            checkpoint.rows.extend(node_to_row(node) for node in department_leaves)
            checkpoint.rows = dedupe_rows(checkpoint.rows)
            checkpoint.department_summaries.append(summary)
            checkpoint.department_summaries = dedupe_department_summaries(checkpoint.department_summaries)
            checkpoint.save(output_path=args.output)
        else:
            summaries.append(summary)

    return leaves[: args.limit] if args.limit else leaves, summaries


async def discover_department_leaves(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    department: dict[str, Any],
    *,
    remaining_limit: int,
    global_request_budget: RequestBudget,
) -> tuple[list[CategoryNode], bool, bool, bool]:
    queue: asyncio.Queue[CategoryNode] = asyncio.Queue()
    leaves: list[CategoryNode] = []
    seen: set[tuple[str, str]] = set()
    stop_event = asyncio.Event()
    request_budget = RequestBudget(args.max_requests_per_department)
    started_at = time.monotonic()
    time_limited = False
    depth_limited = False

    def limit_reached() -> bool:
        return bool(remaining_limit and len(leaves) >= remaining_limit)

    def deadline_reached() -> bool:
        return bool(args.max_seconds_per_department and time.monotonic() - started_at >= args.max_seconds_per_department)

    root = CategoryNode(
        name=department["name"],
        category_ref=department["slug"],
        department_slug=department["slug"],
        path=(department["name"],),
        count=department.get("count"),
        has_children=True,
        depth=0,
    )
    await queue.put(root)
    seen.add((root.department_slug, root.category_ref))

    async def worker() -> None:
        nonlocal depth_limited, time_limited
        while True:
            node = await queue.get()
            try:
                if deadline_reached():
                    time_limited = True
                    stop_event.set()
                    continue
                if stop_event.is_set() or limit_reached():
                    stop_event.set()
                    continue
                if not node.has_children or node.depth >= args.max_depth:
                    if node.has_children and node.depth >= args.max_depth:
                        depth_limited = True
                    leaves.append(node)
                    if limit_reached():
                        stop_event.set()
                    continue
                if deadline_reached():
                    time_limited = True
                    stop_event.set()
                    continue
                category_slug = None if node.depth == 0 and node.category_ref == node.department_slug else node.category_ref
                children = await fetch_category_children(
                    client,
                    args,
                    department_slug=node.department_slug,
                    category_slug=category_slug,
                    parent_path=node.path,
                    parent_depth=node.depth,
                    request_budgets=(global_request_budget, request_budget),
                )
                if children is None:
                    stop_event.set()
                    continue
                if not children:
                    leaves.append(node)
                    if limit_reached():
                        stop_event.set()
                    continue
                for child in children:
                    if stop_event.is_set() or limit_reached():
                        stop_event.set()
                        break
                    key = (child.department_slug, child.category_ref)
                    if key in seen:
                        continue
                    seen.add(key)
                    await queue.put(child)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(max(1, args.concurrency))]
    await queue.join()
    for item in workers:
        item.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    if remaining_limit:
        leaves = leaves[:remaining_limit]
    return leaves, request_budget.exhausted, time_limited, depth_limited


async def fetch_category_children(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    *,
    department_slug: str,
    category_slug: str | None,
    parent_path: tuple[str, ...],
    parent_depth: int,
    request_budgets: tuple[RequestBudget, ...] = (),
) -> list[CategoryNode] | None:
    try:
        payload = await fetch_payload(
            client,
            args,
            department_slug=department_slug,
            category_slug=category_slug,
            request_budgets=request_budgets,
        )
    except RequestBudgetExhausted:
        return None
    children: list[CategoryNode] = []
    for entry in category_entries(payload):
        name = text_value(entry, "display_value")
        child_slug = text_value(entry, "category_slug")
        child_department = text_value(entry, "department_slug") or department_slug
        if not name or not child_slug:
            continue
        children.append(
            CategoryNode(
                name=name,
                category_ref=child_slug,
                department_slug=child_department,
                path=parent_path + (name,),
                count=integer_value(entry.get("num_docs")),
                has_children=bool(entry.get("has_children")),
                depth=parent_depth + 1,
            )
        )
    return children


async def fetch_payload(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    *,
    department_slug: str | None = None,
    category_slug: str | None = None,
    request_budgets: tuple[RequestBudget, ...] = (),
) -> dict[str, Any]:
    params = {
        "customer_id": args.customer_id,
        "client_id": args.client_id,
    }
    if department_slug:
        params["department_slug"] = department_slug
    if category_slug:
        params["category_slug"] = category_slug
    last_error: httpx.HTTPError | None = None
    for attempt in range(args.max_retries + 1):
        for request_budget in request_budgets:
            if not await request_budget.try_acquire():
                raise RequestBudgetExhausted("Request budget exhausted")
        args.fetch_count += 1
        try:
            response = await client.get(args.base_url, params=params)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= args.max_retries:
                raise
            args.retry_count += 1
            await asyncio.sleep(retry_delay_seconds(args, attempt, None))
            continue

        if response.status_code == 429:
            args.rate_limited_count += 1
        if response.status_code in {429, 500, 502, 503, 504} and attempt < args.max_retries:
            args.retry_count += 1
            await asyncio.sleep(retry_delay_seconds(args, attempt, response))
            continue

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected payload for {response.url}")
        if args.request_delay_ms > 0:
            await asyncio.sleep(args.request_delay_ms / 1000)
        if args.verbose:
            print(json.dumps({"event": "category_fetch", "url": str(response.url)}, ensure_ascii=False), flush=True)
        return payload
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to fetch category payload")


def retry_delay_seconds(args: argparse.Namespace, attempt: int, response: httpx.Response | None) -> float:
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after:
        try:
            return min(float(retry_after), args.retry_max_delay_ms / 1000)
        except ValueError:
            pass
    base = max(0, args.retry_base_delay_ms) / 1000
    cap = max(base, args.retry_max_delay_ms / 1000)
    delay = min(cap, base * (2 ** attempt))
    jitter = random.uniform(0, min(0.5, delay * 0.25)) if delay > 0 else 0
    return delay + jitter


def department_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in facet_results(payload):
        facet = item.get("facet") if isinstance(item, dict) else None
        discrete = facet.get("discrete_facet") if isinstance(facet, dict) else None
        if not isinstance(discrete, dict):
            continue
        if discrete.get("filter_name") != "Type":
            continue
        entries = discrete.get("entries")
        if isinstance(entries, list):
            output.extend(entry for entry in entries if isinstance(entry, dict))
    return output


def category_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in facet_results(payload):
        facet = item.get("facet") if isinstance(item, dict) else None
        tree = facet.get("tree_facet") if isinstance(facet, dict) else None
        if not isinstance(tree, dict):
            continue
        if tree.get("filter_name") != "Category":
            continue
        entries = tree.get("entries")
        if isinstance(entries, list):
            output.extend(entry for entry in entries if isinstance(entry, dict))
    return output


def facet_results(payload: dict[str, Any]) -> list[Any]:
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return []
    facets = sections.get("facets")
    if not isinstance(facets, dict):
        return []
    results = facets.get("results")
    return results if isinstance(results, list) else []


def node_to_row(node: CategoryNode) -> dict[str, Any]:
    path = list(node.path)
    return {
        "name": node.name,
        "category_ref": node.category_ref,
        "department_slug": node.department_slug,
        "main_category": path[0] if len(path) > 0 else "",
        "category_level1": path[1] if len(path) > 1 else "",
        "category_level2": path[2] if len(path) > 2 else "",
        "category_level3": " > ".join(path[3:]) if len(path) > 3 else "",
        "count": node.count if node.count is not None else "",
        "depth": node.depth,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "name",
        "category_ref",
        "department_slug",
        "main_category",
        "category_level1",
        "category_level2",
        "category_level3",
        "count",
        "depth",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        department_slug = str(row.get("department_slug") or "")
        category_ref = str(row.get("category_ref") or "")
        key = (department_slug, category_ref)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def dedupe_department_summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        slug = str(item.get("slug") or "")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        output.append(item)
    return output


def text_value(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value in (None, "") or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def integer_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover Takealot leaf categories for selection crawling")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--customer-id", default=DEFAULT_CUSTOMER_ID)
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    parser.add_argument("--department", action="append", help="Limit to a department slug or display name")
    parser.add_argument("--output", default="packages/db/seeds/takealot_selection_categories.csv")
    parser.add_argument("--checkpoint-json", help="JSON checkpoint for resumable department-level discovery")
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many leaf categories")
    parser.add_argument(
        "--limit-per-department",
        type=int,
        default=0,
        help="Stop each department after this many leaf categories; 0 disables the cap",
    )
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument(
        "--max-requests",
        type=int,
        default=0,
        help="Stop the whole run after this many HTTP attempts; 0 disables the cap",
    )
    parser.add_argument(
        "--max-requests-per-department",
        type=int,
        default=0,
        help="Stop a department after this many HTTP attempts during tree discovery; 0 disables the cap",
    )
    parser.add_argument(
        "--max-seconds-per-department",
        type=float,
        default=0,
        help="Stop a department after this many seconds during tree discovery; 0 disables the cap",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--request-delay-ms", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--retry-base-delay-ms", type=int, default=1000)
    parser.add_argument("--retry-max-delay-ms", type=int, default=12000)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = asyncio.run(main_async(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
