#!/usr/bin/env bash
# 一键启动 ArXiv WebUI 并通过 Cloudflare Tunnel 暴露公网地址
# Usage: ./start_webui_cloudflare.sh [start|stop|status|restart]

set -e

# 切换到脚本所在目录
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# 优先使用指定解释器或项目虚拟环境，再使用 PATH 中的 Python。
PYTHON_BIN="${ARXIV_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
        PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python)"
    fi
fi

WEBUI_LOG="./logs/webui.log"
TUNNEL_LOG="./logs/cloudflared.log"
ZOTERO_LOG="./logs/zotero.log"
PID_FILE="./.webui_tunnel.pid"
WEBUI_PORT=5000
ZOTERO_BIN="${ZOTERO_BIN:-}"
if [ -z "$ZOTERO_BIN" ] && command -v zotero >/dev/null 2>&1; then
    ZOTERO_BIN="$(command -v zotero)"
fi
ZOTERO_DISPLAY="${ZOTERO_DISPLAY:-:1}"

ensure_zotero() {
    if curl -fsS "http://127.0.0.1:23119/connector/ping" >/dev/null 2>&1; then
        echo "📚 Zotero 本地 API 已就绪"
        return 0
    fi
    if [ -z "$ZOTERO_BIN" ] || [ ! -x "$ZOTERO_BIN" ]; then
        echo "ℹ️  未配置 Zotero，跳过自动启动（不影响 WebUI）"
        return 0
    fi
    echo "📚 正在服务器图形会话 $ZOTERO_DISPLAY 启动 Zotero..."
    nohup env DISPLAY="$ZOTERO_DISPLAY" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" \
        "$ZOTERO_BIN" > "$ZOTERO_LOG" 2>&1 &
    for i in $(seq 1 40); do
        if curl -fsS "http://127.0.0.1:23119/connector/ping" >/dev/null 2>&1; then
            echo "   ✅ Zotero 本地 API 已就绪"
            return 0
        fi
        sleep 1
    done
    echo "⚠️  Zotero 启动超时；WebUI 将继续启动。日志: $ZOTERO_LOG"
    return 0
}

mkdir -p logs

# 获取 Tailscale 访问地址（IPv4 地址和 DNS 名称）
get_tailscale_info() {
    if ! command -v tailscale >/dev/null 2>&1; then
        return
    fi
    tailscale status --json 2>/dev/null | "$PYTHON_BIN" -c '
import json, sys
try:
    data = json.load(sys.stdin)
    ips = [ip for ip in data.get("TailscaleIPs", []) if ":" not in ip]
    dns = data.get("Self", {}).get("DNSName", "").rstrip(".")
    print("\n".join(ips))
    if dns:
        print("DNS:" + dns)
except Exception:
    pass
'
}

# 检查必要命令
check_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "❌ 错误: 未找到 $1，请先安装"
        exit 1
    fi
}

