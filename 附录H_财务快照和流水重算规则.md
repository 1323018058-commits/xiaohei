# 附录 H：财务快照和流水重算规则

## 1. 目标

财务模块必须保证：

- 流水不可篡改
- 快照可重算
- 调整有痕迹
- 结果可追溯
- 错账可修正

本附录冻结：

- 财务对象边界
- 流水规则
- 快照规则
- 重算触发器
- 汇率与时间口径
- 调整与对账规则

## 2. 财务对象

核心对象至少包括：

- `finance_wallet_accounts`
- `finance_wallet_ledgers`
- `finance_profit_snapshots`
- `jiahong_logistics_charges`
- `finance_recalculation_tasks`
- `finance_adjustments`

建议补充：

- `finance_snapshot_inputs`
- `finance_reconciliation_runs`
- `finance_exchange_rates`

## 3. 基本原则

1. 钱包流水只允许追加，不允许覆盖或物理删除。  
2. 利润快照允许重算，但必须版本化。  
3. 错误流水通过 adjustment 修正，不直接改原流水。  
4. 每个快照必须能追溯到输入来源。  
5. 汇率、税费、物流费用口径必须固定到快照版本。  

## 4. 钱包流水分类

建议分类：

- `sale_income`
- `purchase_cost`
- `po_fee`
- `label_fee`
- `shipping_headhaul`
- `shipping_lastmile`
- `commission_fee`
- `commission_vat`
- `import_vat`
- `customs_duty`
- `warehouse_fee`
- `jiahong_fee`
- `adjustment_positive`
- `adjustment_negative`
- `refund`
- `writeoff`

要求：

- 每条流水必须有明确 `ledger_type`
- 每条流水必须可追溯来源对象

## 5. finance_wallet_ledgers 字段全集

| 字段 | 必填 | 说明 |
|---|---:|---|
| `ledger_id` | 是 | 流水 ID |
| `wallet_account_id` | 是 | 钱包账户 |
| `tenant_id` | 是 | 租户 |
| `store_id` | 否 | 店铺 |
| `order_id` | 否 | 订单 |
| `order_item_id` | 否 | 订单项 |
| `po_id` | 否 | PO |
| `shipment_id` | 否 | Shipment |
| `source_type` | 是 | 来源类型 |
| `source_id` | 否 | 来源对象 ID |
| `ledger_type` | 是 | 流水分类 |
| `currency` | 是 | 货币 |
| `amount` | 是 | 金额，正负分明 |
| `exchange_rate` | 否 | 汇率 |
| `base_currency` | 是 | 基准货币 |
| `base_amount` | 否 | 折算后金额 |
| `occurred_at` | 是 | 业务发生时间 |
| `recorded_at` | 是 | 入账时间 |
| `status` | 是 | `posted` / `reversed` / `adjusted` |
| `snapshot_version` | 否 | 被哪些快照版本消费 |
| `note` | 否 | 备注 |
| `created_by` | 否 | 发起用户或系统 |
| `created_at` | 是 | 创建时间 |

## 6. finance_profit_snapshots 字段全集

| 字段 | 必填 | 说明 |
|---|---:|---|
| `snapshot_id` | 是 | 快照 ID |
| `tenant_id` | 是 | 租户 |
| `store_id` | 否 | 店铺 |
| `scope_type` | 是 | `order` / `order_item` / `store_day` / `store_period` |
| `scope_id` | 否 | 范围对象 ID |
| `snapshot_version` | 是 | 版本号 |
| `status` | 是 | `draft` / `calculated` / `frozen` / `superseded` / `failed` |
| `base_currency` | 是 | 基准币种 |
| `sale_income` | 否 | 销售收入 |
| `purchase_cost` | 否 | 采购成本 |
| `logistics_cost` | 否 | 物流成本 |
| `commission_fee` | 否 | 佣金 |
| `tax_cost` | 否 | 税费 |
| `warehouse_cost` | 否 | 仓库成本 |
| `other_cost` | 否 | 其他成本 |
| `profit_amount` | 否 | 利润 |
| `margin_rate` | 否 | 利润率 |
| `input_hash` | 是 | 输入快照哈希 |
| `calculated_at` | 否 | 计算时间 |
| `frozen_at` | 否 | 冻结时间 |
| `superseded_by` | 否 | 被哪个版本替代 |
| `created_by` | 否 | 发起者 |
| `created_at` | 是 | 创建时间 |

