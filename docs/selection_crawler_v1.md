# 选品库采集 V1

目标：把 Takealot 全站商品按“小类目 + 价格分片 + 分页”写入 `selection_products`，并保留每周快照。

## 核心策略

- 用小类目做第一层分片，避免大类目结果页上限截断。
- 每个类目再按价格区间切片；如果接口返回的 `total` 超过阈值，自动继续二分价格桶。
- 模板分两段：列表模板只做商品发现，详情模板可选补充评论分布、最新评论和报价数。
- 每个采集 run 会持久化到 `selection_ingest_runs`。
- 每个类目价格桶会持久化到 `selection_ingest_buckets`，支持断点续跑。
- 商品当前值写入 `selection_products`，周快照写入 `selection_product_snapshots`。

## 先建计划

```powershell
npm run takealot:selection:crawl -- `
  --url-template "https://<takealot-json-endpoint>/search?category={category}&price_min={min_price}&price_max={max_price}&page={page}&limit={limit}&sort=price_asc" `
  --categories-file .\categories.csv `
  --price-min 0 `
  --price-max 5000 `
  --initial-price-step 100 `
  --plan-only
```

输出里的 `ingest_run_id` 后续用于续跑。

## 执行或续跑

```powershell
npm run takealot:selection:crawl -- `
  --resume-run-id "<ingest_run_id>" `
  --concurrency 12 `
  --flush-size 1000 `
  --max-products 5000000
```

## 查看进度

```powershell
npm run takealot:selection:crawl -- --status-run-id "<ingest_run_id>"
```

## 直接执行

```powershell
npm run takealot:selection:crawl -- `
  --url-template "https://<takealot-json-endpoint>/search?category={category}&price_min={min_price}&price_max={max_price}&page={page}&limit={limit}&sort=price_asc" `
  --detail-url-template "https://<takealot-json-endpoint>/product/{platform_product_id}" `
  --categories-file .\categories.csv `
  --concurrency 12 `
  --detail-concurrency 16 `
  --flush-size 1000
```

## 模板规则

列表模板必须是稳定 JSON 结果，不要用普通网页 URL 当主模板。

必备占位符：

- `{category}`：类目 slug 或类目 id。
- `{min_price}` / `{max_price}`：价格分片边界。
- `{page}` 或 `{offset}`：分页游标。
- `{limit}` 或 `{page_size}`：每页数量。

建议固定参数：

- 固定 `sort=price_asc` 或同等稳定排序，避免默认推荐排序在采集中漂移。
- 固定只请求商品字段，避免接口返回广告、推荐位和页面装饰数据。
- 价格桶允许边界重复，靠 `platform_product_id` 去重；宁可重复，不要漏。

详情模板是可选的，用来补充列表接口没有的字段：

```powershell
--detail-url-template "https://<takealot-json-endpoint>/product/{platform_product_id}"
```

详情模板支持：

- `{platform_product_id}`
- `{plid}`
- `{title_slug}`
- `{brand}`

## 模板验证

先生成可以复制到浏览器打开的 URL：

```powershell
npm run takealot:selection:crawl -- `
  --url-template "https://<takealot-json-endpoint>/search?category={category}&price_min={min_price}&price_max={max_price}&page={page}&limit={limit}&sort=price_asc" `
  --category "Air Fryers|air-fryers" `
  --price-ranges 0:100,100:200 `
  --preview-urls 4
```

浏览器确认 URL 能返回商品后，用脚本看解析结果：

```powershell
npm run takealot:selection:crawl -- `
  --inspect-url "https://<takealot-json-endpoint>/search?category=air-fryers&price_min=0&price_max=100&page=1&limit=48&sort=price_asc" `
  --inspect-category "Air Fryers"
```

## Seed 文件格式

CSV 支持这些列：

```csv
name,category_ref,main_category,category_level1,category_level2,category_level3,url
Air Fryers,air-fryers,Home & Kitchen,Kitchen,Appliances,Air Fryers,
```

如果 `url` 有值，会优先使用这一行的 URL 模板；否则使用全局 `--url-template`。

## HTTP 头

```powershell
$env:XH_TAKEALOT_SELECTION_COOKIE = "..."
npm run takealot:selection:crawl -- --resume-run-id "<ingest_run_id>"
```

也可以用：

```powershell
--headers-json .\takealot_headers.json
```

## 关键参数

- `--split-threshold 900`：单个价格桶结果数超过这个值就二分。
- `--max-split-depth 5`：最多二分深度。
- `--price-profile takealot`：默认非线性价格桶，低价更细、高价更粗。
- `--concurrency 12`：并发请求数。
- `--flush-size 1000`：每 1000 条商品批量写库。
- `--max-products 5000000`：本次最多采集商品数。
- `--dry-run`：只请求和解析，不写库。
- `--verbose`：输出每页和每个 bucket 的日志。
