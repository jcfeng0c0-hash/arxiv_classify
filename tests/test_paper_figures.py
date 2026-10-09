import importlib.util
import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src import paper_figures as figures
from src.models import Base, Paper


def html_figures(count=6):
    return '<article class="ltx_document">' + ''.join(
        f'<figure id="F{i}" class="ltx_figure"><img src="/html/test/x{i}.png">'
        f'<figcaption>Figure {i}: Caption {i} <math alttext="x^2">duplicate</math></figcaption>'
        '</figure>' for i in range(1, count + 1)) + '</article>'


class FigureExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patches = [patch.object(figures, 'FIGURE_DIR', self.root / 'figures'),
                        patch.object(figures, 'PDF_DIR', self.root / 'pdfs')]
        for p in self.patches:
            p.start()
        stream = io.BytesIO()
        Image.new('RGB', (60, 40), 'white').save(stream, format='PNG')
        self.png = stream.getvalue()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temporary.cleanup()

    def test_first_five_with_full_captions_and_no_tables(self):
        html = '<figure class="ltx_table"><figcaption>Figure 9: Table</figcaption><img src="t.png"></figure>' + html_figures()
        result = figures.parse_html_figures(html, 'https://arxiv.org/html/2401.12345v1')
        self.assertEqual([f['number'] for f in result], [1, 2, 3, 4, 5])
        self.assertEqual(result[0]['caption'], 'Figure 1: Caption 1 x^2')

    def test_multiple_panels_and_caption_glyph_excluded(self):
        html = '<figure><img src="a.png"><img src="b.png"><figcaption>Figure 1: Test<img src="formula.png"></figcaption></figure>'
        result = figures.parse_html_figures(html, 'https://arxiv.org/html/2401.12345v1/')
        self.assertEqual(result[0]['sources'], ['https://arxiv.org/html/2401.12345v1/a.png', 'https://arxiv.org/html/2401.12345v1/b.png'])

    def test_nested_panel_does_not_hide_numbered_caption(self):
        html = '<figure><figure><img src="a.png"><figcaption>(a) Panel</figcaption></figure><figcaption>Figure 1: Overall caption</figcaption></figure>'
        result = figures.parse_html_figures(html, 'https://arxiv.org/html/2401.12345v1/')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['caption'], 'Figure 1: Overall caption')
        self.assertEqual(len(result[0]['sources']), 1)

    def test_cache_skips_network_and_versions_are_independent(self):
        with patch.object(figures, '_get', side_effect=lambda url, *a, **kw: html_figures(2).encode() if '/html/2401' in url else self.png) as get:
            result = figures.ensure_figures('2401.12345', 1)
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(len(result['figures']), 2)
            first_count = get.call_count
            figures.ensure_figures('2401.12345', 1)
            self.assertEqual(get.call_count, first_count)
            figures.ensure_figures('2401.12345', 2)
            self.assertGreater(get.call_count, first_count)
        self.assertTrue((self.root / 'figures/2401.12345v1/figure-1-1.png').is_file())
        self.assertEqual(figures.load_figures('2401.12345', 3)['status'], 'pending')

    def test_html_failure_falls_back_and_error_is_retryable(self):
        with patch.object(figures, '_get', side_effect=RuntimeError('network down')):
            self.assertEqual(figures.ensure_figures('2401.12345')['status'], 'error')
        with patch.object(figures, '_get', side_effect=lambda url, *a, **kw: b'%PDF-test' if '/pdf/' in url else b'not HTML'), patch.object(figures, 'extract_pdf_figures', return_value=[]):
            result = figures.ensure_figures('2401.12345')
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['source'], 'pdf')

    def test_missing_image_invalidates_cache(self):
        with patch.object(figures, '_get', side_effect=lambda url, *a, **kw: html_figures(1).encode() if '/html/2401' in url else self.png):
            figures.ensure_figures('2401.12345')
        (self.root / 'figures/2401.12345v1/figure-1-1.png').unlink()
        self.assertEqual(figures.load_figures('2401.12345')['status'], 'pending')

    def test_missing_early_figure_cannot_be_replaced_by_later_one(self):
        html = html_figures().replace('<img src="/html/test/x1.png">', '')
        parsed = figures.parse_html_figures(html, 'https://arxiv.org/html/2401.12345v1')
        self.assertEqual([f['number'] for f in parsed], [1, 2, 3, 4, 5])
        with self.assertRaises(ValueError):
            figures.extract_html_figures(html, 'https://arxiv.org/html/2401.12345v1', self.root)

    def test_true_figureless_html_is_valid_empty_preview(self):
        with patch.object(figures, '_get', return_value=b'<article class="ltx_document">Text-only paper</article>'):
            result = figures.ensure_figures('2401.12345')
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['figures'], [])

    def test_invalid_ids_cannot_escape_cache_directory(self):
        for value in ['../../x', '2401.12345/../../x', '/tmp/x']:
            with self.assertRaises(ValueError):
                figures.cache_key(value)
        self.assertEqual(figures.cache_key('astro-ph/0601001', 2), 'astro-ph__0601001v2')

    def test_real_pdf_vector_and_multipanel_figures(self):
        pdf = figures.ROOT / 'downloads/pdfs/2609.01903v1.pdf'
        if not pdf.exists():
            self.skipTest('Local real-paper QA fixture not available')
        result = figures.extract_pdf_figures(pdf, self.root, 'https://arxiv.org/pdf/2609.01903v1')
        self.assertEqual([f['number'] for f in result], [1, 2, 3, 4, 5])
        self.assertEqual([f['page'] for f in result], [4, 6, 8, 9, 9])
        for figure in result:
            with Image.open(self.root / figure['images'][0]) as image:
                self.assertGreater(image.width, 400)
                self.assertGreater(image.height, 100)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {'ARXIV_WEBUI_SESSION_SECRET': 'figure-test-secret'}), patch('migrate_db.migrate'):
            import webui
        cls.webui = webui
        spec = importlib.util.spec_from_file_location('arxiv_pipeline', figures.ROOT / '__main__.py')
        cls.pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pipeline)

    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.db.add_all([
            Paper(arxiv_id='2401.12345', title='Interested test', abstract='Abstract', my_label='interested'),
            Paper(arxiv_id='2401.12346', title='Irrelevant test', abstract='Abstract', my_label='irrelevant')])
        self.db.commit()
        self.client = self.webui.app.test_client()
        self.db_patch = patch.object(self.webui, 'get_db_session', self.sessions)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.db.close()
        self.engine.dispose()

    def test_gallery_and_escaped_captions_only_on_interested_page(self):
        preview = {'status': 'ready', 'key': '2401.12345v1', 'source': 'html', 'figures': [
            {'number': 1, 'caption': 'Figure 1: <script>unsafe</script>', 'images': ['figure-1-1.png'], 'source_url': 'https://arxiv.org/html/2401.12345v1#F1'}]}
        with patch.object(self.webui, 'load_figures', return_value=preview):
            response = self.client.get('/paper/2401.12345')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'/figures/2401.12345v1/figure-1-1.png', response.data)
            self.assertIn(b'&lt;script&gt;unsafe&lt;/script&gt;', response.data)
            self.assertNotIn('论文图片与图注'.encode(), self.client.get('/paper/2401.12346').data)

    def test_status_and_noninterested_rejection(self):
        with patch.object(self.webui, 'load_figures', return_value={'status': 'pending', 'figures': []}):
            self.assertEqual(self.client.get('/api/paper/2401.12345/figures').json['status'], 'pending')
        self.assertEqual(self.client.post('/api/paper/2401.12346/figures').status_code, 400)
        self.assertEqual(self.client.get('/api/paper/2401.99999/figures').status_code, 404)
        self.assertEqual(self.client.get('/figures/invalid/figure-1-1.png').status_code, 404)

    def test_manual_retry_runs_in_background_and_deduplicates(self):
        started, release = threading.Event(), threading.Event()
        def extract(*args):
            started.set()
            release.wait(timeout=2)
        threads = []
        real_thread = threading.Thread
        def thread_factory(*args, **kwargs):
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread
        with patch.object(self.webui, 'ensure_figures', side_effect=extract) as ensure, patch.object(self.webui.threading, 'Thread', side_effect=thread_factory), patch.object(self.webui, 'load_figures', return_value={'status': 'pending', 'figures': []}):
            try:
                self.assertEqual(self.client.post('/api/paper/2401.12345/figures').status_code, 202)
                self.assertTrue(started.wait(timeout=1))
                self.assertTrue(self.client.get('/api/paper/2401.12345/figures').json['running'])
                self.client.post('/api/paper/2401.12345/figures')
                ensure.assert_called_once_with('2401.12345', 1)
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=1)
            self.assertFalse(self.client.get('/api/paper/2401.12345/figures').json['running'])

    def test_existing_recent_papers_retry_on_daily_analysis(self):
        with patch.object(self.pipeline, 'SessionLocal', self.sessions), patch.object(figures, 'ensure_figures', return_value={'status': 'ready', 'figures': []}) as extract:
            self.assertEqual(self.pipeline.analyze_papers_from_db(), 0)
            extract.assert_called_once_with('2401.12345', 1)

    def test_v3_incomplete_details_are_retried_but_old_labels_are_preserved(self):
        paper = self.db.query(Paper).filter_by(arxiv_id='2401.12345').one()
        paper.classification_version = '3.0.0'
        paper.is_content_analyzed = False
        paper.analysis_error = 'temporary outage'
        self.db.commit()
        with patch.object(self.pipeline, 'SessionLocal', self.sessions), patch.object(self.pipeline, 'analyze_paper_relevance', return_value={'Type': 'interested', 'rule': 'I1', 'details_complete': True, 'Abstract_CN': 'Translation'}) as analyze, patch.object(self.pipeline, 'identify_famous_authors', return_value={}), patch.object(figures, 'ensure_figures', return_value={'status': 'ready', 'figures': []}):
            self.assertEqual(self.pipeline.analyze_papers_from_db(), 1)
            self.assertEqual(analyze.call_count, 1)
        self.db.expire_all()
        self.assertTrue(self.db.query(Paper).filter_by(arxiv_id='2401.12345').one().is_content_analyzed)
        old = self.db.query(Paper).filter_by(arxiv_id='2401.12346').one()
        self.assertEqual(old.my_label, 'irrelevant')
        self.assertIsNone(old.classification_version)

    def test_new_daily_classification_extracts_only_interested_papers(self):
        for p in self.db.query(Paper):
            p.my_label = None
        self.db.commit()
        results = [{'Type': 'interested'}, {'Type': 'irrelevant'}]
        with patch.object(self.pipeline, 'SessionLocal', self.sessions), patch.object(self.pipeline, 'analyze_paper_relevance', side_effect=results), patch.object(self.pipeline, 'identify_famous_authors', return_value={}), patch('src.model_inference.check_important_author', return_value=(False, [])), patch.object(figures, 'ensure_figures', return_value={'status': 'error', 'figures': []}) as extract:
            self.assertEqual(self.pipeline.analyze_papers_from_db(), 2)
            extract.assert_called_once_with('2401.12345', 1)
        self.db.expire_all()
        self.assertEqual(self.db.query(Paper).filter_by(arxiv_id='2401.12346').one().my_label, 'irrelevant')


if __name__ == '__main__':
    unittest.main()
