# Phase 1 Platform Isolation and Product Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate online traffic from heavy sync/repricing workloads, add honest sync progress, and ship product thumbnails plus clickable Takealot title links in `商品管理` and `自动出价`.

**Architecture:** Keep the current FastAPI + PostgreSQL + Redis + Celery modular monolith, but split workload routing more explicitly, move product sync into its own async path with Redis-backed admission/progress state, and stage product media enrichment so image/link data can improve without blocking the online UI. Frontend changes should consume the new sync-status endpoints, render thumbnails safely, and open Takealot product pages in a new tab from the product title.

**Tech Stack:** FastAPI, SQLAlchemy async, Redis, Celery, Nginx, Vue 3, Element Plus, TypeScript, Docker Compose

---

## Scope Notes

This plan intentionally covers only the first implementation slice from the commercial-readiness spec:

- queue isolation and routing cleanup
- basic admission control for product sync
- honest sync progress reporting
- staged product sync with image/link persistence
- thumbnail rendering in `商品管理` and `自动出价`
- clickable product-title links to Takealot

This plan does **not** include:

- object storage or CDN mirroring
- read replicas
- full global caching rollout for every endpoint
- per-tenant billing or quota UI

## Repository Reality Check

- There is currently **no automated backend or frontend test suite** in this repo.
- Validation for this plan must use:
  - Python compilation
  - frontend build
  - frontend lint
  - docker compose config validation
  - targeted manual smoke checks through the UI/API

## File Map

### Backend infrastructure and routing

- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/config.py`
  - Add explicit settings for sync admission limits and Redis connection budget.
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py`
  - Add `sync` and `repricing` queue routing for clearer workload separation.
- Modify: `/Users/Apple/Projects/profitlens-v3/docker/docker-compose.yml`
  - Split workers so sync and repricing no longer compete with listing/scrape pools.
- Modify: `/Users/Apple/Projects/profitlens-v3/docker/docker-compose.prod.yml`
  - Preserve the worker split in production overrides.

### Product sync orchestration

- Create: `/Users/Apple/Projects/profitlens-v3/backend/app/services/product_sync_progress_service.py`
  - Redis-backed admission and progress helpers for product sync.
- Create: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/product_sync_tasks.py`
  - Async product sync and image-enrichment task entrypoints.
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/bid_service.py`
  - Keep core offer upsert logic, but persist `takealot_url`, improve image extraction, and avoid blanking existing media fields.
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/takealot_api.py`
  - Add read-only richer offer-detail helper(s) for media fallback.

### Backend API surface

- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/products.py`
  - Route product sync through new async task flow, return honest enqueue responses, expose sync status, and return `takealot_url`.
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/bids.py`
  - Route bid-page sync through the same new async task flow, expose sync status, and return `takealot_url`.

### Frontend API and UI

- Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/api/index.ts`
  - Add sync-status API methods for product and bid pages.
- Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/views/ProductListView.vue`
  - Render thumbnail column, clickable title link, and honest sync progress state.
- Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/views/BidConsoleView.vue`
  - Render thumbnail column, clickable title link, and honest sync progress state.

## Task 1: Split worker routing and add capacity knobs

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/config.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/docker/docker-compose.yml`
- Modify: `/Users/Apple/Projects/profitlens-v3/docker/docker-compose.prod.yml`
- Test: no repo-native tests; validate with `docker compose ... config --quiet` and Python compile

- [ ] **Step 1: Add sync/admission settings in `config.py`**

Add explicit settings instead of scattering literals:

```python
    # --- Sync admission / workload isolation ---
    product_sync_max_inflight_per_user: int = 2
    product_sync_max_inflight_per_store: int = 1
    product_sync_progress_ttl_seconds: int = 7200
    product_image_enrich_batch_size: int = 100
    redis_max_connections: int = 200
