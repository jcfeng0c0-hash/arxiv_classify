"""Versioned, local previews of the first five numbered figures in a paper.

HTML preserves subfigures and captions reliably. PDF extraction is a layout
heuristic fallback: render graphics above each numbered caption, including
vector plots rather than just embedded bitmap objects.
"""
import io
import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIR = ROOT / 'downloads' / 'figures'
PDF_DIR = ROOT / 'downloads' / 'pdfs'
LIMIT = 5
ID_RE = re.compile(r'(?:\d{4}\.\d{4,5}|[a-zA-Z-]+(?:\.[a-zA-Z-]+)?/\d{7})')
CAPTION_RE = re.compile(r'^\s*(?:Figure|Fig\.?)\s*(\d+)\s*[.:]', re.I)
_locks = {}
_lock_guard = threading.Lock()
_request_lock = threading.Lock()
_last_request = 0.0
log = logging.getLogger(__name__)


def cache_key(arxiv_id, version=1):
    if not ID_RE.fullmatch(arxiv_id) or int(version) < 1:
        raise ValueError('Invalid arXiv ID or version')
    return f'{arxiv_id.replace("/", "__")}v{int(version)}'


def _get(url, session=requests, max_bytes=100 * 1024 * 1024):
    """Bound downloads and space arXiv requests to avoid bursts."""
    global _last_request
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('arxiv.org', 'export.arxiv.org'):
        raise ValueError('Figure source must be on arxiv.org')
    with _request_lock:
        time.sleep(max(0, 3 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
    with session.get(url, timeout=(15, 60), stream=True,
                     headers={'User-Agent': 'arxiv-classify/3.0 (local paper reader)'}) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError('arXiv download exceeds size limit')
            chunks.append(chunk)
        return b''.join(chunks)


def parse_html_figures(html, page_url):
    soup = BeautifulSoup(html, 'html.parser')
    result = []
    for figure in soup.select('figure'):
        # Tables are also wrapped in <figure> by LaTeXML.
        if 'ltx_table' in figure.get('class', []) or figure.find_parent('figure'):
            continue
        # Nested panel captions must not replace the overall Figure caption.
        caption = figure.find('figcaption', recursive=False)
        if caption is None:
            caption = next((c for c in figure.find_all('figcaption')
                            if CAPTION_RE.match(c.get_text(' ', strip=True))), None)
        if caption is None:
            continue
        for math in caption.select('math'):
            math.replace_with(math.get('alttext') or math.get_text(' ', strip=True))
        text = ' '.join(caption.get_text(' ', strip=True).split())
        match = CAPTION_RE.match(text)
        if not match:
            continue
        sources = []
        for img in figure.select('img'):
            # Formula glyphs in the caption are not figure panels.
            if img.find_parent('figcaption'):
                continue
            src = img.get('src') or img.get('data-src')
            if src:
                url = urljoin(page_url, src)
                if url not in sources:
                    sources.append(url)
        result.append({'number': int(match.group(1)), 'caption': text,
                       'source_url': page_url + '#' + figure.get('id', ''),
                       'sources': sources})
        if len(result) == LIMIT:
            break
    return result


def extract_html_figures(html, page_url, target, session=requests):
    result = parse_html_figures(html, page_url)
    for index, figure in enumerate(result, 1):
        if not figure['sources']:
            raise ValueError(f"Figure {figure['number']} 没有可下载的图片")
        figure['images'] = []
        for panel, url in enumerate(figure.pop('sources'), 1):
            data = _get(url, session, max_bytes=20 * 1024 * 1024)
            filename = f'figure-{index}-{panel}.png'
            with Image.open(io.BytesIO(data)) as image:
                image.convert('RGB').save(target / filename)
            figure['images'].append(filename)
    return result


def extract_pdf_figures(pdf_path, target, source_url):
    import pymupdf as fitz

    candidates, caption_numbers = [], set()
    has_figure_content = False
    with fitz.open(pdf_path) as document:
        for page_index, page in enumerate(document):
            blocks = [b for b in page.get_text('blocks') if b[6] == 0]
            has_figure_content = has_figure_content or bool(page.get_image_info()) or any(
                re.search(r'\b(?:Figure|Fig\.?)\s*\d+', b[4], re.I) for b in blocks)
            captions = [(b, CAPTION_RE.match(b[4])) for b in blocks]
            captions = [(b, m) for b, m in captions if m]
            if not captions:
                continue
            graphics = [fitz.Rect(i['bbox']) for i in page.get_image_info()]
            graphics += [d['rect'] for d in page.get_drawings()]
            for block, match in captions:
                caption_numbers.add(int(match.group(1)))
                cap = fitz.Rect(block[:4])
                # Full-width figures use both columns; column figures stay local.
                wide = cap.width > page.rect.width * .55
                x0 = 30 if wide else max(20, cap.x0 - 12)
                x1 = page.rect.width - 30 if wide else min(page.rect.width - 20, cap.x1 + 12)
                boundary = 35.0
                for other in blocks:
                    rect = fitz.Rect(other[:4])
                    if (rect.y1 < cap.y0 - 4 and rect.x0 < x1 and rect.x1 > x0
                            and (len(other[4]) > 180 or CAPTION_RE.match(other[4]))):
                        boundary = max(boundary, rect.y1 + 3)
                selected = [r for r in graphics
                            if r.width > 3 and r.height > 3
                            and r.y0 >= boundary - 2 and r.y1 <= cap.y0 + 2
                            and r.x0 >= x0 - 2 and r.x1 <= x1 + 2]
                if not selected:
                    continue
                top = max(boundary, min(r.y0 for r in selected) - 14)
                if cap.y0 - top < 25:
                    continue
                caption = re.sub(r'(\w)-\n(\w)', r'\1\2', block[4])
                caption = ' '.join(caption.split())
                candidates.append((int(match.group(1)), page_index,
                                   (x0, top, x1, cap.y0 - 3), caption))
        result, seen = [], set()
        wanted = set(sorted(caption_numbers)[:LIMIT])
        for number, page_index, rect, caption in sorted(candidates):
            if number not in wanted:
                continue
            if number in seen:
                continue
            seen.add(number)
            filename = f'figure-{len(result) + 1}-1.png'
            document[page_index].get_pixmap(clip=fitz.Rect(rect), dpi=160).save(target / filename)
            result.append({'number': number, 'caption': caption, 'images': [filename],
                           'page': page_index + 1, 'source_url': source_url + f'#page={page_index + 1}'})
            if len(result) == LIMIT:
                break
    if wanted != seen:
        raise ValueError('PDF 中部分图片未能可靠定位，不能用后续图片替代前五幅图')
    if not result and caption_numbers:
        raise ValueError('PDF 中未能可靠定位图片与图注')
    if not result and has_figure_content:
        raise ValueError('PDF 可能含有图片，但未能识别其编号图注')
    return result


def load_figures(arxiv_id, version=1):
    key = cache_key(arxiv_id, version)
    path = FIGURE_DIR / key / 'manifest.json'
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        if result.get('status') == 'ready' and any(
                not (path.parent / name).is_file()
                for figure in result.get('figures', []) for name in figure['images']):
            return {'status': 'pending', 'figures': [], 'key': key}
        return dict(result, key=key)
    except (OSError, ValueError, KeyError):
        return {'status': 'pending', 'figures': [], 'key': key}


def ensure_figures(arxiv_id, version=1, force=False, session=requests):
    key = cache_key(arxiv_id, version)
    with _lock_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        cached = load_figures(arxiv_id, version)
        if cached['status'] == 'ready' and not force:
            return cached
        target = FIGURE_DIR / key
        target.mkdir(parents=True, exist_ok=True)
        versioned_id = f'{arxiv_id}v{int(version)}'
        html_url = f'https://arxiv.org/html/{versioned_id}'
        pdf_url = f'https://arxiv.org/pdf/{versioned_id}'
        result = {'arxiv_id': arxiv_id, 'version': int(version), 'figures': []}
        try:
            try:
                html = _get(html_url, session, max_bytes=20 * 1024 * 1024).decode('utf-8')
                figures = extract_html_figures(html, html_url, target, session)
                if not figures:
                    soup = BeautifulSoup(html, 'html.parser')
                    if not soup.select_one('article.ltx_document') or soup.select_one('figure.ltx_figure, figure img'):
                        raise ValueError('未返回有效的 HTML 全文')
                result.update(source='html', figures=figures)
            except Exception as html_error:
                log.info('HTML figure extraction unavailable for %s: %s', versioned_id, html_error)
                # Only versioned PDFs are trusted: an unversioned cache may be stale.
                PDF_DIR.mkdir(parents=True, exist_ok=True)
                pdf_path = PDF_DIR / f'{key}.pdf'
                if not pdf_path.exists():
                    data = _get(pdf_url, session)
                    if not data.startswith(b'%PDF-'):
                        raise ValueError('arXiv 未返回 PDF 文件')
                    temporary = pdf_path.with_suffix('.tmp')
                    temporary.write_bytes(data)
                    temporary.replace(pdf_path)
                result.update(source='pdf', figures=extract_pdf_figures(pdf_path, target, pdf_url))
            result['status'] = 'ready'
        except Exception as exc:
            # Keep previously good previews when a forced refresh fails.
            result.update(status='error', error=str(exc), figures=cached.get('figures', []))
            log.warning('Figure extraction failed for %s: %s', versioned_id, exc)
        temporary = target / 'manifest.tmp'
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target / 'manifest.json')
        return dict(result, key=key)


def collect_interested_figures(papers):
    """Independent failures must not interrupt classification or daily reports."""
    for paper in papers:
        if paper.my_label == 'interested':
            try:
                result = ensure_figures(paper.arxiv_id, paper.version or 1)
                print(f"图片提取 {paper.arxiv_id}: {result['status']} ({len(result['figures'])} 幅)")
            except Exception:
                log.exception('Cannot collect figures for %s', paper.arxiv_id)
