# Schema Blueprint

## 1. 目标

本文件把主 PRD 与附录 A/B/F/G/H/I 中的对象边界，落实为数据库层蓝图，供后端 Schema 设计、迁移计划、索引设计与上线前核对使用。

目标：

- 保证 `P0` 业务域有完整的最小可用数据骨架
- 保证任务、审计、幂等、版本、财务、回滚相关字段前置
- 区分 `P0 / P1 / P2` 的落库优先级，避免首发过度设计

---

## 2. 设计原则

- PostgreSQL 为主库
- 所有核心表默认包含 `created_at`、`updated_at`
- 需要并发保护的表必须包含 `version`
- 所有高危写路径必须可追踪到 `request_id`、`actor_user_id`
- 外部原始数据优先入 inbox / raw 表，再做标准化写入
- 钱包流水、审计日志只追加，不覆盖、不物理删除

---

## 3. 分层

### 3.1 控制面

- `users`
- `user_sessions`
- `subscriptions`
- `feature_flag_grants`
- `audit_logs`
- `idempotency_records`

### 3.2 执行面

- `stores`
- `store_credentials`
- `store_sync_inbox`
- `store_sync_runs`
- `selection_products`
- `listing_jobs`
- `listing_job_attempts`
- `listing_job_snapshots`
- `bid_products`
- `bid_logs`
- `autobid_store_policies`
- `fulfillment_orders`
- `fulfillment_order_items`
- `fulfillment_pos`
- `fulfillment_po_items`
- `shipments`
- `warehouse_batches`
- `finance_wallet_accounts`
- `finance_wallet_ledgers`
- `finance_profit_snapshots`
- `finance_adjustments`

### 3.3 运行面

- `task_definitions`
- `task_runs`
- `task_events`
- `task_leases`
- `task_dead_letters`
- `task_checkpoints`
- `system_metrics_snapshots`

---

## 4. `P0` 必须落地表

| 表名 | 作用 | 优先级 |
|---|---|---|
| `users` | 用户主表 | `P0` |
| `user_sessions` | 登录会话 | `P0` |
| `subscriptions` | 账号订阅与到期 | `P0` |
| `feature_flag_grants` | 功能开关授权 | `P0` |
| `audit_logs` | 审计日志 | `P0` |
| `idempotency_records` | 幂等记录 | `P0` |
| `stores` | 店铺主表 | `P0` |
| `store_credentials` | 店铺凭证 | `P0` |
| `store_sync_inbox` | 外部同步原始数据 | `P0` |
| `store_sync_runs` | 店铺同步执行记录 | `P0` |
| `bid_products` | 竞价商品 | `P0` |
| `bid_logs` | 调价日志 | `P0` |
| `autobid_store_policies` | 店铺竞价策略 | `P0` |
| `fulfillment_orders` | 订单主表 | `P0` |
| `fulfillment_order_items` | 订单项 | `P0` |
| `fulfillment_pos` | PO 主表 | `P0` |
| `fulfillment_po_items` | PO 明细 | `P0` |
| `shipments` | 运单主表 | `P0` |
| `task_definitions` | 任务模板 | `P0` |
| `task_runs` | 任务实例 | `P0` |
| `task_events` | 任务事件 | `P0` |
| `task_leases` | 任务租约 | `P0` |

---

## 5. `P1` 受限可用表

| 表名 | 作用 | 优先级 |
|---|---|---|
| `selection_products` | 选品池 | `P1` |
| `warehouse_batches` | 仓库批次 | `P1` |
| `finance_wallet_accounts` | 钱包账户 | `P1` |
| `finance_wallet_ledgers` | 财务流水 | `P1` |
| `finance_profit_snapshots` | 利润快照 | `P1` |
| `finance_adjustments` | 财务调整 | `P1` |
| `task_dead_letters` | 死信 | `P1` |
| `task_checkpoints` | 任务恢复点 | `P1` |

---

## 6. `P2` 延后表

