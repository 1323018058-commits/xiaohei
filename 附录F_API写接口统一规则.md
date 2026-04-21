# 附录 F：API 写接口统一规则

## 1. 目标

本附录用于冻结所有写接口的统一约束，确保后端写路径满足：

- 权限可控
- 状态前置条件明确
- 幂等可验证
- 高危操作可审计
- 长任务可追踪
- 错误码可消费

所有写接口必须遵守本附录，不允许按页面临时发明写法。

## 2. 写接口总原则

1. 所有写接口都必须由后端领域服务收口。  
2. 所有写接口都必须先做权限校验，再做状态校验，再进入写逻辑。  
3. 所有高风险写接口都必须带幂等键、审计原因和 request_id。  
4. 所有长耗时写操作都必须任务化，不允许同步阻塞完成。  
5. 所有写接口都必须返回 canonical `status / stage / ui_meta` 或 `task_id`。  
6. 所有终态对象默认只读，除非进入受审计的人工修正流程。  
7. 外部平台写操作必须通过 adapter 与 task 执行，不允许 API 直接串行调用外部平台并返回“成功”。  

## 3. 标准请求头

所有写接口必须支持以下请求头：

| Header | 必填 | 说明 |
|---|---:|---|
| `X-Request-Id` | 是 | 请求链路唯一标识 |
| `Idempotency-Key` | 高危必填 | 高风险写操作幂等键 |
| `X-Audit-Reason` | 高危必填 | 高危操作原因 |
| `If-Match-Version` | 推荐 | 乐观锁版本号，防止并发覆盖 |

说明：

- `X-Request-Id` 用于链路追踪、日志关联、审计关联。
- `Idempotency-Key` 缺失时，高危写操作应直接拒绝。
- `X-Audit-Reason` 对普通写操作可选，对高危写操作必填。
- `If-Match-Version` 建议用于 PO、财务、店铺配置、竞价策略等易并发覆盖的对象。

## 4. 标准写接口流程

```text
认证
  → 功能开关校验
  → RBAC / 数据范围校验
  → 状态前置条件校验
  → 幂等校验
  → 参数校验
  → 写领域对象 / 创建任务
  → 写审计日志
  → 返回 canonical status 或 task_id
```

## 5. 写接口返回规范

### 5.1 直接写成功

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

### 5.2 任务化写入

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

### 5.3 幂等重复提交

```json
{
  "ok": true,
  "duplicate": true,
  "task_id": "task_123",
  "request_id": "req_xxx"
}
```

## 6. 何时必须任务化

以下写操作必须任务化：

- 店铺同步
- 商品同步
- submission / review 同步
- 自动铺货创建后续执行
- AutoBid 全店启动 / 停止后的批量生效
- 大批量调价
- 官方订单导入
- 大批量仓库动作
- 利润快照重算
- 外部凭证校验

以下写操作可同步完成：

- 重置密码
- 禁用用户
- 修改功能开关
- 创建 PO
- 补录单个物流单号
- 标记异常

## 7. 高危写操作定义

以下动作一律视为高危写操作：

- 创建 / 删除 / 修改店铺凭证
- 重置密码
- 禁用 / 解禁用户
- 修改到期时间
- 修改功能权限
- 启动 / 停止全店自动竞价
- 导入或修改 SKU 底价
- 批量调价
- 创建 / 取消 PO
- 履约异常改写
- 财务调整
- 外部任务重试 / 死信恢复

高危写操作必须满足：

- `Idempotency-Key`
- `X-Audit-Reason`
- 高危审计日志
- 二次确认前端交互

## 8. 乐观锁与并发覆盖规则

以下对象建议强制乐观锁：

- `stores`
- `autobid_store_policy`
- `bid_products`
- `fulfillment_pos`
- `fulfillment_po_items`
- `finance_profit_snapshots`

规则：

- 如果客户端传入 `If-Match-Version` 与当前版本不一致，返回并发冲突错误。
- 返回错误码：`IDEMP_VERSION_CONFLICT`
- 前端应提示“数据已被他人更新，请刷新后重试”。

## 9. 审计写入规则

满足以下任一条件必须写审计日志：

- 高危写操作
- 涉及权限、密码、到期、功能开关
- 涉及竞价启停、底价、PO、财务调整
- 涉及人工修正异常
- 涉及任务重试、取消、死信恢复

