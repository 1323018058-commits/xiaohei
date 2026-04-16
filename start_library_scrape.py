#!/usr/bin/env python3
"""启动 Takealot 商品库全站爬取

用法:
    python start_library_scrape.py

配置:
    - 修改下面的 API_BASE_URL 和 AUTH_TOKEN
    - 或者先登录获取 token
"""
import asyncio
import httpx
import json
import time

# ============ 配置区域 ============
API_BASE_URL = "http://localhost:8000"  # 后端 API 地址
USERNAME = "your_email@example.com"      # 你的账号
PASSWORD = "your_password"               # 你的密码

# 爬取参数
SCRAPE_CONFIG = {
    "lead_min": 0,           # 最小发货时间（天）0=立即发货
    "lead_max": 999,         # 最大发货时间（天）999=全部
    "price_min": 0,          # 最低价格（ZAR）
    "price_max": 100000,     # 最高价格（ZAR）
    "max_per_cat": 0,        # 每个分类最多爬取数量，0=不限制（推荐）
    "categories": None,      # 指定分类，None=全部25个部门
}
# ==================================


async def login(client: httpx.AsyncClient) -> str:
    """登录并获取 access token"""
    print("🔐 正在登录...")
    resp = await client.post(
        f"{API_BASE_URL}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD}
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    print(f"✅ 登录成功！Token: {token[:20]}...")
    return token


async def start_scrape(client: httpx.AsyncClient, token: str) -> str:
    """启动爬取任务"""
    print("\n🚀 正在启动商品库爬取...")
    print(f"📋 配置: {json.dumps(SCRAPE_CONFIG, indent=2, ensure_ascii=False)}")

    resp = await client.post(
        f"{API_BASE_URL}/api/library/scrape/start",
        json=SCRAPE_CONFIG,
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        print(f"❌ 启动失败: {data.get('error')}")
        return None

    task_id = data.get("task_id")
    print(f"✅ 爬取任务已启动！Task ID: {task_id}")
    return task_id


async def monitor_progress(client: httpx.AsyncClient, token: str):
    """监控爬取进度"""
    print("\n📊 开始监控爬取进度...\n")

    last_total = 0
    start_time = time.time()

    while True:
        try:
            resp = await client.get(
                f"{API_BASE_URL}/api/library/scrape/progress",
                headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("running"):
                mode = data.get("mode", "idle")
                if mode == "done":
                    total = data.get("total_scraped", 0)
                    elapsed = time.time() - start_time
                    print(f"\n🎉 爬取完成！")
                    print(f"   总计爬取: {total:,} 个商品")
                    print(f"   耗时: {elapsed/60:.1f} 分钟")
                    break
                elif mode == "error":
                    print(f"\n❌ 爬取出错: {data.get('error')}")
                    break
                else:
                    print(f"\n⏸️  爬取未运行，状态: {mode}")
                    break

            # 显示进度
            total = data.get("total_scraped", 0)
            current_cat = data.get("current_cat", "")
            done_cats = data.get("done_cats", 0)
            total_cats = data.get("total_cats", 25)
            elapsed = data.get("elapsed_sec", 0)

            # 计算速度
            speed = (total - last_total) / 10 if total > last_total else 0
            last_total = total

            # 进度条
            progress_pct = (done_cats / total_cats * 100) if total_cats > 0 else 0
            bar_length = 30
            filled = int(bar_length * progress_pct / 100)
            bar = "█" * filled + "░" * (bar_length - filled)

            print(f"\r[{bar}] {progress_pct:.1f}% | "
                  f"已爬取: {total:,} | "
                  f"当前: {current_cat} | "
                  f"速度: {speed:.1f}/s | "
                  f"耗时: {elapsed/60:.1f}min", end="", flush=True)

            await asyncio.sleep(10)  # 每 10 秒刷新一次

        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断，爬取任务仍在后台运行")
            print("   可以稍后重新运行此脚本继续监控")
            break
        except Exception as e:
            print(f"\n❌ 监控出错: {e}")
            await asyncio.sleep(10)


async def get_stats(client: httpx.AsyncClient, token: str):
    """获取商品库统计"""
    print("\n📈 商品库统计:")
    resp = await client.get(
        f"{API_BASE_URL}/api/library/stats",
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    data = resp.json()

    print(f"   总商品数: {data.get('total_products', 0):,}")
    print(f"   分类数: {data.get('categories', 0)}")
    print(f"   品牌数: {data.get('brands', 0)}")
    print(f"   隔离商品: {data.get('quarantined', 0)}")
    print(f"   最后更新: {data.get('last_updated', 'N/A')}")


async def main():
    print("=" * 60)
    print("🚀 ProfitLens v3 - Takealot 商品库爬取工具")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. 登录
        token = await login(client)

        # 2. 查看当前统计
        await get_stats(client, token)

        # 3. 启动爬取
        task_id = await start_scrape(client, token)
        if not task_id:
            return

        # 4. 监控进度
        await monitor_progress(client, token)

        # 5. 查看最终统计
        await get_stats(client, token)

    print("\n✅ 完成！")


if __name__ == "__main__":
    asyncio.run(main())
