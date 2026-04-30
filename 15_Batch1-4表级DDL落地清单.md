# Batch 1~4 表级 DDL 落地清单

## 1. 目标

本文件继续下沉 `11_数据库迁移批次拆解.md`，把 Batch 1~4 细化到“几乎可直接写 SQL”的字段级，供后续迁移脚本编写、索引落地、回滚设计和验收使用。

本文件不直接给出完整 SQL，但会明确：

- 表级字段
- 字段类型建议
- `NOT NULL` / 默认值 / 唯一键 / 外键
- 建表即落索引
- 可延后索引
- 回滚策略
- 验收检查点

---

## 2. Batch 1：身份、权限、审计、任务骨架

### 2.1 `tenants`

**建表核心字段**

- `id uuid primary key`
- `slug varchar(64) not null`
- `name varchar(128) not null`
- `status varchar(32) not null default 'active'`
- `plan varchar(64) not null`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `unique (slug)`
- `check (status in ('active','disabled','suspended'))`

**建表即落索引**

- `index on (status)`

**可延后索引**

- 无

**回滚注意点**

- 已关联 `users / stores` 后不做物理回滚

**验收点**

- 可唯一按 `slug` 定位租户
- 租户状态可被后台筛选

---

### 2.2 `users`

**建表核心字段**

- `id uuid primary key`
- `tenant_id uuid not null`
- `username varchar(128) not null`
- `email varchar(255)`
- `role varchar(32) not null`
- `status varchar(32) not null`
- `expires_at timestamptz`
- `force_password_reset boolean not null default false`
- `last_login_at timestamptz`
- `version bigint not null default 1`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (tenant_id) references tenants(id)`
- `unique (username)`
- `check (role in ('super_admin','tenant_admin','operator','warehouse'))`
- `check (status in ('pending','active','locked','expired','disabled'))`

**建表即落索引**

- `index on (tenant_id, status)`
- `index on (tenant_id, role)`

**可延后索引**

- `index on (expires_at)`

**回滚注意点**

- 不做物理删除，优先改 `status`

**验收点**

- `super_admin / tenant_admin` 查询可按租户与角色过滤
- 状态与到期时间可支撑后台控制

---

### 2.3 `user_passwords`

**建表核心字段**

- `id uuid primary key`
- `user_id uuid not null`
- `password_hash varchar(255) not null`
- `password_version integer not null default 1`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (user_id) references users(id)`
- `unique (user_id)`

**建表即落索引**

- 无（`unique (user_id)` 已足够）

**可延后索引**

- 无

**回滚注意点**

- 不保留旧 hash 历史在此表，版本变化交由审计记录

**验收点**

- 每个用户只有一条当前密码记录

---

### 2.4 `auth_sessions`

**建表核心字段**

- `id uuid primary key`
- `user_id uuid not null`
- `session_token varchar(255) not null`
- `status varchar(32) not null`
- `ip inet`
- `user_agent text`
- `expires_at timestamptz not null`
- `revoked_at timestamptz`
- `created_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (user_id) references users(id)`
- `unique (session_token)`
- `check (status in ('active','revoked','forced_logout'))`

**建表即落索引**

- `index on (user_id, status)`
- `index on (expires_at)`

**可延后索引**

- `index on (revoked_at)`

**回滚注意点**

- 回滚优先批量 revoke，不删除会话历史

**验收点**

- 强制下线、过期清理、当前会话查询可用

---

### 2.5 `user_feature_flags`

**建表核心字段**

