# Gemini 前端设计逻辑交接稿

> 用途：这份稿只描述前端产品逻辑、页面职责、数据结构和交互闭环，不要求照搬现有视觉。设计师/Gemini 应基于这些逻辑重新做黑白、极简、高端、商业化的原创企业工具界面。

## 1. 项目定位

小黑 ERP 是面向 Takealot 卖家的运营工作台，不是传统臃肿 ERP，也不是营销官网。

核心目标：

- 让用户围绕“绑店、上架、管价、看单”完成日常运营。
- 普通用户只看到业务主线程。
- 管理员额外看到排障和平台管理能力。
- 页面要高信噪比，少暴露技术字段和内部排障字段。

## 2. 权限与导航逻辑

### 2.1 普通用户可见模块

- 工作台 `/dashboard`
- 店铺管理 `/stores`
- 上架中心（后续独立，当前未完成）
- 自动竞价 `/bidding`
- 上架记录 `/listing`
- 订单中心 `/orders`

### 2.2 管理员附加模块

- 任务中心 `/tasks`
- 平台管理 `/admin`

### 2.3 权限硬约束

- 普通用户不能看到 `任务中心` 和 `平台管理`。
- 这不只是前端隐藏：后端路由也必须做账号级权限校验。
- 已有权限文件不要回退：
  - `apps/web/src/lib/server-session.ts`
  - `apps/web/src/app/(dashboard)/tasks/layout.tsx`
  - `apps/web/src/app/(dashboard)/admin/layout.tsx`
  - `apps/web/src/app/(dashboard)/layout.tsx`
  - `apps/api/src/modules/tasking/routes.py`

## 3. 设计总原则（给 Gemini）

### 3.1 要做成什么

- 黑白为主，低饱和辅助色。
- Apple 式克制、细腻、商业化。
- 企业工具感：清楚、稳定、可信、耐看。
- 信息密度适中偏高，不要做成官网 Hero。
- 表格、筛选条、右侧详情面板是主模式。
- 关键状态必须一眼能判断。

### 3.2 不要做什么

- 不要大面积彩色渐变。
- 不要 AI 味装饰。
- 不要为了“高级”做过度留白。
- 不要照抄竞品的热力图、矩形图、图形组合和具体布局。
- 不要把任务 ID、内部状态机、脱敏 Key、技术排障信息塞给普通用户。
- 不要把自动竞价混在店铺管理里。

## 4. 首发信息架构

```text
工作台
  -> 今日经营概览
  -> 待处理事项
  -> 最近结果
  -> 店铺健康概览

店铺管理
  -> 店铺列表
  -> 店铺详情
  -> 新建店铺
  -> 更新凭证
  -> 立即同步
  -> 全店对账/校准
  -> 店铺视角上架记录

自动竞价
  -> 店铺选择
  -> SKU 策略列表
  -> 保护底价
  -> 策略启用/停用
  -> 批量导入底价
  -> 单条策略编辑 Sheet

上架记录
  -> 已上架
  -> 失败
  -> 处理中
  -> 商品详情
  -> 刷新官方状态

订单中心
  -> 订单列表
  -> 订单详情
  -> 金额/商品数/履约状态
  -> 同步订单

任务中心（管理员）
  -> 异步任务
  -> 重试 / 取消 / 错误详情

平台管理（管理员）
  -> 用户与权限
  -> 租户与订阅
  -> 审计与系统健康
```

## 5. 页面逻辑

### 5.1 工作台 `/dashboard`

页面目的：让用户进入系统后马上知道今天有没有事情要处理。

需要展示：

- 今日订单数
- 今日销售额
- 已上架数量
- 上架失败数量
- 店铺凭证是否有问题
- 最近订单 / 上架结果
- 店铺健康概览

推荐页面结构：

- 顶部：页面标题 + 刷新动作。
- 第一行：4 个简洁 KPI 卡。
- 中部左侧：经营趋势或经营脉冲，不一定要复杂图表。
- 中部右侧：待处理队列。
- 底部：店铺健康表 + 上架结果摘要。

交互：

- KPI 卡可以跳转到对应页面。
- 待处理项跳转到具体模块。
- 页面加载失败时，不要整页崩；展示“部分数据暂不可用”。

