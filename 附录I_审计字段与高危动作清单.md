# 附录 I：审计字段与高危动作清单

## 1. 目标

审计系统用于回答四个问题：

1. 谁操作了什么  
2. 什么时候操作  
3. 操作前后发生了什么变化  
4. 为什么允许这次操作  

本附录冻结：

- 审计字段全集
- 高危动作清单
- 审计事件类型
- 脱敏与保留规则
- 告警触发规则
- 前端展示规则

## 2. 审计总原则

1. 审计日志只追加，不允许覆盖或物理删除。  
2. 高危动作必须先写业务结果，再写审计结果；如果审计失败，高危动作应整体失败或进入补偿队列。  
3. 审计日志必须绑定 `request_id`。  
4. 审计日志必须记录 actor、target、action、before、after、reason。  
5. 审计日志必须支持按用户、租户、对象、动作、时间检索。  
6. 审计日志中的敏感值必须脱敏。  

## 3. audit_logs 字段全集

| 字段 | 必填 | 说明 |
|---|---:|---|
| `audit_id` | 是 | 审计记录 ID |
| `request_id` | 是 | 请求链路 ID |
| `tenant_id` | 否 | 租户 ID |
| `store_id` | 否 | 店铺 ID |
| `actor_type` | 是 | `user` / `system_worker` / `scheduler` / `support` |
| `actor_user_id` | 否 | 操作用户 ID |
| `actor_role` | 否 | 操作角色 |
| `actor_display_name` | 否 | 展示名称 |
| `impersonator_user_id` | 否 | 代操作人 ID |
| `session_id` | 否 | 会话 ID |
| `source` | 是 | `web` / `api` / `worker` / `extension` / `scheduler` |
| `ip` | 否 | 来源 IP |
| `user_agent` | 否 | UA |
| `action` | 是 | 动作编码 |
| `action_label` | 是 | 动作展示名称 |
| `risk_level` | 是 | `low` / `medium` / `high` / `critical` |
| `target_type` | 是 | 目标对象类型 |
| `target_id` | 否 | 目标对象 ID |
| `target_label` | 否 | 目标展示名称 |
| `before` | 否 | 操作前快照 |
| `after` | 否 | 操作后快照 |
| `diff` | 否 | 字段级差异 |
| `reason` | 否 | 操作原因 |
| `result` | 是 | `success` / `failed` / `partial` |
| `error_code` | 否 | 失败错误码 |
| `idempotency_key` | 否 | 幂等键 |
| `task_id` | 否 | 关联任务 |
| `approval_id` | 否 | 审批记录 |
| `metadata` | 否 | 扩展 JSON |
| `created_at` | 是 | 创建时间 |

## 4. 审计风险等级

| 风险等级 | 定义 | 示例 |
|---|---|---|
| `low` | 普通读写，不影响安全和资金 | 商品标注、普通备注 |
| `medium` | 影响业务流程但可恢复 | 任务重试、订单异常标记 |
| `high` | 影响权限、履约、竞价或财务 | 禁用用户、启停竞价、创建 PO |
| `critical` | 影响平台安全、资金或大批量外部写入 | 重置管理员密码、批量调价、财务调整 |

## 5. 高危动作总清单

## 5.1 Auth / Admin / Subscription

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `admin.user.create` | 创建用户 | `medium` | 否 | 否 |
| `admin.user.disable` | 禁用用户 | `high` | 是 | 是 |
| `admin.user.enable` | 启用用户 | `high` | 是 | 是 |
| `admin.user.lock` | 锁定用户 | `high` | 是 | 是 |
| `admin.user.reset_password` | 重置密码 | `critical` | 是 | 是 |
| `admin.user.force_logout` | 强制下线 | `high` | 是 | 是 |
| `admin.user.set_expiry` | 设置到期时间 | `high` | 是 | 是 |
| `admin.user.feature_flags.update` | 修改功能权限 | `critical` | 是 | 是 |
| `admin.role.change` | 修改角色 | `critical` | 是 | 是 |
| `admin.subscription.change` | 修改订阅状态 | `critical` | 是 | 是 |

## 5.2 Store / Credentials

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `store.create` | 创建店铺 | `medium` | 否 | 否 |
| `store.update` | 修改店铺 | `medium` | 否 | 否 |
| `store.delete` | 删除 / 停用店铺 | `critical` | 是 | 是 |
| `store.credentials.update` | 更新店铺凭证 | `critical` | 是 | 是 |
| `store.sync.start` | 触发店铺同步 | `medium` | 否 | 否 |
| `store.sync.force` | 强制全量同步 | `high` | 是 | 是 |

## 5.3 Product / Selection / Listing

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `selection.export` | 导出选品报告 | `medium` | 否 | 否 |
| `listing.job.create` | 创建铺货任务 | `medium` | 否 | 否 |
| `listing.job.retry` | 重试铺货任务 | `high` | 是 | 是 |
| `listing.job.submit` | 提交审核 | `high` | 是 | 是 |
| `listing.job.cancel` | 取消铺货任务 | `medium` | 是 | 是 |
| `listing.job.manual_fix` | 人工修正铺货结果 | `high` | 是 | 是 |

