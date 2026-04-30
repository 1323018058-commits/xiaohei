# Takealot 官方创建报价 Runbook

## 目的

本手册用于把当前小黑 ERP 的扩展 `list-now` 主链，推进到 **真实 Takealot 官方创建报价** 演练与实战。

当前系统已经接通的官方路径：

- `GET /offers/by_barcode/{barcode}`
- `POST /offers`
- `PATCH /offers/by_barcode/{barcode}`
- `GET /seller?expands=warehouses`
- `POST /offers/batch`

## 安全原则

- 默认先走 `dry-run`
- 只有显式加 `--execute` 才允许打真实 Takealot API
- 缺少 `barcode/gtin`、缺少销售价、店铺凭证不可用时，优先停在人工介入，不盲打平台
- Leadtime 店铺优先走 `POST /offers/batch`，不要默认假设 `PATCH /offers/by_barcode` 一定稳定可用
- 若目标是把报价尽量推进到 `buyable`，应配置 `XH_TAKEALOT_LEADTIME_MERCHANT_WAREHOUSE_ID`，让系统在 batch payload 中同时发送 `leadtime_stock + status_action=Re-enable`

## 前置条件

1. 已配置：
   - `XH_DATABASE_URL`
   - `XH_TAKEALOT_API_KEY`
   - 可选 `XH_TAKEALOT_API_SECRET`
2. 已完成：
   - `npm run db:prepare`
   - `npm run db:smoke:extension-guardrail`
3. 已准备测试商品：
   - `PLID`
   - 最好同时准备 `barcode/gtin`
4. 已确认当前店铺允许创建新 offer

## 演练命令

### 1. 执行前预检

```powershell
npm run takealot:real-offer:preflight -- --barcode 6001234567890
```

作用：

- 校验 `XH_DATABASE_URL`
- 校验 `XH_TAKEALOT_API_KEY`
- 拉取 seller profile
- 检查 seller warehouse
- 检查该 barcode 是否已存在 offer

### 2. 单接口 dry-run

```powershell
npm run takealot:real-offer:create -- --barcode 6001234567890 --sku XH-DRYRUN-001 --selling-price 299
```

作用：

- 不会打真实 API
- 只输出将要发送的 payload

### 3. 端到端 dry-run

```powershell
python packages/db/scripts/takealot_real_list_now.py --plid 92833194 --sale-price-zar 299 --protected-floor-price 214.3176 --barcode 6001234567890
```

作用：

- 不会打真实 API
- 输出即将执行的 `list-now` 链路参数

### 4. 真实执行

```powershell
python packages/db/scripts/takealot_real_list_now.py --plid 92833194 --sale-price-zar 299 --protected-floor-price 214.3176 --barcode 6001234567890 --execute
```

作用：

- 校验店铺凭证
- 创建保护价
- 创建 `EXTENSION_LIST_NOW`
- 生成正式 `listing_job`
- 调官方 `/offers` 或 `/offers/by_barcode/{barcode}`

### 5. Leadtime 可售化探针

```powershell
npm run takealot:leadtime:probe -- --barcode 6001234567890 --sku XH-PROBE-001 --selling-price 299 --leadtime-days 14
```

作用：

- dry-run 展示将要测试的官方 batch payload 变体
- 默认包括：
  - baseline
  - `status_action=Re-enable`

真实执行：

```powershell
npm run takealot:leadtime:probe -- --barcode 6001234567890 --sku XH-PROBE-001 --selling-price 299 --leadtime-days 14 --execute
```

适用时机：

- 报价已创建但长期 `not_buyable`
- 需要验证 `status_action` 或 leadtime 参数是否影响可售状态

## 结果判定

成功时，重点看：

- `extension_task_id`
- `listing_job.status`
- `listing_job.stage`
- 返回的 `offer_id`

当前理想成功状态：

- `listing_job.status = ready_to_submit`
- `listing_job.stage = prepared`

## Leadtime 关键结论（2026-04-24 实测）

- 当前测试店铺 `leadtime_enabled = true`
- 当前官方返回的 `leadtime_details = [{min_days: 14, max_days: 16}]`
- 当前店铺未返回 `seller_warehouse`
- 实测结果：
  - `POST /offers`：平台返回 `500`
  - `PATCH /offers/by_barcode/{barcode}`：平台返回 `500`
  - `POST /offers/batch`：成功

结论：

- **Leadtime 跨境店铺应优先采用 `/offers/batch` 创建/更新报价**
- **若要把 `not_buyable` 尽量推进到 `buyable`，下一步要把 `leadtime_stock` 一起写进去**

## 常见阻断

### 1. `LISTING_BARCODE_MISSING`

说明：

- 当前商品没有可用 `barcode/gtin`

处理：

- 手工补 `barcode`
- 或确保 `seller-api` 商品事实补全已拿到 `gtin`

### 2. `LISTING_SELLING_PRICE_MISSING`

说明：

- 没带销售价

处理：

- 明确传 `--sale-price-zar`

### 3. `STORE_AUTH_FAILED`

说明：

- Takealot API Key 无效或过期

处理：

- 重新录入店铺凭证
- 先执行凭证校验

### 4. `LISTING_WORKER_DISABLED`

说明：

- `listing_jobs_enabled` 开关未打开

处理：

- 演练脚本会自动打开
- 若线上执行，需在变更窗口内确认开关

## 当前边界

本 Runbook 当前只覆盖：

- 官方创建/更新报价
- 扩展 `list-now` 到 `listing_job`
- 保护价与 `AutoBid` 闭环

尚未覆盖：

- submission/review 正式提审
- loadsheet 生成
- 类目匹配与 AI 改写
