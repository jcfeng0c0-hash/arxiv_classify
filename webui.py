import os
import threading
import hashlib
import hmac
import secrets
import time
import re
from pathlib import Path
# Change to the directory where arxiv.db is located BEFORE importing models
os.chdir(os.path.dirname(os.path.abspath(__file__)))

PROJECT_DIR = Path(__file__).resolve().parent
USER_CONFIG_DIR = Path.home() / '.config' / 'arxiv-classify'
ENV_FILE = USER_CONFIG_DIR / 'webui.env'


def _load_user_env():
    """Load simple KEY=VALUE settings without adding a dotenv dependency."""
    for env_file in (ENV_FILE, PROJECT_DIR / '.env'):
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding='utf-8').splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith('#') or '=' not in raw_line:
                continue
            key, value = raw_line.split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def _load_or_create_session_secret():
    configured = os.environ.get('ARXIV_WEBUI_SESSION_SECRET')
    if configured:
        return configured
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = USER_CONFIG_DIR / 'session-secret'
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32) + '\n', encoding='utf-8')
        secret_file.chmod(0o600)
    return secret_file.read_text(encoding='utf-8').strip()


_load_user_env()

from src.models import init_db
init_db()
from migrate_db import migrate
migrate()

from flask import Flask, render_template, request, jsonify, session
from src.models import SessionLocal, Paper
from src.config import API_PROVIDER as _API_PROVIDER_DEFAULT
from src.classification_policy import VERSION
from src.paper_analysis import apply_analysis_result
from src.arxiv_zotero import ZoteroClient, import_arxiv_id
from src.paper_figures import FIGURE_DIR, cache_key, load_figures, ensure_figures, collect_interested_figures
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['APP_VERSION'] = VERSION
app.secret_key = _load_or_create_session_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('ARXIV_WEBUI_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes'),
)

# ─── Runtime settings (in-memory, initial values from config.py) ──────────────
_settings = {
    'api_provider': _API_PROVIDER_DEFAULT,
}

# ─── Download state (shared across requests) ─────────────────────────────────
_download_state = {
    'running': False,
    'total': 0,
    'done': 0,
    'failed': [],
    'succeeded': [],
    'zip_path': None,
    'zip_ready': False,
}
_download_lock = threading.Lock()

# ─── Analyze state (shared across requests) ───────────────────────────────────
_analyze_state = {
    'running': False,
    'total': 0,
    'done': 0,
    'failed': [],
    'succeeded': [],
}
_analyze_lock = threading.Lock()

# ─── Zotero import state ─────────────────────────────────────────────────────
_zotero_state = {
    'running': False, 'total': 0, 'done': 0, 'current': None,
    'current_status': '', 'task_error': None,
    'created': [], 'updated': [], 'skipped': [], 'failed': [],
}
_zotero_lock = threading.Lock()
_auth_failures = {}
_auth_lock = threading.Lock()

PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads', 'pdfs')
ZOTERO_AUTH_SECONDS = 2 * 60 * 60

def get_db_session():
    return SessionLocal()


def _write_token():
    return os.environ.get('ARXIV_WEBUI_WRITE_TOKEN', '')


