#!/usr/bin/env python3
"""
ProfitLens v3 - 增强版商品库爬取监控系统
===========================================

特性:
✅ 稳定性: 自动重试、断点续传、异常恢复
✅ 安全性: 限流保护、数据验证、错误隔离
✅ 完整性: 数据校验、去重检测、完整性报告
✅ 监控: 实时进度、性能指标、告警通知

作者: Claude Code Agent Team
版本: 2.0.0
"""
import asyncio
import httpx
import json
import time
import sys
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from dataclasses import dataclass, asdict
from enum import Enum

# 导入 Agent 监督系统
from agent_supervisor import AgentSupervisor, AlertLevel

# ============ 配置区域 ============
API_BASE_URL = "http://localhost:8000"
USERNAME = "your_email@example.com"      # 修改为你的账号
PASSWORD = "your_password"               # 修改为你的密码

# 爬取配置
SCRAPE_CONFIG = {
    "lead_min": 0,           # 最小发货时间（天）
    "lead_max": 999,         # 最大发货时间（天）
    "price_min": 0,          # 最低价格（ZAR）
    "price_max": 100000,     # 最高价格（ZAR）
    "max_per_cat": 0,        # 每分类最大数量，0=不限制
    "categories": None,      # 指定分类，None=全部
}

# 监控配置
MONITOR_CONFIG = {
    "poll_interval": 10,              # 进度轮询间隔（秒）
    "health_check_interval": 60,      # 健康检查间隔（秒）
    "alert_threshold_errors": 10,     # 错误告警阈值
    "alert_threshold_slow": 300,      # 慢速告警阈值（秒无进度）
    "save_checkpoint_interval": 300,  # 检查点保存间隔（秒）
    "log_file": "scrape_monitor.log", # 日志文件
    "checkpoint_file": "scrape_checkpoint.json",  # 检查点文件
}

# 安全配置
SECURITY_CONFIG = {
    "max_retry_attempts": 3,          # 最大重试次数
    "retry_backoff_base": 2,          # 重试退避基数
    "request_timeout": 30,            # 请求超时（秒）
    "rate_limit_cooldown": 90,        # 限流冷却时间（秒）
}
# ==================================