审计日志最少字段：

- `audit_id`
- `request_id`
- `actor_user_id`
- `actor_role`
- `action`
- `target_type`
- `target_id`
- `before`
- `after`
- `reason`
- `result`
- `created_at`

## 10. 写接口分类规则

### 10.1 配置写接口

特点：

- 写配置对象
- 量小但风险高
- 强依赖权限与乐观锁

示例：

- 修改店铺
- 修改竞价策略
- 修改功能开关
- 修改账号到期时间

### 10.2 流程推进写接口

特点：

- 推动对象状态流转
- 必须受状态机约束

示例：

- 提交审核
- 创建 PO
- 逐单补号
- 标记异常
- 仓库推进

### 10.3 批量写接口

特点：

- 涉及大量对象
- 必须任务化

示例：

- 店铺同步
- 批量调价
- 批量铺货
- 批量订单导入

### 10.4 补偿写接口

特点：

- 用于修正失败、异常或错误数据
- 必须高危审计

示例：

- 任务重试
- 死信恢复
- 财务调整
- 履约人工修正

## 11. 分域写接口规则

## 11.1 Auth / Admin / Subscription

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/auth/login` | 登录 | 所有可登录用户 | 用户状态非 `disabled` | 否 | 否 | 会话信息 |
| `POST /api/auth/logout` | 登出 | 已登录用户 | 会话有效 | 否 | 否 | 成功 |
| `POST /admin/api/users` | 创建用户 | `super_admin`、`tenant_admin` | 数据范围合法 | 是 | 是 | 用户对象 |
| `POST /admin/api/users/{id}/reset-password` | 重置密码 | `super_admin`、`tenant_admin` | 目标用户在范围内 | 是 | 是 | 成功 |
| `POST /admin/api/users/{id}/disable` | 禁用用户 | `super_admin`、`tenant_admin` | 目标用户非自身保护账号 | 是 | 是 | 用户状态 |
| `POST /admin/api/users/{id}/set-expiry` | 设置到期时间 | `super_admin` | 目标用户存在 | 是 | 是 | 用户状态 |
| `POST /admin/api/users/{id}/feature-flags` | 配置功能权限 | `super_admin`、`tenant_admin` | 目标用户在范围内 | 是 | 是 | 权限结果 |

规则：

- `tenant_admin` 不得修改超出自身租户的数据。
- 修改密码、禁用、修改到期时间必须强制审计。
- 创建用户后默认状态可为 `pending` 或 `active`，由业务规则决定。

## 11.2 Store Management

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/v2/stores` | 创建店铺 | `super_admin`、`tenant_admin` | 租户可创建店铺 | 是 | 是 | 店铺对象 |
| `PATCH /api/v2/stores/{store_id}` | 编辑店铺 | `super_admin`、`tenant_admin` | 版本一致 | 是 | 是 | 店铺对象 |
| `DELETE /api/v2/stores/{store_id}` | 删除店铺 | `super_admin` | 店铺无阻断依赖或允许软删除 | 是 | 是 | 成功 |
| `POST /api/v2/stores/{store_id}/sync` | 店铺同步 | `super_admin`、`tenant_admin`、`operator` | 店铺凭证有效，当前无同类运行任务 | 是 | 是 | `task_id` |

规则：

- 删除店铺建议为软删除，不建议物理删除。
- 店铺同步属于任务化接口，重复提交返回现有任务。

## 11.3 Product Intelligence / Selection

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/v2/stores/{store_id}/products/sync` | 商品同步 | `super_admin`、`tenant_admin`、`operator` | 店铺同步权限开启 | 是 | 否 | `task_id` |
| `POST /api/selection/annotations` | 商品标注 | `super_admin`、`tenant_admin`、`operator` | 商品存在 | 是 | 否 | 标注对象 |
| `POST /api/selection/export` | 导出 | `super_admin`、`tenant_admin`、`operator` | 有导出权限 | 是 | 是 | `task_id` 或导出记录 |

## 11.4 Listing / Dropship

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/listing/jobs` | 创建链接铺货任务 | `super_admin`、`tenant_admin`、`operator` | `listing` 功能开启 | 是 | 否 | `job_id` 或 `task_id` |
| `POST /api/dropship/jobs` | 创建关键词铺货任务 | `super_admin`、`tenant_admin`、`operator` | `listing` 功能开启 | 是 | 否 | `job_id` 或 `task_id` |
| `POST /api/listing/jobs/{job_id}/retry` | 重试任务 | `super_admin`、`tenant_admin`、`operator` | Job 在可重试状态 | 是 | 是 | `task_id` |
| `POST /api/dropship/jobs/{job_id}/retry` | 重试任务 | `super_admin`、`tenant_admin`、`operator` | Job 在可重试状态 | 是 | 是 | `task_id` |
| `POST /api/dropship/jobs/sync` | 同步 submission/review | `super_admin`、`tenant_admin`、`operator` | 任务存在且未终态 | 是 | 否 | `task_id` |