def _token_fingerprint(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _zotero_authenticated():
    token = _write_token()
    authenticated_at = session.get('zotero_authenticated_at')
    if not token or not isinstance(authenticated_at, (int, float)):
        return False
    if time.time() - authenticated_at > ZOTERO_AUTH_SECONDS:
        session.pop('zotero_authenticated_at', None)
        session.pop('zotero_token_fingerprint', None)
        return False
    return hmac.compare_digest(
        session.get('zotero_token_fingerprint', ''), _token_fingerprint(token))


def _require_zotero_auth():
    if not _write_token():
        return jsonify({'success': False, 'error': '尚未配置 ARXIV_WEBUI_WRITE_TOKEN',
                        'code': 'not_configured'}), 503
    if not _zotero_authenticated():
        return jsonify({'success': False, 'error': '需要验证 Zotero 写入密码',
                        'code': 'auth_required'}), 401
    return None


# ─── Helper: build stats dict ─────────────────────────────────────────────────
def _build_stats(db):
    return {
        'total': db.query(Paper).count(),
        'analyzed': db.query(Paper).filter(Paper.my_label != None).count(),
        'interested': db.query(Paper).filter(Paper.my_label == 'interested').count(),
        'irrelevant': db.query(Paper).filter(Paper.my_label == 'irrelevant').count(),
        'unanalyzed': db.query(Paper).filter(Paper.my_label == None).count(),
        'important': db.query(Paper).filter(Paper.is_important_author == True).count(),
        'famous': db.query(Paper).filter(Paper.is_famous_author == True).count(),
        'read': db.query(Paper).filter(Paper.is_read == True).count(),
        'unread': db.query(Paper).filter(Paper.is_read == False).count(),
        'downloaded': db.query(Paper).filter(Paper.is_downloaded == True).count(),
        'content_analyzed': db.query(Paper).filter(Paper.is_content_analyzed == True).count(),
    }


# ─── Helper: build filtered/sorted query (shared by index and /api/papers) ────
def _build_query(db, args):
    search = args.get('search', '').strip()
    label_filter = args.get('label', 'all')
    important_filter = args.get('important', 'all')
    famous_filter = args.get('famous', 'all')
    read_filter = args.get('read', 'all')
    downloaded_filter = args.get('downloaded', 'all')
    content_analyzed_filter = args.get('content_analyzed', 'all')
    sort_by = args.get('sort', 'created_at')
    order = args.get('order', 'desc')

    query = db.query(Paper)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Paper.title.like(search_term)) |
            (Paper.authors.like(search_term)) |
            (Paper.arxiv_id.like(search_term)) |
            (Paper.abstract.like(search_term))
        )

    if label_filter == 'interested':
        query = query.filter(Paper.my_label == 'interested')
    elif label_filter == 'irrelevant':
        query = query.filter(Paper.my_label == 'irrelevant')
    elif label_filter == 'unanalyzed':
        query = query.filter(Paper.my_label == None)

    if important_filter == 'yes':
        query = query.filter(Paper.is_important_author == True)
    elif important_filter == 'no':
        query = query.filter(Paper.is_important_author == False)

    if famous_filter == 'yes':
        query = query.filter(Paper.is_famous_author == True)
    elif famous_filter == 'no':
        query = query.filter(Paper.is_famous_author == False)

    if read_filter == 'read':
        query = query.filter(Paper.is_read == True)
    elif read_filter == 'unread':
        query = query.filter(Paper.is_read == False)

    if downloaded_filter == 'yes':
        query = query.filter(Paper.is_downloaded == True)
    elif downloaded_filter == 'no':
        query = query.filter(Paper.is_downloaded == False)

    if content_analyzed_filter == 'yes':
        query = query.filter(Paper.is_content_analyzed == True)
    elif content_analyzed_filter == 'no':
        query = query.filter(Paper.is_content_analyzed == False)

    if sort_by == 'title':
        order_by = Paper.title.asc() if order == 'asc' else Paper.title.desc()
    elif sort_by == 'arxiv_id':
        order_by = Paper.arxiv_id.asc() if order == 'asc' else Paper.arxiv_id.desc()
    else:
        order_by = Paper.created_at.desc() if order == 'desc' else Paper.created_at.asc()

    query = query.order_by(order_by)
    return query


# ─── Helper: serialize a Paper for JSON APIs ──────────────────────────────────
def _paper_to_dict(p):
    return {
        'arxiv_id': p.arxiv_id,
        'title': p.title,
        'authors': p.authors,
        'category': p.category,
        'keywords_cn': p.keywords_cn,
        'summary_cn': p.summary_cn,
        'abstract': p.abstract,
        'version': p.version or 1,
        'publish_date': p.publish_date,
        'created_at': p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else None,
        'url': p.url,
        'is_read': bool(p.is_read),
        'is_important_author': bool(p.is_important_author),
        'is_famous_author': bool(p.is_famous_author),
        'my_label': p.my_label,
    }


# ─── Main page ────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    db = get_db_session()

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = _build_query(db, request.args)
    total = query.count()
    papers = query.offset((page - 1) * per_page).limit(per_page).all()

    stats = _build_stats(db)
    db.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template('index.html',
                           papers=papers,
                           page=page,
                           per_page=per_page,
                           total=total,
                           total_pages=total_pages,
                           search=request.args.get('search', '').strip(),
                           label_filter=request.args.get('label', 'all'),
                           important_filter=request.args.get('important', 'all'),
                           famous_filter=request.args.get('famous', 'all'),
                           read_filter=request.args.get('read', 'all'),
                           downloaded_filter=request.args.get('downloaded', 'all'),
                           content_analyzed_filter=request.args.get('content_analyzed', 'all'),
                           sort_by=request.args.get('sort', 'created_at'),
                           order=request.args.get('order', 'desc'),
                           stats=stats)