start() {
    # 检查是否已经在运行
    if [ -f "$PID_FILE" ]; then
        echo "⚠️  服务似乎已在运行"
        echo "   PID 文件: $PID_FILE"
        echo "   查看状态: $0 status"
        echo "   如需重启: $0 restart"
        exit 1
    fi

    if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
        echo "❌ 错误: 未找到 Python 3，请安装 Python，或设置 ARXIV_PYTHON=/完整路径/python"
        exit 1
    fi
    if ! "$PYTHON_BIN" -c 'import flask, sqlalchemy, openai, requests, bs4, PIL, fitz' >/dev/null 2>&1; then
        echo "❌ 缺少依赖，请运行: $PYTHON_BIN -m pip install -r requirements.txt"
        exit 1
    fi
    check_command cloudflared
    check_command curl

    # 检查 webui.py 是否存在
    if [ ! -f "webui.py" ]; then
        echo "❌ 错误: 在当前目录找不到 webui.py"
        echo "   请在项目根目录运行此脚本"
        exit 1
    fi

    echo "====================================="
    echo "🚀 启动 ArXiv WebUI + Cloudflare Tunnel"
    echo "====================================="
    echo ""

    ensure_zotero

    # 清理旧日志
    > "$WEBUI_LOG"
    > "$TUNNEL_LOG"

    # 启动 WebUI
    echo "🖥️  启动 WebUI (http://localhost:$WEBUI_PORT) ..."
    nohup env ARXIV_WEBUI_COOKIE_SECURE=true "$PYTHON_BIN" webui.py > "$WEBUI_LOG" 2>&1 &
    WEBUI_PID=$!
    echo "$WEBUI_PID" > "$PID_FILE"
    echo "   WebUI PID: $WEBUI_PID"

    # 等待 WebUI 启动
    echo "⏳ 等待 WebUI 就绪..."
    for i in $(seq 1 30); do
        if curl -s "http://localhost:$WEBUI_PORT" > /dev/null 2>&1; then
            echo "   ✅ WebUI 已就绪"
            break
        fi
        sleep 1
        if [ $i -eq 30 ]; then
            echo "   ❌ WebUI 启动超时，请查看日志: $WEBUI_LOG"
            stop
            exit 1
        fi
    done

    # 检测 Tailscale 网络地址
    TAILSCALE_INFO=$(get_tailscale_info)
    TAILSCALE_IPS=$(echo "$TAILSCALE_INFO" | grep -v '^DNS:' || true)
    TAILSCALE_DNS=$(echo "$TAILSCALE_INFO" | grep '^DNS:' | sed 's/^DNS://' || true)

    # 启动 Cloudflare Tunnel
    echo "🌐 启动 Cloudflare Tunnel..."
    nohup cloudflared tunnel --url "http://localhost:$WEBUI_PORT" > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    echo "$TUNNEL_PID" >> "$PID_FILE"
    echo "   Tunnel PID: $TUNNEL_PID"

    # 等待并提取公网 URL
    echo "⏳ 等待公网 URL 生成..."
    for i in $(seq 1 60); do
        URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1)
        if [ -n "$URL" ]; then
            echo ""
            echo "====================================="
            echo "✅ WebUI 已成功暴露到公网"
            echo "====================================="
            echo ""
            echo "🌍 公开访问地址 (Cloudflare):"
            echo "   $URL"
            echo ""
            if [ -n "$TAILSCALE_IPS" ] || [ -n "$TAILSCALE_DNS" ]; then
                echo "🔒 Tailscale 访问地址 (仅限同一 Tailnet):"
                if [ -n "$TAILSCALE_DNS" ]; then
                    echo "   http://$TAILSCALE_DNS:$WEBUI_PORT"
                fi
                for IP in $TAILSCALE_IPS; do
                    echo "   http://$IP:$WEBUI_PORT"
                done
                echo ""
            fi
            echo "🏠 本地访问地址:"
            echo "   http://localhost:$WEBUI_PORT"
            echo ""
            echo "📋 常用命令:"
            echo "   查看状态: $0 status"
            echo "   停止服务: $0 stop"
            echo "   重启服务: $0 restart"
            echo ""
            echo "📄 日志文件:"
            echo "   WebUI:   $WEBUI_LOG"
            echo "   Tunnel:  $TUNNEL_LOG"
            echo ""
            # 将 URL 保存到文件方便查看
            echo "$URL" > "./.cloudflare_url.txt"
            # 邮件失败不能触发 set -e 或停止已经运行的服务。
            if "$PYTHON_BIN" -m src.notify_tunnel "$URL"; then
                echo "📧 公网链接已发送到配置的收件邮箱"
            else
                echo "⚠️  邮件未发送成功；可运行 $PYTHON_BIN -m src.notify_tunnel 重试"
            fi
            exit 0
        fi
        sleep 1
    done

    echo "❌ 未能获取 Cloudflare URL，请查看日志: $TUNNEL_LOG"
    stop
    exit 1
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "ℹ️  没有运行中的服务"
        exit 0
    fi

    echo "🛑 停止服务..."
    while read -r PID; do
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            echo "   停止进程 $PID"
            kill "$PID" 2>/dev/null || true
        fi
    done < "$PID_FILE"

    # 等待进程退出
    sleep 2

    # 强制结束仍未退出的进程
    while read -r PID; do
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            echo "   强制结束进程 $PID"
            kill -9 "$PID" 2>/dev/null || true
        fi
    done < "$PID_FILE"

    rm -f "$PID_FILE" "./.cloudflare_url.txt"
    echo "✅ 服务已停止"
}

status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "ℹ️  没有运行中的服务"
        exit 0
    fi

    echo "====================================="
    echo "📊 服务状态"
    echo "====================================="
    echo ""
    echo "PID 列表:"
    while read -r PID; do
        if [ -n "$PID" ]; then
            if kill -0 "$PID" 2>/dev/null; then
                echo "   $PID ✅ 运行中"
            else
                echo "   $PID ❌ 已结束"
            fi
        fi
    done < "$PID_FILE"
    echo ""

    if curl -s "http://localhost:$WEBUI_PORT" > /dev/null 2>&1; then
        echo "🖥️  WebUI 本地访问: http://localhost:$WEBUI_PORT ✅"
    else
        echo "🖥️  WebUI 本地访问: http://localhost:$WEBUI_PORT ❌"
    fi

    if [ -f "./.cloudflare_url.txt" ]; then
        echo "🌍 公开访问地址: $(cat ./.cloudflare_url.txt)"
    else
        echo "🌍 公开访问地址: 获取中或尚未生成"
    fi

    TAILSCALE_INFO=$(get_tailscale_info)
    TAILSCALE_IPS=$(echo "$TAILSCALE_INFO" | grep -v '^DNS:' || true)
    TAILSCALE_DNS=$(echo "$TAILSCALE_INFO" | grep '^DNS:' | sed 's/^DNS://' || true)
    if [ -n "$TAILSCALE_IPS" ] || [ -n "$TAILSCALE_DNS" ]; then
        echo "🔒 Tailscale 访问地址 (仅限同一 Tailnet):"
        if [ -n "$TAILSCALE_DNS" ]; then
            echo "   http://$TAILSCALE_DNS:$WEBUI_PORT"
        fi
        for IP in $TAILSCALE_IPS; do
            echo "   http://$IP:$WEBUI_PORT"
        done
    fi
    echo ""
    echo "📄 日志文件:"
    echo "   WebUI:  $WEBUI_LOG"
    echo "   Tunnel: $TUNNEL_LOG"
}

restart() {
    stop
    sleep 2
    start
}

# 主入口
case "${1:-start}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    restart)
        restart
        ;;
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
