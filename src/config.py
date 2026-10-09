"""Runtime configuration loaded from environment variables or a local .env file.

Copy ``.env.example`` to ``.env`` and fill in only the services you use.
The real ``.env`` file is ignored by Git.
"""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_local_env():
    env_file = ROOT / '.env'
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_local_env()

API_PROVIDER = os.getenv('API_PROVIDER', 'deepseek')

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')

KIMI_API_KEY = os.getenv('KIMI_API_KEY', '')
KIMI_BASE_URL = os.getenv('KIMI_BASE_URL', 'https://api.moonshot.cn/v1')
KIMI_MODEL = os.getenv('KIMI_MODEL', 'moonshot-v1-128k')

EMAIL_USER = os.getenv('EMAIL_USER', '')
EMAIL_PASS = os.getenv('EMAIL_PASS', '')
ARXIV_MAIL_FOLDER = os.getenv('ARXIV_MAIL_FOLDER', 'INBOX')

WECHAT_APPID = os.getenv('WECHAT_APPID', '')
WECHAT_SECRET = os.getenv('WECHAT_SECRET', '')
WECHAT_THUMB_MEDIA_ID = os.getenv('WECHAT_THUMB_MEDIA_ID', '')
WECHAT_AUTHOR = os.getenv('WECHAT_AUTHOR', 'Arxiv Classify')
