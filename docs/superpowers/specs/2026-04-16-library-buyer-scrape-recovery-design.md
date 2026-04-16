# Takealot 买家端选品库恢复与自动补采设计

Date: 2026-04-16  
Status: Draft  
Scope: 修复 `选品库` 当前只能采到少量重复商品的问题，并在此基础上增加自动补采能力。  
Chosen rollout: 先 A 后 B

---

## 1. 背景

当前 ERP 的 `选品库` 页面宣称基于 Takealot 实时爬虫数据构建全链路商品库，但实际数据库里只有 37 条记录，且几乎全部落在 `Vouchers`，明显不符合“多类目、大规模商品池”的目标。

本次工作分两阶段完成：

1. **Phase A：先修手动爬取**
   - 修复现有“启动爬取”链路，使用户手动触发后能真正从 Takealot 买家端补齐大量商品。
2. **Phase B：再加自动补采**
   - 在手动链路稳定后，增加周期性自动补采，避免选品库再次退化成少量陈旧数据。

---

## 2. 已确认根因

### 2.1 旧版类目过滤写法已失效

当前后端使用的采集请求逻辑位于：

- `backend/app/services/library_service.py`

当前实现会构造类似如下的请求：

- `filter = "Available:true Department:Books Price:0-100000 LeadTime:7-21"`

但实测表明，Takealot 当前买家端搜索接口不再按这类旧式拼接字符串理解类目。接口会把上面这串值错误归入 `Available`，从而：

- `Department:Books` 不生效
- `LeadTime:7-21` 也不生效
- 不同“类目”请求最终会命中同一批结果

### 2.2 数据库只剩少量去重后结果

当前数据库实际只有 37 条选品库记录，且分布高度异常：

- `Vouchers`: 36
- `Sport`: 1

这说明系统并不是“完全没有抓到数据”，而是每轮都在重复抓取同一批商品，最终被 `product_id` upsert 去重后只留下极少量记录。

### 2.3 Takealot 当前可用的类目切换方式

实测可用的买家端前台接口参数是：

- `department_slug=books`
- `department_slug=fashion`
- `department_slug=sport`

同一接口在不同 `department_slug` 下会返回不同商品，说明此方式可以作为新的主采集入口。

---

## 3. 目标

### 3.1 Phase A 目标

- 修复 `选品库` 手动爬取，使不同类目真正抓到不同商品
- 保留现有前端交互：仍使用“启动爬取”弹窗、进度条、停止按钮
- 保留现有 Redis 进度、Celery 异步执行、批量 upsert 机制
- 允许用户继续传入价格区间与 lead time 条件
- 修复后首次人工执行即可把选品库从 37 条扩充为明显更大的可用商品池

### 3.2 Phase B 目标

- 增加定时自动补采
- 自动补采与手动爬取共用同一套核心采集实现
- 自动任务与手动任务互斥，不允许同时运行造成重复压力或状态混乱
- 补采以“增量刷新/持续填充”为主，不做破坏性清库

---

## 4. 非目标

- 不切换到卖家端 API 做选品库采集
- 不在本次内引入 Playwright 浏览器重型抓取链路作为主路径
- 不重做 `选品库` 页面结构
- 不改变 `library_products` 的主键与基础 upsert 模型
- 不在本次内做跨站点选品扩展

---

## 5. Phase A 设计

## 5.1 保留买家端公开搜索接口

继续使用当前已有的 Takealot 买家端公开搜索接口：

- `https://api.takealot.com/rest/v-1-10-0/searches/products`

原因：

- 当前系统已具备 `httpx + Celery + Redis + PostgreSQL` 的完整链路
- 只需修正请求参数与过滤策略即可恢复功能
- 风险低，改动小，验证快

## 5.2 类目采集从显示名切换到 `department_slug`

后端新增“显示类目名 -> department slug”的稳定映射，例如：

- `Books -> books`
- `Fashion -> fashion`
- `Sport -> sport`
- `Home & Kitchen -> home-kitchen`

前端仍展示现有类目名，不暴露 slug。
数据库内 `category_main` 也继续保存当前业务展示名，不改存 slug。

手动爬取时：

- 如果用户未指定类目，则遍历全部官方类目
- 每个类目请求时都显式带 `department_slug`
- 不再把 `Department:...` 塞进旧式 `filter` 字符串

这样做的原因是当前整条链路都依赖 `category_main` 为展示名：

- 前端筛选与下拉展示
- 导出结果
- 非法分类清理
- 隔离快照与选择记忆

因此 Phase A 的最小改法是：

- **请求层用 slug**
- **存储层和展示层继续用 label**

## 5.3 价格过滤继续交给前台接口

价格过滤仍通过搜索接口传递，但改成接口当前可正确识别的形式，例如：

- `filter=Available:true,Price:0-200`

这样可继续减少全量抓取压力，同时保持与现有 UI 配置一致。

## 5.4 Lead Time 过滤改为本地过滤

实测表明 `LeadTime:7-21` 这类旧过滤已不再稳定生效，因此改为：

1. 先从接口抓回该类目与价格区间下的候选商品
2. 读取每条商品的 `stock_availability_summary.status`
3. 在本地解析并判定是否落入用户设置的 lead time 范围

本地判定逻辑：

- `Ships in X - Y work days`：提取数值区间并比较
- `Available now` / `In stock`：视为即时到货
- `Pre-order: Ships ...`：归入预售，不满足普通 lead time 范围时可直接排除
- 无法解析的状态：默认保守跳过，避免脏数据混入

