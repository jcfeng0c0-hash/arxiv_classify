#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

choose_python() {
    if [[ -n "${ARXIV_PYTHON:-}" && -x "$ARXIV_PYTHON" ]]; then
        printf '%s\n' "$ARXIV_PYTHON"
    elif [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
        printf '%s\n' "$PROJECT_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    elif command -v python >/dev/null 2>&1; then
        command -v python
    else
        return 1
    fi
}

PYTHON_BIN="$(choose_python)" || {
    echo "错误：未找到 Python 3。请安装 Python，或设置 ARXIV_PYTHON。" >&2
    exit 1
}

if ! "$PYTHON_BIN" -c 'import flask, sqlalchemy, openai, requests, bs4, PIL, fitz' >/dev/null 2>&1; then
    echo "缺少依赖。请先运行：$PYTHON_BIN -m pip install -r requirements.txt" >&2
    exit 1
fi

if [[ ! -f .env ]]; then
    echo "提示：尚未创建 .env。WebUI 可以启动，但在线分析前请复制 .env.example 并填写 API Key。"
fi

echo "启动 ArXiv Paper Database: http://127.0.0.1:5000"
exec "$PYTHON_BIN" webui.py
