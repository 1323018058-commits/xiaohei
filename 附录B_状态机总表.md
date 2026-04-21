# 附录 B：状态机总表

## 1. 全局原则

- 所有状态必须由后端给出 canonical `status / stage / ui_meta`。
- 前端不得基于多个字段自行推导业务状态。
- 每个状态机必须明确：状态集合、允许转移、触发者、幂等键、异常补偿。
- 终态对象默认只读，除非由具备权限的管理员执行受审计的修正动作。

## 2. 通用 TaskRun 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `queued` | 已入队，等待 worker | `leased`、`cancelled` |
| `leased` | 已被 worker 领取 | `running`、`lease_expired` |
| `running` | 正在执行 | `succeeded`、`failed_retryable`、`failed_final`、`cancel_requested` |
| `failed_retryable` | 可重试失败 | `queued`、`dead_letter` |
| `failed_final` | 不可重试失败 | `dead_letter`、`manual_intervention` |
| `cancel_requested` | 用户请求取消 | `cancelled`、`running` |
| `cancelled` | 已取消 | 终态 |
| `succeeded` | 已成功 | 终态 |
| `dead_letter` | 进入死信 | `manual_intervention` |
| `manual_intervention` | 等待人工处理 | `queued`、`failed_final`、`cancelled` |

幂等键：

```text
tenant_id + task_type + target_type + target_id + action_version
```

## 3. User 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `pending` | 已创建未激活 | `active`、`disabled` |
| `active` | 可登录可使用 | `locked`、`disabled`、`expired` |
| `locked` | 登录风险或错误次数过多 | `active`、`disabled` |
| `expired` | 账号或订阅到期 | `active`、`disabled` |
| `disabled` | 被管理员禁用 | `active` |

规则：

- `disabled` 用户所有会话必须进入 `forced_logout`。
- `expired` 用户默认禁止核心写操作。
- 密码重置后可强制所有会话失效。

## 4. StoreSyncTask 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `created` | 创建同步任务 | `validating_credentials`、`cancelled` |
| `validating_credentials` | 校验凭证 | `syncing_offers`、`failed_final` |
| `syncing_offers` | 同步商品 / Offer | `syncing_orders`、`failed_retryable` |
| `syncing_orders` | 同步订单 | `syncing_finance`、`failed_retryable` |
| `syncing_finance` | 同步财务与交易 | `normalizing`、`failed_retryable` |
| `normalizing` | 标准化外部数据 | `completed`、`quarantined` |
| `quarantined` | 脏数据隔离 | `manual_intervention` |
| `completed` | 同步完成 | 终态 |
| `failed_retryable` | 可重试失败 | `syncing_offers`、`manual_intervention` |
| `failed_final` | 不可重试失败 | 终态 |
| `cancelled` | 已取消 | 终态 |

关键规则：

- 同一店铺同一时间只允许一个全量同步任务运行。
- 外部原始响应必须先进入 inbox，再标准化写入业务表。

## 5. ListingJob / DropshipJob 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `draft` | 已创建未执行 | `fetching`、`cancelled` |
| `fetching` | 抓取外部商品 | `ai_rewriting`、`failed_retryable` |
| `ai_rewriting` | AI 改写 | `category_matching`、`failed_retryable` |
| `category_matching` | 类目匹配 | `loadsheet_generating`、`manual_fix_required` |
| `loadsheet_generating` | 生成 loadsheet | `ready_to_submit`、`failed_retryable` |
| `ready_to_submit` | 待提交 | `submitting`、`manual_fix_required` |
| `submitting` | 提交 Takealot | `reviewing`、`failed_retryable` |
| `reviewing` | 审核中 | `approved`、`rejected`、`review_stale` |
| `approved` | 审核通过 | `linked_to_offer` |
| `linked_to_offer` | 已绑定 Offer | 终态 |
| `rejected` | 审核驳回 | `manual_fix_required` |
| `manual_fix_required` | 等待人工修正 | `ready_to_submit`、`cancelled` |
| `review_stale` | 审核状态过期 | `reviewing`、`manual_intervention` |
| `cancelled` | 已取消 | 终态 |

关键规则：

- 每次重新提交必须生成新的 attempt。
- AI 输出、类目匹配和 loadsheet 必须保留版本快照。
- `approved` 后必须通过外部标识绑定到内部 `BidProduct` 或商品域对象。

