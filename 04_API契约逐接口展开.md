# API 契约逐接口展开

## 1. 目标

本文件把 `PRD v2.1`、附录 A/B/C/F/G/I 中已冻结的规则，展开成可直接用于后端接口设计、前端联调、测试编写与上线验收的接口契约。

原则：

- 先定义首发 `P0 / P1 / P2` 接口边界，再定义读写契约
- 所有写接口必须遵守 `附录F_API写接口统一规则.md`
- 所有任务化接口必须遵守 `附录G_任务系统字段与状态全集.md`
- 所有错误码必须从 `附录C_错误码表.md` 选择，不允许页面自造错误语义
- 所有高危动作必须符合 `附录I_审计字段与高危动作清单.md`

---

## 2. 上线分级

### 2.1 `P0` 必须生产可用

- `Auth / Admin / Subscription`
- `Store Management`
- `AutoBid`
- `Fulfillment / PO Workbench`
- `Task / Audit / Security` 相关查询与高危写接口

### 2.2 `P1` 受限可用

- `Product Intelligence / Selection`
- `Finance`
- `Warehouse`
- `Extension`

### 2.3 `P2` 延后补齐

- `Listing / Dropship` 自动铺货闭环

---

## 3. 统一约束

### 3.1 标准请求头

| Header | 必填 | 说明 |
|---|---:|---|
| `X-Request-Id` | 是 | 链路追踪与审计关联 |
| `Idempotency-Key` | 高危必填 | 高危写操作幂等键 |
| `X-Audit-Reason` | 高危必填 | 高危动作原因 |
| `If-Match-Version` | 推荐 | 乐观锁版本 |

### 3.2 标准成功返回

#### 同步写成功

```json
{
  "ok": true,
  "data": {
    "id": "po_123",
    "status": "open",
    "stage": "tracking_in_progress",
    "ui_meta": {}
  },
  "request_id": "req_xxx"
}
```

#### 任务化写成功

```json
{
  "ok": true,
  "task_id": "task_123",
  "status": "queued",
  "stage": "created",
  "ui_meta": {},
  "request_id": "req_xxx"
}
```

#### 幂等重复提交

```json
{
  "ok": true,
  "duplicate": true,
  "task_id": "task_123",
  "request_id": "req_xxx"
}
```

### 3.3 标准错误返回

```json
{
  "ok": false,
  "error_code": "PERM_FORBIDDEN",
  "message": "当前账号没有权限",
  "request_id": "req_xxx",
  "retryable": false,
  "details": {}
}
```

### 3.4 统一读接口规则

- 所有列表接口默认服务端分页、服务端筛选、服务端排序
- 默认返回高信噪比核心字段；高级字段通过 `view=advanced` 或 `fields=` 获取
- 列表接口必须支持 `page`、`page_size`、`sort_by`、`sort_order`、`keyword`
- 状态对象必须返回 canonical `status / stage / ui_meta`
- 终态对象默认只读

---

## 4. Auth / Admin / Subscription

### 4.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/auth/me` | 获取当前登录态、角色、功能开关 | 已登录用户 | `user`、`roles`、`feature_flags`、`subscription_status` |
| `GET /admin/api/users` | 用户列表 | `super_admin`、`tenant_admin` | `status`、`expiry_at`、`feature_flags` |
| `GET /admin/api/users/{id}` | 用户详情 | `super_admin`、`tenant_admin` | 账号、状态、会话、权限摘要 |
| `GET /admin/api/audits` | 审计列表 | `super_admin`、`tenant_admin` | `risk_level`、`action`、`result` |
| `GET /admin/api/system/health` | 系统健康摘要 | `super_admin`、`tenant_admin` 只读 | DB、队列、任务、外部依赖 |

