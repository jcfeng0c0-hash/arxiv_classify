"""Content-keyed inference cache and actual per-request token accounting."""
import hashlib
import json
import logging
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / 'downloads' / 'inference_cache'
USAGE_PATH = ROOT / 'logs' / 'model_usage.jsonl'
_usage_lock = threading.Lock()


def cache_key(task, provider, model, content):
    serialized = json.dumps([task, provider, model, content], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def read_cache(key):
    try:
        value = json.loads((CACHE_DIR / f'{key}.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def write_cache(key, value):
    # An unavailable cache must not turn a successful paid response into a retry.
    temporary = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=CACHE_DIR,
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False)
        temporary.replace(CACHE_DIR / f'{key}.json')
    except OSError:
        logging.exception('Could not persist inference cache')
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def record_usage(provider, model, task, usage, paper_id=None):
    if usage is None:
        data = None
    elif hasattr(usage, 'model_dump'):
        data = usage.model_dump()
    elif isinstance(usage, dict):
        data = usage
    else:
        data = {name: getattr(usage, name, None)
                for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    entry = {'timestamp': datetime.now(timezone.utc).isoformat(), 'provider': provider,
             'model': model, 'task': task, 'paper_id': paper_id, 'usage': data}
    try:
        with _usage_lock:
            USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_PATH.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        logging.exception('Could not record model token usage')
