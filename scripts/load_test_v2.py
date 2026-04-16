#!/usr/bin/env python3
"""ProfitLens v3 — realistic load test simulating 2000 users."""
import asyncio
import time
import statistics
import sys

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx


# Test against backend directly (bypass nginx rate limiting)
BASE_URL = "http://localhost:8000"

SCENARIOS = [
    {"name": "轻量 (500并发)", "concurrency": 500, "total": 5000},
    {"name": "中等 (1000并发)", "concurrency": 1000, "total": 5000},
    {"name": "高压 (2000并发)", "concurrency": 2000, "total": 10000},
]

ENDPOINTS = [
    "/api/health",
]


async def make_request(client, endpoint, results, errors):
    try:
        start = time.perf_counter()
        resp = await client.get(endpoint)
        elapsed = (time.perf_counter() - start) * 1000
        results.append(elapsed)
        if resp.status_code >= 400:
            errors.append(resp.status_code)
    except Exception as e:
        errors.append(str(e)[:50])


async def run_scenario(scenario):
    name = scenario["name"]
    concurrency = scenario["concurrency"]
    total = scenario["total"]

    print(f"\n{'='*60}")
    print(f"场景: {name}")
    print(f"并发数: {concurrency} | 总请求: {total}")
    print(f"{'='*60}")

    results = []
    errors = []

    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )
    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        limits=limits,
        timeout=timeout,
    ) as client:
        # Warm up
        warmup = [make_request(client, "/api/health", [], []) for _ in range(50)]
        await asyncio.gather(*warmup)

        semaphore = asyncio.Semaphore(concurrency)
        start_time = time.perf_counter()

        async def limited_request():
            async with semaphore:
                endpoint = ENDPOINTS[0]
                await make_request(client, endpoint, results, errors)

        tasks = [limited_request() for _ in range(total)]
        await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start_time

    # Report
    success = len(results)
    error_count = len(errors)
    total_reqs = success + error_count
    error_rate = error_count / total_reqs * 100 if total_reqs else 100
    rps = success / total_time if total_time > 0 else 0

    print(f"\n结果:")
    print(f"  总耗时:    {total_time:.2f}s")
    print(f"  RPS:       {rps:.0f}")
    print(f"  成功:      {success}")
    print(f"  失败:      {error_count} ({error_rate:.1f}%)")

    if results:
        results.sort()
        print(f"  延迟 (ms):")
        print(f"    P50:     {results[len(results)//2]:.0f}")
        print(f"    P90:     {results[int(len(results)*0.9)]:.0f}")
        print(f"    P95:     {results[int(len(results)*0.95)]:.0f}")
        print(f"    P99:     {results[int(len(results)*0.99)]:.0f}")
        print(f"    Max:     {max(results):.0f}")

    if errors:
        from collections import Counter
        print(f"  错误类型:")
        for err, count in Counter(errors).most_common(3):
            print(f"    {err}: {count}")

    # Verdict
    p99 = results[int(len(results)*0.99)] if results else float('inf')
    if error_rate < 1 and p99 < 5000:
        verdict = "PASS"
    elif error_rate < 5:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    print(f"\n  判定: {verdict}")
    return verdict


async def main():
    print("ProfitLens v3 — 并发承载能力测试")
    print(f"目标: {BASE_URL} (直连后端，绕过 Nginx)")
    print(f"测试方式: 递增并发 500 → 1000 → 2000")

    verdicts = {}
    for scenario in SCENARIOS:
        v = await run_scenario(scenario)
        verdicts[scenario["name"]] = v

    print(f"\n{'='*60}")
    print("总结:")
    for name, v in verdicts.items():
        print(f"  {name}: {v}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
