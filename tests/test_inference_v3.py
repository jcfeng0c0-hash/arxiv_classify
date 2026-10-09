import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import inference_cache as cache
from src import model_inference as inference
from src.classification_policy import RESEARCH_REQUIREMENTS, VERSION
from src.paper_analysis import apply_analysis_result
from src.models import Paper

DETAILS = {'Abstract_CN': '完整中文摘要', 'keywords': ['gas'], 'keywords_CN': ['气体'],
           'research_content': '星系内部气体', 'methods': '模拟', 'discussion': '', 'conclusion': '结论'}


class InferenceV3Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.patches = [patch.object(cache, 'CACHE_DIR', root / 'cache'),
                        patch.object(cache, 'USAGE_PATH', root / 'usage.jsonl')]
        for p in self.patches:
            p.start()
        self.paper = {'id': '2401.12345', 'Title': 'Molecular cloud structure',
                      'Abstract': 'We study gas morphology in the Milky Way.'}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temporary.cleanup()

    def test_irrelevant_has_one_minimal_call_and_no_details(self):
        with patch.object(inference, '_call_online_api', return_value='{"Type":"irrelevant","rule":"X1"}') as api:
            result = inference.analyze_paper_relevance(self.paper)
        self.assertEqual(api.call_count, 1)
        self.assertFalse(result['details_complete'])
        self.assertNotIn('Abstract_CN', result)
        self.assertEqual(api.call_args.kwargs['task'], 'classification')
        self.assertNotIn('keywords', api.call_args.args[0])

    def test_interested_has_two_calls_then_full_cache_hit(self):
        with patch.object(inference, '_call_online_api', side_effect=[
                '{"Type":"interested","rule":"I1"}', json.dumps(DETAILS)]) as api:
            result = inference.analyze_paper_relevance(self.paper)
            self.assertTrue(result['details_complete'])
            self.assertEqual(result['Abstract_CN'], DETAILS['Abstract_CN'])
            self.assertEqual(inference.analyze_paper_relevance(self.paper), result)
            self.assertEqual(api.call_count, 2)
            self.assertEqual([c.kwargs['task'] for c in api.call_args_list], ['classification', 'details'])

    def test_details_failure_retains_classification_and_retry_skips_classifier(self):
        with patch.object(inference, '_call_online_api', side_effect=[
                '{"Type":"interested","rule":"I1"}', RuntimeError('temporary API outage'),
                json.dumps(DETAILS)]) as api:
            first = inference.analyze_paper_relevance(self.paper)
            self.assertEqual(first['Type'], 'interested')
            self.assertFalse(first['details_complete'])
            self.assertIn('detail_error', first)
            second = inference.analyze_paper_relevance(self.paper)
            self.assertTrue(second['details_complete'])
            self.assertEqual([c.kwargs['task'] for c in api.call_args_list], ['classification', 'details', 'details'])

    def test_policy_or_input_change_does_not_reuse_stale_classification(self):
        with patch.object(inference, '_call_online_api', return_value='{"Type":"irrelevant","rule":"X4"}') as api:
            inference.analyze_paper_relevance(self.paper)
            inference.analyze_paper_relevance(self.paper, requirements=RESEARCH_REQUIREMENTS + '\nUpdated rule')
            inference.analyze_paper_relevance(dict(self.paper, Abstract='Changed abstract'))
            self.assertEqual(api.call_count, 3)

    def test_invalid_classification_is_error_not_silent_rejection(self):
        for raw in ['not JSON', '{"Type":"maybe","rule":"X4"}',
                    '{"Type":"interested","rule":"X1"}', '{"Type":"interested"}']:
            with self.subTest(raw=raw), patch.object(inference, '_call_online_api', return_value=raw):
                self.assertIn('error', inference.analyze_paper_relevance(self.paper))

    def test_incomplete_details_are_not_cached_as_success(self):
        with patch.object(inference, '_call_online_api', side_effect=[
                '{"Type":"interested","rule":"I5"}', '{"Abstract_CN":"only translation"}',
                json.dumps(DETAILS)]) as api:
            self.assertFalse(inference.analyze_paper_relevance(self.paper)['details_complete'])
            self.assertTrue(inference.analyze_paper_relevance(self.paper)['details_complete'])
            self.assertEqual(api.call_count, 3)

    def test_author_feature_is_preserved_and_cached(self):
        with patch.object(inference, '_call_online_api', return_value='{"has_famous_author":true,"famous_authors":["Example"]}') as api:
            first = inference.identify_famous_authors('Example, Another')
            self.assertTrue(first['has_famous_author'])
            self.assertEqual(inference.identify_famous_authors('Example, Another'), first)
            self.assertEqual(api.call_count, 1)
            self.assertEqual(api.call_args.kwargs['task'], 'authors')

    def test_empty_abstract_never_calls_model(self):
        with patch.object(inference, '_call_online_api') as api:
            self.assertIn('error', inference.analyze_paper_relevance({'Abstract': ''}))
            api.assert_not_called()

    def test_actual_api_usage_including_extra_fields_is_recorded(self):
        response = SimpleNamespace(usage=SimpleNamespace(model_dump=lambda: {
            'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120,
            'prompt_cache_hit_tokens': 40}),
            choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
        with patch.object(inference, 'get_openai_client', return_value=client):
            inference._call_online_api('prompt', 'system', 'deepseek', task='classification', paper_id='test')
        entry = json.loads(cache.USAGE_PATH.read_text())
        self.assertEqual(entry['usage']['total_tokens'], 120)
        self.assertEqual(entry['usage']['prompt_cache_hit_tokens'], 40)
        self.assertEqual(entry['paper_id'], 'test')
        self.assertNotIn('prompt', entry)
        self.assertNotIn('api_key', entry)

    def test_missing_usage_is_not_recorded_as_zero(self):
        cache.record_usage('deepseek', 'model', 'details', None)
        self.assertIsNone(json.loads(cache.USAGE_PATH.read_text())['usage'])

    def test_local_ollama_usage_is_recorded(self):
        response = SimpleNamespace(raise_for_status=lambda: None,
                                  json=lambda: {'response': '{}', 'prompt_eval_count': 30, 'eval_count': 10})
        with patch.object(inference.requests, 'post', return_value=response):
            inference._call_local_ollama('prompt', task='classification')
        self.assertEqual(json.loads(cache.USAGE_PATH.read_text())['usage']['total_tokens'], 40)

    def test_database_flags_separate_classification_and_details(self):
        paper = Paper(arxiv_id='2401.12345')
        apply_analysis_result(paper, {'Type': 'interested', 'rule': 'I2',
                                     'details_complete': False, 'detail_error': 'temporary'})
        self.assertEqual(paper.my_label, 'interested')
        self.assertEqual(paper.classification_version, VERSION)
        self.assertFalse(paper.is_content_analyzed)
        self.assertEqual(paper.analysis_error, 'temporary')
        apply_analysis_result(paper, dict(DETAILS, Type='interested', rule='I2', details_complete=True))
        self.assertTrue(paper.is_content_analyzed)
        self.assertIsNone(paper.analysis_error)

    def test_migration_preserves_historical_labels_notes_and_manual_flags(self):
        import migrate_db
        db_path = Path(self.temporary.name) / 'old.db'
        with sqlite3.connect(db_path) as db:
            db.execute('CREATE TABLE papers (id INTEGER PRIMARY KEY, abstract TEXT, my_label TEXT, notes TEXT, famous_authors TEXT, is_famous_author BOOLEAN, is_abstract_invalid BOOLEAN)')
            db.execute("INSERT INTO papers VALUES (1, 'Abstract', 'interested', 'My notes', 'Example', 0, 0)")
        with patch.object(migrate_db, 'DB_PATH', str(db_path)):
            migrate_db.migrate()
            migrate_db.migrate()
        with sqlite3.connect(db_path) as db:
            row = db.execute('SELECT my_label, notes, is_famous_author, classification_version FROM papers').fetchone()
            self.assertEqual(row, ('interested', 'My notes', 0, None))

    def test_revised_or_rejected_paper_does_not_show_stale_details(self):
        paper = Paper(arxiv_id='2401.12345', summary_cn='Old translation', conclusion='Old conclusion')
        apply_analysis_result(paper, {'Type': 'irrelevant', 'rule': 'X1', 'details_complete': False})
        self.assertEqual(paper.summary_cn, '')
        self.assertEqual(paper.conclusion, '')
        self.assertFalse(paper.is_content_analyzed)


if __name__ == '__main__':
    unittest.main()