```

Also update Redis client creation later to use `settings.redis_max_connections` instead of a hard-coded number.

- [ ] **Step 2: Route sync and repricing tasks explicitly in `celery_app.py`**

Replace the coarse routing with queue names that match the platform spec:

```python
    task_default_queue="default",
    task_routes={
        "app.tasks.product_sync_tasks.*": {"queue": "sync"},
        "app.tasks.bid_tasks.run_autobid_cycle": {"queue": "repricing"},
        "app.tasks.listing_tasks.*": {"queue": "listing"},
        "app.tasks.dropship_tasks.*": {"queue": "listing"},
        "app.tasks.scrape_tasks.*": {"queue": "scrape"},
        "app.tasks.snapshot_tasks.*": {"queue": "snapshot"},
    },
```

And add the new task module to `include=[...]`:

```python
        "app.tasks.product_sync_tasks",
```

- [ ] **Step 3: Split worker commands in `docker-compose.yml`**

Keep the current `listing` and `scrape` isolation, but add dedicated workers for `sync` and `repricing`:

```yaml
  celery-worker-sync:
    command: >
      celery -A app.tasks.celery_app worker
      -Q sync
      --concurrency=${CELERY_SYNC_CONCURRENCY:-2}
      --loglevel=info
      --max-tasks-per-child=500

  celery-worker-repricing:
    command: >
      celery -A app.tasks.celery_app worker
      -Q repricing
      --concurrency=${CELERY_REPRICING_CONCURRENCY:-2}
      --loglevel=info
      --max-tasks-per-child=500
```

Update the existing default worker to remove sync/repricing responsibilities:

```yaml
      -Q default,snapshot
```

- [ ] **Step 4: Mirror the worker split in `docker-compose.prod.yml`**

Carry the new worker services into prod overrides with the same baked-code volume policy as other workers:

```yaml
  celery-worker-sync:
    volumes:
      - backend_output:/app/output

  celery-worker-repricing:
    volumes:
      - backend_output:/app/output
```

- [ ] **Step 5: Validate infra config compiles cleanly**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3 && \
docker compose --env-file docker/.env -f docker/docker-compose.yml config --quiet && \
docker compose --env-file docker/.env -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config --quiet && \
python3 -m compileall -q backend/app
```

Expected:

- no compose validation errors
- no Python compilation errors

- [ ] **Step 6: Commit**

```bash
cd /Users/Apple/Projects/profitlens-v3
git add backend/app/config.py backend/app/tasks/celery_app.py docker/docker-compose.yml docker/docker-compose.prod.yml
git commit -m "feat: isolate sync and repricing workers"
```

## Task 2: Add Redis-backed product-sync admission and progress helpers

**Files:**
- Create: `/Users/Apple/Projects/profitlens-v3/backend/app/services/product_sync_progress_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/database.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/products.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/bids.py`
- Test: no repo-native tests; validate with compile and targeted API smoke

- [ ] **Step 1: Create `product_sync_progress_service.py`**

Use the existing scrape/dropship Redis progress style, but scope it by store:

```python
from __future__ import annotations

import json
from datetime import datetime

from app.config import get_settings


def _lock_key(store_id: int) -> str:
    return f"product_sync_lock:{store_id}"


def _progress_key(store_id: int) -> str:
    return f"product_sync_progress:{store_id}"


async def try_acquire_sync(redis, store_id: int) -> bool:
    settings = get_settings()
    return bool(await redis.set(_lock_key(store_id), "1", nx=True, ex=settings.product_sync_progress_ttl_seconds))


async def release_sync(redis, store_id: int) -> None:
    await redis.delete(_lock_key(store_id))


async def get_progress(redis, store_id: int) -> dict:
    raw = await redis.get(_progress_key(store_id))
    if not raw:
        return {"running": False, "stage": "idle"}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"running": False, "stage": "idle"}


async def set_progress(redis, store_id: int, **fields) -> None:
    settings = get_settings()
    current = await get_progress(redis, store_id)
    current.update(fields)
    current["running"] = True
    current["updated_at"] = datetime.utcnow().isoformat()
    await redis.setex(_progress_key(store_id), settings.product_sync_progress_ttl_seconds, json.dumps(current, default=str))


async def clear_progress(redis, store_id: int, *, result: str = "done", **fields) -> None:
    settings = get_settings()
    payload = {"running": False, "stage": result}
    payload.update(fields)
    payload["updated_at"] = datetime.utcnow().isoformat()
    await redis.setex(_progress_key(store_id), settings.product_sync_progress_ttl_seconds, json.dumps(payload, default=str))
```