### 4.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|---|
| `POST /api/auth/login` | 登录 | 所有可登录用户 | - | 用户非 `disabled` 且未锁定 | 否 | 否 | 会话信息 |
| `POST /api/auth/logout` | 登出 | 已登录用户 | - | 会话有效 | 否 | 否 | 成功 |
| `POST /admin/api/users` | 创建用户 | `super_admin`、`tenant_admin` | `admin` | 数据范围合法 | 是 | 是 | 用户对象 |
| `POST /admin/api/users/{id}/reset-password` | 重置密码 | `super_admin`、`tenant_admin` | `admin` | 目标用户在数据范围内 | 是 | 是 | 成功 |
| `POST /admin/api/users/{id}/disable` | 禁用用户 | `super_admin`、`tenant_admin` | `admin` | 目标用户非保护账号 | 是 | 是 | 用户状态 |
| `POST /admin/api/users/{id}/enable` | 启用用户 | `super_admin`、`tenant_admin` | `admin` | 用户当前非 `active` | 是 | 是 | 用户状态 |
| `POST /admin/api/users/{id}/set-expiry` | 设置到期 | `super_admin` | `admin` | 用户存在 | 是 | 是 | 用户状态 |
| `POST /admin/api/users/{id}/feature-flags` | 修改功能开关 | `super_admin`、`tenant_admin` | `admin` | 仅限本租户 | 是 | 是 | 功能开关对象 |
| `POST /admin/api/users/{id}/force-logout` | 强制下线 | `super_admin`、`tenant_admin` | `admin` | 用户存在且有活跃会话 | 是 | 是 | 成功 |

### 4.3 关键错误码

- `AUTH_INVALID_CREDENTIALS`
- `AUTH_ACCOUNT_LOCKED`
- `AUTH_SESSION_EXPIRED`
- `PERM_FORBIDDEN`
- `PERM_FEATURE_DISABLED`
- `SUB_EXPIRED`
- `ADMIN_HIGH_RISK_REASON_REQUIRED`

---

## 5. Store Management

### 5.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/stores` | 店铺列表 | `super_admin`、`tenant_admin`、`operator` | `status`、`last_sync_at`、`credential_status` |
| `GET /api/stores/{id}` | 店铺详情 | 同上 | 店铺配置、同步状态、能力开关 |
| `GET /api/stores/{id}/sync-tasks` | 同步任务列表 | 同上 | 最近任务、状态、失败原因 |

### 5.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 是否任务化 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---:|---|---|---|
| `POST /api/stores` | 创建店铺 | `super_admin`、`tenant_admin` | `admin` | 租户有效 | 否 | 是 | 是 | 店铺对象 |
| `POST /api/stores/{id}` | 修改店铺配置 | `super_admin`、`tenant_admin` | `admin` | 店铺存在 | 否 | 是 | 是 | 店铺对象 |
| `POST /api/stores/{id}/credentials` | 更新凭证 | `super_admin`、`tenant_admin` | `admin` | 店铺存在 | 是 | 是 | 是 | `task_id` |
| `POST /api/stores/{id}/sync` | 触发同步 | `super_admin`、`tenant_admin`、`operator` | `selection` 或基础同步能力 | 同店无运行中全量任务 | 是 | 是 | 是 | `task_id` |
| `POST /api/stores/{id}/sync/force` | 强制全量同步 | `super_admin`、`tenant_admin` | `admin` | 无冲突运行中任务 | 是 | 是 | 是 | `task_id` |

### 5.3 状态与任务要求

- 同店同类全量同步只允许一个运行中任务
- 外部响应先入 inbox，再入标准化表
- 凭证校验必须异步任务化

### 5.4 关键错误码

- `STORE_CREDENTIAL_INVALID`
- `STORE_SYNC_ALREADY_RUNNING`
- `EXT_TIMEOUT`
- `EXT_AUTH_FAILED`
- `EXT_DIRTY_DATA_QUARANTINED`

---

## 6. AutoBid

### 6.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/bidding/products` | 竞价商品列表 | `super_admin`、`tenant_admin`、`operator` | `status`、`floor_price`、`buybox_price`、`ui_meta` |
| `GET /api/bidding/products/{id}` | 单品竞价详情 | 同上 | 价格区间、护栏、最近调价日志 |
| `GET /api/bidding/logs` | 调价日志 | 同上 | `before_price`、`after_price`、`result` |
| `GET /api/bidding/store-policies/{store_id}` | 店铺竞价策略 | `super_admin`、`tenant_admin` | 开关、护栏、批量策略 |