## 5.5 去重、进度与 UI 保持现状

以下机制继续沿用：

- `product_id` 作为 upsert 主键
- Redis `scrape_progress:{user_id}` 作为前端轮询状态
- Redis `scrape_stop:{user_id}` 作为停止信号
- `scrape_lock:{user_id}` 作为并发锁
- 前端 `ProductLibraryView.vue` 的进度条与停止按钮保持不变

这意味着：

- 用户操作方式不变
- 修复主要集中在服务层
- 风险和回归面最小

## 5.6 Phase A 文案建议

前端弹窗无需大改，但建议补一个提示：

- 当前 Lead Time 为“结果筛后过滤”，不是 Takealot 前台原生实时筛选

这样能减少用户误以为抓不到商品就是任务失败的误会。

---

## 6. Phase B 设计

## 6.1 增加周期性自动补采

新增一个定时 Celery 任务，例如每隔数小时执行一次：

- 复用 Phase A 的采集核心函数
- 默认使用系统预设的类目、价格与 lead time 配置
- 不清空历史数据
- 仅持续 upsert / 刷新现有库

## 6.2 手动与自动任务互斥

自动补采必须复用与手动爬取相同的 Redis 锁：

- 若手动爬取在运行，自动补采跳过
- 若自动补采在运行，手动爬取返回“已有任务进行中”

避免以下问题：

- 并行重复抓取
- 进度条状态互相覆盖
- 类目重复高压请求 Takealot

仅复用“同一个 key”还不够，Phase B 需要把现有锁升级为带 owner token 的安全锁：

- 加锁时写入任务 owner
- 续租时只允许 owner 自己续租
- 结束时只允许 owner 自己释放锁

否则 API 手动任务与 beat 自动任务在排队或延迟启动场景下，可能出现：

- 后来的任务误删前一个任务的锁
- 两个任务都认为自己拿到了锁
- 任务结束时把别人的锁删掉

## 6.3 自动补采默认不新增复杂 UI

Phase B 初版只要求后台定时执行成功，不强制新增复杂控制台。

可选的最小前端增强是：

- 在 `选品库` 页面加一行“最近自动补采时间 / 状态”

但不是 Phase B 首发硬要求。

## 6.4 自动补采必须清理旧 stop 信号

当前停止爬取通过用户级 Redis key 实现：

- `scrape_stop:{user_id}`

Phase B 必须在任务启动前主动清理旧 stop 信号，否则前一次手动停止后，短时间内的自动补采可能在启动后立即被误判为“需要停止”。

---

## 7. 受影响文件

### Phase A 核心

- `backend/app/services/library_service.py`
- `backend/app/api/library.py`
- `backend/app/tasks/scrape_tasks.py`
- `backend/app/schemas/library.py`
- `frontend/src/views/ProductLibraryView.vue`

### Phase B 核心

- `backend/app/tasks/scrape_tasks.py`
- `backend/app/tasks/celery_app.py`
- `backend/app/services/product_sync_progress_service.py`
- `backend/app/services/snapshot_service.py`
- `docker/docker-compose.yml`（如需确认 beat/worker 路由）
- 可能新增或修改与定时配置相关文件

### 测试

- `backend/tests/` 下新增选品库采集相关测试文件

---

## 8. 测试与验收标准

## 8.1 Phase A 验收

- 手动点击“启动爬取”后，任务正常入队并更新进度
- 同一轮爬取中，不同类目能抓到明显不同商品
- 数据库 `library_products` 数量显著超过当前 37 条
- 类目分布不再几乎全部是 `Vouchers`
- 原有 `选品库` 列表、筛选、分页、进度展示仍可用

## 8.2 Phase B 验收

- 定时任务可自动执行
- 自动补采不会与手动爬取同时运行
- 任务执行后，`library_products.updated_at` 持续刷新
- 不出现因为自动任务导致的重复报错、锁冲突或前端异常状态
- 前一次手动 stop 不会让后续自动补采被秒停

---

## 9. 风险与控制

### 风险 1：Takealot 前台接口字段再次变动

控制：

- 把请求构造与 lead time 解析集中封装
- 增加针对真实返回结构的单元测试

### 风险 2：Lead time 状态文案不统一

控制：

- 使用宽松文本解析
- 对无法解析的状态做保守跳过
- 在日志中记录未识别状态样本，便于后续补规则

### 风险 3：自动补采与手动操作冲突

控制：

- 统一复用 Redis 锁，并改成 owner token 模式
- 自动任务遇锁直接退出，不抢占前台用户任务

### 风险 4：抓到的新数据被非法分类清理误删

控制：

- Phase A 明确保持 `category_main` 仍保存业务 label
- 仅在请求层引入 `department_slug`
- 补“抓取后分类值”和“cleanup 合法性”回归测试

---

## 10. 实施顺序

1. **先做 Phase A**
   - 修复类目参数
   - 改为本地 lead time 过滤
   - 补后端测试
   - 跑一次真实补采验证库容量恢复
2. **再做 Phase B**
   - 增加定时自动补采
   - 复用同一采集核心
   - 做锁互斥与状态验证

---

## 11. 结论

本次不需要推翻现有选品库架构，问题根因是 **Takealot 买家端旧搜索参数写法失效**。  
最稳妥的方案是：

- **Phase A：先修现有手动采集链路**
- **Phase B：再加自动补采**

这样既能最快恢复选品库可用性，也能满足 ERP 商用场景下对持续数据供给和稳定性的要求。