规则：

- `approved` 后必须绑定外部 `offer_id`，否则不能进入后续竞价域。
- 驳回返修必须进入 `manual_fix_required`，不得直接覆盖原 attempt。

## 11.5 AutoBid

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/v2/stores/{store_id}/bid/start` | 启动店铺竞价 | `super_admin`、`tenant_admin` | 店铺有效、策略完整 | 是 | 是 | 店铺竞价状态 |
| `POST /api/v2/stores/{store_id}/bid/stop` | 停止店铺竞价 | `super_admin`、`tenant_admin` | 当前非已停止 | 是 | 是 | 店铺竞价状态 |
| `POST /api/v2/stores/{store_id}/bid/resume` | 恢复店铺竞价 | `super_admin`、`tenant_admin` | 当前为暂停态 | 是 | 是 | 店铺竞价状态 |
| `POST /api/v2/stores/{store_id}/bid/products/sync` | 同步竞价商品 | `super_admin`、`tenant_admin`、`operator` | 店铺存在 | 是 | 否 | `task_id` |
| `PATCH /api/v2/stores/{store_id}/bid/products/{offer_id}` | 修改竞价商品 | `super_admin`、`tenant_admin`、`operator` | 版本一致 | 是 | 是 | 竞价对象 |
| `POST /api/v2/bid/sku-floor-prices/import` | 导入底价 | `super_admin`、`tenant_admin`、`operator` | 文件或数据格式有效 | 是 | 是 | `task_id` |
| `POST /api/v2/autobid-v3/stores/{store_id}/shadow-run` | 影子扫描 | `super_admin`、`tenant_admin` | 功能开启 | 是 | 是 | `task_id` |
| `POST /api/v2/autobid-v3/stores/{store_id}/cancel-run` | 取消运行 | `super_admin`、`tenant_admin` | 当前任务可取消 | 是 | 是 | 任务状态 |
| `POST /api/v2/autobid-v3/stores/{store_id}/reset` | 重置 | `super_admin` | 非运行中或具备强制权限 | 是 | 是 | 状态 |

规则：

- 无人工底价不得启用单品竞价。
- 全店启动 / 停止视为高危写操作。
- 底价导入必须任务化，且要有导入结果摘要。

## 11.6 Fulfillment / PO

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/fulfillment/import` | 官方订单导入 | `super_admin`、`tenant_admin`、`system_worker` | 当前无同类运行任务或允许分片导入 | 是 | 否 | `task_id` |
| `POST /api/fulfillment/po` | 创建 PO | `super_admin`、`tenant_admin`、`operator` | 订单项可合单、同仓、未绑定 | 是 | 是 | PO 对象 |
| `POST /api/fulfillment/pos/{po_id}/items` | 新增 PO 明细 | `super_admin`、`tenant_admin`、`operator` | PO 非终态 | 是 | 是 | PO 明细 |
| `PATCH /api/fulfillment/pos/{po_id}/items/{item_id}` | 修改 PO 明细 | `super_admin`、`tenant_admin`、`operator` | 版本一致、PO 可编辑 | 是 | 是 | PO 明细 |
| `POST /api/fulfillment/order-items/{order_item_id}/bind-po` | 绑定订单项到 PO | `super_admin`、`tenant_admin`、`operator` | 订单项未绑定、PO 可编辑 | 是 | 是 | 绑定结果 |
| `PATCH /api/fulfillment/shipments/{shipment_id}` | 修改物流 | `super_admin`、`tenant_admin`、`operator`、`warehouse` | Shipment 非终态 | 是 | 是 | Shipment |
| `POST /api/fulfillment/shipments/{shipment_id}/mark-exception` | 标记异常 | `super_admin`、`tenant_admin`、`operator`、`warehouse` | 当前状态允许异常分流 | 是 | 是 | 异常状态 |

