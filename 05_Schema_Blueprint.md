# Schema Blueprint

## 1. 目标

本文件用于把 `PRD v2.1` 中的对象、状态机、权限、任务与财务规则落到 PostgreSQL 主库的表结构蓝图上。

本 Blueprint 关注：

- 主键与命名规范
- 域模型拆分
- 关键字段
- 唯一约束
- 索引策略
- 分区与归档
- 审计、任务、外部连接器基础设施

## 2. 全局设计规范

### 2.1 主键与时间

- 主键统一使用 `uuid`
- 所有时间字段统一使用 `timestamptz`
- 所有业务表必须包含：
  - `created_at`
  - `updated_at`

### 2.2 命名规范

- 表名：小写复数下划线
- 主键：`<entity>_id` 或统一 `id`
- 外键：`<ref_entity>_id`
- 状态字段：`status`
- 阶段字段：`stage`
- 前端元信息：`ui_meta jsonb`

### 2.3 通用基础字段

建议大多数业务表包含：

- `tenant_id`
- `store_id`（若与店铺相关）
- `status`
- `stage`
- `ui_meta`
- `version`（乐观锁）
- `created_at`
- `updated_at`

### 2.4 统一数据类型建议

| 字段类型 | 建议 |
|---|---|
| 主键 | `uuid` |
| 金额 | `numeric(18,4)` |
| 数量 | `integer` 或 `numeric(18,4)` |
| 比例 | `numeric(8,4)` |
| JSON 扩展 | `jsonb` |
| 状态 | `varchar(64)` |
| 货币 | `varchar(8)` |

## 3. 核心跨域表

### 3.1 租户与用户

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `tenants` | 租户主表 | `id` / `slug` 唯一 | `name` `status` `plan` | `status` |
| `users` | 用户主表 | `id` / `username` 唯一 | `tenant_id` `role` `status` `expires_at` | `(tenant_id,status)` `(tenant_id,role)` |
| `user_passwords` | 密码与安全信息 | `id` / `user_id` 唯一 | `password_hash` `password_version` | `user_id` |
| `auth_sessions` | 会话 | `id` / `session_token` 唯一 | `user_id` `status` `expires_at` | `(user_id,status)` `expires_at` |
| `user_feature_flags` | 用户功能开关 | `id` / `(user_id,feature_key)` 唯一 | `enabled` `source` | `(user_id,feature_key)` |
| `user_devices` | 设备与风险识别 | `id` | `user_id` `device_fingerprint` `last_seen_at` | `(user_id,last_seen_at)` |
| `activation_codes` | 激活码 | `id` / `code` 唯一 | `expires_at` `used_at` | `expires_at` |
| `user_subscriptions` | 订阅信息 | `id` / `(tenant_id,plan_version)` | `status` `grace_until` | `(tenant_id,status)` |

### 3.2 平台管理与审计

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `audit_logs` | 审计日志 | `id` | `request_id` `actor_user_id` `action` `risk_level` | `(tenant_id,created_at desc)` `(action,created_at desc)` |
| `licenses` | license / 套餐 | `id` / `license_key` 唯一 | `tenant_id` `plan` `expires_at` | `(tenant_id,expires_at)` |
| `system_settings` | 系统级总控开关与运行参数 | `id` / `setting_key` 唯一 | `value_type` `value_json` `version` | `setting_key` |
| `system_health_snapshots` | 系统健康快照 | `id` | `component` `status` `captured_at` | `(component,captured_at desc)` |

## 4. Store 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `stores` | 店铺主表 | `id` / `(tenant_id,name)` | `status` `api_key_status` `last_synced_at` | `(tenant_id,status)` |
| `store_credentials` | 店铺凭证 | `id` / `store_id` 唯一 | `api_key_encrypted` `masked_api_key` `credential_status` | `store_id` |
| `store_feature_policies` | 店铺级策略 | `id` / `store_id` 唯一 | `bidding_enabled` `listing_enabled` | `store_id` |
| `takealot_webhook_configs` | Webhook 配置 | `id` / `store_id` 唯一 | `webhook_url` `secret_ref` | `store_id` |
| `takealot_webhook_deliveries` | webhook 投递记录 | `id` | `store_id` `event_type` `delivery_status` | `(store_id,created_at desc)` |

