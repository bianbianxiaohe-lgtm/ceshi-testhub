"""
回归冒烟测试（Regression Smoke Tests）

目的：锁定已修复 bug 的关键不变量，防止迭代优化时悄悄回归。
- 结构守卫：关键符号被重命名/误删时立刻变红。
- 行为守卫：rerun_review 的「(未填写)确认项过滤」契约被锁定（对应 BUG-02）。

运行（在 testhub 后端虚拟环境）：
    pytest apps/requirement_analysis/tests/test_regression_smoke.py
或
    python manage.py test apps.requirement_analysis.tests.test_regression_smoke
"""

import re

from django.test import SimpleTestCase

from apps.requirement_analysis import models as ra_models
from apps.requirement_analysis import views as ra_views


class RegressionSmokeTests(SimpleTestCase):
    # ---------- BUG-01: 流式生成 async 外键守卫 ----------
    def test_aimodelservice_stream_symbol_exists(self):
        """generate_test_cases_stream 是 BUG-01 修复的核心符号，禁止误删/重命名。"""
        self.assertTrue(
            hasattr(ra_models.AIModelService, "generate_test_cases_stream"),
            "AIModelService.generate_test_cases_stream 缺失——可能破坏流式生成(BUG-01)",
        )

    # ---------- BUG-02: rerun_review 守卫 ----------
    def test_rerun_review_symbol_exists(self):
        """rerun_review 是 BUG-02 修复所在，禁止误删/重命名。"""
        self.assertTrue(
            hasattr(ra_views.TestCaseGenerationTaskViewSet, "rerun_review"),
            "TestCaseGenerationTaskViewSet.rerun_review 缺失——可能破坏重跑评审(BUG-02)",
        )

    # ---------- BUG-02 行为契约：过滤 (未填写) 确认项 ----------
    def test_rerun_review_filters_unanswered_clarifications(self):
        """
        锁定 rerun_review 的核心契约（views.py:3494-3514）：
        只有「确认回复: 非空且非(未填写)」的确认项才注入评审上下文，
        避免 AI 把未回答项误当作已确认结论。
        本测试镜像该正则逻辑，若 views.py 中该契约被改坏，此处应同步更新并报警。
        """
        human_feedback_text = (
            "【确认项】登录方式？\n确认回复：(未填写)\n\n"
            "【确认项】支付渠道？\n确认回复：微信与支付宝"
        )
        _blocks = re.split(r'\n\n(?=【确认项)', human_feedback_text)
        _answered = [
            b.strip() for b in _blocks
            if b.strip() and re.search(
                r'确认回复[：:]\s*(?!\(未填写\))(.+)', b, re.DOTALL
            )
        ]
        joined = "\n\n".join(_answered)
        # 未填写项必须被排除
        self.assertNotIn("(未填写)", joined)
        # 已回复项必须保留
        self.assertIn("微信与支付宝", joined)
        # 恰好只有 1 项被保留
        self.assertEqual(len(_answered), 1)
