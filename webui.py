import os
import threading
# Change to the directory where arxiv.db is located BEFORE importing models
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify
from src.models import SessionLocal, Paper
from src.config import USE_API as _USE_API_DEFAULT
from datetime import datetime, timedelta

app = Flask(__name__)

# ─── Runtime settings (in-memory, initial values from config.py) ──────────────
_settings = {
    'use_api': _USE_API_DEFAULT,
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

PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads', 'pdfs')

def get_db_session():
    return SessionLocal()


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


# ─── Main page ────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    db = get_db_session()

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    label_filter = request.args.get('label', 'all')
    important_filter = request.args.get('important', 'all')
    famous_filter = request.args.get('famous', 'all')
    read_filter = request.args.get('read', 'all')
    downloaded_filter = request.args.get('downloaded', 'all')
    content_analyzed_filter = request.args.get('content_analyzed', 'all')
    sort_by = request.args.get('sort', 'created_at')
    order = request.args.get('order', 'desc')

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
                           search=search,
                           label_filter=label_filter,
                           important_filter=important_filter,
                           famous_filter=famous_filter,
                           read_filter=read_filter,
                           downloaded_filter=downloaded_filter,
                           content_analyzed_filter=content_analyzed_filter,
                           sort_by=sort_by,
                           order=order,
                           stats=stats)


@app.route('/paper/<arxiv_id>')
def paper_detail(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    db.close()
    if not paper:
        return "Paper not found", 404
    return render_template('detail.html', paper=paper)


# ─── Stats API ────────────────────────────────────────────────────────────────
@app.route('/api/stats')
def api_stats():
    db = get_db_session()
    stats = _build_stats(db)
    db.close()
    return jsonify(stats)


# ─── Toggle read ──────────────────────────────────────────────────────────────
@app.route('/api/paper/<arxiv_id>/toggle_read', methods=['POST'])
def toggle_read(arxiv_id):
    db = get_db_session()
    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        db.close()
        return jsonify({'success': False, 'error': 'Paper not found'}), 404
    paper.is_read = not paper.is_read
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
@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(_settings)

@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.get_json(silent=True) or {}
    if 'use_api' in data:
        _settings['use_api'] = bool(data['use_api'])
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
        use_api = req_data.get('use_api', _settings['use_api'])

        paper_dict = {
            'id': paper.arxiv_id,
            'Title': paper.title or '',
            'Abstract': paper.abstract,
            'Authors': paper.authors or '',
        }
        result = analyze_paper_relevance(paper_dict, use_api=use_api)

        if 'error' in result:
            db.close()
            return jsonify({'success': False, 'error': result['error']}), 500

        paper.my_label = result.get('Type', paper.my_label or 'irrelevant')
        paper.summary_cn = result.get('Abstract_CN', paper.summary_cn or '')
        paper.research_content = result.get('research_content', '')
        paper.methods = result.get('methods', '')
        paper.discussion = result.get('discussion', '')
        paper.conclusion = result.get('conclusion', '')
        paper.is_content_analyzed = True

        keywords_en = result.get('keywords', [])
        keywords_cn = result.get('keywords_CN', [])
        if keywords_en:
            paper.category = ', '.join(keywords_en)
        if keywords_cn:
            paper.keywords_cn = ', '.join(keywords_cn)

        # Identify famous professors and highlight them (independent of the important tag)
        famous_result = identify_famous_authors(paper.authors or '', use_api=use_api)
        if famous_result.get('has_famous_author', False):
            paper.is_famous_author = True
            paper.famous_authors = ', '.join(famous_result.get('famous_authors', []))
        else:
            paper.is_famous_author = False
            paper.famous_authors = None

        db.commit()
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
            updated += 1
    db.commit()
    db.close()
    return jsonify({'success': True, 'updated': updated})


# ─── Batch analyze ────────────────────────────────────────────────────────────
def _do_batch_analyze(arxiv_ids, use_api):
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
            result = analyze_paper_relevance(paper_dict, use_api=use_api)

            if 'error' in result:
                with _analyze_lock:
                    _analyze_state['failed'].append({'arxiv_id': arxiv_id, 'error': result['error']})
            else:
                paper.my_label = result.get('Type', paper.my_label or 'irrelevant')
                paper.summary_cn = result.get('Abstract_CN', paper.summary_cn or '')
                paper.research_content = result.get('research_content', '')
                paper.methods = result.get('methods', '')
                paper.discussion = result.get('discussion', '')
                paper.conclusion = result.get('conclusion', '')
                paper.is_content_analyzed = True
                keywords_en = result.get('keywords', [])
                keywords_cn = result.get('keywords_CN', [])
                if keywords_en:
                    paper.category = ', '.join(keywords_en)
                if keywords_cn:
                    paper.keywords_cn = ', '.join(keywords_cn)
                # Identify famous professors and highlight them (independent of the important tag)
                famous_result = identify_famous_authors(paper.authors or '', use_api=use_api)
                if famous_result.get('has_famous_author', False):
                    paper.is_famous_author = True
                    paper.famous_authors = ', '.join(famous_result.get('famous_authors', []))
                else:
                    paper.is_famous_author = False
                    paper.famous_authors = None
                db.commit()
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

    use_api = data.get('use_api', _settings['use_api'])
    thread = threading.Thread(target=_do_batch_analyze, args=(arxiv_ids, use_api), daemon=True)
    thread.start()
    return jsonify({'success': True, 'message': f'Started analyzing {len(arxiv_ids)} papers', 'total': len(arxiv_ids)})


@app.route('/api/analyze/status')
def analyze_status():
    with _analyze_lock:
        state = dict(_analyze_state)
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
    app.run(debug=True, host='0.0.0.0', port=5000)
