#!/bin/bash
set -e

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/arxiv-classify"
ENV_FILE="$CONFIG_DIR/webui.env"

read -rsp "设置 Zotero 导入密码（至少 8 个字符）: " ARXIV_TOKEN_INPUT
echo
if [ "${#ARXIV_TOKEN_INPUT}" -lt 8 ]; then
    echo "错误：密码至少需要 8 个字符。" >&2
    exit 1
fi
case "$ARXIV_TOKEN_INPUT" in
    *$'\n'*) echo "错误：密码不能包含换行。" >&2; exit 1 ;;
esac

mkdir -p "$CONFIG_DIR"
umask 077
TEMP_FILE=$(mktemp "$CONFIG_DIR/.webui.env.XXXXXX")
if [ -f "$ENV_FILE" ]; then
    grep -v '^ARXIV_WEBUI_WRITE_TOKEN=' "$ENV_FILE" > "$TEMP_FILE" || true
fi
printf 'ARXIV_WEBUI_WRITE_TOKEN=%s\n' "$ARXIV_TOKEN_INPUT" >> "$TEMP_FILE"
mv "$TEMP_FILE" "$ENV_FILE"
chmod 600 "$ENV_FILE"
unset ARXIV_TOKEN_INPUT

echo "密码已保存到 $ENV_FILE"
echo "请重启 WebUI；已有认证会话会立即失效。"
