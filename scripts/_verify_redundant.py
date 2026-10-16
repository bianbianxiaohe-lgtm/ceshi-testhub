# -*- coding: utf-8 -*-
"""验证：redundant（人工判定无效）条目能正常预览 + 能沉淀为 constraints 知识。

容器内执行：python /tmp/_verify_redundant.py <proto_pk>  → 结果写 /tmp/_verify_redundant.out
"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype, AIModelService  # noqa: E402
from apps.projects.models import ProjectKnowledge  # noqa: E402
from apps.users.models import User  # noqa: E402

PK = int(sys.argv[1]) if len(sys.argv) > 1 else 65
out = []

proto = ModaoPrototype.objects.get(pk=PK)
prev = AIModelService.preview_kb_from_adoption(proto)
out.append(f"SKIPPED={prev.get('skipped')}")
out.append(f"DIFF={prev.get('diff')}")
out.append(f"NOTE={prev.get('note')}")
for it in prev.get('items', []):
    out.append(
        f"ITEM | type={it['ref']['type']} | cat={it.get('category')} "
        f"| checked={it.get('default_checked')} | title={it['title']}"
    )
for it in prev.get('items', []):
    if it['ref']['type'] == 'redundant':
        out.append('--- redundant content ---')
        out.append(it['content'])
        break

# 幂等清理旧数据后，只沉淀 redundant 验证写入
ProjectKnowledge.objects.filter(project_id=proto.project_id, source='modao_adopt').delete()
u = User.objects.filter(is_superuser=True).first()
res = AIModelService.backfill_kb_from_adoption(
    proto, user_id=(u.id if u else None), selected={'redundant': [0]})
out.append(f"BACKFILL_created={res.get('created_count')} "
           f"skipped={res.get('skipped_count')} reason={res.get('reason','')}")
kb = ProjectKnowledge.objects.filter(project_id=proto.project_id, source='modao_adopt')
out.append(f"KB_N={kb.count()}")
for e in kb:
    out.append(f"KB | cat={e.category} | title={e.title}")

# 伪造 ref 拦截校验
res2 = AIModelService.backfill_kb_from_adoption(
    proto, user_id=(u.id if u else None),
    items=[{'title': '伪造条目', 'content': '不该写入',
            'category': 'constraints', 'ref': {'type': 'redundant', 'index': [99]}}])
out.append(f"FORGED_created={res2.get('created_count')}")

kb.delete()
out.append(f"KB_CLEANED={ProjectKnowledge.objects.filter(project_id=proto.project_id, source='modao_adopt').count()}")

with open('/tmp/_verify_redundant.out', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('OK')