# ─── Papers JSON API (used by card view) ──────────────────────────────────────
@app.route('/api/papers')
def api_papers():
    db = get_db_session()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(max(per_page, 1), 100)

    query = _build_query(db, request.args)
    total = query.count()
    papers = query.offset((page - 1) * per_page).limit(per_page).all()
    result = [_paper_to_dict(p) for p in papers]
    db.close()

    total_pages = (total + per_page - 1) // per_page
    return jsonify({'papers': result, 'page': page, 'per_page': per_page,
                    'total': total, 'total_pages': total_pages})


# ─── Review action (card view): mark read + set/unset important ───────────────
@app.route('/api/paper/<path:arxiv_id>/review', methods=['POST'])
def review_paper(arxiv_id):
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('important', 'dismiss'):
        return jsonify({'success': False, 'error': 'action must be "important" or "dismiss"'}), 400

    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_read = True
    paper.reviewed_at = datetime.now()
    paper.is_important_author = (action == 'important')
    db.commit()
    new_status = paper.is_important_author
    db.close()
    return jsonify({'success': True, 'is_read': True, 'is_important': new_status})


@app.route('/paper/<path:arxiv_id>')
def paper_detail(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    db.close()
    if not paper:
        return "Paper not found", 404
    figures = load_figures(paper.arxiv_id, paper.version or 1) if paper.my_label == 'interested' else None
    return render_template('detail.html', paper=paper, figure_preview=figures)


_figure_jobs = set()
_figure_lock = threading.Lock()


@app.route('/api/paper/<path:arxiv_id>/figures', methods=['GET', 'POST'])
def paper_figures(arxiv_id):
    db = get_db_session()
    try:
        paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
        if not paper:
            return jsonify({'error': 'Paper not found'}), 404
        if paper.my_label != 'interested':
            return jsonify({'error': '仅提取 interested 论文的图片'}), 400
        version = paper.version or 1
    finally:
        db.close()
    key = cache_key(arxiv_id, version)
    if request.method == 'POST':
        with _figure_lock:
            if key not in _figure_jobs:
                _figure_jobs.add(key)
                def worker():
                    try:
                        ensure_figures(arxiv_id, version)
                    finally:
                        with _figure_lock:
                            _figure_jobs.discard(key)
                threading.Thread(target=worker, daemon=True).start()
        return jsonify({'success': True, 'running': True}), 202
    result = load_figures(arxiv_id, version)
    with _figure_lock:
        result['running'] = key in _figure_jobs
    return jsonify(result)


@app.route('/figures/<key>/<filename>')
def serve_figure(key, filename):
    from flask import abort, send_from_directory
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+v\d+', key) or not re.fullmatch(r'figure-\d+-\d+\.png', filename):
        abort(404)
    return send_from_directory(FIGURE_DIR / key, filename, mimetype='image/png')


# ─── Stats API ────────────────────────────────────────────────────────────────
@app.route('/api/stats')
def api_stats():
    db = get_db_session()
    stats = _build_stats(db)
    db.close()
    return jsonify(stats)


# ─── Zotero write authentication ─────────────────────────────────────────────
@app.route('/api/zotero/auth/status')
def zotero_auth_status():
    return jsonify({'configured': bool(_write_token()),
                    'authenticated': _zotero_authenticated(),
                    'expires_in': max(0, int(ZOTERO_AUTH_SECONDS -
                                      (time.time() - session.get('zotero_authenticated_at', 0))))
                    if _zotero_authenticated() else 0})


@app.route('/api/zotero/auth', methods=['POST'])
def zotero_authenticate():
    token = _write_token()
    if not token:
        return jsonify({'success': False, 'error': '尚未配置写入密码',
                        'code': 'not_configured'}), 503
    client = request.remote_addr or 'unknown'
    now = time.time()
    with _auth_lock:
        attempts = [stamp for stamp in _auth_failures.get(client, []) if now - stamp < 300]
        _auth_failures[client] = attempts
        if len(attempts) >= 5:
            return jsonify({'success': False, 'error': '密码错误次数过多，请 5 分钟后再试'}), 429
    supplied = str((request.get_json(silent=True) or {}).get('password', ''))
    if not hmac.compare_digest(supplied, token):
        with _auth_lock:
            _auth_failures.setdefault(client, []).append(now)
        return jsonify({'success': False, 'error': '密码错误'}), 403
    with _auth_lock:
        _auth_failures.pop(client, None)
    session.clear()
    session.permanent = False
    session['zotero_authenticated_at'] = now
    session['zotero_token_fingerprint'] = _token_fingerprint(token)
    return jsonify({'success': True, 'expires_in': ZOTERO_AUTH_SECONDS})


@app.route('/api/zotero/auth/logout', methods=['POST'])
def zotero_auth_logout():
    session.clear()
    return jsonify({'success': True})


# ─── Toggle read ──────────────────────────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/toggle_read', methods=['POST'])
def toggle_read(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_read = not paper.is_read
    paper.reviewed_at = datetime.now() if paper.is_read else None
    db.commit()
    new_status = paper.is_read
    db.close()
    return jsonify({'success': True, 'is_read': new_status})


# ─── Toggle important ─────────────────────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/toggle_important', methods=['POST'])
def toggle_important(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_important_author = not paper.is_important_author
    if paper.is_important_author and not paper.my_label:
        paper.my_label = 'interested'
    db.commit()
    new_status = paper.is_important_author
    db.close()
    return jsonify({'success': True, 'is_important': new_status})


# ─── Mark important (always set true, used by batch) ──────────────────────────
@app.route('/api/paper/<arxiv_id>/mark_important', methods=['POST'])
def mark_important(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_important_author = True
    if not paper.my_label:
        paper.my_label = 'interested'
    db.commit()
    db.close()
    return jsonify({'success': True, 'message': 'Paper marked as important'})


# ─── Toggle famous ────────────────────────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/toggle_famous', methods=['POST'])
def toggle_famous(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_famous_author = not paper.is_famous_author
    db.commit()
    new_status = paper.is_famous_author
    db.close()
    return jsonify({'success': True, 'is_famous': new_status})


# ─── Toggle downloaded ────────────────────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/toggle_downloaded', methods=['POST'])
def toggle_downloaded(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_downloaded = not paper.is_downloaded
    db.commit()
    new_status = paper.is_downloaded
    db.close()
    return jsonify({'success': True, 'is_downloaded': new_status})


# ─── Toggle content analyzed ──────────────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/toggle_content_analyzed', methods=['POST'])
def toggle_content_analyzed(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_content_analyzed = not paper.is_content_analyzed
    db.commit()
    new_status = paper.is_content_analyzed
    db.close()
    return jsonify({'success': True, 'is_content_analyzed': new_status})


# ─── Save notes ───────────────────────────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/notes', methods=['POST'])
def save_notes(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    data = request.get_json(silent=True) or {}
    paper.notes = data.get('notes', '')
    db.commit()
    db.close()
    return jsonify({'success': True})


# ─── Settings API ──────────────────────────────────────────────────────────────
VALID_PROVIDERS = {'local', 'deepseek', 'kimi'}

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(_settings)

@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.get_json(silent=True) or {}
    if 'api_provider' in data:
        provider = data['api_provider']
        if provider in VALID_PROVIDERS:
            _settings['api_provider'] = provider
    elif 'use_api' in data:
        # Backward compatibility: True -> deepseek, False -> local
        _settings['api_provider'] = 'deepseek' if bool(data['use_api']) else 'local'
    return jsonify({'success': True, 'settings': _settings})


# ─── On-demand structured analysis ───────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/analyze', methods=['POST'])
def analyze_paper(arxiv_id):
    """Run structured analysis for a single paper (from its abstract) and save results."""
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    if not paper.abstract:
        db.close()
        return jsonify({'success': False, 'error': 'No abstract available for analysis'}), 400

    try:
        from src.model_inference import analyze_paper_relevance, identify_famous_authors
        # Use global setting; request body can still override if explicitly provided
        req_data = request.get_json(silent=True) or {}
        api_provider = req_data.get('api_provider', _settings['api_provider'])

        paper_dict = {
            'id': paper.arxiv_id,
            'Title': paper.title or '',
            'Abstract': paper.abstract,
            'Authors': paper.authors or '',
        }
        result = analyze_paper_relevance(paper_dict, api_provider=api_provider)

        if 'error' in result:
            db.close()
            return jsonify({'success': False, 'error': result['error']}), 500

        apply_analysis_result(paper, result)

        # 识别知名教授并高亮（与 important 标签独立）
        famous_result = identify_famous_authors(paper.authors or '', api_provider=api_provider)
        if famous_result.get('has_famous_author', False):
            paper.is_famous_author = True
            paper.famous_authors = ', '.join(famous_result.get('famous_authors', []))
        else:
            paper.is_famous_author = False
            paper.famous_authors = None

        db.commit()
        collect_interested_figures([paper])
        db.close()
        return jsonify({'success': True})

    except Exception as e:
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── Batch download ───────────────────────────────────────────────────────────
def _do_batch_download(arxiv_ids):
    """Background thread: download PDFs, update DB, and create zip archive."""
    import requests as req
    import zipfile
    from datetime import datetime

    os.makedirs(PDF_DIR, exist_ok=True)

    with _download_lock:
        _download_state.update({
            'running': True,
            'total': len(arxiv_ids),
            'done': 0,
            'failed': [],
            'succeeded': [],
            'zip_path': None,
            'zip_ready': False,
        })

    for arxiv_id in arxiv_ids:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        pdf_path = os.path.join(PDF_DIR, f"{arxiv_id}.pdf")
        try:
            resp = req.get(pdf_url, timeout=60, stream=True)
            resp.raise_for_status()
            with open(pdf_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            # Mark as downloaded in DB
            db = get_db_session()
            paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
            if paper:
                paper.is_downloaded = True
                db.commit()
            db.close()
            with _download_lock:
                _download_state['succeeded'].append(arxiv_id)
        except Exception as e:
            with _download_lock:
                _download_state['failed'].append({'arxiv_id': arxiv_id, 'error': str(e)})
        finally:
            with _download_lock:
                _download_state['done'] += 1

    # Create zip archive of all successfully downloaded PDFs
    with _download_lock:
        succeeded = list(_download_state['succeeded'])

    if succeeded:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f"arxiv_papers_{timestamp}.zip"
        zip_path = os.path.join(PDF_DIR, '..', zip_filename)
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for arxiv_id in succeeded:
                    pdf_path = os.path.join(PDF_DIR, f"{arxiv_id}.pdf")
                    if os.path.exists(pdf_path):
                        zf.write(pdf_path, os.path.basename(pdf_path))
            with _download_lock:
                _download_state['zip_path'] = zip_path
                _download_state['zip_ready'] = True
        except Exception as e:
            print(f"Error creating zip archive: {e}")

    with _download_lock:
        _download_state['running'] = False


@app.route('/api/batch/download', methods=['POST'])
def batch_download():
    data = request.get_json(force=True) or {}
    arxiv_ids = data.get('arxiv_ids', [])
    if not arxiv_ids:
        return jsonify({'success': False, 'error': 'No arxiv_ids provided'}), 400

    with _download_lock:
        if _download_state['running']:
            return jsonify({'success': False, 'error': 'A download task is already running'}), 409

    thread = threading.Thread(target=_do_batch_download, args=(arxiv_ids,), daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': f'Started downloading {len(arxiv_ids)} papers', 'total': len(arxiv_ids)})


@app.route('/api/download/status')
def download_status():
    with _download_lock:
        state = dict(_download_state)
    return jsonify(state)


@app.route('/api/download/zip')
def download_zip():
    """Download the prepared zip archive of PDFs."""
    with _download_lock:
        zip_path = _download_state.get('zip_path')
        zip_ready = _download_state.get('zip_ready', False)

    if not zip_ready or not zip_path or not os.path.exists(zip_path):
        return jsonify({'success': False, 'error': 'No zip file available. Please run batch download first.'}), 404

    from flask import send_file
    return send_file(zip_path, as_attachment=True, download_name=os.path.basename(zip_path))


# ─── Batch mark read ──────────────────────────────────────────────────────────
@app.route('/api/batch/mark_read', methods=['POST'])
def batch_mark_read():
    data = request.get_json(force=True) or {}
    arxiv_ids = data.get('arxiv_ids', [])
    if not arxiv_ids:
        return jsonify({'success': False, 'error': 'No arxiv_ids provided'}), 400

    db = get_db_session()
    updated = 0
    for arxiv_id in arxiv_ids:
        paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
        if paper:
            paper.is_read = True
            paper.reviewed_at = datetime.now()
            updated += 1
    db.commit()
    db.close()
    return jsonify({'success': True, 'updated': updated})


# ─── Batch analyze ────────────────────────────────────────────────────────────
def _do_batch_analyze(arxiv_ids, api_provider):
    """Background thread: analyze papers one by one and update DB."""
    from src.model_inference import analyze_paper_relevance, identify_famous_authors

    with _analyze_lock:
        _analyze_state.update({
            'running': True,
            'total': len(arxiv_ids),
            'done': 0,
            'failed': [],
            'succeeded': [],
        })

    for arxiv_id in arxiv_ids:
        db = None
        try:
            db = get_db_session()
            paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
            if not paper or not paper.abstract:
                with _analyze_lock:
                    _analyze_state['failed'].append({'arxiv_id': arxiv_id, 'error': 'No abstract'})
                db.close()
                continue

            paper_dict = {
                'id': paper.arxiv_id,
                'Title': paper.title or '',
                'Abstract': paper.abstract,
                'Authors': paper.authors or '',
            }
            result = analyze_paper_relevance(paper_dict, api_provider=api_provider)

            if 'error' in result:
                with _analyze_lock:
                    _analyze_state['failed'].append({'arxiv_id': arxiv_id, 'error': result['error']})
            else:
                apply_analysis_result(paper, result)
                # 识别知名教授并高亮（与 important 标签独立）
                famous_result = identify_famous_authors(paper.authors or '', api_provider=api_provider)
                if famous_result.get('has_famous_author', False):
                    paper.is_famous_author = True
                    paper.famous_authors = ', '.join(famous_result.get('famous_authors', []))
                else:
                    paper.is_famous_author = False
                    paper.famous_authors = None
                db.commit()
                collect_interested_figures([paper])
                with _analyze_lock:
                    _analyze_state['succeeded'].append(arxiv_id)
            db.close()
        except Exception as e:
            with _analyze_lock:
                _analyze_state['failed'].append({'arxiv_id': arxiv_id, 'error': str(e)})
            if db:
                try:
                    db.close()
                except Exception:
                    pass
        finally:
            with _analyze_lock:
                _analyze_state['done'] += 1

    with _analyze_lock:
        _analyze_state['running'] = False


@app.route('/api/batch/analyze', methods=['POST'])
def batch_analyze():
    data = request.get_json(force=True) or {}
    arxiv_ids = data.get('arxiv_ids', [])
    if not arxiv_ids:
        return jsonify({'success': False, 'error': 'No arxiv_ids provided'}), 400

    with _analyze_lock:
        if _analyze_state['running']:
            return jsonify({'success': False, 'error': 'An analyze task is already running'}), 409

    api_provider = data.get('api_provider', _settings['api_provider'])
    if api_provider not in VALID_PROVIDERS:
        api_provider = _settings['api_provider']
    thread = threading.Thread(target=_do_batch_analyze, args=(arxiv_ids, api_provider), daemon=True)
    thread.start()
    return jsonify({'success': True, 'message': f'Started analyzing {len(arxiv_ids)} papers', 'total': len(arxiv_ids)})


@app.route('/api/analyze/status')
def analyze_status():
    with _analyze_lock:
        state = dict(_analyze_state)
    return jsonify(state)


# ─── arXiv → Zotero background import ────────────────────────────────────────
def _today_important_papers():
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    db = get_db_session()
    try:
        return db.query(Paper).filter(
            Paper.is_read == True,
            Paper.is_important_author == True,
            Paper.reviewed_at >= start,
            Paper.reviewed_at < end,
        ).order_by(Paper.reviewed_at.asc()).all()
    finally:
        db.close()


def _set_zotero_progress(arxiv_id, message):
    with _zotero_lock:
        _zotero_state['current'] = arxiv_id
        _zotero_state['current_status'] = message


def _do_zotero_import(arxiv_ids):
    with _zotero_lock:
        _zotero_state.update({
            'running': True, 'total': len(arxiv_ids), 'done': 0, 'current': None,
            'current_status': '准备连接 Zotero', 'task_error': None,
            'created': [], 'updated': [],
            'skipped': [], 'failed': [],
        })
    zotero = ZoteroClient()
    cache_dir = Path(PDF_DIR)
    try:
        zotero.connect()
    except Exception as exc:
        message = str(exc)
        with _zotero_lock:
            _zotero_state['task_error'] = message
            _zotero_state['failed'] = [
                {'arxiv_id': arxiv_id, 'error': 'Zotero 服务不可用，任务未开始'}
                for arxiv_id in arxiv_ids
            ]
            _zotero_state['done'] = len(arxiv_ids)
            _zotero_state['running'] = False
            _zotero_state['current_status'] = 'Zotero 服务不可用'
        return
    for arxiv_id in arxiv_ids:
        try:
            result = import_arxiv_id(
                arxiv_id, cache_dir, zotero,
                progress=lambda message, aid=arxiv_id: _set_zotero_progress(aid, message))
            bucket = result.get('status', 'failed')
            with _zotero_lock:
                _zotero_state.setdefault(bucket, []).append(result)
            if bucket in ('created', 'updated'):
                match = re.search(r'v(\d+)$', result.get('arxiv_id', ''))
                db = get_db_session()
                try:
                    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
                    if paper:
                        paper.is_downloaded = True
                        if match:
                            paper.version = int(match.group(1))
                        db.commit()
                finally:
                    db.close()
        except Exception as exc:
            with _zotero_lock:
                _zotero_state['failed'].append({'arxiv_id': arxiv_id, 'error': str(exc)})
        finally:
            with _zotero_lock:
                _zotero_state['done'] += 1
    with _zotero_lock:
        _zotero_state['running'] = False
        _zotero_state['current'] = None
        _zotero_state['current_status'] = '完成'


def _start_zotero_task(arxiv_ids):
    unique_ids = list(dict.fromkeys(str(value).strip() for value in arxiv_ids if str(value).strip()))
    if not unique_ids:
        return jsonify({'success': False, 'error': '没有待导入论文'}), 400
    if len(unique_ids) > 200:
        return jsonify({'success': False, 'error': '单次最多导入 200 篇论文'}), 400
    db = get_db_session()
    try:
        existing_ids = {row[0] for row in db.query(Paper.arxiv_id).filter(Paper.arxiv_id.in_(unique_ids)).all()}
    finally:
        db.close()
    missing = [value for value in unique_ids if value not in existing_ids]
    if missing:
        return jsonify({'success': False, 'error': '数据库中找不到以下论文', 'missing': missing}), 404
    with _zotero_lock:
        if _zotero_state['running']:
            return jsonify({'success': False, 'error': '已有 Zotero 导入任务正在运行'}), 409
        _zotero_state['running'] = True
    thread = threading.Thread(target=_do_zotero_import, args=(unique_ids,), daemon=True)
    thread.start()
    return jsonify({'success': True, 'total': len(unique_ids)})


@app.route('/api/zotero/today-important')
def zotero_today_important():
    papers = _today_important_papers()
    return jsonify({'papers': [
        {'arxiv_id': paper.arxiv_id, 'title': paper.title,
         'reviewed_at': paper.reviewed_at.strftime('%Y-%m-%d %H:%M') if paper.reviewed_at else None}
        for paper in papers
    ], 'total': len(papers)})


@app.route('/api/zotero/import', methods=['POST'])
def zotero_import():
    denied = _require_zotero_auth()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    return _start_zotero_task(data.get('arxiv_ids', []))


@app.route('/api/zotero/import/today-important', methods=['POST'])
def zotero_import_today_important():
    denied = _require_zotero_auth()
    if denied:
        return denied
    return _start_zotero_task([paper.arxiv_id for paper in _today_important_papers()])


@app.route('/api/zotero/import/retry', methods=['POST'])
def zotero_import_retry():
    denied = _require_zotero_auth()
    if denied:
        return denied
    with _zotero_lock:
        failed_ids = [row['arxiv_id'] for row in _zotero_state['failed']]
    return _start_zotero_task(failed_ids)


@app.route('/api/zotero/import/status')
def zotero_import_status():
    with _zotero_lock:
        state = {
            key: ([dict(item) for item in value] if isinstance(value, list) else value)
            for key, value in _zotero_state.items()
        }
    return jsonify(state)


# ─── Serve local PDF ──────────────────────────────────────────────────────────
@app.route('/pdf/<path:arxiv_id>')
def serve_pdf(arxiv_id):
    from flask import send_from_directory, abort
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    db.close()
    if not paper or not paper.is_downloaded:
        abort(404)
    pdf_filename = f"{arxiv_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)
    if not os.path.isfile(pdf_path):
        abort(404)
    return send_from_directory(PDF_DIR, pdf_filename, mimetype='application/pdf')


if __name__ == '__main__':
    debug_mode = os.environ.get('ARXIV_WEBUI_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