- `id uuid primary key`
- `user_id uuid not null`
- `feature_key varchar(64) not null`
- `enabled boolean not null`
- `source varchar(32) not null default 'manual'`
- `updated_by uuid`
- `version bigint not null default 1`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (user_id) references users(id)`
- `foreign key (updated_by) references users(id)`
- `unique (user_id, feature_key)`

**建表即落索引**

- 无（`unique (user_id, feature_key)` 已足够）

**可延后索引**

- `index on (feature_key, enabled)`

**回滚注意点**

- 回滚优先恢复上一版本值，并写审计

**验收点**

- 用户功能开关能被精确覆盖与追踪

---

### 2.5.1 `system_settings`

**建表核心字段**

- `id uuid primary key`
- `setting_key varchar(128) not null`
- `value_type varchar(32) not null`
- `value_json jsonb not null`
- `description text`
- `updated_by uuid`
- `change_reason text`
- `version bigint not null default 1`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `unique (setting_key)`
- `foreign key (updated_by) references users(id)`
- `check (value_type in ('boolean','string','number','json'))`

**建表即落索引**

- `index on (setting_key)`

**可延后索引**

- 无

**回滚注意点**

- 回滚优先恢复上一版本值或关闭对应开关，不物理删除历史配置

**验收点**

- 可唯一维护 `auth_enabled / admin_enabled / store_sync_enabled / maintenance_mode`
- 开关值可映射上线 Runbook 与发布降级矩阵

---

### 2.6 `audit_logs`

**建表核心字段**

- `id uuid primary key`
- `request_id varchar(128) not null`
- `tenant_id uuid`
- `store_id uuid`
- `actor_user_id uuid`
- `actor_role varchar(32)`
- `action varchar(128) not null`
- `risk_level varchar(16) not null`
- `target_type varchar(64) not null`
- `target_id varchar(128)`
- `before jsonb`
- `after jsonb`
- `diff jsonb`
- `reason text`
- `result varchar(16) not null`
- `error_code varchar(64)`
- `task_id uuid`
- `created_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (tenant_id) references tenants(id)`
- `foreign key (actor_user_id) references users(id)`
- `check (risk_level in ('low','medium','high','critical'))`
- `check (result in ('success','failed','partial','blocked'))`

**建表即落索引**

- `index on (tenant_id, created_at desc)`
- `index on (action, created_at desc)`

**可延后索引**

- `index on (request_id)`
- `index on (target_type, target_id, created_at desc)`

**回滚注意点**

- append-only，不做物理回滚

**验收点**

- 高危动作可按时间、动作、租户检索
- before/after/diff 可回查

---

### 2.7 `task_definitions`

**建表核心字段**

- `id uuid primary key`
- `task_type varchar(128) not null`
- `queue_name varchar(64) not null`
- `priority integer not null default 100`
- `max_retries integer not null default 3`
- `enabled boolean not null default true`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `unique (task_type)`

**建表即落索引**

- 无（`unique (task_type)` 已足够）

**可延后索引**

- `index on (queue_name, enabled)`

**回滚注意点**

- 回滚优先 `enabled=false`

**验收点**

- 任务模板可唯一映射任务类型

---

### 2.8 `task_runs`

**建表核心字段**

- `id uuid primary key`
- `task_type varchar(128) not null`
- `status varchar(32) not null`
- `stage varchar(64) not null`
- `tenant_id uuid`
- `store_id uuid`
- `target_type varchar(64)`
- `target_id varchar(128)`
- `request_id varchar(128) not null`
- `progress_percent numeric(5,2)`
- `error_code varchar(64)`
- `error_message text`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`
- `started_at timestamptz`
- `finished_at timestamptz`

**建表即落约束**

- `foreign key (tenant_id) references tenants(id)`
- `check (status in ('created','queued','leased','running','waiting_dependency','waiting_retry','cancel_requested','cancelled','succeeded','failed_retryable','failed_final','dead_letter','manual_intervention','timed_out','quarantined'))`

**建表即落索引**

- `index on (status, created_at desc)`
- `index on (tenant_id, created_at desc)`

**可延后索引**

- `index on (task_type, status)`
- `index on (request_id)`
- `index on (target_type, target_id)`

**回滚注意点**

- 不回滚历史实例，回滚优先停消费与停入队

**验收点**

- 可按状态、租户、时间稳定查询任务
- request_id 可回链

---

### 2.9 `task_events`

**建表核心字段**

- `id uuid primary key`
- `task_id uuid not null`
- `event_type varchar(128) not null`
- `stage varchar(64)`
- `message text`
- `details jsonb`
- `created_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (task_id) references task_runs(id)`

**建表即落索引**

- `index on (task_id, created_at desc)`

**可延后索引**

- `index on (event_type, created_at desc)`

**回滚注意点**

- append-only，不做物理回滚

**验收点**

- 任务时间线完整可查

---