## 5. Product / Selection / Extension 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `library_products` | 共享商品事实库 | `id` / `(platform,external_product_id)` | `title` `brand` `category` `price_min` `price_max` `fact_status` `last_refreshed_at` | `(platform,external_product_id)` `(platform,category)` `gin(search_vector)` |
| `product_media` | 图片与媒体 | `id` | `product_id` `media_type` `sort_order` | `(product_id,sort_order)` |
| `product_annotations` | 商品标注 | `id` | `product_id` `actor_user_id` `annotation_type` | `(product_id,created_at desc)` |
| `auto_selection_batches` | 自动选品批次 | `id` | `tenant_id` `status` `task_id` | `(tenant_id,created_at desc)` |
| `auto_selection_products` | 候选商品池 | `id` / `(batch_id,product_id)` | `profit_estimate` `risk_score` | `(batch_id,risk_score)` |
| `tenant_product_guardrails` | 租户保护价护栏 | `id` / `(tenant_id,store_id,product_id)` | `protected_floor_price` `autobid_sync_status` `linked_bidding_rule_id` | `(tenant_id,store_id,updated_at desc)` |
| `selection_memory` | 选品与扩展记忆层 | `id` | `tenant_id` `scope_type` `key` `value jsonb` | `(tenant_id,scope_type,key)` |
| `extension_auth_tokens` | 扩展鉴权令牌 | `id` / `token_hash` 唯一 | `tenant_id` `user_id` `store_id` `expires_at` `last_seen_at` | `(user_id,expires_at)` `(tenant_id,expires_at)` |

### 5.1 上下文与记忆管理

- `library_products` 保存共享商品事实，不再按 `store_id` 重复抓取同一 `PLID`
- 原始 payload 与标准化字段必须并存，至少保留：
  - 原始平台响应
  - 标准化重量、长宽高、价格区间
  - 来源、刷新时间、置信度、最近校验时间
- `tenant_product_guardrails` 只保存保护价护栏，不得扩展成成本、运费、费率的大杂烩配置表
- `selection_memory` 负责保存公式版本、人工备注、最近查询、手动覆盖与上下文摘要；成本、运费、费率不属于后端持久化记忆
- 浏览器扩展的任何利润试算、推荐售价、保护低价，都必须由后端基于“共享事实 + 保护价护栏 + 记忆层”统一计算
- 当商品已映射到真实 `listing/sku` 时，保护价应优先同步到 `bidding_rules` 或 `sku_floor_prices`；当映射尚未建立时，先在 `tenant_product_guardrails` 暂存，待上架后再 hydrate 到 `AutoBid`

## 6. Listing / Dropship 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `listing_jobs` | 链接铺货任务 | `id` | `store_id` `status` `stage` `source_url` `attempt_count` | `(store_id,status)` `(store_id,created_at desc)` |
| `dropship_jobs` | 关键词采买任务 | `id` | `store_id` `status` `stage` `keyword` `attempt_count` | `(store_id,status)` `(keyword)` |
| `listing_job_attempts` | 铺货尝试版本 | `id` | `job_id` `attempt_no` `status` `input_payload` `output_payload` | `(job_id,attempt_no desc)` |
| `listing_ai_rewrites` | AI 改写版本 | `id` | `job_id` `attempt_id` `model_name` `rewrite_payload` | `(job_id,created_at desc)` |
| `listing_reviews` | 审核状态 | `id` | `job_id` `submission_id` `review_status` `review_reason` | `(job_id,created_at desc)` |
| `loadsheet_artifacts` | loadsheet 产物 | `id` | `job_id` `artifact_type` `file_ref` | `(job_id,artifact_type)` |

## 7. Bidding 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `bid_products` | 竞价商品 | `id` / `(store_id,offer_id)` | `status` `floor_price_zar` `current_price_zar` `buybox_price_zar` | `(store_id,status)` `(store_id,offer_id)` |
| `sku_floor_prices` | SKU 底价库 | `id` / `(tenant_id,sku)` | `floor_price_zar` `source` | `(tenant_id,sku)` |
| `bid_log` | 调价日志 | `id` | `store_id` `offer_id` `action` `before_price` `after_price` | `(store_id,created_at desc)` `(offer_id,created_at desc)` |
| `bid_engine_state` | 运行态摘要 | `id` / `store_id` 唯一 | `engine_status` `last_run_at` | `store_id` |
| `autobid_store_policy` | 店铺竞价策略 | `id` / `store_id` 唯一 | `enabled` `ceiling_multiplier` | `store_id` |
| `autobid_store_run` | 每轮运行记录 | `id` | `store_id` `status` `started_at` `finished_at` | `(store_id,started_at desc)` |
| `autobid_scan_result` | 扫描结果 | `id` | `run_id` `offer_id` `buybox_price` | `(run_id,offer_id)` |
| `autobid_decision_result` | 决策结果 | `id` | `run_id` `offer_id` `decision` `guardrail_reason` | `(run_id,offer_id)` |
| `autobid_execution_task` | 执行任务映射 | `id` | `run_id` `task_id` `status` | `(run_id,task_id)` |

