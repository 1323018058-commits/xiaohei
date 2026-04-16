# Extension One-Click Listing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 Chrome 扩展“立即上架”闭环，让 Takealot 商品页上的一键上架可以真正异步创建 seller offer，并把排队、成功、失败状态回流给扩展与 ERP。

**Architecture:** V1 不走现有 `listing_jobs -> listing_tasks.py` 的 Amazon/AI/loadsheet 流水线，而是新增一条独立的扩展上架通道：`extension content.js -> /api/extension/list-now -> ExtensionAction -> Celery task -> TakealotSellerAPI.create_offer_by_barcode()`。现有 `ExtensionAction` 继续承担审计与状态机职责，`buybox_service` 负责用 `plid` 补齐商品基础信息，`BidProduct` 与 `ExtensionAction` 共同承担去重。

**Tech Stack:** Chrome Extension, FastAPI, Pydantic v2, SQLAlchemy AsyncSession, Celery, Redis, Takealot Seller API, pytest, pytest-asyncio

---

## File Map

- `/Users/Apple/Projects/profitlens-v3/backend/app/schemas/extension.py`
  责任：定义扩展 `list-now` 的正式请求/响应 schema，替换裸 `dict`。
- `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_service.py`
  责任：保留 token/status/action log，并补动作查询与状态更新辅助。
- `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_listing_service.py`
  责任：扩展一键上架专用服务；做 payload 归一化、判重、商品信息回填、Takealot 提交参数组装。
- `/Users/Apple/Projects/profitlens-v3/backend/app/api/extension.py`
  责任：鉴权、参数校验、判重、落表、入队、返回前端可消费状态。
- `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/extension_tasks.py`
  责任：异步执行上架任务、写回 `ExtensionAction` 状态与远端返回结果。
- `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py`
  责任：注册扩展任务模块并接入合适队列。
- `/Users/Apple/Projects/profitlens-v3/extension/content.js`
  责任：把成功提示从“已经上架”改成“已提交/处理中”，消费新的后端响应结构。
- `/Users/Apple/Projects/profitlens-v3/extension/background.js`
  责任：继续透传 `LIST_NOW` 响应；如需要，补最近动作查询。
- `/Users/Apple/Projects/profitlens-v3/backend/tests/test_extension_list_now_api.py`
  责任：覆盖 `/api/extension/list-now` 的校验、判重、入队与返回格式。
- `/Users/Apple/Projects/profitlens-v3/backend/tests/test_extension_tasks.py`
  责任：覆盖异步任务成功/失败状态迁移。

## Scope Guard

- V1 目标是“基于已有 Takealot catalog 商品直接创建 seller offer”。
- V1 不重构 `/api/listings/jobs`、`listing_jobs`、`listing_tasks.py`。
- V1 不替换扩展授权 UX。
- V1 不新增复杂 ERP 工作台，只保证扩展和现有 `list-history` 可以看到真实状态。

### Task 1: 收紧扩展 API 合同与状态语义

**Files:**
- Create: `/Users/Apple/Projects/profitlens-v3/backend/app/schemas/extension.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/extension.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_service.py`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_extension_list_now_api.py`

- [ ] **Step 1: 为 `/api/extension/list-now` 写失败测试**
- [ ] **Step 2: 新增 `ExtensionListNowRequest` / `ExtensionListNowResponse` / `ExtensionActionHistoryItem` schema**
- [ ] **Step 3: 把 `list-now`、`list-history` 从裸 `dict` 改成 schema 驱动**
- [ ] **Step 4: 统一动作状态枚举，至少覆盖 `queued`、`processing`、`submitted`、`failed`、`already_pending`、`already_listed`**
- [ ] **Step 5: 运行 `pytest backend/tests/test_extension_list_now_api.py -q`，确认先失败再转绿**

### Task 2: 抽出扩展一键上架专用服务层

**Files:**
- Create: `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_listing_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/extension.py`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_extension_list_now_api.py`

- [ ] **Step 1: 新增 payload 归一化辅助，统一解析 `store_id`、`plid`、`barcode`、`target_price_zar`、`pricing_snapshot`**
- [ ] **Step 2: 新增 `find_pending_action()`，基于 `ExtensionAction(user_id, store_id, plid, action_status)` 判 `ALREADY_PENDING`**
- [ ] **Step 3: 新增 `find_existing_offer()`，先用 `BidProduct(store_binding_id + plid/barcode)` 判 `ALREADY_LISTED`**
- [ ] **Step 4: 新增 `hydrate_product_detail_by_plid()`，必要时复用 `buybox_service.fetch_product_detail()` 补齐标题、图片、Takealot URL**
- [ ] **Step 5: 新增 `build_create_offer_payload()`，明确 V1 默认规则：`selling_price = target_price_zar`，`rrp = max(page_price_zar, target_price_zar)`，`leadtime_days` 固定为实现方约定值**
- [ ] **Step 6: 保证条码非法或缺失时返回明确业务错误，不进入队列**

### Task 3: 把 `/api/extension/list-now` 从“记录动作”改成“记录并入队”

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/extension.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_listing_service.py`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_extension_list_now_api.py`