- [ ] **Step 2: Wire Redis max-connection setting into `database.py`**

Replace the Redis pool constant:

```python
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
    )
```

- [ ] **Step 3: Add `/sync/status` endpoints**

In `api/products.py` add:

```python
@router.get("/sync/status")
async def products_sync_status(store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn):
    await _require_store(db, store_id, user.id)
    from app.services import product_sync_progress_service
    progress = await product_sync_progress_service.get_progress(redis, store_id)
    return {"ok": True, **progress}
```

In `api/bids.py` add the bid-page equivalent:

```python
@router.get("/products/sync/status")
async def bid_sync_status(store_id: int, user: ActiveUser, db: DbSession, redis: RedisConn):
    await _require_store(db, store_id, user.id)
    from app.services import product_sync_progress_service
    progress = await product_sync_progress_service.get_progress(redis, store_id)
    return {"ok": True, **progress}
```

- [ ] **Step 4: Change sync-start endpoints to be honest and admission-aware**

In both `api/products.py` and `api/bids.py`, replace the fire-and-forget start path with:

```python
    from app.services import product_sync_progress_service
    from app.tasks.product_sync_tasks import run_product_sync

    acquired = await product_sync_progress_service.try_acquire_sync(redis, store_id)
    if not acquired:
        progress = await product_sync_progress_service.get_progress(redis, store_id)
        return {"ok": False, "running": True, **progress}

    await product_sync_progress_service.set_progress(
        redis, store_id, stage="queued", message="任务已提交，等待同步开始..."
    )
    task = run_product_sync.delay(store_id)
    return {"ok": True, "async": True, "task_id": task.id, "stage": "queued"}
```

Note: update the route signatures to accept `redis: RedisConn`.

- [ ] **Step 5: Validate compile and smoke the new status endpoints**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3 && python3 -m compileall -q backend/app
```

Then smoke manually after the stack is running:

```bash
curl -s http://localhost:8000/api/products/1/sync/status
curl -s http://localhost:8000/api/bids/1/products/sync/status
```

Expected:

- JSON shape includes `running` and `stage`

- [ ] **Step 6: Commit**

```bash
cd /Users/Apple/Projects/profitlens-v3
git add backend/app/services/product_sync_progress_service.py backend/app/database.py backend/app/api/products.py backend/app/api/bids.py
git commit -m "feat: add product sync admission and progress endpoints"
```

## Task 3: Move product sync into dedicated async tasks and persist media/link fields

**Files:**
- Create: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/product_sync_tasks.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/bid_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/takealot_api.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/products.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/bids.py`
- Test: compile + targeted manual sync smoke

- [ ] **Step 1: Add a dedicated product-sync task module**

Create `product_sync_tasks.py` with two tasks:

```python
from __future__ import annotations

import asyncio
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="app.tasks.product_sync_tasks.run_product_sync", max_retries=2, default_retry_delay=30)
def run_product_sync(self, store_id: int):
    async def _run():
        from app.database import task_db_session
        from app.services import bid_service, product_sync_progress_service, store_service
        import redis.asyncio as aioredis
        from app.config import get_settings

        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            async with task_db_session() as db:
                store = await store_service.get_store_admin(db, store_id)
                if not store:
                    await product_sync_progress_service.clear_progress(redis, store_id, result="error", error="store_not_found")
                    return {"ok": False, "error": "store not found"}

                await product_sync_progress_service.set_progress(redis, store_id, stage="syncing", message="正在同步商品主数据...")
                result = await bid_service.sync_bid_products(db, store)
                await db.commit()

                missing_image_offer_ids = result.get("missing_image_offer_ids", [])
                if missing_image_offer_ids:
                    run_product_image_enrichment.delay(store_id, missing_image_offer_ids[:])
                    await product_sync_progress_service.set_progress(
                        redis, store_id, stage="enriching_images", queued_image_jobs=len(missing_image_offer_ids)
                    )
                else:
                    await product_sync_progress_service.clear_progress(redis, store_id, result="done", **result)
                return result
        finally:
            await redis.aclose()

    return _run_async(_run())


@celery_app.task(bind=True, name="app.tasks.product_sync_tasks.run_product_image_enrichment", max_retries=2, default_retry_delay=30)
def run_product_image_enrichment(self, store_id: int, offer_ids: list[str]):
    ...
```