## 8. Fulfillment 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `fulfillment_orders` | 订单主表 | `id` / `(store_id,external_order_id)` | `platform_status` `fulfillment_status` | `(store_id,platform_status)` |
| `fulfillment_order_items` | 订单项 | `id` | `order_id` `sku` `qty` `warehouse_code` `status` | `(order_id)` `(warehouse_code,status)` |
| `fulfillment_pos` | PO 主表 | `id` / `(tenant_id,po_no)` | `status` `warehouse_code` `version` | `(tenant_id,status)` |
| `fulfillment_po_items` | PO 明细 | `id` | `po_id` `sku` `qty` `tracking_no` | `(po_id)` |
| `fulfillment_order_item_po_relations` | 订单项与 PO 绑定 | `id` / `(order_item_id,po_item_id)` | `binding_status` | `(order_item_id)` `(po_item_id)` |
| `fulfillment_purchase_shipments` | 物流 / 发货 | `id` | `po_id` `shipment_status` `carrier` `tracking_no` | `(po_id,status)` |
| `fulfillment_exceptions` | 履约异常 | `id` | `target_type` `target_id` `reason_code` `status` | `(target_type,target_id)` |

## 9. Warehouse / CNExpress 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `warehouse_operations` | 仓库动作日志 | `id` | `target_type` `target_id` `operation_type` `status` | `(target_type,target_id,created_at desc)` |
| `warehouse_outbound_batches` | 出库批次 | `id` | `status` `warehouse_code` `shipped_at` | `(warehouse_code,status)` |
| `warehouse_label_records` | 标签记录 | `id` | `shipment_id` `label_ref` `status` | `(shipment_id)` |
| `warehouse_scans` | 扫描记录 | `id` | `shipment_id` `scan_code` `scan_type` | `(shipment_id,scan_type)` |
| `cnexpress_orders` | 嘉鸿订单镜像 | `id` / `(tenant_id,external_order_id)` | `status` `route_code` | `(tenant_id,status)` |
| `cnexpress_wallet_transactions` | 嘉鸿钱包镜像 | `id` | `tenant_id` `amount` `currency` | `(tenant_id,created_at desc)` |

## 10. Finance 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `finance_wallet_accounts` | 钱包账户 | `id` / `(tenant_id,currency)` | `balance` `available_balance` | `(tenant_id,currency)` |
| `finance_wallet_ledgers` | 钱包流水 | `id` | `tenant_id` `ledger_type` `amount` `status` `occurred_at` | `(tenant_id,occurred_at desc)` `(tenant_id,ledger_type)` |
| `finance_profit_snapshots` | 利润快照 | `id` / `(scope_type,scope_id,snapshot_version)` | `status` `profit_amount` `input_hash` | `(tenant_id,created_at desc)` `(scope_type,scope_id,snapshot_version)` |
| `jiahong_logistics_charges` | 嘉鸿费用 | `id` | `shipment_id` `amount` `currency` | `(shipment_id)` |
| `finance_adjustments` | 财务调整 | `id` | `ledger_id` `amount_delta` `reason` | `(ledger_id,created_at desc)` |
| `finance_exchange_rates` | 汇率表 | `id` / `(base_currency,quote_currency,effective_date)` | `rate` | `(base_currency,quote_currency,effective_date desc)` |

## 11. Task / Connector / Infra 域

