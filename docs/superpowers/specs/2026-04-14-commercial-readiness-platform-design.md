# ProfitLens Commercial Readiness Platform Design

Date: 2026-04-14
Project: ProfitLens v3
Scope: Evolve ProfitLens into a commercial-grade ERP that supports roughly 2000 concurrent online users while also handling heavy background workloads such as product sync, auto repricing, listing, dropship, scraping, and image enrichment.

Supersedes: `/Users/Apple/Projects/profitlens-v3/docs/superpowers/specs/2026-04-14-product-image-sync-design.md`

## Background

ProfitLens already has a usable single-stack architecture:

- Nginx serves the SPA and proxies API traffic.
- FastAPI runs with multiple Uvicorn workers.
- PostgreSQL stores transactional data.
- Redis is used for app cache and Celery infrastructure.
- Celery workers are split into `default` and `listing` pools.

Current deployment is good enough for a small team, but it is not yet a commercial-ready multi-tenant platform for sustained concurrent traffic plus heavy asynchronous operations.

Observed current-state characteristics:

- One backend service instance, one PostgreSQL instance, one Redis instance, one Nginx instance.
- Backend concurrency is bounded in-process rather than horizontally scaled.
- Heavy tasks and user-facing read traffic still share several dependencies and failure domains.
- Product image support exists in the schema (`bid_products.image_url`) but image sync and UI rendering are incomplete.
- Several core features already rely on Celery, which is a strong foundation for further isolation.
- Some user-triggered async flows still present optimistic “done” messaging before work is actually completed.

## Primary Goal

Build a platform architecture that can support commercial usage with two simultaneous conditions:

1. Around 2000 concurrent users browsing and performing normal ERP actions.
2. Concurrent heavy background operations including sync, repricing, listing, dropship, scraping, and image enrichment.

## Secondary Goal

Implement product image sync and image rendering in a way that fits the commercial-grade architecture instead of becoming a point solution that later needs to be rewritten.

## Non-Goals

- Full microservice decomposition in this phase.
- Multi-region deployment.
- Self-hosted object storage/CDN rollout in the first implementation phase.
- Rewriting all existing business modules.
- Solving every historical schema and migration issue in one pass.

## Problem Statement

The system must protect the online user experience from background load.

Today, a large sync, scrape, listing burst, or repricing cycle can compete indirectly for:

- database connections
- Redis throughput
- external API budgets
- worker CPU/memory
- application-level retries and timeouts

That means the right design goal is not just “make requests faster.” The real goal is:

- keep read APIs predictable
- keep auth and core navigation responsive
- isolate heavy workloads
- bound failure blast radius
- degrade gracefully under overload

## Approaches Considered

### Approach A — Continue patching the existing app feature by feature

Add image sync, add more limits, tune a few endpoints, and iterate as issues appear.

Pros:

- Lowest short-term effort.

Cons:

- High long-term rewrite risk.
- No clear separation between online and heavy workloads.
- Hard to reason about capacity and failure domains.

### Approach B — Platform hardening inside the current modular monolith (Recommended)

Keep FastAPI + PostgreSQL + Redis + Celery, but introduce stronger workload isolation, explicit queue classes, cache strategy, task admission control, and online-path protection. Fold image sync into the async workload model.

Pros:

- Reuses current codebase and infrastructure patterns.
- Can be delivered in phases.
- Strongest balance of speed, stability, and cost.

Cons:

- Requires architectural discipline and phased rollout.
- Still a monolith, so module boundaries must be enforced in code.

### Approach C — Immediate service split into many services

Separate auth, catalog, repricing, sync, listing, media, and analytics into independent services now.

Pros:

- Best theoretical long-term isolation.

Cons:

- Too much operational overhead for the current stage.
- Higher delivery risk than the business needs right now.

## Chosen Direction

Adopt Approach B.

Inside that direction, design the platform as two operating planes:

1. **Online plane** — login, browsing, dashboard reads, product views, settings, lightweight writes.
2. **Workload plane** — repricing cycles, product sync, image enrichment, listing generation, dropship execution, scraping, recovery jobs.

The core rule is:

> No heavy workflow should be able to materially degrade the online browsing path.

## Architecture Overview

### Online plane

- Nginx terminates traffic and enforces request-rate protection.
- FastAPI serves user-facing APIs with strict latency budgets.
- Read-heavy endpoints use Redis-backed caching where safe.
- Expensive user-triggered workflows become async job submissions rather than inline processing.

### Workload plane

- Celery queues are split by workload type and priority.
- Each workload class has bounded concurrency.
- Jobs are idempotent, retry-safe, and rate-limited against upstream APIs.
- Long-running jobs publish progress rather than holding open HTTP requests.

### Data plane

- PostgreSQL remains the source of truth.
- Redis is used for:
  - short-lived cache
  - distributed locks
  - queue brokering
  - throttling tokens / admission control state

## Current-State Anchors

