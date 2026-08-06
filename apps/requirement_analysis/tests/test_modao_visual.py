from django.test import SimpleTestCase

from apps.requirement_analysis.modao_extractor import ModaoExtractor


class DecisionTableValidationTests(SimpleTestCase):
    @staticmethod
    def _artifact():
        identities = [
            ('Android', '新用户'), ('iOS', '新用户'),
            ('Android', '老用户'), ('iOS', '老用户'),
        ]
        rows = []
        for left_index, left in enumerate(identities):
            for right in identities[left_index:]:
                blocked = (left[1] == right[1] == '新用户'
                           and (left[0] == 'iOS' or right[0] == 'iOS'))
                rows.append({
                    'user_a_platform': left[0], 'user_a_type': left[1],
                    'user_b_platform': right[0], 'user_b_type': right[1],
                    'user_a_result': '屏蔽' if blocked else '不屏蔽',
                    'user_b_result': '屏蔽' if blocked else '不屏蔽',
                })
        return {
            'artifact_type': 'decision_table',
            'dimensions': [
                {'name': 'user_a_platform', 'values': ['Android', 'iOS']},
                {'name': 'user_a_type', 'values': ['新用户', '老用户']},
                {'name': 'user_b_platform', 'values': ['Android', 'iOS']},
                {'name': 'user_b_type', 'values': ['新用户', '老用户']},
            ],
            'result_fields': ['user_a_result', 'user_b_result'],
            'rows': rows,
            'derived_rules': [{'condition': '任一方为老用户', 'result': '双方不屏蔽',
                               'source_rows': [3, 4, 6, 7, 8, 9, 10]}],
        }

    def test_symmetric_ten_rows_expand_to_all_sixteen_ordered_combinations(self):
        result = ModaoExtractor._validate_visual_artifact(self._artifact())
        self.assertEqual(result['raw_combination_count'], 10)
        self.assertEqual(result['expanded_combination_count'], 16)
        self.assertEqual(result['expected_combination_count'], 16)
        self.assertTrue(result['symmetry_expanded'])
        self.assertTrue(result['coverage_complete'])
        self.assertTrue(result['shape_valid'])
        self.assertEqual(result['duplicate_combinations'], [])
        self.assertTrue(result['rules_traceable'])

    def test_invalid_derived_rule_row_reference_is_rejected(self):
        artifact = self._artifact()
        artifact['derived_rules'][0]['source_rows'] = [1, 11]
        result = ModaoExtractor._validate_visual_artifact(artifact)
        self.assertFalse(result['rules_traceable'])
        self.assertEqual(result['invalid_rule_references'], [1])


class StateMatrixValidationTests(SimpleTestCase):
    def test_numbered_state_spec_table_is_promoted_without_rewriting_cells(self):
        source_rows = [
            ['1', '1、标题：断食中\n2、副标题：已经断食\n3、计时：正计时'],
            ['2', '1、标题：饮食中\n2、副标题：距离断食\n3、计时：倒计时'],
            ['3', '1、标题：断食待开始\n2、下次断食时间：与app内保持一致'],
            ['4', '1、标题：断食迟到啦\n2、开始时间：与app内保持一致'],
            ['5', '点击小组件进入断食页面。'],
        ]
        artifacts = ModaoExtractor._promote_numbered_state_tables([{
            'artifact_type': 'table',
            'columns': ['编号', '内容'],
            'rows': source_rows,
        }])

        self.assertEqual(len(artifacts), 1)
        matrix = artifacts[0]
        self.assertEqual(matrix['artifact_type'], 'state_matrix')
        self.assertEqual(
            [state['state'] for state in matrix['states']],
            ['断食中', '饮食中', '断食待开始', '断食迟到啦'],
        )
        self.assertEqual(matrix['states'][0]['raw_spec'], source_rows[0][1])
        self.assertEqual(matrix['rules'][0]['raw_rule'], source_rows[4][1])
        self.assertEqual(matrix['source_table']['rows'], source_rows)

        validation = ModaoExtractor._validate_visual_artifact(matrix)
        self.assertTrue(validation['structure_valid'])
        self.assertEqual(validation['state_count'], 4)
        self.assertEqual(validation['duplicate_states'], [])

    def test_transition_to_unknown_state_is_invalid(self):
        matrix = {
            'artifact_type': 'state_matrix',
            'states': [{'state': '饮食中'}, {'state': '断食迟到啦'}],
            'transitions': [{'from': '饮食中', 'trigger': '倒计时结束', 'to': '断食中'}],
        }

        validation = ModaoExtractor._validate_visual_artifact(matrix)

        self.assertFalse(validation['transitions_traceable'])
        self.assertEqual(validation['invalid_transitions'], [1])

    def test_malformed_model_text_recovers_unique_literal_states(self):
        malformed = (
            '{"states":[{"raw_spec":"1、标题：断食中\\n2、计时：正计时"},'
            '{"raw_spec":"1、标题：饮食中\\n2、计时：倒计时"},'
            '{"raw_spec":"1、标题：断食中\\n输出被截断'
        )

        matrix = ModaoExtractor._state_matrix_from_text(malformed)

        self.assertIsNotNone(matrix)
        self.assertEqual([item['state'] for item in matrix['states']], ['断食中', '饮食中'])
        self.assertEqual(matrix['states'][0]['source'], 'literal_text_fallback')
