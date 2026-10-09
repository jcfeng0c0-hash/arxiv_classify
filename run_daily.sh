#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [[ -n "${ARXIV_PYTHON:-}" && -x "$ARXIV_PYTHON" ]]; then
    PYTHON_BIN="$ARXIV_PYTHON"
elif [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
else
    echo "错误：未找到 Python 3。" >&2
    exit 1
fi

if [[ "$#" -eq 0 ]]; then
    set -- --all
fi

if command -v flock >/dev/null 2>&1; then
    exec flock -n "$PROJECT_DIR/.daily.lock" "$PYTHON_BIN" "$PROJECT_DIR/__main__.py" "$@"
fi
exec "$PYTHON_BIN" "$PROJECT_DIR/__main__.py" "$@"