| 表名 | 作用 | 优先级 |
|---|---|---|
| `listing_jobs` | 铺货任务 | `P2` |
| `listing_job_attempts` | 铺货提交尝试 | `P2` |
| `listing_job_snapshots` | AI / loadsheet 快照 | `P2` |

---

## 7. 核心表蓝图

### 7.1 `users`

| 字段 | 类型建议 | 说明 |
|---|---|---|
| `user_id` | uuid | 主键 |
| `tenant_id` | uuid | 租户 |
| `email` | varchar(255) | 唯一登录标识 |
| `password_hash` | varchar(255) | 密码哈希 |
| `status` | varchar(32) | `pending / active / locked / expired / disabled` |
| `role` | varchar(32) | `super_admin / tenant_admin / operator / warehouse` |
| `expiry_at` | timestamptz | 到期时间 |
| `force_password_reset` | boolean | 是否强制改密 |
| `last_login_at` | timestamptz | 最近登录 |
| `version` | bigint | 乐观锁 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

约束：

- 唯一键：`email`
- 索引：`tenant_id + status`

### 7.2 `user_sessions`

| 字段 | 类型建议 | 说明 |
|---|---|---|
| `session_id` | uuid | 主键 |
| `user_id` | uuid | 用户 |
| `status` | varchar(32) | `active / revoked / forced_logout` |
| `refresh_token_hash` | varchar(255) | 刷新凭证 |
| `ip` | inet | IP |
| `user_agent` | text | UA |
| `expires_at` | timestamptz | 过期时间 |
| `revoked_at` | timestamptz | 失效时间 |
| `created_at` | timestamptz | 创建时间 |

索引：

- `user_id + status`
- `expires_at`

### 7.3 `subscriptions`

| 字段 | 类型建议 | 说明 |
|---|---|---|
| `subscription_id` | uuid | 主键 |
| `tenant_id` | uuid | 租户 |
| `plan_code` | varchar(64) | 套餐 |
| `status` | varchar(32) | `trial / paid / grace / expired` |
| `started_at` | timestamptz | 开始时间 |
| `expires_at` | timestamptz | 到期时间 |
| `grace_until` | timestamptz | 宽限期 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

### 7.4 `feature_flag_grants`

| 字段 | 类型建议 | 说明 |
|---|---|---|
| `grant_id` | uuid | 主键 |
| `tenant_id` | uuid | 租户 |
| `user_id` | uuid | 可为空，表示租户级 |
| `feature_key` | varchar(64) | `selection / listing / bidding / fulfillment / finance / warehouse / admin / extension` |
| `enabled` | boolean | 是否启用 |
| `reason` | text | 变更原因 |
| `updated_by` | uuid | 操作人 |
| `version` | bigint | 乐观锁 |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

唯一键：

- `tenant_id + user_id + feature_key`

### 7.5 `audit_logs`

关键字段必须与附录 I 对齐：

- `audit_id`
- `request_id`
- `tenant_id`
- `store_id`
- `actor_type`
- `actor_user_id`
- `actor_role`
- `source`
- `ip`
- `user_agent`
- `action`
- `action_label`
- `risk_level`
- `target_type`
- `target_id`
- `before`
- `after`
- `diff`
- `reason`
- `result`
- `error_code`
- `idempotency_key`
- `task_id`
- `metadata`
- `created_at`

索引：

- `tenant_id + created_at desc`
- `actor_user_id + created_at desc`
- `target_type + target_id + created_at desc`
- `request_id`

### 7.6 `idempotency_records`

| 字段 | 类型建议 | 说明 |
|---|---|---|
| `idempotency_key` | varchar(255) | 主键或唯一键 |
| `request_id` | varchar(128) | 请求 ID |
| `scope` | varchar(128) | 业务作用域 |
| `target_type` | varchar(64) | 目标对象类型 |
| `target_id` | varchar(128) | 目标对象 |
| `response_ref` | jsonb | 已有响应摘要 |
| `expires_at` | timestamptz | 过期时间 |
| `created_at` | timestamptz | 创建时间 |

---

## 8. Store 与同步

### 8.1 `stores`

关键字段：