## 7. 利润公式口径

首发统一利润口径：

```text
利润
  = 销售收入
  - 采购成本
  - PO 费
  - 贴单费
  - 头程运费
  - 尾程运费
  - 佣金
  - 佣金 VAT
  - 进口 VAT
  - 关税
  - 仓库费用
  - 嘉鸿费用
  - 其他已确认费用
```

要求：

- 公式必须版本化
- 版本变化不得静默影响历史快照

## 8. 快照范围

支持以下快照粒度：

- `order_item`
- `order`
- `store_day`
- `store_period`

首发优先级：

1. `order_item`
2. `order`
3. `store_day`

## 9. 重算触发器

以下事件必须触发重算或重算评估：

- 订单导入或订单状态变化
- PO 创建或 PO 成本变化
- 运单补录
- Shipment 状态变化
- 嘉鸿费用写入
- 财务流水新增
- 汇率变更
- 税费规则变更
- 人工 adjustment
- 外部交易流水同步完成

## 10. 重算模式

### 10.1 增量重算

适用于：

- 单个订单
- 单个订单项
- 单个 PO
- 单笔费用补录

规则：

- 仅重算受影响对象
- 如果对象已冻结，则生成新版本快照

### 10.2 批量重算

适用于：

- 店铺日级重算
- 某时间段重算
- 汇率口径变化
- 公式版本变化

规则：

- 必须任务化
- 必须产出批量重算报告
- 必须可中断、可恢复

## 11. 冻结规则

- `calculated` 表示已算出，但仍可被替代
- `frozen` 表示已作为正式财务口径对外展示
- `superseded` 表示已有新版本替代

冻结条件建议：

- 订单已履约完成
- 相关费用已到齐或超过等待窗口
- 当前账期确认

## 12. adjustment 规则

错误数据不得直接覆盖，必须通过 adjustment 修正。

adjustment 最少字段：

- `adjustment_id`
- `ledger_id`
- `snapshot_id`
- `reason`
- `amount_delta`
- `created_by`
- `created_at`

规则：

- adjustment 必须有审计原因
- adjustment 必须保留原始引用
- adjustment 后必须触发受影响快照重算

## 13. 汇率规则

- 所有跨币种成本必须记录使用的汇率版本
- 快照必须写入 `exchange_rate`
- 汇率来源必须固定，不得在同一快照中混用多个口径
- 汇率变化后只触发新版本快照，不覆盖历史结果

## 14. 输入哈希与版本化

每个快照都必须计算 `input_hash`。

输入应至少包含：

- 订单收入
- 采购成本
- 物流费用
- 佣金
- 税费
- 仓库费用
- 其他费用
- 汇率版本
- 公式版本

当以下任一变化时，应生成新版本：

- 输入数据变化
- 汇率变化
- 公式版本变化
- adjustment 发生

## 15. 重算任务规则

利润重算必须走任务系统。

建议任务类型：

- `finance.snapshot.recalculate.item`
- `finance.snapshot.recalculate.order`
- `finance.snapshot.recalculate.store_day`
- `finance.snapshot.recalculate.store_period`

任务返回必须包含：

- 受影响对象数量
- 新增快照数量
- superseded 快照数量
- 失败对象数量

## 16. 对账规则

首发必须支持基础对账视图：

- 订单收入 vs 钱包收入
- Shipment / 嘉鸿费用 vs 财务费用
- PO 成本 vs 采购成本
- 快照利润 vs 流水累计成本

对账结果状态：

- `matched`
- `tolerance_warning`
- `mismatch`
- `missing_input`

## 17. 失败与异常

以下情况进入异常处理：

- 来源数据缺失
- 金额异常
- 汇率缺失
- 输入对象已删除或不可用
- 成本重复入账
- 同一来源多次记账

处理策略：

- 阻止冻结
- 标记异常
- 进入人工介入
- 保留原始数据引用

## 18. 页面展示规则

- 财务页面优先展示 `frozen` 快照
- 若只有 `calculated` 无 `frozen`，必须标识为“预估”
- 若存在 `superseded`，前端默认展示最新版本
- 必须能查看快照版本历史
- 必须能查看利润由哪些流水与费用构成

## 19. 首发必须落地的能力

- 钱包流水只追加
- 嘉鸿费用写入
- 订单级或订单项级利润快照
- 受影响对象重算
- 冻结与替代机制
- adjustment 机制
- 基础对账视图