## 3. Batch 2：店铺、凭证、连接器入口

### 3.1 `stores`

**建表核心字段**

- `id uuid primary key`
- `tenant_id uuid not null`
- `name varchar(128) not null`
- `platform varchar(32) not null default 'takealot'`
- `status varchar(32) not null`
- `api_key_status varchar(32)`
- `last_synced_at timestamptz`
- `deleted_at timestamptz`
- `version bigint not null default 1`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (tenant_id) references tenants(id)`
- `unique (tenant_id, name)`

**建表即落索引**

- `index on (tenant_id, status)`

**可延后索引**

- `index on (platform, status)`

**回滚注意点**

- 回滚优先 `status=disabled` 或 `deleted_at`，不物理删店铺

**验收点**

- 可按租户、状态稳定查店铺

---

### 3.2 `store_credentials`

**建表核心字段**

- `id uuid primary key`
- `store_id uuid not null`
- `api_key_encrypted text not null`
- `masked_api_key varchar(64) not null`
- `credential_status varchar(32) not null`
- `last_validated_at timestamptz`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (store_id) references stores(id)`
- `unique (store_id)`

**建表即落索引**

- 无（`unique (store_id)` 已足够）

**可延后索引**

- `index on (credential_status)`

**回滚注意点**

- 不回滚密文历史到旧值，优先停用凭证状态

**验收点**

- 每店仅一份当前凭证记录
- 前端只读脱敏值

---

### 3.3 `connector_inbox`

**建表核心字段**

- `id uuid primary key`
- `provider varchar(32) not null`
- `external_id varchar(128) not null`
- `payload_hash varchar(128) not null`
- `endpoint varchar(128) not null`
- `payload jsonb not null`
- `status varchar(32) not null default 'received'`
- `created_at timestamptz not null default now()`

**建表即落约束**

- `unique (provider, external_id, payload_hash)`

**建表即落索引**

- `index on (provider, created_at desc)`

**可延后索引**

- `index on (status, created_at desc)`

**回滚注意点**

- append-only，不清空原始响应

**验收点**

- 外部响应可防重复、可追溯

---

## 4. Batch 3：履约主链

### 4.1 `fulfillment_orders`

**建表核心字段**

- `id uuid primary key`
- `store_id uuid not null`
- `external_order_id varchar(128) not null`
- `platform_status varchar(32) not null`
- `fulfillment_status varchar(32) not null`
- `buyer_name_masked varchar(128)`
- `ordered_at timestamptz`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (store_id) references stores(id)`
- `unique (store_id, external_order_id)`

**建表即落索引**

- `index on (store_id, platform_status)`

**可延后索引**

- `index on (fulfillment_status, ordered_at desc)`

**回滚注意点**

- 不物理删除订单

**验收点**

- 订单导入与状态筛选可用

---

### 4.2 `fulfillment_order_items`

**建表核心字段**

- `id uuid primary key`
- `order_id uuid not null`
- `sku varchar(128) not null`
- `qty integer not null`
- `warehouse_code varchar(32) not null`
- `status varchar(32) not null`
- `product_image_url text`
- `tracking_no varchar(128)`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (order_id) references fulfillment_orders(id)`
- `check (qty > 0)`

**建表即落索引**

- `index on (order_id)`
- `index on (warehouse_code, status)`

**可延后索引**

- `index on (sku)`

**回滚注意点**

- 回滚优先改状态，不删订单项

**验收点**

- 可支持按仓库筛选待合单订单项

---

### 4.3 `fulfillment_pos`

**建表核心字段**

- `id uuid primary key`
- `tenant_id uuid not null`
- `po_no varchar(64) not null`
- `status varchar(32) not null`
- `warehouse_code varchar(32) not null`
- `version bigint not null default 1`
- `created_by uuid`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (tenant_id) references tenants(id)`
- `foreign key (created_by) references users(id)`
- `unique (tenant_id, po_no)`

**建表即落索引**

- `index on (tenant_id, status)`

**可延后索引**

- `index on (warehouse_code, status)`

**回滚注意点**

- 不删除已创建 PO，优先 cancel + 审计

**验收点**

- 可稳定支撑 PO 列表与状态流转

---

### 4.4 `fulfillment_purchase_shipments`

**建表核心字段**

- `id uuid primary key`
- `po_id uuid not null`
- `shipment_status varchar(32) not null`
- `carrier varchar(64)`
- `tracking_no varchar(128)`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (po_id) references fulfillment_pos(id)`

