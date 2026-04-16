# Library Buyer Scrape Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复选品库手动抓取只剩 37 条重复商品的问题，并补上自动补采基础能力。

**Architecture:** 保留现有 Takealot 买家端搜索接口、Celery、Redis、PostgreSQL 链路，仅在 `library_service` 内修正类目参数与本地 Lead Time 过滤；自动补采复用同一抓取入口，并补上安全锁与 stop 清理，避免与手动任务冲突。

**Tech Stack:** FastAPI, Celery, Redis, SQLAlchemy AsyncSession, httpx, pytest, pytest-asyncio

---

### Task 1: 为选品库抓取恢复补失败测试

**Files:**
- Create: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_library_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/library_service.py`

- [ ] **Step 1: 写 `department_slug` 与分类落库失败测试**
- [ ] **Step 2: 写本地 Lead Time 过滤失败测试**
- [ ] **Step 3: 写 `cleanup_invalid_categories` 合法分类回归测试**
- [ ] **Step 4: 运行 `pytest backend/tests/test_library_service.py -q`，确认先失败**

### Task 2: 修复 Phase A 手动抓取链路

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/library_service.py`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_library_service.py`

- [ ] **Step 1: 新增展示类目到 `department_slug` 的映射辅助**
- [ ] **Step 2: 把抓取请求改成 `department_slug + 新 filter`**
- [ ] **Step 3: 把 Lead Time 改为抓回结果后本地过滤**
- [ ] **Step 4: 保持 `category_main` 继续写入展示名**
- [ ] **Step 5: 运行 `pytest backend/tests/test_library_service.py -q`，确认转绿**

### Task 3: 为自动补采补失败测试

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_library_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_bid_periodic_sync_schedule.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/scrape_tasks.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/config.py`

- [ ] **Step 1: 写自动补采调度项失败测试**
- [ ] **Step 2: 写 scrape 锁 owner / stop 清理失败测试**
- [ ] **Step 3: 运行相关 pytest，确认先失败**

### Task 4: 实现 Phase B 自动补采

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/scrape_tasks.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/config.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/docker/docker-compose.yml`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_library_service.py`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_bid_periodic_sync_schedule.py`

- [ ] **Step 1: 抽出可复用的 scrape 锁/stop 辅助**
- [ ] **Step 2: 新增自动补采 dispatcher 任务**
- [ ] **Step 3: 注册 beat 调度与默认配置**
- [ ] **Step 4: 确保自动补采与手动抓取互斥**
- [ ] **Step 5: 运行相关 pytest，确认转绿**

### Task 5: 验证与真实回填

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/docs/superpowers/specs/2026-04-16-library-buyer-scrape-recovery-design.md`

- [ ] **Step 1: 运行本次相关测试集**
- [ ] **Step 2: 手动触发一次真实选品库抓取**
- [ ] **Step 3: 验证库内数量不再停留在 37 条**
- [ ] **Step 4: 记录剩余风险与后续优化点**