### 6.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 是否任务化 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---:|---|---|---|
| `POST /api/bidding/floors/import` | 导入 SKU 底价 | `super_admin`、`tenant_admin`、`operator` | `bidding` | 文件合法 | 是 | 是 | 是 | `task_id` |
| `POST /api/bidding/products/{id}/floor` | 修改单个底价 | `super_admin`、`tenant_admin`、`operator` | `bidding` | 商品存在 | 否 | 是 | 是 | 商品对象 |
| `POST /api/bidding/products/{id}/enable` | 启用单品竞价 | `super_admin`、`tenant_admin`、`operator` | `bidding` | 已配置人工底价 | 否 | 是 | 是 | 商品状态 |
| `POST /api/bidding/products/{id}/disable` | 禁用单品竞价 | `super_admin`、`tenant_admin`、`operator` | `bidding` | 商品存在 | 否 | 是 | 是 | 商品状态 |
| `POST /api/bidding/stores/{id}/start` | 启动全店竞价 | `super_admin`、`tenant_admin` | `bidding` | 店铺未暂停且护栏配置完整 | 是 | 是 | 是 | `task_id` |
| `POST /api/bidding/stores/{id}/stop` | 停止全店竞价 | `super_admin`、`tenant_admin` | `bidding` | 当前已启用 | 是 | 是 | 是 | `task_id` |
| `POST /api/bidding/runs/{task_id}/cancel` | 取消竞价任务 | `super_admin`、`tenant_admin` | `bidding` | 任务可取消 | 否 | 是 | 是 | 任务状态 |

### 6.3 关键规则

- 无人工底价不得启用
- 调价执行必须由 `system_worker` 完成
- 前端修改 Slider 不直接触发调价，只修改配置
- 每次调价必须写 `bid_log` 与审计日志

### 6.4 关键错误码

- `BID_NO_FLOOR_PRICE`
- `BID_BUYBOX_STALE`
- `BID_GUARDRAIL_BLOCKED`
- `BID_PRICE_UPDATE_FAILED`
- `TASK_ALREADY_RUNNING`

---

## 7. Fulfillment / PO Workbench

### 7.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/fulfillment/orders` | 订单池列表 | `super_admin`、`tenant_admin`、`operator`、`warehouse` | `status`、`po_id`、`next_action` |
| `GET /api/fulfillment/orders/{id}` | 订单项详情 | 同上 | 图片、SKU、仓库、异常原因 |
| `GET /api/fulfillment/pos` | PO 列表 | `super_admin`、`tenant_admin`、`operator` | `status`、`stage`、`version` |
| `GET /api/fulfillment/pos/{id}` | PO 详情 | 同上 | 订单项、物流、审计摘要 |
| `GET /api/shipments/{id}` | 运单详情 | `super_admin`、`tenant_admin`、`operator`、`warehouse` | `status`、阶段、物流信息 |

### 7.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 是否任务化 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---:|---|---|---|
| `POST /api/fulfillment/orders/import` | 强制导入订单 | `super_admin`、`tenant_admin` | `fulfillment` | 店铺有效 | 是 | 是 | 是 | `task_id` |
| `POST /api/fulfillment/pos` | 创建 PO | `super_admin`、`tenant_admin`、`operator` | `fulfillment` | 同仓、可合单、订单项未绑定 | 否 | 是 | 是 | PO 对象 |
| `POST /api/fulfillment/pos/{id}/items` | 新增或调整 PO 明细 | `super_admin`、`tenant_admin`、`operator` | `fulfillment` | `po.status=open` | 否 | 是 | 是 | PO 对象 |
| `POST /api/fulfillment/pos/{id}/tracking` | 批量补号 | `super_admin`、`tenant_admin`、`operator`、`warehouse` | `fulfillment` | `tracking_required` | 否 | 是 | 是 | PO 对象 |
| `POST /api/fulfillment/pos/{id}/cancel` | 取消 PO | `super_admin`、`tenant_admin` | `fulfillment` | 非终态 | 否 | 是 | 是 | PO 状态 |
| `POST /api/fulfillment/orders/{id}/exception` | 标记异常 | `super_admin`、`tenant_admin`、`operator`、`warehouse` | `fulfillment` | 非终态 | 否 | 是 | 是 | 订单状态 |
| `POST /api/shipments/{id}` | 修改物流信息 | `super_admin`、`tenant_admin`、`operator` | `fulfillment` | Shipment 存在 | 否 | 是 | 是 | Shipment 对象 |

