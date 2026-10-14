# -*- coding: utf-8 -*-
"""为「墨刀线新旧提示词对比」挑选候选画布（只读，不写库）。

目标：找一个 dev 库里**已完成**的墨刀原型，其画布上已有
  - page_testpoints_json（旧提示词生成的测试点）
  - page_testcases_json（旧提示词生成的用例）
且这些产物是在 **2026-10-13 16:22（dev 后端 restart 清 _CACHE 的时刻）之前**生成的
⇒ 它们就是「旧提示词」的基准产物。

然后用 page_ids=[该画布] 只重跑这一个画布（画布级独立运行会放宽确认闸门，
产物写在 page 级、不覆盖 proto 级），即可同输入对比新旧。

用法：
  docker exec testhub-dev-backend-1 python /app/scripts/_find_modao_candidate.py
  docker exec testhub-dev-backend-1 cat /tmp/_find_modao_candidate.txt
"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype, ModaoPage  # noqa: E402

OUT = '/tmp/_find_modao_candidate.txt'
lines = []


def w(s=''):
    lines.append(s)


# 先看字段名，避免猜时间字段（曾经按 Django 默认猜表名/字段名错过）
w('=== ModaoPrototype fields ===')
w(', '.join(f.name for f in ModaoPrototype._meta.fields))
w('=== ModaoPage fields ===')
w(', '.join(f.name for f in ModaoPage._meta.fields))
w('')

protos = ModaoPrototype.objects.all().order_by('-id')
w('=== prototypes (%d) ===' % protos.count())
for p in protos:
    pages = p.pages.all()
    n_tp = sum(1 for x in pages if (x.page_testpoints_json or '').strip())
    n_tc = sum(1 for x in pages if (x.page_testcases_json or '').strip())
    w('id=%-4s status=%-12s stage=%-3s pages=%-3d tp=%-3d tc=%-3d  %s'
      % (p.id, p.status, getattr(p, 'current_stage', '?'), pages.count(), n_tp, n_tc,
         (p.title or '')[:40]))
    w('     updated_at=%s  project=%s version=%s'
      % (getattr(p, 'updated_at', None), p.project_id, p.version_id))

w('')
w('=== 候选画布（同时有旧测试点+旧用例）===')
cand = ModaoPage.objects.exclude(page_testpoints_json='').exclude(
    page_testcases_json='').exclude(page_testcases_json__isnull=True)
w('count=%d' % cand.count())
for pg in cand.select_related('prototype').order_by('prototype_id', 'page_no')[:40]:
    w('proto=%-4s page_id=%-5s P%-3s %-28s tp_len=%-6d tc_len=%-6d'
      % (pg.prototype_id, pg.id, pg.page_no, (pg.page_name or '')[:26],
         len(pg.page_testpoints_json or ''), len(pg.page_testcases_json or '')))
    for attr in ('updated_at', 'created_at'):
        if hasattr(pg, attr):
            w('       %s=%s' % (attr, getattr(pg, attr)))

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
