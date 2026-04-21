# 附录 C：错误码表

## 1. 标准错误返回

所有 API 错误必须返回统一结构：

```json
{
  "ok": false,
  "error_code": "AUTH_INVALID_CREDENTIALS",
  "message": "用户名或密码错误",
  "request_id": "req_xxx",
  "retryable": false,
  "details": {}
}
```

## 2. 命名空间

| 前缀 | 领域 |
|---|---|
| `AUTH` | 登录、会话、密码 |
| `PERM` | 权限、角色、功能授权 |
| `SUB` | 订阅、到期、套餐 |
| `RATE` | 限流、并发门禁 |
| `IDEMP` | 幂等、重复提交 |
| `TASK` | 任务、队列、worker |
| `EXT` | 外部平台集成 |
| `VALIDATION` | 参数校验 |
| `STORE` | 店铺 |
| `LISTING` | 铺货 |
| `BID` | 自动竞价 |
| `FULFILL` | 履约 |
| `WAREHOUSE` | 仓库 |
| `FINANCE` | 财务 |
| `SYSTEM` | 系统级错误 |

## 3. 通用错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `VALIDATION_INVALID_INPUT` | 400 | 否 | 输入内容不正确 | 高亮字段错误 |
| `PERM_FORBIDDEN` | 403 | 否 | 当前账号没有权限 | 提示联系管理员 |
| `PERM_FEATURE_DISABLED` | 403 | 否 | 当前功能未开通 | 展示功能开关原因 |
| `SUB_EXPIRED` | 403 | 否 | 账号已到期 | 引导续费或联系管理员 |
| `RATE_LIMITED` | 429 | 是 | 操作过于频繁，请稍后重试 | 前端退避 |
| `IDEMP_DUPLICATE_REQUEST` | 409 | 否 | 请求已提交，请勿重复操作 | 返回已有任务或对象 |
| `SYSTEM_UNAVAILABLE` | 503 | 是 | 系统繁忙，请稍后重试 | 熔断或降级 |
| `SYSTEM_INTERNAL_ERROR` | 500 | 否 | 系统异常，请联系管理员 | 记录 request_id |

## 4. Auth / Admin 错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `AUTH_INVALID_CREDENTIALS` | 401 | 否 | 用户名或密码错误 | 登录失败计数 |
| `AUTH_ACCOUNT_LOCKED` | 423 | 否 | 账号已锁定 | 引导管理员解锁 |
| `AUTH_SESSION_EXPIRED` | 401 | 否 | 登录已过期 | 跳转登录 |
| `AUTH_SESSION_REVOKED` | 401 | 否 | 当前会话已失效 | 跳转登录 |
| `AUTH_PASSWORD_RESET_REQUIRED` | 403 | 否 | 请先修改密码 | 跳转改密 |
| `ADMIN_HIGH_RISK_REASON_REQUIRED` | 400 | 否 | 高危操作必须填写原因 | 阻止提交 |

## 5. Task 错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `TASK_ALREADY_RUNNING` | 409 | 否 | 同类任务正在执行 | 返回现有 task_id |
| `TASK_NOT_FOUND` | 404 | 否 | 任务不存在 | 刷新任务列表 |
| `TASK_LEASE_EXPIRED` | 409 | 是 | 任务执行超时，系统将重试 | 重新入队 |
| `TASK_CANCEL_NOT_ALLOWED` | 409 | 否 | 当前阶段不允许取消 | 展示阶段原因 |
| `TASK_DEAD_LETTERED` | 500 | 否 | 任务多次失败，等待人工处理 | 进入死信队列 |

## 6. 外部平台错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `EXT_TIMEOUT` | 504 | 是 | 外部平台响应超时 | 指数退避重试 |
| `EXT_RATE_LIMITED` | 429 | 是 | 外部平台限流 | 延迟重试 |
| `EXT_AUTH_FAILED` | 401 | 否 | 外部平台凭证无效 | 标记凭证异常 |
| `EXT_BAD_RESPONSE` | 502 | 是 | 外部平台返回异常 | 原始响应入隔离区 |
| `EXT_DIRTY_DATA_QUARANTINED` | 422 | 否 | 外部数据异常，已隔离 | 人工处理 |
| `EXT_PROVIDER_DOWN` | 503 | 是 | 外部服务不可用 | 熔断降级 |

## 7. Store 错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `STORE_CREDENTIAL_INVALID` | 401 | 否 | 店铺 API Key 无效 | 更新凭证 |
| `STORE_SYNC_ALREADY_RUNNING` | 409 | 否 | 店铺正在同步 | 返回现有任务 |
| `STORE_SYNC_PARTIAL_FAILED` | 207 | 是 | 部分数据同步失败 | 展示失败分段 |
| `STORE_NOT_FOUND` | 404 | 否 | 店铺不存在 | 刷新店铺列表 |

## 8. Listing 错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `LISTING_FETCH_FAILED` | 502 | 是 | 商品抓取失败 | 重试或人工修正 |
| `LISTING_AI_FAILED` | 502 | 是 | AI 改写失败 | 重试或人工编辑 |
| `LISTING_CATEGORY_UNMATCHED` | 422 | 否 | 类目无法自动匹配 | 进入人工修正 |
| `LISTING_LOADSHEET_INVALID` | 422 | 否 | loadsheet 校验失败 | 展示字段错误 |
| `LISTING_REVIEW_REJECTED` | 409 | 否 | 审核被驳回 | 进入返修 |

## 9. Bid 错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `BID_NO_FLOOR_PRICE` | 409 | 否 | 未配置底价，禁止竞价 | 引导导入底价 |
| `BID_BUYBOX_STALE` | 409 | 是 | BuyBox 数据过期，本轮跳过 | 重新同步 |
| `BID_GUARDRAIL_BLOCKED` | 409 | 否 | 已被安全护栏拦截 | 展示 floor / ceiling |
| `BID_PRICE_UPDATE_FAILED` | 502 | 是 | 调价失败 | 重试或人工处理 |
| `BID_STORE_PAUSED` | 409 | 否 | 店铺竞价已暂停 | 提示恢复 |

## 10. Fulfillment / Warehouse / Finance 错误码

| 错误码 | HTTP | 可重试 | 用户提示 | 处理策略 |
|---|---:|---:|---|---|
| `FULFILL_CROSS_WAREHOUSE_PO_DENIED` | 409 | 否 | 禁止跨仓合单 | 阻止创建 PO |
| `FULFILL_ORDER_ALREADY_BOUND` | 409 | 否 | 订单已绑定 PO | 返回已有 PO |
| `FULFILL_TERMINAL_READONLY` | 409 | 否 | 已完成或取消对象只读 | 禁止修改 |
| `WAREHOUSE_SCAN_DUPLICATED` | 409 | 否 | 重复扫描 | 展示已有记录 |
| `WAREHOUSE_OPERATION_INVALID_STAGE` | 409 | 否 | 当前阶段不允许该操作 | 展示下一步 |
| `FINANCE_LEDGER_IMMUTABLE` | 409 | 否 | 财务流水不可覆盖 | 使用调整流水 |
| `FINANCE_SNAPSHOT_STALE` | 409 | 是 | 利润快照已过期 | 触发重算 |