Use the second task to fill images only for products still missing them, then call `clear_progress(..., result="done")`.

- [ ] **Step 2: Add read-only richer-offer media helper(s) in `takealot_api.py`**

Add a helper that does not mutate anything:

```python
    async def get_offer_media_detail(self, offer_id: str) -> dict:
        seller_detail = await self.get_offer_detail(offer_id)
        if seller_detail:
            return seller_detail
        try:
            return await self.get_marketplace_offer(offer_id)
        except RuntimeError:
            return {}
```

This keeps fallback logic in the API client instead of hard-coding request details inside `bid_service.py`.

- [ ] **Step 3: Add focused media extraction helpers in `bid_service.py`**

Create helper functions near `sync_bid_products()`:

```python
def _extract_offer_takealot_url(offer: dict) -> str:
    for key in ("offer_url", "product_url", "url"):
        value = str(offer.get(key) or "").strip()
        if value.startswith("http"):
            return value
    return ""


def _extract_offer_image_url(offer: dict) -> str:
    for key in ("image_url", "image", "main_image", "thumbnail"):
        value = str(offer.get(key) or "").strip()
        if value.startswith("http"):
            return value

    images = offer.get("images") or offer.get("image_urls") or []
    if isinstance(images, list):
        for item in images:
            if isinstance(item, str) and item.startswith("http"):
                return item
            if isinstance(item, dict):
                for subkey in ("url", "src", "image_url"):
                    subval = str(item.get(subkey) or "").strip()
                    if subval.startswith("http"):
                        return subval
    return ""
```

- [ ] **Step 4: Make `sync_bid_products()` persist `takealot_url` and preserve existing media**

Replace the current inline media fields:

```python
            offer_url = _extract_offer_takealot_url(offer)
            image_url = _extract_offer_image_url(offer)
```

Populate `data` with:

```python
                "image_url": image_url,
                "takealot_url": offer_url,
```

When updating an existing product, do **not** blank media fields:

```python
                for k, v in data.items():
                    if k in ("offer_id",):
                        continue
                    if k in ("image_url", "takealot_url") and not v:
                        continue
                    if v is not None:
                        setattr(existing, k, v)
```

Track missing-image products for later enrichment:

```python
    missing_image_offer_ids: list[str] = []
    ...
            if not image_url:
                missing_image_offer_ids.append(offer_id)
```

Return them:

```python
    return {
        "ok": True,
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "missing_image_offer_ids": missing_image_offer_ids,
    }
```

- [ ] **Step 5: Add image-enrichment update logic**

Inside `run_product_image_enrichment`, use the richer-offer helper and update only missing fields:

```python
media = await api.get_offer_media_detail(offer_id)
image_url = bid_service._extract_offer_image_url(media)
takealot_url = bid_service._extract_offer_takealot_url(media)
if image_url or takealot_url:
    product = await bid_service.get_bid_product(db, store_id, offer_id)
    if product:
        if image_url and not product.image_url:
            product.image_url = image_url
        if takealot_url and not product.takealot_url:
            product.takealot_url = takealot_url
```

Update progress after batches:

```python
await product_sync_progress_service.set_progress(
    redis,
    store_id,
    stage="enriching_images",
    processed=processed,
    total=len(offer_ids),
)
```

- [ ] **Step 6: Expose `takealot_url` in API payloads**

In `api/products.py` add:

```python
            "takealot_url": p.takealot_url,
```

and in product detail:

```python
            "takealot_url": product.takealot_url,
```

In `api/bids.py` add:

```python
            "takealot_url": p.takealot_url,
```