数据来源：

- `GET /api/auth/me`
- `GET /api/v1/stores`
- `GET /api/v1/orders`
- `GET /api/listing/jobs`
- 管理员可额外读 `GET /admin/api/tenant/usage`

### 5.2 店铺管理 `/stores`

页面目的：管理店铺接入和同步，不处理自动竞价策略。

必须保留业务动作：

- 新建店铺
- 更新凭证
- 立即同步
- 全店对账/校准
- 创建成功后自动聚焦新店铺
- 黑白极简 toast 反馈

页面结构：

- 顶部：标题 + 新增店铺按钮。
- 工具条：搜索店铺、刷新、全店对账/校准。
- 主区左侧：店铺表格。
- 主区右侧：当前店铺详情面板。

店铺表格字段：

- 店铺名称
- 平台
- 状态
- 凭证状态
- 最近同步
- 上架 SKU 数

右侧详情只展示：

- 当前状态
- 凭证状态
- 最近同步
- 数据同步是否可用
- 上架能力是否可用
- 最近上架 SKU

不要展示：

- API Key / masked key
- 内部任务队列
- request id
- error stack
- 复杂审计内容

接口：

- `GET /api/v1/stores`
- `POST /api/v1/stores`
- `GET /api/v1/stores/{store_id}`
- `POST /api/v1/stores/{store_id}/credentials`
- `POST /api/v1/stores/{store_id}/sync`
- `POST /api/v1/stores/sync/reconcile`
- `GET /api/v1/stores/{store_id}/listings`

### 5.3 自动竞价 `/bidding`

页面目的：独立管理 SKU 价格策略，不属于店铺管理 Tab。

必须保留业务动作：

- 按店铺选择 SKU 策略
- 搜索 SKU / 标题
- 查看当前售价、保护底价、最高限价、策略类型、启用状态
- 批量导入底价
- 单条策略 Sheet 编辑
- 保存后刷新策略列表

页面结构：

- 顶部：标题 + 刷新策略。
- KPI：启用策略数、守护策略数、平均底价、当前店铺。
- 工具条：店铺选择、状态筛选、搜索。
- 主区左侧：策略表格。
- 主区右侧：批量导入底价面板。
- 单条编辑：右侧 Sheet / Drawer。

策略表字段：

- SKU / 商品标题
- 当前售价
- 保护底价
- 最高限价
- 策略类型
- 启用状态
- 更新时间

批量导入格式：

```text
SKU-001, 99.90
SKU-002, 128.00
```

策略编辑字段：

- 关联上架 ID（可选）
- 保护底价（必填，大于 0）
- 最高限价（可选，不能低于保护底价）
- 策略类型：手动底价 / 守护策略 / 进取策略
- 启用状态

接口：

- `GET /api/v1/stores`
- `GET /api/v1/stores/{store_id}/listings`
- `GET /api/v1/bidding/rules?store_id={store_id}`
- `PATCH /api/v1/bidding/rules/{rule_id}`
- `POST /api/v1/bidding/rules/bulk-import?store_id={store_id}`

### 5.4 上架记录 `/listing`

页面目的：展示上架结果，不做任务排障。

筛选：

- 全部记录
- 已上架
- 失败
- 店铺筛选
- 搜索标题 / PLID / Barcode / SKU

表格字段：

- 商品标题
- 店铺
- PLID
- Barcode
- SKU
- 售价
- 保护底价
- 状态

右侧详情：

- 商品标题
- 当前状态
- 售价
- 保护底价
- SKU
- Barcode
- PLID
- 更新时间
- 刷新官方状态按钮
- 一句用户可理解的说明

不要展示：

- task id
- stage 原始值
- request id
- raw payload
- stack trace

接口：

- `GET /api/listing/jobs`
- `POST /api/listing/jobs/{job_id}/refresh-status`
- `GET /api/v1/stores`

### 5.5 订单中心 `/orders`

页面目的：查看订单和履约状态，支持按店铺同步订单。

页面结构：

- 顶部：标题 + 同步订单按钮。
- KPI：订单数、销售额、待处理、当前店铺。
- 工具条：店铺筛选、状态筛选、搜索订单号 / SKU。
- 主区左侧：订单表格。
- 主区右侧：订单详情。