### 7.3 关键规则

- 禁止跨仓合单
- `PO_Manager` 是唯一写路径 owner
- 终态 PO 默认只读
- PO、Shipment、订单异常都要求 `If-Match-Version`

### 7.4 关键错误码

- `FULFILL_CROSS_WAREHOUSE_PO_DENIED`
- `FULFILL_ORDER_ALREADY_BOUND`
- `FULFILL_TERMINAL_READONLY`
- `WAREHOUSE_OPERATION_INVALID_STAGE`
- `IDEMP_VERSION_CONFLICT`

---

## 8. Finance

### 8.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/finance/snapshots` | 快照列表 | `super_admin`、`tenant_admin`、`operator` | `scope_type`、`status`、`profit_amount` |
| `GET /api/finance/snapshots/{id}` | 快照详情 | 同上 | 成本拆解、输入哈希、版本 |
| `GET /api/finance/ledgers` | 流水列表 | `super_admin`、`tenant_admin` | `ledger_type`、`amount`、`source` |
| `GET /api/finance/recalculation-tasks` | 重算任务列表 | `super_admin`、`tenant_admin` | 状态、进度、失败原因 |

### 8.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 是否任务化 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---:|---|---|---|
| `POST /api/finance/ledgers` | 新增流水 | `system_worker`、`super_admin`、`tenant_admin` | `finance` | 来源对象存在 | 否 | 是 | 是 | 流水对象 |
| `POST /api/finance/adjustments` | 财务调整 | `system_worker`、`super_admin` | `finance` | 原流水存在 | 否 | 是 | 是 | adjustment 对象 |
| `POST /api/finance/snapshots/recalculate` | 重算快照 | `super_admin`、`tenant_admin` | `finance` | 范围合法 | 是 | 是 | 是 | `task_id` |
| `POST /api/finance/snapshots/{id}/freeze` | 冻结快照 | `super_admin` | `finance` | 快照已 `calculated` | 否 | 是 | 是 | 快照对象 |

### 8.3 关键规则

- 流水只追加，不允许覆盖
- 错误数据通过 adjustment 修正
- 批量重算必须任务化且可恢复
- 快照必须版本化并携带 `input_hash`

### 8.4 关键错误码

- `FINANCE_LEDGER_IMMUTABLE`
- `FINANCE_SNAPSHOT_STALE`
- `TASK_DEAD_LETTERED`
- `PERM_FORBIDDEN`

---

## 9. Warehouse

### 9.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/warehouse/tasks` | 仓库任务列表 | `super_admin`、`tenant_admin`、`warehouse` | 状态、目的仓、下一步 |
| `GET /api/warehouse/batches/{id}` | 出库批次详情 | 同上 | 批次状态、订单项、异常 |

### 9.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 是否任务化 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---:|---|---|---|
| `POST /api/warehouse/shipments/{id}/receive` | 到仓扫描 | `warehouse`、`system_worker` | `warehouse` | `status=pending` | 否 | 是 | 是 | Shipment 状态 |
| `POST /api/warehouse/shipments/{id}/pack` | 打包 | `warehouse` | `warehouse` | `status=received` | 否 | 是 | 是 | Shipment 状态 |
| `POST /api/warehouse/shipments/{id}/label` | 贴标 | `warehouse` | `warehouse` | `status=packing` | 否 | 是 | 是 | Shipment 状态 |
| `POST /api/warehouse/shipments/{id}/ship` | 标记出库 | `warehouse` | `warehouse` | `status=ready_to_ship` | 否 | 是 | 是 | Shipment 状态 |

### 9.3 关键错误码

- `WAREHOUSE_SCAN_DUPLICATED`
- `WAREHOUSE_OPERATION_INVALID_STAGE`
- `PERM_FEATURE_DISABLED`

---

## 10. Selection / Extension

### 10.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/selection/products` | 候选商品列表 | `super_admin`、`tenant_admin`、`operator` | 评分、状态、推荐动作 |
| `GET /api/extension/profile` | 扩展授权与状态 | 已登录用户 | 用户、店铺、功能开关 |

