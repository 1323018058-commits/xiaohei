#!/usr/bin/env python3
"""快速检查爬取状态和速度"""
import asyncio
import httpx
import json
from datetime import timedelta

API_BASE = "http://localhost:8000"

async def check_status():
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            # 获取进度
            resp = await client.get(f"{API_BASE}/api/library/scrape/progress")
            if resp.status_code == 200:
                data = resp.json()

                print("=" * 60)
                print("📊 当前爬取状态")
                print("=" * 60)

                if data.get("running"):
                    total = data.get("total_scraped", 0)
                    current_cat = data.get("current_cat", "")
                    done_cats = data.get("done_cats", 0)
                    total_cats = data.get("total_cats", 25)
                    elapsed = data.get("elapsed_sec", 0)

                    # 计算速度
                    if elapsed > 0:
                        speed = total / elapsed
                        print(f"✅ 爬取运行中")
                        print(f"\n📈 实时数据:")
                        print(f"   已爬取: {total:,} 个商品")
                        print(f"   当前分类: {current_cat}")
                        print(f"   进度: {done_cats}/{total_cats} 个分类")
                        print(f"   已用时间: {str(timedelta(seconds=int(elapsed)))}")
                        print(f"\n⚡ 速度指标:")
                        print(f"   当前速度: {speed:.2f} 商品/秒")
                        print(f"   每分钟: {speed * 60:.0f} 个商品")
                        print(f"   每小时: {speed * 3600:.0f} 个商品")

                        # 估算剩余时间
                        if done_cats > 0:
                            progress = done_cats / total_cats
                            if progress > 0.05:
                                total_time = elapsed / progress
                                remaining = total_time - elapsed
                                print(f"\n⏱️  预计剩余: {str(timedelta(seconds=int(remaining)))}")
                    else:
                        print("⏳ 爬取刚启动，正在初始化...")
                else:
                    mode = data.get("mode", "idle")
                    print(f"⏸️  爬取未运行，状态: {mode}")

                    if mode == "done":
                        total = data.get("total_scraped", 0)
                        print(f"✅ 爬取已完成！总计: {total:,} 个商品")
            else:
                print(f"❌ 无法获取进度 (HTTP {resp.status_code})")

        except httpx.ConnectError:
            print("❌ 无法连接到后端服务")
            print("   请确认 Docker 服务运行: docker-compose ps")
        except Exception as e:
            print(f"❌ 错误: {e}")

        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(check_status())
