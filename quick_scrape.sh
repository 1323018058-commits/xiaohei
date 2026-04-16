#!/bin/bash
# 快速启动 Takealot 商品库爬取
# 用法: ./quick_scrape.sh

set -e

echo "🚀 ProfitLens v3 - 快速启动商品库爬取"
echo "=========================================="

# 配置
API_BASE="http://localhost:8000"
USERNAME="your_email@example.com"  # 修改为你的账号
PASSWORD="your_password"           # 修改为你的密码

# 1. 登录获取 token
echo "🔐 正在登录..."
TOKEN=$(curl -s -X POST "$API_BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
  | jq -r '.access_token')

if [ "$TOKEN" = "null" ] || [ -z "$TOKEN" ]; then
  echo "❌ 登录失败，请检查账号密码"
  exit 1
fi

echo "✅ 登录成功！"

# 2. 启动爬取（全站爬取，不限制数量）
echo ""
echo "🚀 正在启动全站爬取..."
RESPONSE=$(curl -s -X POST "$API_BASE/api/library/scrape/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "lead_min": 0,
    "lead_max": 999,
    "price_min": 0,
    "price_max": 100000,
    "max_per_cat": 0,
    "categories": null
  }')

echo "$RESPONSE" | jq '.'

if echo "$RESPONSE" | jq -e '.ok' > /dev/null; then
  TASK_ID=$(echo "$RESPONSE" | jq -r '.task_id')
  echo ""
  echo "✅ 爬取任务已启动！"
  echo "   Task ID: $TASK_ID"
  echo ""
  echo "📊 监控进度："
  echo "   方法1: 访问前端 http://localhost:5173 查看实时进度"
  echo "   方法2: 访问 Flower http://localhost:5555 查看 Celery 任务"
  echo "   方法3: 运行 python start_library_scrape.py 监控进度"
  echo ""
  echo "⏱️  预计耗时: 根据网络速度，全站爬取可能需要 6-12 小时"
  echo "💡 提示: 爬取任务在后台运行，你可以关闭此窗口"
else
  ERROR=$(echo "$RESPONSE" | jq -r '.error // "未知错误"')
  echo "❌ 启动失败: $ERROR"
  exit 1
fi