订单表字段：

- 订单号
- 店铺
- 时间
- 金额
- 商品数
- 状态
- 履约状态

右侧详情：

- 订单号
- 店铺
- 下单时间
- 金额
- 商品数
- 履约状态
- 最近同步
- 商品列表
- 订单事件

接口：

- `GET /api/v1/stores`
- `GET /api/v1/orders?store_id=&status=&q=`
- `GET /api/v1/orders/{order_id}`
- `POST /api/v1/stores/{store_id}/orders/sync/force`

### 5.6 任务中心 `/tasks`（管理员）

页面目的：管理员排障，不给普通用户看。

应展示：

- 任务列表
- 状态
- 进度
- 失败原因
- 重试
- 取消

注意：这个页面可以展示更多技术信息，因为它是管理员排障页。

### 5.7 平台管理 `/admin`（管理员）

页面目的：管理用户、租户、订阅、权限与审计。

应展示：

- 用户列表
- 租户列表
- 订阅状态
- 到期时间
- 权限摘要
- 高风险操作抽屉

高风险动作必须二次确认。

## 6. 用户角色逻辑

角色：

- `super_admin`：可看全部模块。
- `tenant_admin`：可看业务模块 + 管理员附加模块。
- `operator`：只能看业务模块。
- `warehouse`：当前不作为首发主用户，订单相关可读。

前端导航必须根据 session role 控制显示。
后端也必须按 role 校验。

## 7. 通用交互逻辑

### 7.1 Toast

- 成功：黑白极简 toast。
- 失败：清楚说明用户能做什么。
- 不要大弹窗打断普通成功反馈。

### 7.2 Drawer / Sheet

适合承载：

- 单条 SKU 策略编辑
- 订单详情
- 上架记录详情
- 高风险动作确认

### 7.3 表格

默认只展示 5～8 个核心字段。
高级字段不要默认出现。
表格点击行后右侧展示详情。

### 7.4 空状态

空状态要告诉用户下一步：

- 没有店铺：提示新建店铺。
- 没有策略：提示批量导入底价。
- 没有上架记录：提示先从上架中心或扩展发起上架。
- 没有订单：提示同步订单。

## 8. 当前前端文件位置

- 壳层：`apps/web/src/app/(dashboard)/layout.tsx`
- 导航：`apps/web/src/components/system/DashboardNav.tsx`
- 工作台：`apps/web/src/app/(dashboard)/dashboard/page.tsx`
- 店铺管理：`apps/web/src/app/(dashboard)/stores/page.tsx`
- 自动竞价：`apps/web/src/app/(dashboard)/bidding/page.tsx`
- 上架记录：`apps/web/src/app/(dashboard)/listing/page.tsx`
- 订单中心：`apps/web/src/app/(dashboard)/orders/page.tsx`
- 任务中心：`apps/web/src/app/(dashboard)/tasks/page.tsx`
- 平台管理：`apps/web/src/app/(dashboard)/admin/page.tsx`

## 9. 已知技术注意事项

- PowerShell 中文历史乱码不可信，源码里用户可见文案必须保持 UTF-8 中文。
- `npm run build:web` 在 PowerShell 可能被 `npm.ps1` 策略拦截，建议用 `npm.cmd run build:web`。
- 本地 API 如果返回 `Not Found`，先确认 uvicorn 是否是旧进程；重启 API 后 `/api/listing/jobs` 和 `/api/v1/orders` 应返回 200。
- 普通用户不可见 `任务中心 / 平台管理` 不能回退。

## 10. 给 Gemini 的设计任务

请基于以上逻辑，重新设计一个原创的黑白极简企业工具 UI：

- 不要复制辉光 ERP 的具体图形和布局。
- 不要做营销官网式大 Hero。
- 重点设计：导航、表格密度、筛选条、右侧详情、Drawer、空状态、KPI 卡片、订单/上架/竞价三类业务表。
- 输出时请按页面分别给设计方案：`dashboard`、`stores`、`bidding`、`listing`、`orders`。
- 每个页面要说明：布局、信息层级、关键组件、状态样式、空状态、移动端降级方式。