## 5.4 AutoBid

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `bid.store.start` | 启动全店竞价 | `critical` | 是 | 是 |
| `bid.store.stop` | 停止全店竞价 | `high` | 是 | 是 |
| `bid.store.resume` | 恢复全店竞价 | `critical` | 是 | 是 |
| `bid.product.enable` | 启用单品竞价 | `high` | 是 | 是 |
| `bid.product.disable` | 禁用单品竞价 | `medium` | 否 | 否 |
| `bid.floor.import` | 导入 SKU 底价 | `critical` | 是 | 是 |
| `bid.floor.update` | 修改 SKU 底价 | `critical` | 是 | 是 |
| `bid.execution.force` | 强制执行调价 | `critical` | 是 | 是 |
| `bid.run.cancel` | 取消竞价任务 | `high` | 是 | 是 |
| `bid.reset` | 重置竞价状态 | `critical` | 是 | 是 |

## 5.5 Fulfillment / PO

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `fulfill.import.force` | 强制导入订单 | `high` | 是 | 是 |
| `po.create` | 创建 PO | `high` | 是 | 是 |
| `po.item.add` | 新增 PO 明细 | `medium` | 否 | 否 |
| `po.item.update` | 修改 PO 明细 | `high` | 是 | 是 |
| `po.cancel` | 取消 PO | `critical` | 是 | 是 |
| `po.bind_order_item` | 绑定订单项到 PO | `high` | 是 | 是 |
| `shipment.update` | 修改物流信息 | `high` | 是 | 是 |
| `shipment.mark_exception` | 标记物流异常 | `high` | 是 | 是 |
| `fulfill.manual_override` | 履约人工覆盖 | `critical` | 是 | 是 |

## 5.6 Warehouse

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `warehouse.scan_received` | 到仓扫描 | `medium` | 否 | 否 |
| `warehouse.packing` | 打包 | `medium` | 否 | 否 |
| `warehouse.label_record` | 标签记录 | `medium` | 否 | 否 |
| `warehouse.mark_shipped` | 标记出库 | `high` | 是 | 是 |
| `warehouse.batch.create` | 创建出库批次 | `high` | 是 | 是 |
| `warehouse.operation.override` | 仓库动作人工覆盖 | `critical` | 是 | 是 |

## 5.7 Finance

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `finance.ledger.create` | 新增流水 | `high` | 是 | 是 |
| `finance.ledger.adjust` | 调整流水 | `critical` | 是 | 是 |
| `finance.charge.create` | 写入嘉鸿费用 | `high` | 是 | 是 |
| `finance.snapshot.recalculate` | 重算利润快照 | `high` | 是 | 是 |
| `finance.snapshot.freeze` | 冻结快照 | `critical` | 是 | 是 |
| `finance.snapshot.supersede` | 替代快照 | `critical` | 是 | 是 |

## 5.8 Task / Recovery

| 动作编码 | 动作 | 风险 | 必填原因 | 是否二次确认 |
|---|---|---|---:|---:|
| `task.retry` | 重试任务 | `medium` | 否 | 否 |
| `task.cancel` | 取消任务 | `high` | 是 | 是 |
| `task.dead_letter.retry` | 死信重试 | `critical` | 是 | 是 |
| `task.manual_intervention` | 人工介入任务 | `critical` | 是 | 是 |
| `task.force_unlock` | 强制释放租约 | `critical` | 是 | 是 |

## 6. before / after 记录规则

必须记录 before / after 的对象：

- 用户状态
- 角色与权限
- 到期时间
- 功能开关
- 店铺凭证状态
- 竞价配置
- SKU 底价
- PO 与 PO 明细
- Shipment
- 财务流水与 adjustment
- 利润快照状态

敏感值规则：

- 密码永不记录明文或 hash。
- API Key、Token 只记录脱敏前后缀。
- 金额字段必须记录完整值。
- 权限字段必须记录完整差异。

## 7. 审计结果规则

| result | 含义 |
|---|---|
| `success` | 操作成功 |
| `failed` | 操作失败 |
| `partial` | 部分成功 |
| `blocked` | 被权限、状态机或护栏拦截 |

要求：

- 被系统拦截的高危操作也要记录审计。
- 失败审计必须绑定 `error_code`。

## 8. 审计与告警

以下情况必须触发告警或进入安全观察：

- 短时间内多次登录失败
- 多次重置密码
- 非工作时间大量修改权限
- 大批量导入底价
- 启动全店自动竞价
- 批量调价失败率异常
- 财务 adjustment 金额异常
- 死信任务被频繁恢复
- 同一账号从异常 IP 登录

告警对象：

- `super_admin`
- 系统运维
- 对应租户管理员

## 9. 审计保留规则

- 高危审计至少保留 2 年。
- 普通审计至少保留 180 天。
- 财务审计不得短于财务数据保留周期。
- 审计数据归档后仍必须可检索。

## 10. 前端展示规则

Admin 审计页面必须支持：

- 按用户过滤
- 按对象过滤
- 按动作过滤
- 按风险等级过滤
- 按时间过滤
- 查看 before / after diff
- 查看 request_id 与 task_id

展示原则：

- 默认只展示摘要
- 详情通过抽屉展开
- 敏感字段默认脱敏
- critical 操作使用更明显的视觉标记

## 11. 首发必须落地的审计能力

`2026-05-01` 前必须落地：

- 用户禁用 / 启用审计
- 密码重置审计
- 到期时间修改审计
- 功能权限修改审计
- 店铺凭证修改审计
- 自动竞价启停审计
- SKU 底价导入审计
- PO 创建 / 取消审计
- 履约异常标记审计
- 财务流水与 adjustment 审计
- 任务死信恢复审计

## 12. 禁止事项

- 禁止物理删除审计日志。
- 禁止记录密码明文。
- 禁止在前端绕过高危确认。
- 禁止无 `request_id` 写高危审计。
- 禁止高危操作无原因通过。
- 禁止审计失败但业务高危操作静默成功。
