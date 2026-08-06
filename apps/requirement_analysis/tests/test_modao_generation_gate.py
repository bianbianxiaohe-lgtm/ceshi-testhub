import json

from django.test import SimpleTestCase

from apps.requirement_analysis.models import ModaoPrototype


class ModaoGenerationGateTests(SimpleTestCase):
    def make_proto(self, clarification_log='[]', confirmations=None):
        return ModaoPrototype(
            clarification_log=clarification_log,
            final_testpoints_json='[{"title":"登录成功"}]',
            stage_confirmations=json.dumps(confirmations or {}, ensure_ascii=False),
        )

    def test_unresolved_clarification_blocks_generation(self):
        proto = self.make_proto(json.dumps([{
            'type': '模糊点',
            'location': '第2页/标注1',
            'issue': '失败后从哪一步重试',
            'resolution': '',
        }], ensure_ascii=False), {'stage2_confirmed': True})

        gate = proto.case_generation_gate()

        self.assertFalse(gate['allowed'])
        self.assertEqual(gate['unresolved_count'], 1)
        self.assertEqual(gate['unresolved_items'][0]['location'], '第2页/标注1')

    def test_matching_human_approval_allows_generation(self):
        proto = self.make_proto(json.dumps([{
            'issue': '失败后从哪一步重试',
            'resolution': '仅从失败步骤继续，已由产品确认',
        }], ensure_ascii=False), {'stage2_confirmed': True})
        confirmations = proto.get_confirmations()
        confirmations.update({
            'case_generation_approved': True,
            'case_generation_fingerprint': proto.case_generation_fingerprint(),
        })
        proto.stage_confirmations = json.dumps(confirmations, ensure_ascii=False)

        self.assertTrue(proto.case_generation_gate()['allowed'])

    def test_edit_after_approval_invalidates_gate(self):
        proto = self.make_proto('[]', {'stage2_confirmed': True})
        confirmations = proto.get_confirmations()
        confirmations.update({
            'case_generation_approved': True,
            'case_generation_fingerprint': proto.case_generation_fingerprint(),
        })
        proto.stage_confirmations = json.dumps(confirmations, ensure_ascii=False)
        proto.final_testpoints_json = '[{"title":"已修改的测试点"}]'

        gate = proto.case_generation_gate()

        self.assertFalse(gate['allowed'])
        self.assertFalse(gate['fingerprint_matches'])
        self.assertIn('原生成批准已失效', '；'.join(gate['reasons']))
