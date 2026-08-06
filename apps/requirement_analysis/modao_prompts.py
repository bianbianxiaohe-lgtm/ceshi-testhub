# -*- coding: utf-8 -*-
"""
墨刀技能 - Prompt 加载器

忠实复用现成技能包 modao_skill/prompts/ 下的 9 个 prompt（p0~p8）：
  p0 需求结构化 / p1 模块拆分 / p2 测试点生成 / p3 用例生成
  p4 冒烟提取 / p5 风险识别 / p6 PCI 识别 / p7 三路合并去重 / p8 质量自检

只替换文档中约定的「输入占位符」（如 {requirement_text}），其余指令/示例原样保留。
"""
import os

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), 'modao_skill', 'prompts')
_CACHE = {}

# 技能约定的输入占位符（仅这些会被渲染替换）
_INPUT_KEYS = {
    'requirement_text', 'requirement_yaml', 'module_info_yaml', 'test_point_yaml',
    'module_context', 'all_test_points_yaml', 'test_points_json',
    'risk_extended_testpoints', 'pci_blocked_scenarios', 'draft_testpoints',
    'generated_testcases_json', 'smoke_testcases_json', 'final_testpoints_json', 'stage2_issues',
    'expected_module_list', 'module_skeleton', 'focus_instruction',
    'c3_precheck',
}


def get_prompt(name: str) -> str:
    """读取并缓存 prompt 原文（name 不含扩展名）。"""
    if name not in _CACHE:
        path = os.path.join(_PROMPT_DIR, f'{name}.md')
        with open(path, 'r', encoding='utf-8') as f:
            _CACHE[name] = f.read()
    return _CACHE[name]


def render_prompt(name: str, **kwargs) -> str:
    """渲染 prompt：仅替换传入的输入占位符。"""
    text = get_prompt(name)
    for key, value in kwargs.items():
        if key in _INPUT_KEYS:
            text = text.replace('{' + key + '}', str(value))
    return text


# 便捷别名
P0_REQUIREMENT_STRUCT = 'p0_requirement_struct'
P1_MODULE_SPLIT = 'p1_module_split'
P2_TESTPOINT_GEN = 'p2_testpoint_gen'
P3_CASE_GEN = 'p3_case_gen'
P4_SMOKE_EXTRACT = 'p4_smoke_extract'
P5_RISK_IDENTIFY = 'p5_risk_identify'
P6_PCI_IDENTIFY = 'p6_pci_identify'
P7_MERGE_DEDUP = 'p7_merge_dedup'
P8_QUALITY_CHECK = 'p8_quality_check'