- [ ] **Step 7: Validate sync flow**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3 && python3 -m compileall -q backend/app
```

Then trigger a sync manually and verify:

```bash
curl -s -X POST http://localhost:8000/api/products/1/sync
curl -s http://localhost:8000/api/products/1/sync/status
curl -s http://localhost:8000/api/products/1 | head
```

Expected:

- sync endpoint returns `async: true`
- status endpoint moves through `queued` / `syncing` / `enriching_images` / `done`
- product payload now contains `image_url` and `takealot_url`

- [ ] **Step 8: Commit**

```bash
cd /Users/Apple/Projects/profitlens-v3
git add backend/app/tasks/product_sync_tasks.py backend/app/services/bid_service.py backend/app/services/takealot_api.py backend/app/api/products.py backend/app/api/bids.py
git commit -m "feat: stage product sync and persist takealot media"
```

## Task 4: Add short-TTL cache for hot sync/status reads

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/products.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/bids.py`
- Test: compile + manual API smoke

- [ ] **Step 1: Cache product-sync status reads**

Wrap sync-status endpoints with a tiny Redis TTL so repeated polling from many browsers stays cheap:

```python
    cache_key = f"product_sync_status_cache:{store_id}"
    cached = await redis.get(cache_key)
    if cached:
        return {"ok": True, **json.loads(cached)}

    progress = await product_sync_progress_service.get_progress(redis, store_id)
    await redis.setex(cache_key, 3, json.dumps(progress))
    return {"ok": True, **progress}
```

- [ ] **Step 2: Cache bid status endpoint**

In `api/bids.py`, use a similar short TTL for `/status`:

```python
    cache_key = f"bid_status_cache:{store_id}"
    cached = await redis.get(cache_key)
    if cached:
        return {"ok": True, "state": json.loads(cached)}

    state = await bid_service.get_engine_state(db, store_id)
    ...
    await redis.setex(cache_key, 10, json.dumps(state, default=str))
    return {"ok": True, "state": state}
```

Keep this small and conservative; do **not** cache filtered list payloads in this task.

- [ ] **Step 3: Validate cached endpoints**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3 && python3 -m compileall -q backend/app
```

Then hit the endpoints repeatedly:

```bash
for i in 1 2 3; do curl -s http://localhost:8000/api/bids/1/status >/dev/null; done
for i in 1 2 3; do curl -s http://localhost:8000/api/products/1/sync/status >/dev/null; done
```

Expected:

- no errors
- polling remains fast and stable

- [ ] **Step 4: Commit**

```bash
cd /Users/Apple/Projects/profitlens-v3
git add backend/app/api/products.py backend/app/api/bids.py
git commit -m "feat: cache hot sync and status reads"
```

## Task 5: Update `商品管理` to show sync progress, thumbnails, and Takealot links

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/api/index.ts`
- Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/views/ProductListView.vue`
- Test: frontend build/lint + browser smoke

- [ ] **Step 1: Add sync-status client methods**

In `frontend/src/api/index.ts` extend `productApi`:

```ts
  syncStatus: (storeId: number) => http.get(`/products/${storeId}/sync/status`),
```

Extend `bidApi`:

```ts
  syncStatus: (storeId: number) => http.get(`/bids/${storeId}/products/sync/status`),
```

- [ ] **Step 2: Replace optimistic “同步完成” flow in `ProductListView.vue`**

Add sync-progress state and polling:

```ts
const syncProgress = ref<any>({ running: false, stage: 'idle' })
let syncTimer: ReturnType<typeof setInterval> | null = null

async function fetchSyncStatus() {
  if (!storeStore.activeStoreId) return
  const { data } = await productApi.syncStatus(storeStore.activeStoreId)
  syncProgress.value = data || { running: false, stage: 'idle' }
  if (!syncProgress.value.running && syncTimer) {
    clearInterval(syncTimer)
    syncTimer = null
    fetchProducts()
  }
}
```

Change `syncProducts()` to:

```ts
async function syncProducts() {
  if (!storeStore.activeStoreId) return
  syncing.value = true
  try {
    const { data } = await productApi.sync(storeStore.activeStoreId)
    if (data.running) {
      ElMessage.warning('该店铺已有同步任务在运行')
    } else {
      ElMessage.success('同步任务已提交')
    }
    await fetchSyncStatus()
    if (!syncTimer) syncTimer = setInterval(fetchSyncStatus, 3000)
  } finally {
    syncing.value = false
  }
}
```

- [ ] **Step 3: Add thumbnail column and clickable title**

Update the table markup to include:

```vue
<el-table-column label="图片" width="84" align="center">
  <template #default="{ row }">
    <img
      v-if="row.image_url"
      :src="row.image_url"
      alt=""
      style="width: 48px; height: 48px; object-fit: cover; border-radius: 6px; border: 1px solid #ebeef5"
    />
    <div
      v-else
      style="width: 48px; height: 48px; border-radius: 6px; background: #f5f7fa; color: #c0c4cc; display: flex; align-items: center; justify-content: center; margin: 0 auto"
    >图</div>
  </template>
