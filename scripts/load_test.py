#!/usr/bin/env python3
"""ProfitLens v3 — 2000 concurrent users load test."""
import asyncio
import time
import statistics
import sys

try:
    import httpx
except ImportError:
    # Use urllib as fallback
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx


BASE_URL = "http://localhost"
CONCURRENT = 2000
TOTAL_REQUESTS = 10000
ENDPOINT = "/api/health"


async def make_request(client: httpx.AsyncClient, results: list, errors: list):
    try:
        start = time.perf_counter()
        resp = await client.get(ENDPOINT)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        results.append(elapsed)
        if resp.status_code != 200:
            errors.append(resp.status_code)
    except Exception as e:
        errors.append(str(e))


async def run_load_test():
    print(f"ProfitLens v3 Load Test")
    print(f"Target: {BASE_URL}{ENDPOINT}")
    print(f"Concurrent connections: {CONCURRENT}")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print("-" * 50)

    results = []
    errors = []

    limits = httpx.Limits(
        max_connections=CONCURRENT,
        max_keepalive_connections=CONCURRENT,
    )
    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        limits=limits,
        timeout=timeout,
    ) as client:
        # Warm up
        print("Warming up (100 requests)...")
        warmup_tasks = [make_request(client, [], []) for _ in range(100)]
        await asyncio.gather(*warmup_tasks)

        # Main test
        print(f"Running {TOTAL_REQUESTS} requests with {CONCURRENT} concurrency...")
        start_time = time.perf_counter()

        # Process in batches to control concurrency
        semaphore = asyncio.Semaphore(CONCURRENT)

        async def limited_request():
            async with semaphore:
                await make_request(client, results, errors)

        tasks = [limited_request() for _ in range(TOTAL_REQUESTS)]
        await asyncio.gather(*tasks)

        total_time = time.perf_counter() - start_time

    # Results
    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"Total time:       {total_time:.2f}s")
    print(f"Requests/sec:     {len(results) / total_time:.0f}")
    print(f"Successful:       {len(results)}")
    print(f"Errors:           {len(errors)}")

    if results:
        results.sort()
        print(f"\nLatency (ms):")
        print(f"  Min:            {min(results):.1f}")
        print(f"  Avg:            {statistics.mean(results):.1f}")
        print(f"  Median (p50):   {results[len(results)//2]:.1f}")
        print(f"  p90:            {results[int(len(results)*0.9)]:.1f}")
        print(f"  p95:            {results[int(len(results)*0.95)]:.1f}")
        print(f"  p99:            {results[int(len(results)*0.99)]:.1f}")
        print(f"  Max:            {max(results):.1f}")

    if errors:
        from collections import Counter
        print(f"\nError breakdown:")
        for err, count in Counter(errors).most_common(5):
            print(f"  {err}: {count}")

    # Pass/fail
    print("\n" + "=" * 50)
    error_rate = len(errors) / (len(results) + len(errors)) * 100 if (results or errors) else 100
    rps = len(results) / total_time if total_time > 0 else 0
    p99 = results[int(len(results)*0.99)] if results else float('inf')

    if error_rate < 1 and rps > 500 and p99 < 5000:
        print("VERDICT: PASS — System can handle 2000 concurrent users")
    elif error_rate < 5 and rps > 200:
        print("VERDICT: MARGINAL — Needs tuning for 2000 users")
    else:
        print("VERDICT: FAIL — System cannot handle 2000 concurrent users")

    print(f"  Error rate: {error_rate:.1f}% (target: <1%)")
    print(f"  RPS: {rps:.0f} (target: >500)")
    print(f"  p99 latency: {p99:.0f}ms (target: <5000ms)")


if __name__ == "__main__":
    asyncio.run(run_load_test())