- `store_id`
- `tenant_id`
- `platform`
- `store_name`
- `status`
- `credential_status`
- `sync_status`
- `last_sync_at`
- `version`
- `created_at`
- `updated_at`

索引：

- `tenant_id + status`
- `tenant_id + platform`

### 8.2 `store_credentials`

关键字段：

- `credential_id`
- `store_id`
- `provider`
- `credential_masked`
- `credential_ciphertext_ref`
- `status`
- `last_validated_at`
- `version`
- `created_at`
- `updated_at`

约束：

- 前端永不读取明文

### 8.3 `store_sync_inbox`

关键字段：

- `inbox_id`
- `store_id`
- `sync_run_id`
- `source_type`
- `source_ref`
- `payload_raw`
- `payload_hash`
- `status`
- `quarantined_reason`
- `created_at`

用途：

- 存储外部原始响应
- 支持脏数据隔离与回放

### 8.4 `store_sync_runs`

关键字段：

- `sync_run_id`
- `store_id`
- `task_id`
- `status`
- `stage`
- `started_at`
- `finished_at`
- `result_summary`
- `created_at`

---

## 9. AutoBid

### 9.1 `bid_products`

关键字段：

- `bid_product_id`
- `tenant_id`
- `store_id`
- `external_offer_id`
- `sku`
- `status`
- `floor_price`
- `ceiling_price`
- `current_price`
- `buybox_price`
- `buybox_updated_at`
- `guardrail_state`
- `last_run_at`
- `version`
- `created_at`
- `updated_at`

唯一键：

- `store_id + external_offer_id`

索引：

- `store_id + status`
- `store_id + sku`

### 9.2 `autobid_store_policies`

关键字段：

- `policy_id`
- `store_id`
- `enabled`
- `floor_strategy`
- `ceiling_strategy`
- `batch_size`
- `cooldown_seconds`
- `version`
- `updated_by`
- `updated_at`

### 9.3 `bid_logs`

关键字段：

- `bid_log_id`
- `bid_product_id`
- `task_id`
- `before_price`
- `after_price`
- `buybox_price`
- `result`
- `error_code`
- `created_at`

---

## 10. Fulfillment / PO / Shipment

### 10.1 `fulfillment_orders`

关键字段：

- `order_id`
- `tenant_id`
- `store_id`
- `external_order_id`
- `status`
- `buyer_name_masked`
- `destination_warehouse`
- `ordered_at`
- `version`
- `created_at`
- `updated_at`

### 10.2 `fulfillment_order_items`

关键字段：

- `order_item_id`
- `order_id`
- `sku`
- `product_title`
- `product_image_url`
- `quantity`
- `status`
- `po_id`
- `shipment_id`
- `exception_code`
- `version`
- `created_at`
- `updated_at`

索引：

- `order_id`
- `po_id`
- `status + destination_warehouse`

### 10.3 `fulfillment_pos`

关键字段：

- `po_id`
- `tenant_id`
- `store_id`
- `warehouse_code`
- `status`
- `stage`
- `item_count`
- `tracking_completion_ratio`
- `created_by`
- `request_id`
- `version`
- `created_at`
- `updated_at`

唯一约束建议：

- 不做跨仓唯一合单；通过写服务约束同仓

### 10.4 `fulfillment_po_items`

关键字段：

- `po_item_id`
- `po_id`
- `order_item_id`
- `sku`
- `quantity`
- `tracking_number`
- `status`
- `version`
- `created_at`
- `updated_at`

### 10.5 `shipments`

关键字段：

- `shipment_id`
- `tenant_id`
- `po_id`
- `carrier`
- `tracking_number`
- `status`
- `received_at`
- `shipped_at`
- `delivered_at`
- `exception_code`
- `version`
- `created_at`
- `updated_at`

---

## 11. Finance

### 11.1 `finance_wallet_accounts`

关键字段：

- `wallet_account_id`
- `tenant_id`
- `store_id`
- `currency`
- `status`
- `created_at`
- `updated_at`

### 11.2 `finance_wallet_ledgers`

字段与附录 H 对齐，至少包含：

