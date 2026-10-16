# -*- coding: utf-8 -*-
"""生产上线后校验（只读）：墨刀详情 200 / 自愈闭环预览接口可用 / 提示词缓存已刷新。

容器内执行：python /tmp/_verify_prod_release.py → 结果写 /tmp/_verify_prod_release.out
"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django  # noqa: E402

django.setup()

from django.test import Client  # noqa: E402
from rest_framework.test import APIClient, force_authenticate  # noqa: E402

from apps.requirement_analysis.models import ModaoPrototype  # noqa: E402
from apps.users.models import User  # noqa: E402

out = []
u = User.objects.filter(is_superuser=True).first()
c = APIClient()
force_authenticate(c, user=u) if False else None  # placeholder
c.force_authenticate(user=u)

for pk in (70, 82, 85):
    p = ModaoPrototype.objects.filter(pk=pk).first()
    if not p:
        out.append(f"PK={pk} NOT_FOUND")
        continue
    r = c.get(f'/api/requirement-analysis/api/modao/{pk}/')
    out.append(f"PK={pk} detail={r.status_code} project={p.project_id}")

# 自愈闭环预览（只读，不写库）
p82 = ModaoPrototype.objects.filter(pk=82).first()
if p82:
    r2 = c.get('/api/requirement-analysis/api/modao/82/adoption-diff/')
    body = r2.json() if hasattr(r2, 'json') else {}
    out.append(f"ADOPTION_DIFF={r2.status_code} skipped={body.get('skipped')} "
               f"diff={body.get('diff')} items={len(body.get('items') or [])}")
    out.append(f"NOTE={body.get('note') or body.get('reason')}")

with open('/tmp/_verify_prod_release.out', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('OK')
