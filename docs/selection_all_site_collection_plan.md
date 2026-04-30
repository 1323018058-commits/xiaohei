# Takealot 全站选品库采集方案

## 目标

把 Takealot 全站商品尽量完整地采集到 `selection_products`，每周刷新一次，供约 1000 个用户筛选选品。

V1 只做公共商品情报，不混入店铺商品、自动竞价、候选池、备注或导出。

## 采集原则

核心策略不是从搜索页硬翻页，而是：

1. 先发现类目树，尽量下钻到最小叶子类目。
2. 对每个叶子类目按价格区间切片。
3. 每个切片结果数必须低于平台分页可稳定遍历的上限。
4. 用商品 ID 去重，宁可价格边界有重复，也不要漏商品。
5. 用采集 run、bucket 状态和 facet count 做覆盖率校验。

截图里的 `Fashion > Men > Clothing > Tops & T-Shirts > T-Shirts / Polos & Golfers / Vests` 就是正确的切入方式：不要直接扫 `Fashion` 或 `Men`，而是扫最小的 `T-Shirts`、`Polos & Golfers`、`Vests` 这类叶子节点。

## 哪些筛选能用于覆盖

### 可以作为覆盖分片

- 类目：主类目、一级、二级、三级、四级，优先叶子类目。
- 价格：`min_price` / `max_price`，用于拆分大类目。
- 分页：`page + limit` 或 `offset + limit`。
- 排序：固定稳定排序，比如 `price_asc`。

这些筛选适合做主采集，因为它们能形成相对完整的全集分片。

### 不作为主覆盖分片

- Deal / Featured Deals。
- In Stock 城市。
- Brand。
- Gender。
- Sponsored 广告位。

这些筛选容易有重叠、动态变化或业务含义不完整。它们可以用于补充字段或后续分析，但不应该作为全站覆盖主索引。

Brand 只有在某个叶子类目即使用价格也切不小的时候，才作为最后兜底分片。

## 类目树发现

类目树要单独采：

```text
All Categories
  Fashion
    Men
      Clothing
        Tops & T-Shirts
          T-Shirts           41337
          Polos & Golfers      455
          Vests                 82
```

每个节点记录：

- 类目路径。
- 类目 URL 或 category id/slug。
- 页面显示 count。
- 是否有子类目。
- 最近发现时间。

判定规则：

- 有子类目的节点优先继续下钻。
- 无子类目的节点进入商品采集计划。
- 如果父类目 count 明显大于所有子类目 count 之和，需要保留父类目补扫，防止存在未归入子类目的商品。

## 价格分片

对每个叶子类目建立价格桶。

初始桶可以粗一点：

```text
0-50
50-100
100-200
200-300
300-500
500-750
750-1000
1000-1500
1500-2500
2500-5000
5000-10000
10000+
```

然后按返回结果数动态拆分：

- 如果 bucket 返回 `total <= 3000`，直接分页采集。
- 如果 `total > 3000`，继续二分价格。
- 如果已经二分到很小价格宽度仍然超过阈值，才启用品牌或其他 facet 兜底。

不要用页面右侧 `5000+ results` 作为可遍历上限。它代表当前结果太大，必须继续切。

## 分页规则

每个 bucket 固定：

- 固定类目。
- 固定价格区间。
- 固定排序。
- 固定每页数量。

模板示例：

```text
https://<json-endpoint>/search?category={category}&price_min={min_price}&price_max={max_price}&page={page}&limit={limit}&sort=price_asc
```

或：

```text
https://<json-endpoint>/search?category={category}&price_min={min_price}&price_max={max_price}&offset={offset}&limit={limit}&sort=price_asc
```

价格边界建议采用半开区间：

```text
[min_price, max_price)
```

如果接口不支持半开区间，就允许边界重复，最终靠 `platform_product_id` 去重。

## 字段采集分层

列表接口负责：

- 产品图。
- 标题。
- 类目路径。
- 品牌。
- 当前价格。
- 综合评分。
- 总评论数。
- 库存状态。

详情接口负责：

- 5/4/3/2/1 星评论数。
- 最新评论时间。
- 报价数。
- 更完整图片。
- 更准确类目路径。

不要强迫列表接口一次拿全所有字段。

## 覆盖率校验

每周采集完成后做三层校验：

1. 类目层：叶子类目采集数与页面/facet count 对比。
2. bucket 层：每个价格桶状态必须是 `succeeded` 或明确 `split`。
3. 商品层：本周快照商品数、去重前数量、去重后数量、上周对比增减。

异常规则：

- 某叶子类目页面 count 是 41337，但 bucket 去重后只有 20000，必须重扫或继续拆价。
- 某 bucket 连续 403/429/5xx，标记 failed，不让整轮假成功。
- 某 bucket 返回 0，但相邻价格桶有大量商品，需要人工检查价格参数是否失效。

## 推荐执行顺序

### 第 1 步：类目树

先只采类目树和 count，不采商品。

产物是 `categories.csv`：

```csv
name,category_ref,main_category,category_level1,category_level2,category_level3,url,count
T-Shirts,t-shirts,Fashion,Men,Clothing,Tops & T-Shirts,,41337
Polos & Golfers,polos-golfers,Fashion,Men,Clothing,Tops & T-Shirts,,455
Vests,vests,Fashion,Men,Clothing,Tops & T-Shirts,,82
```

### 第 2 步：小规模试采

选择 1 个大叶子类目和 2 个小叶子类目：

- T-Shirts。
- Polos & Golfers。
- Vests。

先跑 `--preview-urls`，复制 URL 到浏览器确认。

再跑 `--inspect-url`，看解析字段。

### 第 3 步：单类目完整采集

对 `T-Shirts` 完整跑价格桶，验证：

- 去重商品数是否接近 41337。
- 大价格桶是否自动拆分。
- 失败 bucket 能否续跑。

### 第 4 步：全站试跑

挑 100 个叶子类目跑一轮，观察速度：

- products/second。
- 请求失败率。
- DB 写入速度。
- 平均每个 bucket 页数。

### 第 5 步：全站周更

全量 500 万商品跑周更。

建议目标：

- 每批写库 1000-5000 条。
- 列表并发从 8 起步，稳定后逐步升到 16/32。
- 详情并发单独控制，不要和列表共用一个并发数。
- 每轮失败 bucket 保留，单独重试。

## 已落地能力

当前采集器已经具备：

- `--preview-urls`：生成可复制到浏览器的候选 URL。
- `--inspect-url`：检查单个 URL 是否能解析出商品。
- `--plan-only`：先建采集计划。
- `--resume-run-id`：断点续跑。
- `--status-run-id`：查看进度。
- 自动价格二分。
- 批量 upsert。
- 列表模板 + 详情模板。