</el-table-column>

<el-table-column label="商品标题" min-width="320" show-overflow-tooltip>
  <template #default="{ row }">
    <a
      v-if="row.takealot_url"
      :href="row.takealot_url"
      target="_blank"
      rel="noopener noreferrer"
      style="color: #409eff; text-decoration: none"
    >
      {{ row.title }}
    </a>
    <span v-else>{{ row.title }}</span>
  </template>
</el-table-column>
```

- [ ] **Step 4: Surface sync progress in the page header**

Add a small status block under the toolbar:

```vue
<el-alert
  v-if="syncProgress.running"
  :title="`同步进行中：${syncProgress.stage || 'running'}`"
  type="info"
  :closable="false"
  show-icon
  style="margin-bottom: 12px"
/>
```

- [ ] **Step 5: Validate frontend**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3/frontend && npm run build && npm run lint
```

Expected:

- build passes
- lint reports no new errors

Manual smoke:

- click “同步商品” and confirm the page shows queued/running status
- wait for completion and confirm product list refreshes
- confirm thumbnails render
- click a product title and confirm it opens Takealot in a new tab

- [ ] **Step 6: Commit**

```bash
cd /Users/Apple/Projects/profitlens-v3
git add frontend/src/api/index.ts frontend/src/views/ProductListView.vue
git commit -m "feat: add product sync progress and takealot links to product list"
```

## Task 6: Update `自动出价` to show sync progress, thumbnails, and Takealot links

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/views/BidConsoleView.vue`
- Test: frontend build/lint + browser smoke

- [ ] **Step 1: Add sync-status polling**

Reuse the same API client from Task 5 and add in `BidConsoleView.vue`:

```ts
const syncProgress = ref<any>({ running: false, stage: 'idle' })
let syncTimer: ReturnType<typeof setInterval> | null = null

async function fetchSyncStatus() {
  if (!storeStore.activeStoreId) return
  const { data } = await bidApi.syncStatus(storeStore.activeStoreId)
  syncProgress.value = data || { running: false, stage: 'idle' }
  if (!syncProgress.value.running && syncTimer) {
    clearInterval(syncTimer)
    syncTimer = null
    fetchProducts()
    fetchStatus()
  }
}
```

Change `syncBidProducts()` to:

```ts
async function syncBidProducts() {
  if (!storeStore.activeStoreId) return
  syncing.value = true
  try {
    const { data } = await bidApi.syncProducts(storeStore.activeStoreId)
    if (data.running) {
      ElMessage.warning('该店铺已有同步任务在运行')
    } else {
      ElMessage.success('商品同步任务已提交')
    }
    await fetchSyncStatus()
    if (!syncTimer) syncTimer = setInterval(fetchSyncStatus, 3000)
  } finally {
    syncing.value = false
  }
}
```

- [ ] **Step 2: Add sync-progress alert near the header**

Insert:

```vue
<el-alert
  v-if="syncProgress.running"
  :title="`商品同步中：${syncProgress.stage || 'running'}`"
  type="info"
  :closable="false"
  show-icon
  class="mb-4"
/>
```

- [ ] **Step 3: Add thumbnail column and clickable title**

Insert before SKU/title pricing controls:

```vue
<el-table-column label="图片" width="84" align="center">
  <template #default="{ row }">
    <img
      v-if="row.image_url"
      :src="row.image_url"
      alt=""
      style="width: 44px; height: 44px; object-fit: cover; border-radius: 6px; border: 1px solid #ebeef5"
    />
    <div
      v-else
      style="width: 44px; height: 44px; border-radius: 6px; background: #f5f7fa; color: #c0c4cc; display: flex; align-items: center; justify-content: center; margin: 0 auto"
    >图</div>
  </template>