## 6. BidProduct 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `no_floor` | 无人工底价 | `ready` |
| `ready` | 可竞价 | `enabled`、`disabled` |
| `enabled` | 已启用自动竞价 | `running`、`paused_by_user`、`paused_by_guardrail` |
| `running` | 本轮执行中 | `price_updated`、`skipped`、`api_error`、`paused_by_guardrail` |
| `price_updated` | 已调价 | `enabled` |
| `skipped` | 本轮跳过 | `enabled` |
| `api_error` | API 失败 | `enabled`、`paused_by_guardrail` |
| `paused_by_user` | 用户暂停 | `enabled` |
| `paused_by_guardrail` | 护栏暂停 | `enabled`、`disabled` |
| `disabled` | 已禁用 | `ready` |

关键规则：

- 无人工底价不得进入 `enabled`。
- 每次调价必须写 `bid_log`。
- BuyBox 数据过期时只能 `skipped`，不能调价。
- Slider 或输入框修改底价只改变配置，不直接触发调价。

## 7. FulfillmentOrderItem 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `imported` | 官方导入 | `po_candidate`、`cancelled` |
| `po_candidate` | 可合单 | `bound_to_po`、`exception` |
| `bound_to_po` | 已绑定 PO | `tracking_required`、`exception` |
| `tracking_required` | 待补号 | `tracking_filled`、`exception` |
| `tracking_filled` | 已补号 | `warehouse_pending` |
| `warehouse_pending` | 等待仓库动作 | `warehouse_processing`、`exception` |
| `warehouse_processing` | 仓库处理中 | `shipped`、`exception` |
| `shipped` | 已发出 | `fulfilled`、`exception` |
| `fulfilled` | 履约完成 | 终态 |
| `cancelled` | 官方取消 | 终态 |
| `exception` | 异常 | `manual_intervention` |
| `manual_intervention` | 人工处理 | `tracking_required`、`warehouse_pending`、`cancelled` |

关键规则：

- 禁止跨仓合单。
- 图片、SKU、数量、目的仓必须参与视觉化对账。

## 8. PO 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `draft` | 草稿 | `open`、`cancelled` |
| `open` | 已创建可编辑 | `tracking_in_progress`、`cancelled` |
| `tracking_in_progress` | 正在补号 | `ready_for_warehouse`、`exception` |
| `ready_for_warehouse` | 可进入仓库流程 | `warehouse_processing` |
| `warehouse_processing` | 仓库处理中 | `shipped`、`exception` |
| `shipped` | 已出库 | `completed`、`exception` |
| `completed` | 完成 | 终态 |
| `cancelled` | 已取消 | 终态 |
| `exception` | 异常 | `manual_intervention` |
| `manual_intervention` | 人工处理 | `open`、`ready_for_warehouse`、`cancelled` |

关键规则：

- `PO_Manager` 是唯一写路径 owner。
- 已完成 / 已取消 PO 默认只读。
- PO 修改必须记录审计和版本。

## 9. Shipment / WarehouseOperation 状态机

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `pending` | 待处理 | `received`、`exception` |
| `received` | 已到仓 | `packing`、`exception` |
| `packing` | 打包中 | `labeling`、`exception` |
| `labeling` | 贴标中 | `ready_to_ship`、`exception` |
| `ready_to_ship` | 待出库 | `shipped`、`exception` |
| `shipped` | 已发货 | `delivered`、`exception` |
| `delivered` | 已送达 | 终态 |
| `exception` | 异常 | `manual_intervention` |
| `manual_intervention` | 人工处理 | `packing`、`ready_to_ship`、`shipped` |

## 10. FinanceSnapshot / WalletLedger 状态机

### FinanceSnapshot

| 状态 | 含义 | 可转移到 |
|---|---|---|
| `draft` | 初始计算 | `calculated`、`failed_retryable` |
| `calculated` | 已计算 | `frozen`、`superseded` |
| `frozen` | 已冻结 | `adjusted` |
| `adjusted` | 已通过调整修正 | `frozen`、`superseded` |
| `superseded` | 被新快照替代 | 终态 |

### WalletLedger

- 流水只允许追加，不允许覆盖或物理删除。
- 错误流水必须通过 adjustment 反向修正。
- 所有财务调整必须有审计原因。