- [ ] **Step 1: 保留当前店铺归属校验，但在落表前先跑判重**
- [ ] **Step 2: 把 `ExtensionAction` 初始状态从 `recorded + NOT_IMPLEMENTED` 改成 `queued`**
- [ ] **Step 3: 新增任务派发，记录 `task_id` 到 `ExtensionAction.task_id`**
- [ ] **Step 4: 返回前端可直接消费的响应：`ok`、`action_id`、`status`、`message`，并在判重场景返回 `error_code=ALREADY_PENDING/ALREADY_LISTED`**
- [ ] **Step 5: 扩充 `/api/extension/list-history` 返回字段，至少包括 `task_id`、`offer_id`、`error_code`、`status`**

### Task 4: 新增扩展异步执行任务

**Files:**
- Create: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/extension_tasks.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/store_service.py`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_extension_tasks.py`

- [ ] **Step 1: 为任务成功、条码缺失、远端 API 失败写失败测试**
- [ ] **Step 2: 在任务入口读取 `ExtensionAction`，把状态改成 `processing`**
- [ ] **Step 3: 加载 `StoreBinding` 凭证并构造 `TakealotSellerAPI`**
- [ ] **Step 4: 调用 `create_offer_by_barcode()`，把远端完整响应写回 `raw_json`**
- [ ] **Step 5: 能识别 offer id 时写入 `ExtensionAction.offer_id`；识别不到时至少保存远端 submission/batch 结果到 `raw_json`**
- [ ] **Step 6: 成功时写 `submitted`，失败时写 `failed + error_code + error_msg`**
- [ ] **Step 7: 在 `celery_app.py` 注册 `extension_tasks`，并放到合适队列，避免跑在在线请求线程里**

### Task 5: 做最小闭环的数据回流

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/tasks/extension_tasks.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/extension_listing_service.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/services/bid_service.py`
- Test: `/Users/Apple/Projects/profitlens-v3/backend/tests/test_extension_tasks.py`

- [ ] **Step 1: 成功创建 offer 后，尽量触发该店铺商品同步或单商品补录，避免 ERP 长时间看不到结果**
- [ ] **Step 2: 如果能从远端返回拿到 offer id，则优先用 offer id 回填到本地产品体系**
- [ ] **Step 3: 如果暂时拿不到 offer id，则至少保证 `ExtensionAction` 可见，作为 ERP 里的事实来源**
- [ ] **Step 4: 记录剩余限制：V1 只保证扩展动作闭环，不保证秒级回填到所有 ERP 页面**

### Task 6: 调整扩展端提示与交互语义

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/extension/content.js`
- Modify: `/Users/Apple/Projects/profitlens-v3/extension/background.js`
- Modify: `/Users/Apple/Projects/profitlens-v3/extension/popup/popup.js`

- [ ] **Step 1: 把成功提示从“已提交上架/已上架”统一调整为“已进入 ERP 队列”或“正在处理中”**
- [ ] **Step 2: 保持 `ALREADY_PENDING`、`ALREADY_LISTED` 两种提示与后端真实返回对齐**
- [ ] **Step 3: 如果后端返回 `action_id`，在成功提示里保留可追踪信息**
- [ ] **Step 4: 可选地在 popup 中补最近一次动作状态；如果本轮不做，至少不要让 popup 误导用户认为已完成**

### Task 7: 补最小可见性入口

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/backend/app/api/extension.py`
- Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/api/index.ts`
- Optional Create: `/Users/Apple/Projects/profitlens-v3/frontend/src/views/ExtensionActionsView.vue`
- Optional Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/router/index.ts`
- Optional Modify: `/Users/Apple/Projects/profitlens-v3/frontend/src/components/AppLayout.vue`

- [ ] **Step 1: 先保证 `/api/extension/list-history` 返回足够状态字段**
- [ ] **Step 2: 前端 API 层补 `extensionApi.listHistory()`**
- [ ] **Step 3: 如果本轮做 ERP 可视化，优先做一个轻量“扩展上架记录”页，不要混入现有 `AI铺货` 任务列表**
- [ ] **Step 4: 如果本轮不做新页面，则把该项明确记为下一阶段，而不是把状态显示责任留空**

### Task 8: 验证、回归与文档

**Files:**
- Modify: `/Users/Apple/Projects/profitlens-v3/docs/superpowers/specs/2026-04-14-profitlens-stabilization-design.md`
- Modify: `/Users/Apple/Projects/profitlens-v3/docs/superpowers/plans/2026-04-16-extension-one-click-listing.md`

- [ ] **Step 1: 运行 `pytest backend/tests/test_extension_list_now_api.py backend/tests/test_extension_tasks.py -q`**
- [ ] **Step 2: 运行 `python3 -m compileall -q backend/app`**
- [ ] **Step 3: 手动验证扩展端：授权扩展 -> 打开 Takealot 商品页 -> 触发一键上架 -> 看到 queued/processing/submitted 或 failed**
- [ ] **Step 4: 手动验证 ERP 端：`list-history` 或对应前端页面能看到真实状态**
- [ ] **Step 5: 在稳定性文档里补一句：`list-now` 已从“记录动作”升级为“真实异步上架入口”**

## Implementation Notes

- V1 优先复用 `TakealotSellerAPI.create_offer_by_barcode()`，不要把扩展输入硬塞给 `ListingJobCreate(amazon_url, store_id, ...)`。
- `listing_tasks.py` 仍可作为后续“AI 铺货”主线继续补完，但不应阻塞扩展一键上架上线。
- 现有 `ExtensionAction` 字段基本够用；如果后续确认远端必须单独保存 `submission_id`，再补 migration，而不是本轮先做过度设计。
