# -*- coding: utf-8 -*-
"""一次性回填：把「人工补充」（merged_testcases_json 里 _manual=True）采纳入库时
被错标成 source='ai' 的用例改为 'manual'。

判据：遍历所有 ModaoPrototype 的 merged_testcases_json，取 _manual=True 条目的
(project, title)，把 TestCase 中 项目+标题命中 且 source='ai' 的改为 'manual'。
只改 AI→manual，绝不反向，幂等可重跑。
"""
import json
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype  # noqa: E402
from apps.testcases.models import TestCase  # noqa: E402

out = []
fixed_total = 0
for proto in ModaoPrototype.objects.all().iterator():
    try:
        merged = json.loads(proto.merged_testcases_json or '[]')
    except Exception:
        continue
    if not isinstance(merged, list):
        continue
    manual = [m for m in merged
              if isinstance(m, dict) and m.get('_manual') and m.get('title')]
    if not manual or not proto.project_id:
        continue
    for m in manual:
        title = str(m['title']).strip()
        qs = TestCase.objects.filter(project_id=proto.project_id, title=title,
                                     source='ai')
        n = qs.update(source='manual')
        if n:
            fixed_total += n
            out.append(f"FIXED proto={proto.pk} project={proto.project_id} "
                       f"title={title} n={n}")

out.append(f"TOTAL_FIXED={fixed_total}")
with open('/tmp/_fix_manual_source.out', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('OK')