</el-table-column>
```

Replace the title column:

```vue
<el-table-column label="商品名称" min-width="240" show-overflow-tooltip>
  <template #default="{ row }">
    <a
      v-if="row.takealot_url"
      :href="row.takealot_url"
      target="_blank"
      rel="noopener noreferrer"
      style="color: #409eff; text-decoration: none"
    >
      {{ row.title }}
    </a>
    <span v-else>{{ row.title }}</span>
  </template>
</el-table-column>
```

- [ ] **Step 4: Clean up timers on unmount and store switch**

Update lifecycle cleanup:

```ts
function stopSyncPolling() {
  if (syncTimer) {
    clearInterval(syncTimer)
    syncTimer = null
  }
}

watch(() => storeStore.activeStoreId, async () => {
  stopSyncPolling()
  currentPage.value = 1
  await fetchSyncStatus()
  fetchStatus()
  fetchProducts()
  if (activeTab.value === 'log') fetchLog()
})

onUnmounted(() => {
  stopAutoRefresh()
  stopSyncPolling()
})
```

- [ ] **Step 5: Validate frontend**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3/frontend && npm run build && npm run lint
```

Manual smoke:

- trigger sync from the bid page
- confirm progress banner appears
- confirm thumbnails render in the repricing table
- click a title and confirm it opens the correct Takealot page
- confirm the table refreshes after sync completion

- [ ] **Step 6: Commit**

```bash
cd /Users/Apple/Projects/profitlens-v3
git add frontend/src/views/BidConsoleView.vue
git commit -m "feat: add media and sync progress to bid console"
```

## Task 7: Final validation pass for the first slice

**Files:**
- Modify: none if all previous tasks are clean
- Test: full validation commands only

- [ ] **Step 1: Validate backend compilation**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3 && python3 -m compileall -q backend/app
```

Expected:

- no compilation errors

- [ ] **Step 2: Validate frontend build and lint**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3/frontend && npm run build && npm run lint
```

Expected:

- build succeeds
- lint has no new errors

- [ ] **Step 3: Validate docker compose configuration**

Run:

```bash
cd /Users/Apple/Projects/profitlens-v3 && \
docker compose --env-file docker/.env -f docker/docker-compose.yml config --quiet && \
docker compose --env-file docker/.env -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config --quiet
```

Expected:

- both commands exit successfully

- [ ] **Step 4: Run end-to-end smoke checks**

Check these flows manually:

```text
1. 商品管理 -> 点击同步商品 -> 看到“已提交/进行中/完成”而不是立即“同步完成”
2. 商品管理 -> 列表中有缩略图，无图时有占位
3. 商品管理 -> 点击标题，浏览器新标签打开 Takealot 页面
4. 自动出价 -> 点击同步商品 -> 看到同步进度 banner
5. 自动出价 -> 表格里有缩略图
6. 自动出价 -> 点击标题，浏览器新标签打开 Takealot 页面
7. 重复点击同步 -> 返回“已有同步任务在运行”而不是重复排队
```

- [ ] **Step 5: Commit validation checkpoint**

```bash
cd /Users/Apple/Projects/profitlens-v3
git add .
git commit -m "chore: validate phase1 platform and product media slice"
```

## Plan Self-Review

### Spec coverage

- Queue isolation and routing cleanup → Task 1
- Basic admission control → Task 2
- Honest sync progress → Task 2, Task 5, Task 6
- Staged product sync with media enrichment → Task 3
- Hot-read cache for key status polling → Task 4
- Product thumbnails → Task 5, Task 6
- Clickable Takealot title links → Task 5, Task 6

### Placeholder scan

- No `TODO` / `TBD` placeholders intentionally left.
- No test files were added because this repo currently has no automated test suite.

### Type consistency

- Redis progress payload uses `running` + `stage` consistently in backend and frontend.
- API payload name for external navigation is `takealot_url` in both product and bid pages.
- Sync endpoints stay asynchronous and return `task_id` when dispatch succeeds.
