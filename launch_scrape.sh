#!/bin/bash
# ProfitLens v3 - 一键启动增强版爬取系统
# 使用方法: ./launch_scrape.sh

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   ProfitLens v3 - 增强版商品库爬取系统                        ║"
echo "║   Takealot 900万商品全站爬取                                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目路径
PROJECT_DIR="/Users/Apple/Projects/profitlens-v3"
DOCKER_DIR="$PROJECT_DIR/docker"
SCRIPT_PATH="$PROJECT_DIR/enhanced_scrape_monitor.py"

# 步骤 1: 检查 Docker 服务
echo -e "${BLUE}[1/5]${NC} 检查 Docker 服务状态..."
cd "$DOCKER_DIR"

if ! docker-compose ps | grep -q "Up"; then
    echo -e "${YELLOW}⚠️  Docker 服务未运行，正在启动...${NC}"
    docker-compose up -d
    echo -e "${GREEN}✅ Docker 服务已启动${NC}"
    echo "   等待服务初始化（30秒）..."
    sleep 30
else
    echo -e "${GREEN}✅ Docker 服务运行正常${NC}"
fi

# 步骤 2: 检查必要服务
echo ""
echo -e "${BLUE}[2/5]${NC} 检查必要服务..."

REQUIRED_SERVICES=("postgres" "redis" "backend" "celery-worker-default" "celery-beat")
ALL_OK=true

for service in "${REQUIRED_SERVICES[@]}"; do
    if docker-compose ps | grep "$service" | grep -q "Up"; then
        echo -e "   ${GREEN}✅${NC} $service"
    else
        echo -e "   ${RED}❌${NC} $service"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    echo -e "${RED}❌ 部分服务未运行，请检查 Docker 日志${NC}"
    echo "   运行: docker-compose logs"
    exit 1
fi

# 步骤 3: 检查 Python 脚本
echo ""
echo -e "${BLUE}[3/5]${NC} 检查监控脚本..."

if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${RED}❌ 找不到监控脚本: $SCRIPT_PATH${NC}"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/agent_supervisor.py" ]; then
    echo -e "${RED}❌ 找不到 Agent 监督系统: $PROJECT_DIR/agent_supervisor.py${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 监控脚本就绪${NC}"

# 步骤 4: 检查配置
echo ""
echo -e "${BLUE}[4/5]${NC} 检查配置..."

if grep -q "your_email@example.com" "$SCRIPT_PATH"; then
    echo -e "${YELLOW}⚠️  检测到默认配置，需要修改账号密码${NC}"
    echo ""
    read -p "请输入你的账号邮箱: " username
    read -sp "请输入你的密码: " password
    echo ""

    # 使用 sed 替换配置（macOS 兼容）
    sed -i '' "s/your_email@example.com/$username/g" "$SCRIPT_PATH"
    sed -i '' "s/your_password/$password/g" "$SCRIPT_PATH"

    echo -e "${GREEN}✅ 配置已更新${NC}"
else
    echo -e "${GREEN}✅ 配置已就绪${NC}"
fi

# 步骤 5: 启动监控
echo ""
echo -e "${BLUE}[5/5]${NC} 启动增强版监控系统..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd "$PROJECT_DIR"

# 检查是否安装了 httpx
if ! python3 -c "import httpx" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  缺少依赖库，正在安装...${NC}"
    pip3 install httpx
fi

# 启动监控
python3 "$SCRIPT_PATH"

# 脚本结束
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ 监控系统已退出${NC}"
echo ""
echo "💡 提示:"
echo "   - 查看日志: tail -f $PROJECT_DIR/scrape_monitor.log"
echo "   - 查看进度: http://localhost:5173"
echo "   - Celery 监控: http://localhost:5555"
echo ""
