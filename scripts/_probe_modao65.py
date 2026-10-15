# -*- coding: utf-8 -*-
"""探查 proto 65 各画布的批注/底模情况，用于挑选端到端验证对象。"""
import json

d = json.load(open('tmp/_m65.json', encoding='utf-8'))
ps = d['pages']
out = []

for pg in ps:
    out.append('id=%s no=%s name=%s sel=%s stage=%s' % (
        pg.get('id'), pg.get('page_no'), pg.get('page_name'),
        pg.get('selected'), pg.get('current_stage')))

out.append('')
out.append('=== annotations 原文 ===')
for pg in ps:
    out.append('  id=%s  %s' % (pg.get('id'), repr(pg.get('annotations'))))

for pid in (718, 720, 719):
    pg = next((x for x in ps if x.get('id') == pid), None)
    if pg:
        out.append('')
        out.append('=== id=%s page_name=%s  text 前700 ===' % (pid, pg.get('page_name')))
        out.append((pg.get('text') or '')[:700])

pg722 = next((x for x in ps if x.get('id') == 722), None)
if pg722:
    out.append('')
    out.append('=== id=722 page_clarification 前1500（看历史是否串台）===')
    out.append((pg722.get('page_clarification') or '')[:1500])

open('tmp/_pages_probe.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('OK len=', len(out))