### 10.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 是否任务化 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---:|---|---|---|
| `POST /api/selection/products/{id}/mark` | 标注候选商品 | `super_admin`、`tenant_admin`、`operator` | `selection` | 商品存在 | 否 | 是 | 否 | 商品对象 |
| `POST /api/selection/export` | 导出选品报告 | `super_admin`、`tenant_admin`、`operator` | `selection` | 筛选条件合法 | 是 | 是 | 是 | `task_id` |

---

## 11. Listing / Dropship（`P2`）

### 11.1 读接口

| 接口 | 说明 | 角色 | 关键返回 |
|---|---|---|---|
| `GET /api/listing/jobs` | 铺货任务列表 | `super_admin`、`tenant_admin`、`operator` | `status`、`stage`、失败原因 |
| `GET /api/listing/jobs/{id}` | 铺货任务详情 | 同上 | 商品快照、AI 版本、loadsheet 状态 |

### 11.2 写接口

| 接口 | 动作 | 角色 | 功能开关 | 前置条件 | 是否任务化 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---:|---|---|---|
| `POST /api/listing/jobs` | 创建铺货任务 | `super_admin`、`tenant_admin`、`operator` | `listing` | 店铺能力开启 | 是 | 是 | 是 | `task_id` |
| `POST /api/listing/jobs/{id}/retry` | 重试铺货 | `super_admin`、`tenant_admin`、`operator` | `listing` | 当前任务可重试 | 是 | 是 | 是 | `task_id` |
| `POST /api/listing/jobs/{id}/submit` | 提交审核 | `super_admin`、`tenant_admin`、`operator` | `listing` | `status=ready_to_submit` | 是 | 是 | 是 | `task_id` |
| `POST /api/listing/jobs/{id}/cancel` | 取消铺货 | `super_admin`、`tenant_admin`、`operator` | `listing` | 非终态 | 否 | 是 | 是 | 任务状态 |

### 11.3 关键错误码

- `LISTING_FETCH_FAILED`
- `LISTING_AI_FAILED`
- `LISTING_CATEGORY_UNMATCHED`
- `LISTING_LOADSHEET_INVALID`
- `LISTING_REVIEW_REJECTED`

---

## 12. Task / Audit 公共接口

### 12.1 Task

| 接口 | 说明 | 角色 | 返回 |
|---|---|---|---|
| `GET /api/tasks` | 任务列表 | 已登录且有域权限用户 | `status`、`stage`、`progress` |
| `GET /api/tasks/{id}` | 任务详情 | 同上 | 任务实例、`ui_meta`、最近事件 |
| `GET /api/tasks/{id}/events` | 任务事件流 | 同上 | 事件列表 |
| `POST /api/tasks/{id}/retry` | 重试任务 | `super_admin`、`tenant_admin`、`system_worker` | 任务状态 |
| `POST /api/tasks/{id}/cancel` | 取消任务 | 发起人、`tenant_admin`、`super_admin` | 任务状态 |
| `POST /api/tasks/{id}/force-unlock` | 强制释放租约 | `super_admin`、`system_worker` | 任务状态 |

### 12.2 Audit

| 接口 | 说明 | 角色 | 返回 |
|---|---|---|---|
| `GET /api/audits` | 审计列表 | `super_admin`、`tenant_admin` | `risk_level`、`action`、`target`、`result` |
| `GET /api/audits/{id}` | 审计详情 | `super_admin`、`tenant_admin` | `before`、`after`、`diff` |

---

## 13. 首发联调优先顺序

1. `GET /api/auth/me`
2. `POST /admin/api/users/{id}/feature-flags`
3. `POST /api/stores/{id}/sync`
4. `GET /api/tasks/{id}`
5. `POST /api/bidding/stores/{id}/start`
6. `POST /api/fulfillment/pos`
7. `POST /api/fulfillment/pos/{id}/tracking`
8. `POST /api/finance/snapshots/recalculate`

---

## 14. 检查点

本文件首版完成后，下一检查点必须确认：

- 每个 `P0` 写接口是否都已绑定权限、状态前置、幂等、审计、错误码
- `P1` 接口是否已经标注清楚“只读 / 受限可用”边界
- `P2` 是否只保留任务壳与状态壳，未错误承诺完整闭环
