# =============================================================================
# API Keys & Credentials Configuration
# All sensitive keys and credentials are managed here.
# =============================================================================

# ── Inference Mode ────────────────────────────────────────────────────────────
# True  = use DeepSeek online API (requires DEEPSEEK_API_KEY)
# False = use local Ollama (requires Ollama running at localhost:11434)
USE_API = True

# ── DeepSeek API ──────────────────────────────────────────────────────────────
# Get your API key from: https://platform.deepseek.com
DEEPSEEK_API_KEY = "sk-your-deepseek-api-key-here"

# ── Email (QQ Mail) ───────────────────────────────────────────────────────────
# For fetching arXiv daily mailing emails via IMAP and sending summaries via SMTP.
# EMAIL_PASS should be the QQ Mail authorization code, NOT your login password.
EMAIL_USER = "your_qq@qq.com"
EMAIL_PASS = "your_qq_auth_code"

# ── WeChat Public Account ─────────────────────────────────────────────────────
# Optional: used only if you call --send-gzh.
# Get these from https://mp.weixin.qq.com
WECHAT_APPID = "your-wechat-appid"
WECHAT_SECRET = "your-wechat-secret"
# Upload a cover image via WeChat API first, then paste its media_id here.
WECHAT_THUMB_MEDIA_ID = "your-thumb-media-id"
