# ProfitLens v3 选品库自动补采状态报告

- 生成时间：中国时间 `2026-04-16 17:15:34`
- 项目路径：`/Users/Apple/Projects/profitlens-v3`
- 报告用途：记录本轮自动补采运行状态、已完成修复、agent team 复核结论与后续建议

## 一、当前实时状态

- 当前自动补采任务 ID：`a2613df4-9d10-410e-953f-9d94b7599cba`
- 当前自动补采状态：`running`
- 当前库内商品总数：`85779`
- 当前本轮已采集 / 更新：`92975`
- 当前活动抓取任务数：`1`
- 当前抓取任务是否重复投递：`否（redelivered=false）`
- 当前 Redis 自动补采状态：
  - `running=true`
  - `status=running`
  - `last_started_at=2026-04-16T06:15:55.362044+00:00`
  - `last_finished_at=null`
  - `last_total_scraped=0`
  - `last_new_products=0`

说明：

- 这一轮任务**尚未完成**，所以“本轮最终采集/更新多少条、净新增多少个”还不能下最终结论。
- 但目前已经确认：任务正在继续推进，而且没有再出现之前的“一小时后重复投递、同一任务 ID 多份并发”的问题。

## 二、这次已经落地的关键修复

### 1. 修复长任务被 Redis broker 重复投递

根因：

- `run_library_scrape` 是长任务；
- Celery 使用 `task_acks_late=True`；
- Redis broker 原先没有显式加长 `visibility_timeout`；
- 导致运行时间超过默认可见性窗口后，同一个未 ack 的任务被 broker 重新投递。

已修复：

- 新增 `celery_visibility_timeout_seconds = 86400`
  - 文件：`/Users/Apple/Projects/profitlens-v3/backend/app/config.py:42`
- 把 broker / result backend 的 `visibility_timeout` 都配置到 Celery
  - 文件：`/Users/Apple/Projects/profitlens-v3/backend/app/tasks/celery_app.py:39`

效果：

- 当前 live runtime 复核显示只有 **1 个** 活动 scrape 任务；
- 当前任务 `redelivered=false`；
- 不再出现同一个任务 ID 重复占多个 worker slot。

### 2. 修复同任务 ID 多执行实例共享同一把锁

根因：

- 之前抓取锁 owner 直接用 task id；
- 当同一任务被重复投递时，不同执行实例可能被视为“同 owner”，导致锁保护失效。

已修复：

- 抓取执行 owner 改为 `task_id + uuid`
  - 文件：`/Users/Apple/Projects/profitlens-v3/backend/app/tasks/scrape_tasks.py:166`
- `claim_library_scrape_lock()` 只允许从 `pending_owner -> execution_owner` 单向接管，不再允许同 task id 的其他执行实例直接复用锁
  - 文件：`/Users/Apple/Projects/profitlens-v3/backend/app/tasks/scrape_tasks.py:96`

效果：

- 当前 Redis 锁值已变为 `task_id:execution_uuid` 格式；
- 即使 broker 再次投递，同一 task id 的其他执行实例也不会再共享当前执行锁。

### 3. 给分页 cursor 增加环路护栏

根因：

- 全量价格切片下，部分类目会出现 cursor 循环或抖动；
- 原先只有“下一页 cursor 与上一页完全相同”才退出；
- 如果 cursor 在多个值之间循环，会造成单个价格片段长时间空转。

已修复：

- 新增 `seen_cursors` 集合；
- 一旦同一 slice 中出现重复 cursor，直接中断该 slice，并打 warning 日志
  - 文件：`/Users/Apple/Projects/profitlens-v3/backend/app/services/library_service.py:392`
  - 文件：`/Users/Apple/Projects/profitlens-v3/backend/app/services/library_service.py:439`

效果：

- 运行日志已经能看到 `Library scrape cursor loop detected`；
- 说明新的护栏已在 live 任务中生效，避免单 slice 无限循环。

## 三、验证结果

### 代码验证

- 定向测试通过：`18 passed`
- 全量后端测试通过：`40 passed`

相关测试文件：

- `/Users/Apple/Projects/profitlens-v3/backend/tests/test_bid_periodic_sync_schedule.py:23`
- `/Users/Apple/Projects/profitlens-v3/backend/tests/test_scrape_tasks.py:67`
- `/Users/Apple/Projects/profitlens-v3/backend/tests/test_library_service.py:235`

### 运行时验证

已重启以下服务并确认新配置生效：

- `profitlens-backend`
- `profitlens-celery-default`
- `profitlens-celery-beat`

运行时复核结果：

- `visibility_timeout = 86400`
- 当前活动 scrape 任务只有 1 个
- 当前活动 scrape 任务 `redelivered=false`
- 当前自动补采仍在持续推进

## 四、agent team 复核结论

本轮已启用 agent team 并做并行复核，结论如下：

### 结论 A：当前修复已经解决“重复投递 + 多实例并发”问题

- 当前 scrape 任务只有 1 个；
- 当前任务仍在继续请求 Takealot；
- 当前没有看到新的重复投递现象。

### 结论 B：如果 Takealot 总商品量级接近 900 万，当前“12 小时一轮 + 全量完整价格切片”方案不现实

原因：

- 当前抓取本质仍是串行：
  - `department × 价格切片 × cursor`
- 当前每页 100 条，且带固定请求间隔；
- 即使不算 429、重试、解析和数据库写入，仅理论请求时间下限就已经很大；
- 实测速度也远远达不到“12 小时扫完整站”的目标。

agent team 给出的关键判断：

- 当前 12 小时策略适合作为“持续补采”；
- 但不适合作为“900 万商品量级全站全量轮询”的商业级长期方案。

## 五、当前商业判断

### 当前方案适合什么

- 作为选品库持续增长方案；
- 作为站点覆盖率逐步扩张方案；
- 作为修复稳定性后的过渡方案。

### 当前方案不适合什么

- 不适合把“12 小时一轮”理解成“12 小时全站扫完一遍”；
- 不适合 900 万量级下继续用单任务串行全量遍历做长期商用主策略。

## 六、下一步建议

下一阶段建议改造成真正适合 900 万量级的商用补采架构：

1. 热门类目高频增量
2. 长尾类目低频轮转
3. 分片并行抓取
4. 断点续扫
5. 以覆盖率 / 新增率为目标，而不是每轮全站扫完

建议目标不是“12 小时扫完整站”，而是：

- 在可控请求预算内，
- 保证持续新增，
- 保证热销区新鲜度，
- 保证系统稳定性和商用可维护性。

## 七、相关页面

- 选品库页面：`http://localhost/library`

