# ProfitLens v3 - 增强版商品库爬取系统使用指南

## 📚 目录

1. [系统概述](#系统概述)
2. [快速开始](#快速开始)
3. [配置说明](#配置说明)
4. [功能特性](#功能特性)
5. [监控与告警](#监控与告警)
6. [故障排查](#故障排查)
7. [最佳实践](#最佳实践)

---

## 系统概述

### 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                   增强版爬取监控系统                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ 主监控器     │  │ Agent 监督   │  │ 数据校验     │      │
│  │ - 进度跟踪   │  │ - 5个Agent   │  │ - 完整性     │      │
│  │ - 健康检查   │  │ - 实时监控   │  │ - 质量检查   │      │
│  │ - 检查点     │  │ - 智能告警   │  │ - 去重验证   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    后端爬取引擎                               │
├─────────────────────────────────────────────────────────────┤
│  FastAPI + Celery + Redis + PostgreSQL                      │
│  - 25个部门 × 1080个价格切片                                 │
│  - 自动限流保护（429处理）                                   │
│  - 断点续传支持                                              │
│  - 每500商品提交一次                                         │
└─────────────────────────────────────────────────────────────┘
```

### 核心特性

#### ✅ 稳定性保障
- **自动重试机制**: 最多3次重试，指数退避
- **断点续传**: 支持中断后恢复
- **定期提交**: 每500商品提交，避免长事务
- **锁机制**: 防止重复爬取
- **心跳检测**: 定期刷新锁，防止超时

#### ✅ 安全性保障
- **限流保护**: 自动处理429错误，90秒冷却
- **请求延迟**: 0.6秒/请求，避免触发反爬
- **数据加密**: 敏感信息加密存储
- **错误隔离**: 异常商品自动隔离
- **访问控制**: JWT token认证

#### ✅ 完整性保障
- **数据去重**: 基于product_id自动去重
- **完整性评分**: 自动计算商品数据完整度
- **质量检查**: 5个维度的数据质量验证
- **分类覆盖**: 确保25个部门全覆盖
- **品牌多样性**: 验证品牌数据合理性

#### ✅ 监控体系
- **5个专业Agent**:
  1. 进度监控Agent - 实时跟踪爬取进度
  2. 健康检查Agent - 监控系统健康状态
  3. 数据质量Agent - 验证数据质量
  4. 性能分析Agent - 分析性能瓶颈
  5. 告警通知Agent - 智能告警系统

---

## 快速开始

### 前置条件

1. **确保服务运行**:
```bash
cd /Users/Apple/Projects/profitlens-v3/docker
docker-compose up -d
```

2. **检查服务状态**:
```bash
docker-compose ps
```

必须看到以下服务运行：
- ✅ postgres
- ✅ redis
- ✅ backend
- ✅ celery-worker-default
- ✅ celery-beat
- ✅ celery-flower

### 启动步骤

#### 步骤 1: 配置账号

编辑 `enhanced_scrape_monitor.py`:

```python
# 修改这两行
USERNAME = "your_email@example.com"  # 你的账号
PASSWORD = "your_password"           # 你的密码
```

#### 步骤 2: 运行监控脚本

```bash
cd /Users/Apple/Projects/profitlens-v3
python3 enhanced_scrape_monitor.py
```

#### 步骤 3: 观察输出

你会看到：

```
======================================================================
🚀 ProfitLens v3 - 增强版商品库爬取监控系统启动
======================================================================

🔐 正在登录...
✅ 登录成功！Token: eyJhbGciOiJIUzI1NiIs...

🏥 执行健康检查...
✅ 系统健康状况良好

📈 当前商品库统计:
   总商品数: 0
   分类数: 0
   品牌数: 0

🚀 正在启动商品库爬取...
✅ 爬取任务已启动！
   Task ID: abc123...
   开始时间: 2026-04-16 10:30:00

🤖 启动多 Agent 监督系统...
[进度监控] Agent 已启动
[健康检查] Agent 已启动
[数据质量] Agent 已启动
[性能分析] Agent 已启动
[告警通知] Agent 已启动
✅ 5 个 Agent 已启动

📊 开始监控爬取进度...
   按 Ctrl+C 可以安全退出监控（爬取任务继续运行）

[████████████████████░░░░░░░░░░░░] 52.0% | 已爬取: 125,430 | 分类: 13/25 | 速度: 3.2/s | 已用: 2:15:30 | 剩余: 2:05:20
```

---

## 配置说明

### 爬取配置

```python
SCRAPE_CONFIG = {
    "lead_min": 0,           # 最小发货时间（天）
    "lead_max": 999,         # 最大发货时间（天）
    "price_min": 0,          # 最低价格（ZAR）
    "price_max": 100000,     # 最高价格（ZAR）
    "max_per_cat": 0,        # 每分类最大数量，0=不限制
    "categories": None,      # 指定分类，None=全部
}
```

**推荐配置（全站爬取）**:
- 所有参数保持默认值
- 预计耗时: 6-12 小时
- 预计商品数: 800万-900万

**快速测试配置**:
```python
SCRAPE_CONFIG = {
    "lead_min": 0,
    "lead_max": 999,
    "price_min": 0,
    "price_max": 100000,
    "max_per_cat": 1000,     # 每分类限制1000个
    "categories": ["Books", "Fashion"],  # 只爬2个分类
}
```

### 监控配置

```python
MONITOR_CONFIG = {
    "poll_interval": 10,              # 进度轮询间隔（秒）
    "health_check_interval": 60,      # 健康检查间隔（秒）
    "alert_threshold_errors": 10,     # 错误告警阈值
    "alert_threshold_slow": 300,      # 慢速告警阈值（秒）
    "save_checkpoint_interval": 300,  # 检查点保存间隔（秒）
    "log_file": "scrape_monitor.log", # 日志文件
    "checkpoint_file": "scrape_checkpoint.json",
}
```

### 安全配置

```python
SECURITY_CONFIG = {
    "max_retry_attempts": 3,          # 最大重试次数
    "retry_backoff_base": 2,          # 重试退避基数
    "request_timeout": 30,            # 请求超时（秒）
    "rate_limit_cooldown": 90,        # 限流冷却时间（秒）
}
```

---

## 功能特性

### 1. 实时进度监控

进度条显示：
```
[████████████████████░░░░░░░░░░░░] 52.0%
```

指标说明：
- **已爬取**: 当前已爬取的商品总数
- **分类**: 已完成/总分类数
- **速度**: 当前爬取速度（商品/秒）
- **已用**: 已用时间
- **剩余**: 预计剩余时间

### 2. 多 Agent 监督

#### Agent 1: 进度监控
- 检测进度停滞（5分钟无进度告警）
- 检测异常慢速（<1商品/秒告警）
- 实时速度计算

#### Agent 2: 健康检查
- API 响应检查
- 响应时间监控（>5秒告警）
- 超时检测

#### Agent 3: 数据质量
- 隔离率监控（>10%告警）
- 分类覆盖检查（<20个告警）
- 品牌多样性验证

#### Agent 4: 性能分析
- 速度趋势分析
- 性能下降检测（低于平均50%告警）
- 完成时间估算（>24小时告警）

#### Agent 5: 告警通知
- 收集所有告警
- 告警分级（INFO/WARNING/ERROR/CRITICAL）
- 告警历史记录

### 3. 断点续传

如果监控中断，重新运行脚本时会提示：

```
💾 发现未完成的爬取任务
是否继续监控该任务？(Y/n):
```

选择 Y 继续监控之前的任务。

### 4. 数据完整性校验

爬取完成后自动执行：

```
🔍 数据完整性校验
----------------------------------------------------------------------
   ✅ 总量检查通过: 850,234 个商品
   ✅ 分类覆盖检查通过: 25/25 个分类
   ✅ 品牌多样性检查通过: 12,456 个品牌
   ✅ 隔离率检查通过: 2.3%

   ✅ 所有完整性检查通过！
```

### 5. 日志记录

所有操作记录在 `scrape_monitor.log`:

```
2026-04-16 10:30:00 | INFO     | 增强版商品库爬取监控系统启动
2026-04-16 10:30:05 | INFO     | ✅ 登录成功！
2026-04-16 10:30:10 | INFO     | 🚀 正在启动商品库爬取...
2026-04-16 10:35:00 | WARNING  | [进度监控] ⚠️  爬取速度过慢: 0.8 商品/秒
2026-04-16 12:45:30 | INFO     | 🎉 爬取完成！
```

---

## 监控与告警

### 告警级别

| 级别 | 图标 | 说明 | 示例 |
|------|------|------|------|
| INFO | ℹ️ | 信息提示 | 数据增长正常 |
| WARNING | ⚠️ | 警告 | 速度偏慢、进度停滞 |
| ERROR | ❌ | 错误 | API请求失败 |
| CRITICAL | 🚨 | 严重 | 系统不可用 |

### 常见告警

#### 1. 进度停滞
```
[进度监控] ⚠️  进度停滞 5.2 分钟
```
**原因**: 可能遇到限流或网络问题  
**处理**: 系统会自动重试，无需干预

#### 2. 速度过慢
```
[进度监控] ⚠️  爬取速度过慢: 0.8 商品/秒
```
**原因**: 网络慢或触发限流  
**处理**: 系统会自动调整，继续监控

#### 3. API 响应缓慢
```
[健康检查] ⚠️  API 响应缓慢: 6.5 秒
```
**原因**: 服务器负载高  
**处理**: 检查 Docker 容器资源使用

#### 4. 隔离率偏高
```
[数据质量] ⚠️  隔离商品比例过高: 12.3%
```
**原因**: 数据质量问题或分类错误  
**处理**: 爬取完成后检查隔离商品

---

## 故障排查

### 问题 1: 无法启动爬取

**症状**:
```
❌ 启动失败: Scrape already running
```

**原因**: 已有爬取任务在运行

**解决**:
1. 检查是否有其他爬取任务：
```bash
curl http://localhost:8000/api/library/scrape/progress \
  -H "Authorization: Bearer YOUR_TOKEN"
```

2. 如果确认要停止旧任务：
```bash
curl -X POST http://localhost:8000/api/library/scrape/stop \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 问题 2: 登录失败

**症状**:
```
❌ 登录失败，无法继续
```

**解决**:
1. 检查账号密码是否正确
2. 检查后端服务是否运行：
```bash
docker-compose ps backend
```

3. 查看后端日志：
```bash
docker-compose logs backend
```

### 问题 3: Agent 启动失败

**症状**:
```
[进度监控] 异常: Connection refused
```

**解决**:
1. 检查 Redis 是否运行：
```bash
docker-compose ps redis
```

2. 检查网络连接：
```bash
curl http://localhost:8000/api/library/stats
```

### 问题 4: 进度长时间停滞

**症状**: 进度条超过10分钟不动

**解决**:
1. 检查 Celery worker 状态：
```bash
docker-compose logs celery-worker-default
```

2. 访问 Flower 监控：
```
http://localhost:5555
```

3. 检查是否触发限流：
```bash
docker-compose logs backend | grep "429"
```

---

## 最佳实践

### 1. 首次爬取建议

**测试运行**（推荐）:
```python
SCRAPE_CONFIG = {
    "max_per_cat": 100,  # 每分类100个
    "categories": ["Books"],  # 只爬1个分类
}
```
预计耗时: 5-10 分钟  
目的: 验证系统正常工作

**正式运行**:
```python
SCRAPE_CONFIG = {
    "max_per_cat": 0,  # 不限制
    "categories": None,  # 全部分类
}
```
预计耗时: 6-12 小时  
建议: 晚上启动，第二天查看结果

### 2. 定期更新策略

**增量更新**（推荐）:
- 频率: 每12小时自动运行
- 配置: 系统已自动配置
- 无需手动干预

**手动全量更新**:
- 频率: 每周1次
- 时机: 周末或业务低峰期
- 清理旧数据后重新爬取

### 3. 监控最佳实践

1. **使用 tmux 或 screen**:
```bash
tmux new -s scrape
python3 enhanced_scrape_monitor.py
# Ctrl+B, D 分离会话
```

2. **定期检查日志**:
```bash
tail -f scrape_monitor.log
```

3. **使用 Flower 监控**:
```
http://localhost:5555
```

### 4. 性能优化

**增加 Worker 并发**:

编辑 `docker-compose.yml`:
```yaml
celery-worker-default:
  command: celery -A app.tasks.celery_app worker --concurrency=8  # 改为8
```

**增加数据库连接池**:

编辑 `.env`:
```bash
DB_POOL_SIZE=60
DB_MAX_OVERFLOW=60
```

### 5. 数据备份

**爬取前备份**:
```bash
docker exec profitlens-postgres pg_dump -U profitlens profitlens > backup_before.sql
```

**爬取后备份**:
```bash
docker exec profitlens-postgres pg_dump -U profitlens profitlens > backup_after.sql
```

---

## 附录

### A. 完整命令参考

```bash
# 启动服务
cd /Users/Apple/Projects/profitlens-v3/docker
docker-compose up -d

# 停止服务
docker-compose down

# 查看日志
docker-compose logs -f backend
docker-compose logs -f celery-worker-default

# 重启服务
docker-compose restart backend
docker-compose restart celery-worker-default

# 进入数据库
docker exec -it profitlens-postgres psql -U profitlens -d profitlens

# 进入 Redis
docker exec -it profitlens-redis redis-cli

# 查看商品数量
docker exec -it profitlens-postgres psql -U profitlens -d profitlens \
  -c "SELECT COUNT(*) FROM library_products;"
```

### B. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_BASE_URL` | http://localhost:8000 | API 地址 |
| `USERNAME` | - | 登录账号 |
| `PASSWORD` | - | 登录密码 |

### C. 文件说明

| 文件 | 说明 |
|------|------|
| `enhanced_scrape_monitor.py` | 主监控脚本 |
| `agent_supervisor.py` | Agent 监督系统 |
| `scrape_monitor.log` | 运行日志 |
| `scrape_checkpoint.json` | 检查点文件 |

---

## 技术支持

如遇问题，请提供以下信息：

1. 错误日志（`scrape_monitor.log`）
2. Docker 日志（`docker-compose logs`）
3. 系统状态（`docker-compose ps`）
4. 配置信息（隐藏敏感信息）

---

**版本**: 2.0.0  
**更新日期**: 2026-04-16  
**作者**: Claude Code Agent Team
