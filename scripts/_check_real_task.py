"""只读检查：生产上「正在跑的真实任务」用了哪版墨刀提示词。

背景：2026-10-14 把「兜底句不得单独成条」+「历史缺陷高发维度①②③④」补进
modao_skill/prompts/p2_testpoint_gen.md 与 p3_case_gen.md 并固化进 prod 镜像。
现在是真实用户在跑新任务，需要判断这批产物是不是真的用了新提示词。

只读，不写任何业务表；唯一输出是 /tmp/_check_real_task.txt。
"""
import os
import sys
import json
import django

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.apps import apps  # noqa: E402
from apps.requirement_analysis.models import ModaoPrototype, ModaoPage  # noqa: E402

OUT = '/tmp/_check_real_task.txt'
lines = []


def P(s=''):
    lines.append(str(s))


# ---- 1. 谁在跑（只看状态，不改） ----
P('=== 1. 近期墨刀任务状态 ===')
for p in ModaoPrototype.objects.order_by('-id')[:8]:
    P('proto id=%-4s status=%-18s stage=%-14s updated=%s' % (
        p.id,
        getattr(p, 'status', '?'),
        getattr(p, 'current_stage', '?'),
        getattr(p, 'updated_at', None) or getattr(p, 'update_time', '?'),
    ))

# ---- 2. 当前任务走到了哪一步 ----
P('')
P('=== 2. 最近一次活动的 proto 的 work_log 尾部 ===')
active = ModaoPrototype.objects.order_by('-updated_at', '-id').first() if any(
    f.name in ('updated_at', 'update_time') for f in ModaoPrototype._meta.get_fields()
) else None
if active is None:
    P('(无法按时间排序，跳过)')
else:
    P('active proto id=%s status=%s' % (active.id, active.status))
    log = getattr(active, 'work_log', '') or ''
    if isinstance(log, (list, tuple)):
        for item in log[-6:]:
            P('  %s' % item)
    else:
        P(str(log)[-800:])

# ---- 3. AIExecutionRecord 字段（找能证明"用了哪版 prompt"的字段） ----
P('')
P('=== 3. AIExecutionRecord 字段 ===')
Rec = None
for m in apps.get_models():
    if m.__name__ == 'AIExecutionRecord':
        Rec = m
        break
if Rec is None:
    P('AIExecutionRecord NOT_FOUND')
else:
    P('label=' + Rec._meta.label)
    P('fields=' + ','.join(f.name for f in Rec._meta.get_fields()))

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print('\n'.join(lines))