规则：

- `PO_Manager` 是唯一写路径 owner，其他接口必须通过它。
- 禁止跨仓合单。
- 已完成 / 已取消对象只读。

## 11.7 Warehouse

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/warehouse/scan-received` | 到仓扫描 | `warehouse`、`system_worker` | Shipment 存在且在可接收状态 | 是 | 否 | 操作结果 |
| `POST /api/warehouse/packing` | 打包 | `warehouse` | 到仓已确认 | 是 | 否 | 操作结果 |
| `POST /api/warehouse/mark-shipped` | 标记发货 | `warehouse` | 当前批次可出库 | 是 | 是 | 批次状态 |
| `POST /api/warehouse/outbound-batch` | 创建出库批次 | `warehouse`、`operator` | 对象可出库 | 是 | 是 | 批次对象 |
| `POST /api/warehouse/label-record` | 记录标签 | `warehouse` | 当前状态允许贴标 | 是 | 否 | 标签记录 |

规则：

- 扫码接口必须天然幂等，重复扫描返回已有结果。
- 仓库动作优先保证低误触，不允许阶段跨越。

## 11.8 Finance

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/fulfillment/wallet/ledger` | 新增流水 | `super_admin`、`tenant_admin`、`system_worker` | 来源数据合法 | 是 | 是 | 流水对象 |
| `POST /api/finance/jiahong-charges` | 写入嘉鸿费用 | `super_admin`、`tenant_admin`、`system_worker` | 来源记录合法 | 是 | 是 | 费用记录 |
| `POST /api/finance/profit-snapshots/recalculate` | 重算利润快照 | `super_admin`、`tenant_admin` | 对象存在 | 是 | 是 | `task_id` |
| `POST /api/finance/ledgers/{ledger_id}/adjust` | 调整流水 | `super_admin` | 原流水存在且不可直接改写 | 是 | 是 | adjustment 记录 |

规则：

- 财务流水不可覆盖，只能追加 adjustment。
- 利润重算必须任务化。

## 11.9 Extension

| 接口 | 动作 | 角色 | 前置条件 | 幂等 | 审计 | 返回 |
|---|---|---|---|---|---|---|
| `POST /api/extension/auth` | 扩展鉴权 | 已登录用户 | `extension` 功能开启 | 是 | 否 | token |
| `POST /api/extension/profit-preview` | 利润试算 | 已登录用户 | 具备数据访问权限 | 是 | 否 | 预览结果 |
| `POST /api/extension/list-now` | 快速创建任务 | `operator` 以上 | 功能开启、来源合法 | 是 | 是 | `task_id` 或 `job_id` |

## 12. 写接口与错误码绑定规则

每个写接口必须至少绑定：

- `PERM_FORBIDDEN`
- `PERM_FEATURE_DISABLED`
- `VALIDATION_INVALID_INPUT`
- `IDEMP_DUPLICATE_REQUEST`
- `SYSTEM_INTERNAL_ERROR`

如果是任务化接口，还必须绑定：

- `TASK_ALREADY_RUNNING`
- `TASK_DEAD_LETTERED`

如果涉及外部平台，还必须绑定：

- `EXT_TIMEOUT`
- `EXT_RATE_LIMITED`
- `EXT_BAD_RESPONSE`

## 13. 写接口与状态机绑定规则

所有流程推进型接口必须明确声明：

- 当前允许状态
- 写入后的目标状态
- 谁能触发
- 是否可回滚

禁止以下行为：

- 跳过中间状态直接推进终态
- 在终态对象上继续写
- 通过前端拖拽绕过后端状态机
- 用“修正”名义覆盖历史事实

## 14. Smoke Test 最小清单

上线前必须对以下写接口做 smoke test：

- 登录、登出、当前用户
- 创建用户、禁用用户、重置密码
- 创建店铺、触发店铺同步
- 导入底价、启动 / 停止店铺竞价
- 创建 PO、绑定订单项、补录运单
- 到仓扫描、打包、出库
- 新增嘉鸿费用、重算利润快照
- 创建铺货任务、重试铺货任务