| 表 | 作用 | 主键 / 唯一约束 | 关键字段 | 关键索引 |
|---|---|---|---|---|
| `task_definitions` | 任务模板 | `id` / `task_type` 唯一 | `queue_name` `max_retries` | `task_type` |
| `task_runs` | 任务实例 | `id` | `task_type` `status` `stage` `tenant_id` `store_id` | `(status,created_at desc)` `(tenant_id,created_at desc)` |
| `task_events` | 任务事件 | `id` | `task_id` `event_type` `stage` | `(task_id,created_at desc)` |
| `task_leases` | 租约 | `id` / `task_id` 唯一 | `worker_id` `lease_token` `expires_at` | `(expires_at)` |
| `task_dead_letters` | 死信 | `id` | `task_id` `reason` `resolved_at` | `(resolved_at)` |
| `connector_inbox` | 外部原始响应 | `id` / `(provider,external_id,payload_hash)` | `endpoint` `payload` `status` | `(provider,created_at desc)` |
| `outbox_events` | 内部事件 outbox | `id` / `(event_type,aggregate_type,aggregate_id,version)` | `payload` `published_at` | `(published_at)` |
| `notifications` | 站内通知 | `id` | `user_id` `type` `read_at` | `(user_id,read_at,created_at desc)` |

## 12. 关键关系

```text
Tenant 1 ── N Users
Tenant 1 ── N Stores
Store 1 ── N LibraryProducts
Store 1 ── N ListingJobs / BidProducts / Orders
Order 1 ── N OrderItems
PO 1 ── N POItems
OrderItem N ── M POItem
PO 1 ── N Shipments
Shipment 1 ── N WarehouseOperations
Tenant 1 ── N WalletAccounts / Ledgers / ProfitSnapshots
TaskRun 1 ── N TaskEvents
Store / Order / Bid / Finance 1 ── N AuditLogs
```

## 13. 约束与唯一键

### 必须唯一

- `users.username`
- `licenses.license_key`
- `(stores.tenant_id, stores.name)`
- `(bid_products.store_id, bid_products.offer_id)`
- `(fulfillment_orders.store_id, fulfillment_orders.external_order_id)`
- `(finance_profit_snapshots.scope_type, scope_id, snapshot_version)`

### 必须业务唯一

- 同一店铺同一时间只允许一个 `store.sync.full` 运行任务
- 同一 `BidProduct` 在同一 `run_id` 内只允许一条决策记录
- 同一 `order_item_id` 不得重复绑定同一 `po_item_id`

## 14. 索引策略

### 热表必须索引

- `bid_log`
- `task_runs`
- `task_events`
- `finance_wallet_ledgers`
- `audit_logs`
- `warehouse_operations`

### 全文 / 搜索

- `library_products` 建议建立 `tsvector` 搜索列
- 大量 JSONB 过滤字段建议用 `gin` 索引，但需谨慎控制

## 15. 分区与归档

建议按月分区的表：

- `bid_log`
- `task_events`
- `finance_wallet_ledgers`
- `audit_logs`
- `takealot_webhook_deliveries`
- `connector_inbox`

归档建议：

- 热数据：近 30 ~ 90 天
- 温数据：3 ~ 12 个月
- 冷归档：1 年以上

## 16. 软删除与不可变规则

### 软删除

建议使用软删除的表：

- `stores`
- `users`
- `listing_jobs`
- `dropship_jobs`

建议字段：

- `deleted_at`
- `deleted_by`

### 不可变

以下对象不建议直接更新覆盖历史事实：

- `finance_wallet_ledgers`
- `audit_logs`
- `task_events`
- `connector_inbox`
- `bid_log`

## 17. 迁移顺序建议

1. 租户、用户、会话、功能开关
2. 店铺、凭证、Webhook
3. 商品情报与选品
4. Listing / Dropship
5. Bid 域
6. Fulfillment / Warehouse
7. Finance
8. Task / Audit / Connector 基础设施

## 18. 首发必须落地的表

### P0

- `users`
- `auth_sessions`
- `user_feature_flags`
- `system_settings`
- `stores`
- `store_credentials`
- `bid_products`
- `sku_floor_prices`
- `bid_log`
- `fulfillment_orders`
- `fulfillment_order_items`
- `fulfillment_pos`
- `fulfillment_po_items`
- `fulfillment_order_item_po_relations`
- `fulfillment_purchase_shipments`
- `finance_wallet_ledgers`
- `finance_profit_snapshots`
- `task_runs`
- `task_events`
- `audit_logs`

### P1

- `library_products`
- `auto_selection_batches`
- `auto_selection_products`
- `warehouse_outbound_batches`
- `warehouse_label_records`

### P2

- `listing_jobs`
- `dropship_jobs`
- `listing_job_attempts`
- `listing_reviews`