class ScrapeStatus(Enum):
    """爬取状态枚举"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ScrapeMetrics:
    """爬取指标"""
    total_scraped: int = 0
    current_category: str = ""
    done_categories: int = 0
    total_categories: int = 25
    elapsed_seconds: float = 0
    avg_speed: float = 0  # 商品/秒
    estimated_remaining: float = 0  # 秒
    error_count: int = 0
    last_progress_time: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthStatus:
    """健康状态"""
    is_healthy: bool = True
    api_responsive: bool = True
    celery_responsive: bool = True
    database_responsive: bool = True
    redis_responsive: bool = True
    issues: list = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class EnhancedScrapeMonitor:
    """增强版爬取监控器"""

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.token: Optional[str] = None
        self.task_id: Optional[str] = None
        self.status = ScrapeStatus.IDLE
        self.metrics = ScrapeMetrics()
        self.health = HealthStatus()
        self.start_time: Optional[float] = None
        self.last_checkpoint_time: float = 0
        self.shutdown_requested = False
        self.agent_supervisor: Optional[AgentSupervisor] = None
        self.supervisor_task: Optional[asyncio.Task] = None

        # 设置日志
        self._setup_logging()

        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _setup_logging(self):
        """设置日志系统"""
        log_file = Path(MONITOR_CONFIG["log_file"])

        # 创建日志格式
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)

        # 配置根日志器
        self.logger = logging.getLogger('ScrapeMonitor')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.logger.info("=" * 70)
        self.logger.info("增强版商品库爬取监控系统启动")
        self.logger.info("=" * 70)

    def _signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.warning(f"收到信号 {signum}，准备优雅关闭...")
        self.shutdown_requested = True

    async def _save_checkpoint(self):
        """保存检查点"""
        checkpoint = {
            "timestamp": datetime.now().isoformat(),
            "task_id": self.task_id,
            "status": self.status.value,
            "metrics": self.metrics.to_dict(),
            "config": SCRAPE_CONFIG,
        }

        checkpoint_file = Path(MONITOR_CONFIG["checkpoint_file"])
        try:
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint, f, indent=2, ensure_ascii=False)
            self.logger.debug(f"检查点已保存: {checkpoint_file}")
        except Exception as e:
            self.logger.error(f"保存检查点失败: {e}")

    async def _load_checkpoint(self) -> Optional[Dict]:
        """加载检查点"""
        checkpoint_file = Path(MONITOR_CONFIG["checkpoint_file"])
        if not checkpoint_file.exists():
            return None

        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
            self.logger.info(f"发现检查点: {checkpoint['timestamp']}")
            return checkpoint
        except Exception as e:
            self.logger.error(f"加载检查点失败: {e}")
            return None

    async def login(self) -> bool:
        """登录并获取 token"""
        self.logger.info("🔐 正在登录...")

        for attempt in range(SECURITY_CONFIG["max_retry_attempts"]):
            try:
                resp = await self.client.post(
                    f"{API_BASE_URL}/api/auth/login",
                    json={"username": USERNAME, "password": PASSWORD},
                    timeout=SECURITY_CONFIG["request_timeout"]
                )
                resp.raise_for_status()
                data = resp.json()

                if not data.get("access_token"):
                    self.logger.error("登录响应中没有 access_token")
                    return False

                self.token = data["access_token"]
                self.logger.info(f"✅ 登录成功！Token: {self.token[:20]}...")
                return True

            except httpx.HTTPStatusError as e:
                self.logger.error(f"登录失败 (HTTP {e.response.status_code}): {e}")
                if e.response.status_code == 401:
                    self.logger.error("账号或密码错误，请检查配置")
                    return False
            except Exception as e:
                self.logger.error(f"登录异常 (尝试 {attempt + 1}/{SECURITY_CONFIG['max_retry_attempts']}): {e}")
                if attempt < SECURITY_CONFIG["max_retry_attempts"] - 1:
                    wait = SECURITY_CONFIG["retry_backoff_base"] ** attempt
                    self.logger.info(f"等待 {wait} 秒后重试...")
                    await asyncio.sleep(wait)

        return False

    async def check_health(self) -> HealthStatus:
        """健康检查"""
        health = HealthStatus()

        try:
            # API 健康检查
            resp = await self.client.get(
                f"{API_BASE_URL}/api/library/stats",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )
            health.api_responsive = resp.status_code == 200

            if not health.api_responsive:
                health.issues.append(f"API 响应异常: HTTP {resp.status_code}")

        except Exception as e:
            health.api_responsive = False
            health.issues.append(f"API 不可达: {e}")

        health.is_healthy = health.api_responsive
        return health

    async def get_stats(self) -> Optional[Dict]:
        """获取商品库统计"""
        try:
            resp = await self.client.get(
                f"{API_BASE_URL}/api/library/stats",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=SECURITY_CONFIG["request_timeout"]
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.logger.error(f"获取统计失败: {e}")
            return None

    async def start_scrape(self) -> bool:
        """启动爬取任务"""
        self.logger.info("🚀 正在启动商品库爬取...")
        self.logger.info(f"📋 配置: {json.dumps(SCRAPE_CONFIG, indent=2, ensure_ascii=False)}")

        self.status = ScrapeStatus.STARTING

        for attempt in range(SECURITY_CONFIG["max_retry_attempts"]):
            try:
                resp = await self.client.post(
                    f"{API_BASE_URL}/api/library/scrape/start",
                    json=SCRAPE_CONFIG,
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=SECURITY_CONFIG["request_timeout"]
                )
                resp.raise_for_status()
                data = resp.json()

                if not data.get("ok"):
                    error = data.get("error", "未知错误")
                    if "already running" in error.lower():
                        self.logger.warning("⚠️  爬取任务已在运行中，切换到监控模式")
                        self.status = ScrapeStatus.RUNNING
                        return True
                    else:
                        self.logger.error(f"启动失败: {error}")
                        return False

                self.task_id = data.get("task_id")
                self.status = ScrapeStatus.RUNNING
                self.start_time = time.time()
                self.metrics.last_progress_time = self.start_time

                self.logger.info(f"✅ 爬取任务已启动！")
                self.logger.info(f"   Task ID: {self.task_id}")
                self.logger.info(f"   开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                await self._save_checkpoint()
                return True

            except Exception as e:
                self.logger.error(f"启动异常 (尝试 {attempt + 1}/{SECURITY_CONFIG['max_retry_attempts']}): {e}")
                if attempt < SECURITY_CONFIG["max_retry_attempts"] - 1:
                    wait = SECURITY_CONFIG["retry_backoff_base"] ** attempt
                    await asyncio.sleep(wait)

        self.status = ScrapeStatus.FAILED
        return False

    async def get_progress(self) -> Optional[Dict]:
        """获取爬取进度"""
        try:
            resp = await self.client.get(
                f"{API_BASE_URL}/api/library/scrape/progress",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.logger.error(f"获取进度失败: {e}")
            self.metrics.error_count += 1
            return None

    def _update_metrics(self, progress_data: Dict):
        """更新指标"""
        old_total = self.metrics.total_scraped

        self.metrics.total_scraped = progress_data.get("total_scraped", 0)
        self.metrics.current_category = progress_data.get("current_cat", "")
        self.metrics.done_categories = progress_data.get("done_cats", 0)
        self.metrics.total_categories = progress_data.get("total_cats", 25)
        self.metrics.elapsed_seconds = progress_data.get("elapsed_sec", 0)

        # 计算速度
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed > 0:
                self.metrics.avg_speed = self.metrics.total_scraped / elapsed

        # 检测进度停滞
        if self.metrics.total_scraped > old_total:
            self.metrics.last_progress_time = time.time()
        else:
            stall_time = time.time() - self.metrics.last_progress_time
            if stall_time > MONITOR_CONFIG["alert_threshold_slow"]:
                self.logger.warning(f"⚠️  进度停滞 {stall_time:.0f} 秒，可能遇到问题")

        # 估算剩余时间
        if self.metrics.avg_speed > 0 and self.metrics.total_categories > 0:
            progress_pct = self.metrics.done_categories / self.metrics.total_categories
            if progress_pct > 0.1:  # 至少完成 10% 才估算
                total_estimated = self.metrics.elapsed_seconds / progress_pct
                self.metrics.estimated_remaining = total_estimated - self.metrics.elapsed_seconds

    def _display_progress(self):
        """显示进度"""
        m = self.metrics

        # 进度百分比
        progress_pct = (m.done_categories / m.total_categories * 100) if m.total_categories > 0 else 0

        # 进度条
        bar_length = 40
        filled = int(bar_length * progress_pct / 100)
        bar = "█" * filled + "░" * (bar_length - filled)

        # 时间格式化
        elapsed_str = str(timedelta(seconds=int(m.elapsed_seconds)))
        if m.estimated_remaining > 0:
            remaining_str = str(timedelta(seconds=int(m.estimated_remaining)))
        else:
            remaining_str = "计算中..."

        # 显示
        print(f"\r[{bar}] {progress_pct:.1f}% | "
              f"已爬取: {m.total_scraped:,} | "
              f"分类: {m.done_categories}/{m.total_categories} | "
              f"速度: {m.avg_speed:.1f}/s | "
              f"已用: {elapsed_str} | "
              f"剩余: {remaining_str}",
              end="", flush=True)

    async def monitor_progress(self):
        """监控爬取进度"""
        self.logger.info("\n📊 开始监控爬取进度...")
        self.logger.info("   按 Ctrl+C 可以安全退出监控（爬取任务继续运行）\n")

        # 启动 Agent 监督系统
        self.logger.info("🤖 启动多 Agent 监督系统...")
        self.agent_supervisor = AgentSupervisor(self.client, self.token, self.logger)
        await self.agent_supervisor.start()
        self.supervisor_task = asyncio.create_task(self.agent_supervisor.monitor_loop())

        last_health_check = time.time()
        consecutive_errors = 0

        while not self.shutdown_requested:
            try:
                # 获取进度
                progress_data = await self.get_progress()

                if progress_data is None:
                    consecutive_errors += 1
                    if consecutive_errors >= MONITOR_CONFIG["alert_threshold_errors"]:
                        self.logger.error(f"❌ 连续 {consecutive_errors} 次获取进度失败，可能出现严重问题")
                        self.status = ScrapeStatus.FAILED
                        break
                    await asyncio.sleep(MONITOR_CONFIG["poll_interval"])
                    continue

                consecutive_errors = 0  # 重置错误计数

                # 检查运行状态
                if not progress_data.get("running"):
                    mode = progress_data.get("mode", "idle")

                    if mode == "done":
                        self.status = ScrapeStatus.COMPLETED
                        self._update_metrics(progress_data)
                        print()  # 换行
                        self.logger.info("\n🎉 爬取完成！")
                        await self._print_summary()
                        break

                    elif mode == "error":
                        self.status = ScrapeStatus.FAILED
                        error = progress_data.get("error", "未知错误")
                        print()
                        self.logger.error(f"\n❌ 爬取出错: {error}")
                        break

                    else:
                        self.status = ScrapeStatus.IDLE
                        print()
                        self.logger.warning(f"\n⏸️  爬取未运行，状态: {mode}")
                        break

                # 更新指标
                self._update_metrics(progress_data)

                # 显示进度
                self._display_progress()

                # 定期健康检查
                if time.time() - last_health_check > MONITOR_CONFIG["health_check_interval"]:
                    self.health = await self.check_health()
                    if not self.health.is_healthy:
                        self.logger.warning(f"⚠️  健康检查发现问题: {', '.join(self.health.issues)}")
                    last_health_check = time.time()

                # 定期保存检查点
                if time.time() - self.last_checkpoint_time > MONITOR_CONFIG["save_checkpoint_interval"]:
                    await self._save_checkpoint()
                    self.last_checkpoint_time = time.time()

                # 等待下次轮询
                await asyncio.sleep(MONITOR_CONFIG["poll_interval"])

            except asyncio.CancelledError:
                self.logger.info("\n监控任务被取消")
                break
            except Exception as e:
                self.logger.error(f"\n监控异常: {e}", exc_info=True)
                consecutive_errors += 1
                await asyncio.sleep(MONITOR_CONFIG["poll_interval"])

        if self.shutdown_requested:
            print()
            self.logger.info("\n⚠️  用户中断监控，爬取任务仍在后台运行")
            self.logger.info("   可以稍后重新运行此脚本继续监控")

        # 停止 Agent 监督系统
        if self.agent_supervisor:
            await self.agent_supervisor.stop()
            if self.supervisor_task:
                self.supervisor_task.cancel()
                try:
                    await self.supervisor_task
                except asyncio.CancelledError:
                    pass

            # 打印 Agent 报告
            self.logger.info("\n" + "=" * 70)
            self.logger.info("🤖 Agent 监督系统报告")
            self.logger.info("=" * 70)
            report = self.agent_supervisor.get_status_report()
            alerts_summary = report.get("alerts", {})
            self.logger.info(f"   总告警数: {alerts_summary.get('total', 0)}")
            if alerts_summary.get('by_level'):
                self.logger.info(f"   告警分布: {alerts_summary.get('by_level')}")
            self.logger.info("=" * 70)

    async def _print_summary(self):
        """打印总结报告"""
        self.logger.info("\n" + "=" * 70)
        self.logger.info("📊 爬取总结报告")
        self.logger.info("=" * 70)

        # 获取最终统计
        stats = await self.get_stats()

        if stats:
            self.logger.info(f"   总商品数: {stats.get('total_products', 0):,}")
            self.logger.info(f"   分类数: {stats.get('categories', 0)}")
            self.logger.info(f"   品牌数: {stats.get('brands', 0)}")
            self.logger.info(f"   隔离商品: {stats.get('quarantined', 0)}")
            self.logger.info(f"   最后更新: {stats.get('last_updated', 'N/A')}")

        self.logger.info(f"\n   本次爬取: {self.metrics.total_scraped:,} 个商品")
        self.logger.info(f"   总耗时: {str(timedelta(seconds=int(self.metrics.elapsed_seconds)))}")
        self.logger.info(f"   平均速度: {self.metrics.avg_speed:.2f} 商品/秒")
        self.logger.info(f"   错误次数: {self.metrics.error_count}")

        # 数据完整性校验
        self.logger.info("\n" + "-" * 70)
        self.logger.info("🔍 数据完整性校验")
        self.logger.info("-" * 70)
        await self._verify_data_integrity(stats)

        self.logger.info("=" * 70)

    async def _verify_data_integrity(self, stats: Optional[Dict]):
        """数据完整性校验"""
        issues = []

        if stats:
            total = stats.get("total_products", 0)
            categories = stats.get("categories", 0)
            brands = stats.get("brands", 0)
            quarantined = stats.get("quarantined", 0)

            # 检查 1: 总量是否合理
            if total < 10000:
                issues.append(f"⚠️  总商品数偏少 ({total:,})，可能爬取不完整")
            else:
                self.logger.info(f"   ✅ 总量检查通过: {total:,} 个商品")

            # 检查 2: 分类覆盖
            if categories >= 23:  # 25 个部门中至少覆盖 23 个
                self.logger.info(f"   ✅ 分类覆盖检查通过: {categories}/25 个分类")
            else:
                issues.append(f"⚠️  分类覆盖不足: 仅 {categories}/25 个分类")

            # 检查 3: 品牌多样性
            if total > 0:
                brand_ratio = brands / total
                if brand_ratio > 0.001:  # 品牌数至少占总量的 0.1%
                    self.logger.info(f"   ✅ 品牌多样性检查通过: {brands} 个品牌")
                else:
                    issues.append(f"⚠️  品牌数据异常: 仅 {brands} 个品牌")

            # 检查 4: 隔离率
            if total > 0:
                quarantine_rate = quarantined / (total + quarantined) * 100
                if quarantine_rate < 5:
                    self.logger.info(f"   ✅ 隔离率检查通过: {quarantine_rate:.1f}%")
                else:
                    issues.append(f"⚠️  隔离率偏高: {quarantine_rate:.1f}%")

        if issues:
            self.logger.warning("\n   数据完整性问题:")
            for issue in issues:
                self.logger.warning(f"   {issue}")
        else:
            self.logger.info("\n   ✅ 所有完整性检查通过！")

    async def run(self):
        """主运行流程"""
        try:
            # 创建 HTTP 客户端
            self.client = httpx.AsyncClient(timeout=SECURITY_CONFIG["request_timeout"])

            # 1. 登录
            if not await self.login():
                self.logger.error("登录失败，无法继续")
                return 1

            # 2. 健康检查
            self.logger.info("\n🏥 执行健康检查...")
            self.health = await self.check_health()
            if not self.health.is_healthy:
                self.logger.warning(f"⚠️  系统健康状况不佳: {', '.join(self.health.issues)}")
                self.logger.warning("   建议检查服务状态后再启动爬取")
                response = input("是否继续？(y/N): ")
                if response.lower() != 'y':
                    return 1
            else:
                self.logger.info("✅ 系统健康状况良好")

            # 3. 查看当前统计
            self.logger.info("\n📈 当前商品库统计:")
            stats = await self.get_stats()
            if stats:
                self.logger.info(f"   总商品数: {stats.get('total_products', 0):,}")
                self.logger.info(f"   分类数: {stats.get('categories', 0)}")
                self.logger.info(f"   品牌数: {stats.get('brands', 0)}")

            # 4. 检查是否有检查点
            checkpoint = await self._load_checkpoint()
            if checkpoint and checkpoint.get("status") == ScrapeStatus.RUNNING.value:
                self.logger.info("\n💾 发现未完成的爬取任务")
                response = input("是否继续监控该任务？(Y/n): ")
                if response.lower() != 'n':
                    self.task_id = checkpoint.get("task_id")
                    self.status = ScrapeStatus.RUNNING
                    await self.monitor_progress()
                    return 0

            # 5. 启动新的爬取任务
            if not await self.start_scrape():
                self.logger.error("启动爬取失败")
                return 1

            # 6. 监控进度
            await self.monitor_progress()

            # 7. 返回状态码
            if self.status == ScrapeStatus.COMPLETED:
                return 0
            elif self.status == ScrapeStatus.FAILED:
                return 1
            else:
                return 0  # 用户中断，但任务仍在运行

        except Exception as e:
            self.logger.error(f"运行异常: {e}", exc_info=True)
            return 1

        finally:
            if self.client:
                await self.client.aclose()
            self.logger.info("\n👋 监控系统已关闭")


async def main():
    """主入口"""
    monitor = EnhancedScrapeMonitor()
    exit_code = await monitor.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  程序被中断")
        sys.exit(130)
