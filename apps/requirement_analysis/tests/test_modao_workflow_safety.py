import os
import tempfile

from django.test import SimpleTestCase

from apps.requirement_analysis.modao_extractor import ModaoExtractor
from apps.requirement_analysis.modao_workflow import ModaoWorkflow


class ModaoExtractionSafetyTests(SimpleTestCase):
    def test_duplicate_screenshots_are_marked_for_audit(self):
        with tempfile.TemporaryDirectory() as media_root:
            extractor = ModaoExtractor(run_id='test-run', media_root=media_root)
            first = os.path.join(extractor.shot_dir, 'page_1.png')
            second = os.path.join(extractor.shot_dir, 'page_2.png')
            with open(first, 'wb') as fh:
                fh.write(b'same-canvas')
            with open(second, 'wb') as fh:
                fh.write(b'same-canvas')
            pages = [
                {'page_no': 1, 'screenshot': os.path.relpath(first, media_root)},
                {'page_no': 2, 'screenshot': os.path.relpath(second, media_root)},
            ]

            groups = extractor._mark_duplicate_screenshots(pages)

            self.assertEqual(groups, [[1, 2]])
            self.assertEqual(pages[1]['duplicate_of_page'], 1)
            self.assertTrue(pages[0]['screenshot_sha256'])
            self.assertIn('未计为独立有效页面', pages[1]['extraction_warnings'][0])


class ModaoDedupAuditTests(SimpleTestCase):
    def test_vector_dedup_returns_removed_item_and_similarity(self):
        workflow = object.__new__(ModaoWorkflow)
        workflow.dedup_threshold = 0.85
        workflow._embed = lambda texts: [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]
        items = [
            {'id': 'TP-1', 'title': '搜索动作', 'description': '按名称搜索动作', 'priority': 'P1', 'source': ['draft']},
            {'id': 'TP-2', 'title': '动作搜索', 'description': '根据动作名称搜索', 'priority': 'P1', 'source': ['risk']},
            {'id': 'TP-3', 'title': '删除动作', 'description': '删除自定义动作', 'priority': 'P1', 'source': ['draft']},
        ]

        kept, count, audit = workflow._vector_dedup(items)

        self.assertEqual(count, 1)
        self.assertEqual([item['id'] for item in kept], ['TP-1', 'TP-3'])
        self.assertEqual(audit[0]['kept_id'], 'TP-1')
        self.assertEqual(audit[0]['removed_id'], 'TP-2')
        self.assertGreaterEqual(audit[0]['similarity'], 0.85)
