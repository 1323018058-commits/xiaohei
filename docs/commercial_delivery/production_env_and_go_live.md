# 生产环境配置与上线步骤

## 1. 目的

这份文档只回答两件事：

- 生产环境到底要配哪些变量
- 正式上线前后按什么顺序执行

它服务于当前首发主线程：

- 登录
- 店铺管理
- 扩展试算
- 保护价 / AutoBid
- 一键上架
- 上架记录
- 订单中心
- 任务中心（管理员）
- 平台管理（管理员）

## 2. 生产环境变量

### 必填

- `XH_DATABASE_URL`
- `XH_STORE_CREDENTIAL_ENCRYPTION_KEY`
- `XH_TAKEALOT_API_KEY`
- `XH_SESSION_COOKIE_SECURE=true`
- `XH_DB_BOOTSTRAP_DEMO_DATA=false`
- `XH_TAKEALOT_WEBHOOK_SECRET`
- `XH_TAKEALOT_WEBHOOK_PUBLIC_URL`
- `XH_TAKEALOT_WEBHOOK_STORE_ID`
- `XH_ALERT_WEBHOOK_URL`

### 部署后压测 / 预热必填

- `XH_LOAD_BASE_URL`
- `XH_LOAD_USERNAME`
- `XH_LOAD_PASSWORD`

### 可选

- `XH_TAKEALOT_CATALOG_API_KEY`
- `XH_TAKEALOT_CATALOG_EMAIL`
- `XH_TAKEALOT_CATALOG_PASSWORD`
- `API_PROXY_TARGET`

参考模板：

- `.env.production.example`

## 3. 上线前顺序

### A. 配置

1. 复制 `.env.production.example`
2. 填入正式库、正式域名、正式告警地址
3. 确认没有再使用开发默认值：
   - `XH_STORE_CREDENTIAL_ENCRYPTION_KEY`
   - `XH_DB_BOOTSTRAP_DEMO_DATA`
   - `XH_SESSION_COOKIE_SECURE`

### B. 环境检查

先跑：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/env-readiness.ps1 -RequireHttps -RequireWebhook -RequireAlertWebhook
```

通过标准：

- 没有 `fail`
- `session_cookie_secure` 为 `ok`
- `demo_bootstrap` 为 `ok`
- webhook 三项为 `ok`
- `alert_webhook_url` 为 `ok`

### C. 备份 / 恢复

```powershell
powershell -ExecutionPolicy Bypass -File scripts/db-backup.ps1
powershell -ExecutionPolicy Bypass -File scripts/db-restore-check.ps1
```

通过标准：

- 备份文件成功产出
- 恢复检查成功

### D. 告警通道

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-alert-channel.ps1 -RequireWebhook
```

通过标准：

- 本地 alert 文件写入成功
- webhook 状态为 `delivered`

### E. 预检

```powershell
powershell -ExecutionPolicy Bypass -File scripts/release-preflight.ps1 -RequireHttps -RequireWebhook -RequireAlertWebhook
```

说明：

- 如果还没有正式公网域名，`XH_LOAD_BASE_URL` 未配置时，压测 freshness 会被自动跳过，不再误报失败
- 一旦正式域名就绪，必须补跑预热和商业 Gate

### F. 运维护栏

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ops-guardrails.ps1 -Strict
```

通过标准：

- 没有 `fail`
- `warn` 需要逐项确认是已接受风险

## 4. 部署后复验

按这条主链验收：

1. 管理员登录
2. 店铺凭证可读
3. 扩展登录 ERP
4. 保存保护价
5. 一键上架
6. `上架记录` 显示 `已上架` 或 `失败`
7. 订单同步成功

## 5. 当前最关键的阻塞项口径

正式上线前，这几项没完成就不要宣布上线：

- 正式域名与 HTTPS
- `XH_SESSION_COOKIE_SECURE=true`
- `XH_DB_BOOTSTRAP_DEMO_DATA=false`
- webhook 三项配置齐全
- 告警 webhook 可投递
- 备份与恢复检查成功
- worker 常驻稳定

## 6. 当前脚本口径

### `ops:guardrails:strict`

如果出现以下 `warn`，需要人工判断：

- `store_freshness`
- `listing_health`
- `sync_failure_budget`

如果是测试残留、老样本或未开始正式公网运行，可以接受；如果是生产店铺真实异常，就不能放过。

### `release:preflight`

这是上线前总闸门，建议始终保留最新一份报告在：

- `reports/release/`

## 7. 推荐执行顺序（正式发布日）

```text
配置生产环境
  -> env-readiness
  -> db-backup
  -> db-restore-check
  -> alert-channel-test
  -> release-preflight
  -> ops-guardrails:strict
  -> 部署 API / Web / Worker
  -> 主链 smoke
  -> 小范围灰度
  -> 放量
```