**建表即落索引**

- `index on (po_id, shipment_status)`

**可延后索引**

- `index on (tracking_no)`

**回滚注意点**

- 物流修改优先人工修正，不删历史 shipment

**验收点**

- 支持按 PO 查询 Shipment 与物流状态

---

## 5. Batch 4：竞价主链

### 5.1 `bid_products`

**建表核心字段**

- `id uuid primary key`
- `store_id uuid not null`
- `offer_id varchar(128) not null`
- `status varchar(32) not null`
- `floor_price_zar numeric(18,4)`
- `current_price_zar numeric(18,4)`
- `buybox_price_zar numeric(18,4)`
- `version bigint not null default 1`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (store_id) references stores(id)`
- `unique (store_id, offer_id)`

**建表即落索引**

- `index on (store_id, status)`
- `index on (store_id, offer_id)`

**可延后索引**

- `index on (status, updated_at desc)`

**回滚注意点**

- 不删除竞价商品事实记录，优先改状态为 disabled

**验收点**

- 商品列表与详情查询稳定
- 单品竞价状态与价格字段齐全

---

### 5.2 `sku_floor_prices`

**建表核心字段**

- `id uuid primary key`
- `tenant_id uuid not null`
- `sku varchar(128) not null`
- `floor_price_zar numeric(18,4) not null`
- `source varchar(32) not null default 'manual'`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (tenant_id) references tenants(id)`
- `unique (tenant_id, sku)`
- `check (floor_price_zar >= 0)`

**建表即落索引**

- `index on (tenant_id, sku)`

**可延后索引**

- 无

**回滚注意点**

- 回滚优先恢复上一版本值，不删记录

**验收点**

- SKU 底价可唯一定位

---

### 5.3 `bid_log`

**建表核心字段**

- `id uuid primary key`
- `store_id uuid not null`
- `offer_id varchar(128) not null`
- `action varchar(64) not null`
- `before_price numeric(18,4)`
- `after_price numeric(18,4)`
- `result varchar(16) not null`
- `error_code varchar(64)`
- `created_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (store_id) references stores(id)`
- `check (result in ('success','failed','blocked','skipped'))`

**建表即落索引**

- `index on (store_id, created_at desc)`
- `index on (offer_id, created_at desc)`

**可延后索引**

- 月分区 / 分区索引

**回滚注意点**

- append-only，不物理回滚

**验收点**

- 调价日志可按店铺和 offer 回查

---

### 5.4 `autobid_store_policy`

**建表核心字段**

- `id uuid primary key`
- `store_id uuid not null`
- `enabled boolean not null default false`
- `ceiling_multiplier numeric(8,4)`
- `version bigint not null default 1`
- `updated_by uuid`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

**建表即落约束**

- `foreign key (store_id) references stores(id)`
- `foreign key (updated_by) references users(id)`
- `unique (store_id)`

**建表即落索引**

- 无（`unique (store_id)` 已足够）

**可延后索引**

- `index on (enabled)`

**回滚注意点**

- 回滚优先 `enabled=false`

**验收点**

- 每店只有一条当前竞价策略

---

## 6. 批次级统一规则

### 6.1 建表即落

必须在第一版 migration 里直接落下：

- 主键
- 最小外键
- 最小唯一键
- 最小热路径索引
- `created_at / updated_at`
- 必需 `status / version`

### 6.2 可延后落地

可以在后续 migration 再补：

- 大 JSONB / GIN 索引
- 月分区
- 低频筛选索引
- 报表类派生索引

### 6.3 回滚原则

- append-only 表不物理回滚
- 核心业务表优先停写 + 降级 + 人工修正
- 数据修正优先于删表重建

---

## 7. 验收总口径

- Batch 1~4 的每张核心表都已经具备“可建、可查、可约束、可回滚说明”
- 后续编写 SQL 时不再需要倒推字段和约束
- 接口批次、页面实施、压测、上线文档与表级事实一致