- `ledger_id`
- `wallet_account_id`
- `tenant_id`
- `store_id`
- `order_id`
- `order_item_id`
- `po_id`
- `shipment_id`
- `source_type`
- `source_id`
- `ledger_type`
- `currency`
- `amount`
- `exchange_rate`
- `base_currency`
- `base_amount`
- `occurred_at`
- `recorded_at`
- `status`
- `snapshot_version`
- `note`
- `created_by`
- `created_at`

索引：

- `tenant_id + occurred_at desc`
- `store_id + occurred_at desc`
- `order_item_id`
- `ledger_type + occurred_at`

### 11.3 `finance_profit_snapshots`

字段与附录 H 对齐，至少包含：

- `snapshot_id`
- `tenant_id`
- `store_id`
- `scope_type`
- `scope_id`
- `snapshot_version`
- `status`
- `base_currency`
- `sale_income`
- `purchase_cost`
- `logistics_cost`
- `commission_fee`
- `tax_cost`
- `warehouse_cost`
- `other_cost`
- `profit_amount`
- `margin_rate`
- `input_hash`
- `calculated_at`
- `frozen_at`
- `superseded_by`
- `created_by`
- `created_at`

唯一键建议：

- `scope_type + scope_id + snapshot_version`

### 11.4 `finance_adjustments`

关键字段：

- `adjustment_id`
- `ledger_id`
- `snapshot_id`
- `reason`
- `amount_delta`
- `created_by`
- `request_id`
- `created_at`

---

## 12. Task System

### 12.1 `task_definitions`

直接采用附录 G 字段全集。

### 12.2 `task_runs`

直接采用附录 G 字段全集，并增加以下索引：

- `tenant_id + created_at desc`
- `queue_name + status + priority`
- `task_type + target_type + target_id + status`
- `request_id`
- `root_task_id`

### 12.3 `task_events`

索引：

- `task_id + created_at`
- `event_type + created_at`

### 12.4 `task_leases`

唯一约束建议：

- `task_id + lease_token`

### 12.5 `task_dead_letters`

关键字段：

- `dead_letter_id`
- `task_id`
- `task_type`
- `reason`
- `last_error_code`
- `last_error_msg`
- `moved_at`
- `resolved_at`
- `resolved_by`

### 12.6 `task_checkpoints`

关键字段：

- `checkpoint_id`
- `task_id`
- `stage`
- `checkpoint_payload`
- `created_at`

---

## 13. 索引与约束重点

### 13.1 必要唯一键

- `users.email`
- `feature_flag_grants(tenant_id, user_id, feature_key)`
- `bid_products(store_id, external_offer_id)`
- `finance_profit_snapshots(scope_type, scope_id, snapshot_version)`

### 13.2 必要乐观锁

以下表强制带 `version`：

- `users`
- `feature_flag_grants`
- `stores`
- `store_credentials`
- `autobid_store_policies`
- `bid_products`
- `fulfillment_pos`
- `fulfillment_po_items`
- `shipments`
- `finance_profit_snapshots`

### 13.3 软删除策略

- 核心财务、审计、任务、幂等表不使用软删除
- 用户、店铺如需停用，使用 `status` 表达，不做物理删除

---

## 14. 迁移顺序建议

1. 控制面：`users / sessions / subscriptions / feature flags / audit / idempotency`
2. 运行面：`task_*`
3. 店铺与同步：`stores / credentials / inbox / sync_runs`
4. AutoBid：`bid_products / bid_logs / store_policies`
5. Fulfillment：`orders / order_items / pos / po_items / shipments`
6. Finance：`wallet_accounts / ledgers / snapshots / adjustments`
7. `P2`：`listing_jobs` 相关表

---

## 15. 上线前 Schema 检查点

- `P0` 表是否全部具备状态字段、审计字段、时间字段
- 所有高危写路径是否都能落到 `audit_logs`
- 所有任务化路径是否都能落到 `task_runs + task_events`
- 财务与审计是否仍保持 append-only
- 关键列表查询索引是否已覆盖 `tenant_id + status + created_at` 这类高频组合