This design intentionally builds on what already exists:

- Backend workers: `/Users/Apple/Projects/profitlens-v3/docker/docker-compose.yml`
- Queue split: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py`
- Nginx rate limiting and proxying: `/Users/Apple/Projects/profitlens-v3/docker/nginx/nginx.conf`
- App configuration and pool sizing: `/Users/Apple/Projects/profitlens-v3/backend/app/config.py`

## Design Principles

1. User-facing requests must be fast even when background jobs are busy.
2. Every heavy workflow must be resumable and safe to retry.
3. Remote API budgets must be explicitly controlled.
4. Read paths should prefer cache and snapshots where freshness allows.
5. Slow enrichments such as images must never block the basic product sync path.
6. Capacity planning must be based on queue classes and concurrency ceilings, not hope.

## Platform Design

### 1. Queue classes and workload isolation

Define explicit queue classes:

- `online-light`: very short async work triggered by UI but expected to finish fast
- `sync`: product sync, store sync, image enrichment
- `repricing`: scheduled repricing and buybox refresh
- `listing`: AI listing and browser-automation tasks
- `dropship`: supplier and order workflows
- `scrape`: library and external catalog scraping
- `maintenance`: cleanup, recovery, snapshot refresh

Rules:

- `listing`, `dropship`, and `scrape` never share workers with latency-sensitive jobs.
- `repricing` gets its own bounded worker pool because it is periodic and bursty.
- `sync` and image enrichment are separated from online requests and can be rate-limited independently.

### 2. Admission control for heavy workflows

Every heavy task submission must check:

- per-user in-flight job count
- per-store in-flight job count
- global queue saturation
- upstream API budget availability

When limits are exceeded:

- return an accepted-but-deferred response, or
- reject with a clear “queue busy” message and retry guidance

This prevents 2000 active users from all firing expensive tasks at once and collapsing shared infrastructure.

### 3. Online API protection

Protect the online browsing path by making these operations read-optimized:

- dashboard cards
- store summary views
- product lists
- repricing status pages
- notifications and admin summaries

Mechanisms:

- cache list responses and summary cards with short TTLs
- use precomputed snapshots for dashboard-like panels
- keep pagination mandatory on large list endpoints
- never do expensive remote enrichment during synchronous page loads

### 4. Database strategy

PostgreSQL remains primary, but the app should be prepared for commercial load by:

- separating online read query budgets from heavy job write bursts
- budgeting connection pools per process class instead of tuning a single default in isolation
- adding index review for hottest product/store/job tables
- enforcing predictable pagination and sort keys
- reducing ORM query fan-out on list endpoints
- preparing a future read-replica path without requiring it in phase one

Phase-one database target:

- optimize current primary for predictable response times at 2000 concurrent users
- do not require immediate sharding or service split

Important implementation note:

- connection-pool math must be validated against actual process counts because API workers and Celery workers both consume PostgreSQL connections

### 5. Redis strategy

Redis responsibilities should be partitioned logically:

- API cache keys
- lock keys
- Celery broker/result keys
- queue-budget tokens and rate-limit counters

Operationally, this means:

- define key naming conventions
- set TTLs aggressively
- avoid unbounded result retention
- track memory pressure early

Future-ready option:

- move broker/result and cache/locks to separate Redis deployments when operational load justifies it

### 6. External API budget control

Takealot, scraping sources, and image-related upstream calls must be treated as scarce resources.

Every heavy integration should have:

- bounded concurrency
- exponential backoff
- circuit-breaker style temporary suppression on repeated failures
- per-integration quotas

This is especially important for:

- product sync
- buybox refresh
- product image enrichment
- listing and dropship remote lookups

### 7. Product image sync in the platform model

Product image sync is implemented as part of the `sync` workload plane, not as an inline UI operation.

Behavior:

1. User triggers product sync.
2. Core offer data sync runs first and stores products immediately.
3. Missing-image products are queued for image enrichment in a separate async stage.
4. ERP views render available images immediately and progressively improve as enrichment completes.

Why this design:

- basic product sync stays fast
- image failures do not fail the whole sync
- image enrichment can be throttled separately
- the online product list remains responsive

Product-link strategy:

- persist a canonical `takealot_url` for each synced product whenever the upstream payload already provides an `offer_url`
- if only `PLID` and a usable slug/detail payload are available, construct a best-effort canonical product URL
- preserve an already-stored `takealot_url` if a later sync payload omits URL data

Image-source strategy:

- use seller/offer payload image first
- fall back to richer offer detail lookup only for products missing images
- preserve existing `image_url` if a later sync has no usable image

Progress strategy:

- reuse the existing Redis-backed progress pattern already used by scrape/dropship style workflows
- expose sync/enrichment progress to the UI so product sync is shown as accepted/running/completed rather than “already done”

### 8. Frontend behavior for commercial readiness

Frontend list views should assume async eventual consistency:

- `商品管理` and `自动出价` render thumbnails when available
- `商品管理` and `自动出价` render clickable product titles that open the Takealot product page in a new tab when `takealot_url` exists
- missing images show lightweight placeholders
- UI never blocks waiting for image enrichment
- sync actions show job acceptance/progress states instead of pretending work is already finished

Immediate UX correction:

- product sync entry points must stop showing “同步完成” immediately after enqueueing a background task

This aligns the UI with a queue-based backend rather than a synchronous mental model.

### 9. Observability and SLOs

Commercial readiness requires first-class visibility.

Required telemetry:

- API p50/p95/p99 latency by route family
- error rate by route family
- queue depth by queue
- task duration by task type
- task retries/failures by task type
- DB pool saturation
- Redis memory and ops/sec
- upstream API failure rates

Suggested service objectives:

- auth and core navigation APIs: low-latency, high-availability priority
- list/detail pages: predictable p95 under normal load
- heavy async jobs: eventual completion with bounded retry policy

### 10. Graceful degradation

Under overload or upstream failure:

- browsing still works
- dashboard can serve stale snapshots
- heavy job submission slows or rejects before taking down the API
- image enrichment pauses first
- scraping and non-critical recoveries yield before repricing or core sync jobs

Degradation priority from first-to-pause:

1. image enrichment
2. scraping
3. non-urgent maintenance
4. bulk sync expansion
5. listing/dropship expansions
6. core repricing
7. online API reads and auth

## Phased Delivery Plan

This project is too broad for a single implementation step. It should be delivered in phases.

### Phase 1 — Platform foundation

- define queue classes
- split worker routing cleanly
- add admission control and per-task concurrency ceilings
- add process-level database and Redis connection budgets
- add online-path protection and short-TTL caching for hot reads
- add operational metrics and dashboards

### Phase 2 — Product sync and image enrichment

- refactor product sync into staged workflow
- store image URLs more reliably
- store `takealot_url` reliably during sync
- queue missing-image enrichment separately
- add sync/enrichment progress reporting endpoints and UI polling
- render thumbnails in product and repricing views
- render product titles as external links to Takealot product pages

### Phase 3 — Business-heavy workflow hardening

- isolate listing/dropship/scrape budgets further
- add progress/state models where workflows still appear synchronous
- add per-tenant quotas and abuse protection

### Phase 4 — Scale expansion options

- optional read replica
- optional dedicated Redis roles
- horizontal backend scaling
- optional object-storage/CDN media strategy

## Error Handling Model

### Online requests

- fail fast
- return cached or stale-safe data when allowed
- never wait on heavy remote work if a queued alternative exists

### Background jobs

- must be idempotent
- must record terminal state
- must have bounded retries
- must not retry forever on validation failures

### Image enrichment

- image failures are non-fatal
- keep core product data even if image lookup fails
- mark products eligible for later re-enrichment

## Testing and Verification Strategy

### Load and capacity verification

Before claiming commercial readiness, verify:

- online browsing under representative concurrent sessions
- concurrent job submissions during sustained browsing traffic
- queue saturation behavior
- degraded-upstream behavior

### Functional verification

- product sync still works without image enrichment
- image enrichment fills missing images without blocking sync
- `商品管理` and `自动出价` both render image thumbnails safely
- `商品管理` and `自动出价` both open the correct Takealot product page when users click the product title
- product sync UI correctly distinguishes queued/running/completed states

### Operational verification

- metrics visible for API, queue, DB, Redis, upstream failures
- overload handling triggers predictably
- worker crashes do not corrupt task state

## Risks

- Single PostgreSQL and Redis deployments remain a scaling ceiling if growth is faster than expected.
- Queue isolation without observability is incomplete; metrics must ship with the architecture.
- Adding async stages without clear UX can confuse users unless progress reporting is surfaced.
- External image and marketplace payloads may vary and require defensive extraction logic.
- Connection-pool overcommit across API workers and Celery workers can exhaust PostgreSQL long before CPU saturation.

## Acceptance Criteria

The platform design is successful when:

- online browsing remains responsive during concurrent heavy workloads
- heavy workloads are admitted, queued, throttled, and retried in controlled ways
- no heavy workflow performs remote enrichment inline on user-facing page loads
- product image sync becomes an asynchronous, non-blocking enrichment path
- queued workflows communicate honest progress states to users
- `商品管理` and `自动出价` display product thumbnails
- `商品管理` and `自动出价` allow one-click navigation to the Takealot product page from the product title
- the implementation can be planned in phases rather than one unsafe “big bang”

## Recommended First Implementation Plan

The first implementation plan should target **Phase 1 + the minimal safe subset of Phase 2**:

- queue isolation and routing cleanup
- basic admission control
- hot-read cache for key list/status endpoints
- staged product sync with separate image enrichment and `takealot_url` persistence
- thumbnail rendering plus clickable Takealot title links in the two ERP views

This gives business-visible progress without sacrificing platform direction.
