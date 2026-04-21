# 附录 D：外部接口去重与重试策略

## 1. 总原则

- 所有外部平台必须通过 adapter 层访问。
- 业务服务不得直接调用 Takealot、1688、Amazon、DeepSeek、CNExpress。
- 外部响应必须先进入 `connector_inbox`，再标准化进入业务表。
- 内部状态变更必须通过 `outbox` 事件分发给下游模块。
- 外部接口失败不能拖垮主站。

## 2. Connector 标准流程

```text
业务请求
  → 创建 TaskRun
  → Adapter 调外部平台
  → 原始响应写 connector_inbox
  → Normalizer 标准化
  → 写业务表
  → 写 outbox 事件
  → 下游幂等消费
```

## 3. 去重键

### Inbox 去重键

```text
provider + endpoint + external_id + payload_hash
```

### Outbox 去重键

```text
event_type + aggregate_type + aggregate_id + version
```

### 写操作幂等键

```text
tenant_id + actor_id + action + target_type + target_id + client_request_id
```

## 4. 通用超时与重试

| 操作类型 | 超时建议 | 重试次数 | 策略 |
|---|---:|---:|---|
| 外部 `GET` / 查询 | 5s ~ 10s | 3 | 指数退避 + 抖动 |
| 外部 `POST` / 创建 | 10s ~ 20s | 1 ~ 2 | 仅在可确认幂等时重试 |
| 外部 `PATCH` / 修改 | 10s ~ 20s | 1 | 必须带幂等或状态确认 |
| AI 调用 | 20s ~ 45s | 2 | 失败可进入人工编辑 |
| 文件 / loadsheet 上传 | 30s ~ 60s | 2 | 失败保留草稿 |

重试退避：

```text
第 1 次：5s + jitter
第 2 次：30s + jitter
第 3 次：120s + jitter
后续：进入 dead_letter 或 manual_intervention
```

## 5. 熔断策略

触发以下条件之一时进入 provider 级熔断：

- 连续超时达到阈值
- 外部返回大量 `5xx`
- 外部返回限流
- 响应结构明显异常
- 关键字段缺失率异常升高

熔断后：

- 暂停新的非关键任务
- 保留手工重试入口
- Dashboard 展示外部依赖异常
- 已入队任务延迟执行

## 6. Provider 策略

### 6.1 Takealot

优先级：`P0`

用途：

- 店铺同步
- 商品 / offers
- 订单
- 财务
- loadsheet submission
- 调价

策略：

- 订单、商品、财务同步允许分段失败，不能整体回滚全部结果
- 调价操作必须先记录决策，再执行外部 PATCH
- 调价后必须写 `bid_log`
- 调价失败不得假成功
- BuyBox 数据必须记录 `fetched_at`，过期不得用于调价

### 6.2 CNExpress

优先级：`P0`

用途：

- 物流轨迹
- 仓库动作
- 钱包 / 费用
- 标签

策略：

- 物流状态允许延迟最终一致
- 仓库动作必须幂等
- 重复扫描必须返回已有记录
- 费用数据进入财务前必须保留来源快照

### 6.3 1688

优先级：`P1`

用途：

- 图搜
- 商品匹配
- 价格与货源参考

策略：

- 失败不阻塞主站
- 脏数据进入隔离区
- 相似度低于阈值不得自动进入铺货
- 首发允许结果只读或人工确认

### 6.4 Amazon / 886it

优先级：`P1`

用途：

- 商品详情抓取
- 关键词 seeds

策略：

- API 失败可降级到 Playwright 兜底
- Playwright 任务必须限并发
- 抓取失败进入可重试任务，不阻塞其他模块

### 6.5 DeepSeek AI

优先级：`P1`

用途：

- 标题改写
- 描述改写
- 卖点生成
- 类目建议

策略：

- AI 输出必须保留原始版本
- AI 输出必须允许人工编辑
- AI 不得直接越过审核提交外部平台
- AI 失败时任务进入 `manual_fix_required` 或 `failed_retryable`

## 7. 脏数据隔离

进入隔离区的条件：

- 必填字段缺失
- 金额、数量、价格明显异常
- 外部状态无法映射到内部状态机
- 响应结构不符合预期
- 关键唯一标识缺失

隔离区要求：

- 保存原始 payload
- 保存解析错误
- 保存 provider、endpoint、request_id
- 支持人工标记为忽略、重试、手工修正

## 8. 队列与限流

- 每个 provider 必须有独立并发限制。
- 外部 API 任务不得与核心登录、管理后台请求共用资源池。
- 店铺同步、全量抓取、大规模调价必须排队削峰。
- 恢复 watcher 不得无限循环重试失败任务。

## 9. 禁止事项

- 禁止业务代码直接调用外部平台。
- 禁止外部返回未经标准化直接写业务核心表。
- 禁止外部调用超时后向用户返回业务成功。
- 禁止无幂等地重试外部写操作。
- 禁止 AI 输出直接进入外部 submission。

