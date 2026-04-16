#!/usr/bin/env python3
"""
ProfitLens v3 - 多 Agent 监督系统
==================================

功能:
- Agent 1: 进度监控 Agent（实时监控爬取进度）
- Agent 2: 健康检查 Agent（监控系统健康状态）
- Agent 3: 数据质量 Agent（验证数据完整性和质量）
- Agent 4: 性能分析 Agent（分析性能瓶颈）
- Agent 5: 告警通知 Agent（异常告警和通知）

协调机制: 主控制器协调所有 Agent，实现全方位监督
"""
import asyncio
import httpx
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import logging


class AgentStatus(Enum):
    """Agent 状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """告警信息"""
    level: AlertLevel
    agent_name: str
    message: str
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "level": self.level.value,
            "agent_name": self.agent_name,
            "message": self.message,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "details": self.details
        }


class BaseAgent:
    """Agent 基类"""

    def __init__(self, name: str, client: httpx.AsyncClient, token: str, logger: logging.Logger):
        self.name = name
        self.client = client
        self.token = token
        self.logger = logger
        self.status = AgentStatus.IDLE
        self.alerts: List[Alert] = []
        self.last_check_time: float = 0
        self.check_interval: float = 30  # 默认 30 秒检查一次

    async def check(self) -> List[Alert]:
        """执行检查（子类实现）"""
        raise NotImplementedError

    async def run(self):
        """运行 Agent"""
        self.status = AgentStatus.RUNNING
        self.logger.info(f"[{self.name}] Agent 已启动")

        while self.status == AgentStatus.RUNNING:
            try:
                if time.time() - self.last_check_time >= self.check_interval:
                    alerts = await self.check()
                    if alerts:
                        self.alerts.extend(alerts)
                        for alert in alerts:
                            self._log_alert(alert)
                    self.last_check_time = time.time()

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"[{self.name}] 异常: {e}", exc_info=True)
                await asyncio.sleep(5)

        self.logger.info(f"[{self.name}] Agent 已停止")

    def _log_alert(self, alert: Alert):
        """记录告警"""
        if alert.level == AlertLevel.INFO:
            self.logger.info(f"[{self.name}] ℹ️  {alert.message}")
        elif alert.level == AlertLevel.WARNING:
            self.logger.warning(f"[{self.name}] ⚠️  {alert.message}")
        elif alert.level == AlertLevel.ERROR:
            self.logger.error(f"[{self.name}] ❌ {alert.message}")
        elif alert.level == AlertLevel.CRITICAL:
            self.logger.critical(f"[{self.name}] 🚨 {alert.message}")

    def stop(self):
        """停止 Agent"""
        self.status = AgentStatus.IDLE


class ProgressMonitorAgent(BaseAgent):
    """进度监控 Agent"""

    def __init__(self, *args, **kwargs):
        super().__init__("进度监控", *args, **kwargs)
        self.check_interval = 10
        self.last_total = 0
        self.stall_threshold = 300  # 5 分钟无进度视为停滞
        self.last_progress_time = time.time()

    async def check(self) -> List[Alert]:
        alerts = []

        try:
            resp = await self.client.get(
                "http://localhost:8000/api/library/scrape/progress",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("running"):
                return alerts

            total = data.get("total_scraped", 0)
            current_cat = data.get("current_cat", "")
            done_cats = data.get("done_cats", 0)
            total_cats = data.get("total_cats", 25)

            # 检测进度停滞
            if total > self.last_total:
                self.last_progress_time = time.time()
                self.last_total = total
            else:
                stall_time = time.time() - self.last_progress_time
                if stall_time > self.stall_threshold:
                    alerts.append(Alert(
                        level=AlertLevel.WARNING,
                        agent_name=self.name,
                        message=f"进度停滞 {stall_time/60:.1f} 分钟",
                        details={"stall_seconds": stall_time, "current_category": current_cat}
                    ))

            # 检测异常慢速
            elapsed = data.get("elapsed_sec", 0)
            if elapsed > 0 and total > 0:
                speed = total / elapsed
                if speed < 1:  # 低于 1 商品/秒
                    alerts.append(Alert(
                        level=AlertLevel.WARNING,
                        agent_name=self.name,
                        message=f"爬取速度过慢: {speed:.2f} 商品/秒",
                        details={"speed": speed, "total": total, "elapsed": elapsed}
                    ))

        except Exception as e:
            alerts.append(Alert(
                level=AlertLevel.ERROR,
                agent_name=self.name,
                message=f"获取进度失败: {e}",
                details={"error": str(e)}
            ))

        return alerts


class HealthCheckAgent(BaseAgent):
    """健康检查 Agent"""

    def __init__(self, *args, **kwargs):
        super().__init__("健康检查", *args, **kwargs)
        self.check_interval = 60

    async def check(self) -> List[Alert]:
        alerts = []

        try:
            # API 健康检查
            resp = await self.client.get(
                "http://localhost:8000/api/library/stats",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )

            if resp.status_code != 200:
                alerts.append(Alert(
                    level=AlertLevel.ERROR,
                    agent_name=self.name,
                    message=f"API 响应异常: HTTP {resp.status_code}",
                    details={"status_code": resp.status_code}
                ))

            # 检查响应时间
            if resp.elapsed.total_seconds() > 5:
                alerts.append(Alert(
                    level=AlertLevel.WARNING,
                    agent_name=self.name,
                    message=f"API 响应缓慢: {resp.elapsed.total_seconds():.2f} 秒",
                    details={"response_time": resp.elapsed.total_seconds()}
                ))

        except httpx.TimeoutException:
            alerts.append(Alert(
                level=AlertLevel.CRITICAL,
                agent_name=self.name,
                message="API 请求超时",
                details={"error": "timeout"}
            ))
        except Exception as e:
            alerts.append(Alert(
                level=AlertLevel.ERROR,
                agent_name=self.name,
                message=f"健康检查失败: {e}",
                details={"error": str(e)}
            ))

        return alerts


class DataQualityAgent(BaseAgent):
    """数据质量 Agent"""

    def __init__(self, *args, **kwargs):
        super().__init__("数据质量", *args, **kwargs)
        self.check_interval = 120  # 2 分钟检查一次
        self.last_total = 0
        self.duplicate_threshold = 0.05  # 重复率超过 5% 告警

    async def check(self) -> List[Alert]:
        alerts = []

        try:
            resp = await self.client.get(
                "http://localhost:8000/api/library/stats",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            total = data.get("total_products", 0)
            categories = data.get("categories", 0)
            brands = data.get("brands", 0)
            quarantined = data.get("quarantined", 0)

            # 检查数据增长
            if total > self.last_total:
                growth = total - self.last_total
                self.logger.debug(f"[{self.name}] 数据增长: +{growth} 商品")
                self.last_total = total

            # 检查隔离率
            if total > 0:
                quarantine_rate = quarantined / total
                if quarantine_rate > 0.1:  # 隔离率超过 10%
                    alerts.append(Alert(
                        level=AlertLevel.WARNING,
                        agent_name=self.name,
                        message=f"隔离商品比例过高: {quarantine_rate*100:.1f}%",
                        details={"quarantined": quarantined, "total": total, "rate": quarantine_rate}
                    ))

            # 检查分类覆盖
            if categories < 20:  # 少于 20 个分类
                alerts.append(Alert(
                    level=AlertLevel.WARNING,
                    agent_name=self.name,
                    message=f"分类覆盖不足: 仅 {categories}/25 个分类",
                    details={"categories": categories}
                ))

            # 检查品牌数量
            if total > 10000 and brands < 100:
                alerts.append(Alert(
                    level=AlertLevel.WARNING,
                    agent_name=self.name,
                    message=f"品牌数量异常: {brands} 个品牌 / {total} 个商品",
                    details={"brands": brands, "total": total}
                ))

        except Exception as e:
            alerts.append(Alert(
                level=AlertLevel.ERROR,
                agent_name=self.name,
                message=f"数据质量检查失败: {e}",
                details={"error": str(e)}
            ))

        return alerts


class PerformanceAnalysisAgent(BaseAgent):
    """性能分析 Agent"""

    def __init__(self, *args, **kwargs):
        super().__init__("性能分析", *args, **kwargs)
        self.check_interval = 60
        self.speed_history: List[float] = []
        self.max_history = 10

    async def check(self) -> List[Alert]:
        alerts = []

        try:
            resp = await self.client.get(
                "http://localhost:8000/api/library/scrape/progress",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("running"):
                return alerts

            total = data.get("total_scraped", 0)
            elapsed = data.get("elapsed_sec", 0)

            if elapsed > 0 and total > 0:
                current_speed = total / elapsed
                self.speed_history.append(current_speed)

                # 保持历史记录在限制内
                if len(self.speed_history) > self.max_history:
                    self.speed_history.pop(0)

                # 计算平均速度
                if len(self.speed_history) >= 3:
                    avg_speed = sum(self.speed_history) / len(self.speed_history)

                    # 检测性能下降
                    if current_speed < avg_speed * 0.5:
                        alerts.append(Alert(
                            level=AlertLevel.WARNING,
                            agent_name=self.name,
                            message=f"性能下降: 当前 {current_speed:.2f}/s，平均 {avg_speed:.2f}/s",
                            details={"current_speed": current_speed, "avg_speed": avg_speed}
                        ))

                # 估算完成时间
                done_cats = data.get("done_cats", 0)
                total_cats = data.get("total_cats", 25)
                if done_cats > 0 and total_cats > 0:
                    progress = done_cats / total_cats
                    if progress > 0.1:
                        estimated_total_time = elapsed / progress
                        estimated_remaining = estimated_total_time - elapsed

                        if estimated_remaining > 86400:  # 超过 24 小时
                            alerts.append(Alert(
                                level=AlertLevel.WARNING,
                                agent_name=self.name,
                                message=f"预计剩余时间过长: {estimated_remaining/3600:.1f} 小时",
                                details={"estimated_remaining_hours": estimated_remaining/3600}
                            ))

        except Exception as e:
            alerts.append(Alert(
                level=AlertLevel.ERROR,
                agent_name=self.name,
                message=f"性能分析失败: {e}",
                details={"error": str(e)}
            ))

        return alerts


class AlertNotificationAgent(BaseAgent):
    """告警通知 Agent"""

    def __init__(self, *args, **kwargs):
        super().__init__("告警通知", *args, **kwargs)
        self.check_interval = 5
        self.alert_history: List[Alert] = []
        self.max_history = 100

    async def check(self) -> List[Alert]:
        # 此 Agent 不产生新告警，只处理其他 Agent 的告警
        return []

    def process_alerts(self, alerts: List[Alert]):
        """处理告警"""
        for alert in alerts:
            self.alert_history.append(alert)

            # 保持历史记录在限制内
            if len(self.alert_history) > self.max_history:
                self.alert_history.pop(0)

            # 这里可以添加通知逻辑（邮件、Slack、钉钉等）
            # 目前只记录日志
            self._log_alert(alert)

    def get_alert_summary(self) -> Dict[str, Any]:
        """获取告警摘要"""
        if not self.alert_history:
            return {"total": 0, "by_level": {}, "by_agent": {}}

        by_level = {}
        by_agent = {}

        for alert in self.alert_history:
            level = alert.level.value
            agent = alert.agent_name

            by_level[level] = by_level.get(level, 0) + 1
            by_agent[agent] = by_agent.get(agent, 0) + 1

        return {
            "total": len(self.alert_history),
            "by_level": by_level,
            "by_agent": by_agent,
            "recent": [a.to_dict() for a in self.alert_history[-10:]]
        }


class AgentSupervisor:
    """Agent 监督控制器"""

    def __init__(self, client: httpx.AsyncClient, token: str, logger: logging.Logger):
        self.client = client
        self.token = token
        self.logger = logger
        self.agents: List[BaseAgent] = []
        self.tasks: List[asyncio.Task] = []
        self.running = False

        # 初始化所有 Agent
        self.progress_agent = ProgressMonitorAgent(client, token, logger)
        self.health_agent = HealthCheckAgent(client, token, logger)
        self.quality_agent = DataQualityAgent(client, token, logger)
        self.performance_agent = PerformanceAnalysisAgent(client, token, logger)
        self.alert_agent = AlertNotificationAgent(client, token, logger)

        self.agents = [
            self.progress_agent,
            self.health_agent,
            self.quality_agent,
            self.performance_agent,
            self.alert_agent,
        ]

    async def start(self):
        """启动所有 Agent"""
        self.logger.info("🤖 启动多 Agent 监督系统...")
        self.running = True

        # 启动所有 Agent
        for agent in self.agents:
            task = asyncio.create_task(agent.run())
            self.tasks.append(task)

        self.logger.info(f"✅ {len(self.agents)} 个 Agent 已启动")

    async def stop(self):
        """停止所有 Agent"""
        self.logger.info("🛑 停止多 Agent 监督系统...")
        self.running = False

        # 停止所有 Agent
        for agent in self.agents:
            agent.stop()

        # 取消所有任务
        for task in self.tasks:
            task.cancel()

        # 等待所有任务完成
        await asyncio.gather(*self.tasks, return_exceptions=True)

        self.logger.info("✅ 所有 Agent 已停止")

    async def collect_alerts(self) -> List[Alert]:
        """收集所有 Agent 的告警"""
        all_alerts = []
        for agent in self.agents:
            if agent.alerts:
                all_alerts.extend(agent.alerts)
                agent.alerts.clear()  # 清空已收集的告警

        return all_alerts

    async def monitor_loop(self):
        """监控循环"""
        while self.running:
            try:
                # 收集告警
                alerts = await self.collect_alerts()

                # 处理告警
                if alerts:
                    self.alert_agent.process_alerts(alerts)

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"监控循环异常: {e}", exc_info=True)
                await asyncio.sleep(5)

    def get_status_report(self) -> Dict[str, Any]:
        """获取状态报告"""
        return {
            "supervisor_running": self.running,
            "agents": [
                {
                    "name": agent.name,
                    "status": agent.status.value,
                    "last_check": datetime.fromtimestamp(agent.last_check_time).isoformat() if agent.last_check_time > 0 else None,
                    "check_interval": agent.check_interval,
                }
                for agent in self.agents
            ],
            "alerts": self.alert_agent.get_alert_summary(),
        }


# 导出
__all__ = [
    'AgentSupervisor',
    'Alert',
    'AlertLevel',
]
