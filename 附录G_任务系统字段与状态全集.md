# 附录 G：任务系统字段与状态全集

## 1. 目标

任务系统是全局运行骨架，用于承载所有长耗时、可重试、需审计、需异步化的动作。

本附录冻结：

- 任务对象模型
- 字段全集
- 状态全集
- 事件全集
- 租约与重试规则
- 进度表达规则
- 死信与人工介入规则

## 2. 任务对象分层

任务系统至少包含以下四类对象：

- `task_definitions`
- `task_runs`
- `task_events`
- `task_leases`

建议补充：

- `task_dead_letters`
- `task_checkpoints`
- `task_dependencies`

## 3. task_definitions 字段全集

`task_definitions` 用于定义任务模板，而非执行实例。

| 字段 | 必填 | 说明 |
|---|---:|---|
| `task_type` | 是 | 任务类型，如 `store.sync.full` |
| `domain` | 是 | 所属业务域，如 `store`、`bidding` |
| `display_name` | 是 | 页面展示名称 |
| `queue_name` | 是 | 所属队列 |
| `priority` | 是 | 默认优先级 |
| `max_retries` | 是 | 最大重试次数 |
| `lease_timeout_seconds` | 是 | 默认租约超时 |
| `is_cancellable` | 是 | 是否允许取消 |
| `is_high_risk` | 是 | 是否高危任务 |
| `idempotency_scope` | 是 | 幂等范围定义 |
| `retention_days` | 是 | 数据保留天数 |
| `enabled` | 是 | 是否启用 |
| `created_at` | 是 | 创建时间 |
| `updated_at` | 是 | 更新时间 |

## 4. task_runs 字段全集

`task_runs` 是任务执行实例的核心表。

| 字段 | 必填 | 说明 |
|---|---:|---|
| `task_id` | 是 | 任务唯一标识 |
| `task_type` | 是 | 任务类型 |
| `domain` | 是 | 所属业务域 |
| `status` | 是 | 任务状态 |
| `stage` | 是 | 当前阶段 |
| `progress_percent` | 否 | 0~100 进度 |
| `progress_current` | 否 | 当前完成数量 |
| `progress_total` | 否 | 总数量 |
| `priority` | 是 | 当前优先级 |
| `queue_name` | 是 | 所属队列 |
| `tenant_id` | 否 | 所属租户 |
| `store_id` | 否 | 关联店铺 |
| `actor_user_id` | 否 | 发起人 |
| `actor_role` | 否 | 发起角色 |
| `source_type` | 否 | 来源，如 `api`、`scheduler`、`worker` |
| `target_type` | 否 | 目标对象类型 |
| `target_id` | 否 | 目标对象 ID |
| `request_id` | 是 | 请求链路 ID |
| `idempotency_key` | 否 | 幂等键 |
| `parent_task_id` | 否 | 父任务 |
| `root_task_id` | 否 | 根任务 |
| `dependency_state` | 否 | 依赖状态 |
| `attempt_count` | 是 | 当前尝试次数 |
| `max_retries` | 是 | 最大重试次数 |
| `retryable` | 是 | 当前是否允许重试 |
| `next_retry_at` | 否 | 下次重试时间 |
| `lease_owner` | 否 | 当前 worker |
| `lease_token` | 否 | fencing token |
| `lease_expires_at` | 否 | 租约过期时间 |
| `started_at` | 否 | 开始时间 |
| `finished_at` | 否 | 完成时间 |
| `last_heartbeat_at` | 否 | 最近心跳 |
| `cancel_requested_at` | 否 | 请求取消时间 |
| `cancel_reason` | 否 | 取消原因 |
| `error_code` | 否 | 当前错误码 |
| `error_msg` | 否 | 错误摘要 |
| `error_details` | 否 | 错误详情 JSON |
| `ui_meta` | 否 | 前端展示元信息 |
| `input_payload_ref` | 否 | 输入快照引用 |
| `output_payload_ref` | 否 | 输出快照引用 |
| `created_at` | 是 | 创建时间 |
| `updated_at` | 是 | 更新时间 |

## 5. task_events 字段全集

`task_events` 用于保存任务生命周期事件。

| 字段 | 必填 | 说明 |
|---|---:|---|
| `event_id` | 是 | 事件 ID |
| `task_id` | 是 | 关联任务 |
| `event_type` | 是 | 事件类型 |
| `from_status` | 否 | 原状态 |
| `to_status` | 否 | 新状态 |
| `stage` | 否 | 当前阶段 |
| `message` | 否 | 人类可读信息 |
| `details` | 否 | JSON 详情 |
| `source` | 是 | `api`、`worker`、`watcher` |
| `source_id` | 否 | 来源对象 ID |
| `created_at` | 是 | 事件时间 |

## 6. task_leases 字段全集

`task_leases` 用于约束 worker 执行权。

| 字段 | 必填 | 说明 |
|---|---:|---|
| `task_id` | 是 | 任务 ID |
| `worker_id` | 是 | worker 实例 ID |
| `lease_token` | 是 | fencing token |
| `leased_at` | 是 | 领取时间 |
| `expires_at` | 是 | 过期时间 |
| `heartbeat_at` | 否 | 最近心跳 |
| `released_at` | 否 | 释放时间 |
| `release_reason` | 否 | 释放原因 |

## 7. 状态全集

