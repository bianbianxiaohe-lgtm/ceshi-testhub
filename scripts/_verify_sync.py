# -*- coding: utf-8 -*-
"""验收：判定侧新常量是否生效 + 知识库是否已进入向量召回条件。"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

lines = []
w = lines.append

try:
    from apps.zentao import services as svc
    w('JUDGE_CASE_CHARS=%s' % svc.JUDGE_CASE_CHARS)
    w('JUDGE_BUG_CHARS=%s' % svc.JUDGE_BUG_CHARS)
    w('JUDGE_TEMPERATURE=%s' % svc.JUDGE_TEMPERATURE)
    w('_case_text_compact_doc=%s' % (svc._case_text_compact.__doc__ or '').strip().splitlines()[:1])
except Exception as exc:  # noqa: BLE001
    w('services 导入失败: %s' % exc)

from apps.zentao.models import CoverageReport  # noqa: E402
from apps.projects.models import ProjectKnowledge  # noqa: E402

r = CoverageReport.objects.filter(id=29).first()
if r:
    proj = r.config.project
    qs = ProjectKnowledge.objects.filter(project=proj, source='zentao_coverage')
    total = qs.count()
    promoted = qs.filter(version__isnull=True, needs_review=False).count()
    pending_review = qs.filter(needs_review=True).count()
    w('')
    w('project=%s zentao_coverage 条目=%d' % (proj, total))
    w('已跨版本通用(version=None 且 needs_review=False)=%d' % promoted)
    w('仍待人工确认=%d' % pending_review)

open('/tmp/_verify_sync.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('DONE')