| 状态 | 含义 | 是否终态 |
|---|---|---:|
| `created` | 已创建未入队 | 否 |
| `queued` | 已入队等待执行 | 否 |
| `leased` | 已被 worker 领取 | 否 |
| `running` | 正在执行 | 否 |
| `waiting_dependency` | 等待依赖任务 | 否 |
| `waiting_retry` | 等待下次重试 | 否 |
| `cancel_requested` | 已请求取消 | 否 |
| `cancelled` | 已取消 | 是 |
| `succeeded` | 已成功 | 是 |
| `failed_retryable` | 可重试失败 | 否 |
| `failed_final` | 不可重试失败 | 是 |
| `dead_letter` | 已进入死信 | 是 |
| `manual_intervention` | 等待人工介入 | 否 |
| `timed_out` | 超时 | 否 |
| `quarantined` | 因脏数据或风险被隔离 | 否 |

## 8. 阶段全集

阶段是任务内部语义，不同任务类型可有不同取值，但必须符合统一规则。

统一阶段模板：

- `created`
- `precheck`
- `preparing`
- `fetching`
- `validating`
- `normalizing`
- `executing`
- `syncing`
- `reconciling`
- `finalizing`
- `completed`
- `failed`
- `cancelled`
- `manual_intervention`

要求：

- `status` 体现生命周期
- `stage` 体现当前步骤
- 页面必须同时消费二者

## 9. 事件类型全集

| 事件类型 | 含义 |
|---|---|
| `task.created` | 创建任务 |
| `task.queued` | 入队 |
| `task.leased` | 被 worker 领取 |
| `task.started` | 开始执行 |
| `task.progress` | 进度更新 |
| `task.stage.changed` | 阶段变化 |
| `task.retry.scheduled` | 安排重试 |
| `task.retry.started` | 开始重试 |
| `task.cancel.requested` | 请求取消 |
| `task.cancelled` | 已取消 |
| `task.failed.retryable` | 可重试失败 |
| `task.failed.final` | 不可重试失败 |
| `task.dead_lettered` | 进入死信 |
| `task.manual_intervention` | 人工介入 |
| `task.succeeded` | 成功完成 |
| `task.quarantined` | 被隔离 |
| `task.resumed` | 人工恢复 |

## 10. 进度字段规则

### 10.1 百分比进度

适用于已知总量的任务：

- 商品同步
- 订单导入
- 大规模调价
- 批量铺货

规则：

```text
progress_percent = floor(progress_current / progress_total * 100)
```

### 10.2 阶段型进度

适用于总量未知或外部阻塞型任务：

- 审核同步
- AI 调用
- 外部校验

规则：

- 前端优先展示 `stage`
- 百分比可为空
- 必须提供最近事件

## 11. UI 元信息规范

`ui_meta` 至少支持：

- `title`
- `subtitle`
- `action_label`
- `action_enabled`
- `severity`
- `highlight_fields`
- `next_suggested_action`
- `blocking_reason`
- `detail_url`

要求：

- `ui_meta` 只用于前端表达，不替代真实状态。

## 12. 重试规则

| 情况 | 策略 |
|---|---|
| 外部超时 | 指数退避重试 |
| 外部限流 | 延迟重试 |
| 参数错误 | 不重试 |
| 权限错误 | 不重试 |
| 脏数据 | 隔离或人工介入 |
| worker 崩溃 | 由 lease 过期后重新入队 |

重试必须记录：

- 当前 attempt
- 上次错误
- 下次重试时间
- 是否仍可重试

## 13. 取消规则

- 非所有任务都允许取消。
- `cancel_requested` 不等于立即取消。
- worker 必须在安全 checkpoint 才能执行取消。
- 已对外部平台发出不可逆写操作的任务，不得直接伪装成已取消。

取消最少字段：

- `cancel_requested_at`
- `cancel_reason`
- `cancelled_by_user_id`
- `cancel_result`

## 14. 死信与人工介入

进入 `dead_letter` 的条件：

- 达到最大重试次数
- 不可恢复数据异常
- 外部平台持续异常且超过时限

死信必须支持：

- 查看原始输入
- 查看错误历史
- 查看依赖对象
- 重新入队
- 标记忽略
- 转人工修正

## 15. 心跳与 watcher 规则

- 运行中任务必须定期刷新 `last_heartbeat_at`
- watcher 发现租约过期后：
  - 标记 `timed_out`
  - 写 `task.failed.retryable` 或 `task.dead_lettered`
  - 根据规则重新入队或进入人工介入

## 16. 队列与优先级

优先级建议：

- `P0`: 登录态恢复、管理员高危修正、订单导入
- `P1`: 店铺同步、竞价执行、PO 推进
- `P2`: 商品情报、选品导出、AI 改写
- `P3`: 批量抓取、低优先级报表

要求：

- 不同队列必须支持隔离
- 外部依赖任务不得挤占核心登录和管理操作资源

## 17. 保留与归档

- `task_runs` 热数据保留至少 30 天
- `task_events` 详细事件保留至少 30 天
- `dead_letter` 保留至少 90 天
- 审计关联任务不得提前删除

## 18. 首发必须落地的任务类型

- `store.sync.full`
- `store.sync.products`
- `store.sync.orders`
- `listing.job.run`
- `listing.review.sync`
- `bidding.products.sync`
- `bidding.store.start`
- `bidding.bulk.execute`
- `fulfillment.import.orders`
- `fulfillment.po.reconcile`
- `finance.snapshot.recalculate`
- `provider.credentials.validate`

