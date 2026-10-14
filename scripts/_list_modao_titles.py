# -*- coding: utf-8 -*-
"""列出快照里所有用例/测试点的标题，用于人工判断「维度是否真被覆盖」。
（自动化关键词统计会漏，标题列表是交叉验证手段。）

用法：python /app/scripts/_list_modao_titles.py <tag> [testcases|testpoints]
输出：/tmp/_list_modao_titles.txt
"""
import json
import sys

tag = sys.argv[1] if len(sys.argv) > 1 else 'after'
field = ('page_testcases_json' if len(sys.argv) <= 2 else
         ('page_testcases_json' if sys.argv[2] == 'testcases' else 'page_testpoints_json'))

with open('/tmp/_dump_modao_%s.json' % tag, encoding='utf-8') as f:
    data = json.load(f)

raw = data['page']['fields'].get(field) or ''
try:
    obj = json.loads(raw)
except Exception:
    obj = None

lines = []
if isinstance(obj, list):
    for i, c in enumerate(obj, 1):
        if isinstance(c, dict):
            title = c.get('title') or c.get('name') or c.get('point') or str(c)[:80]
            extra = c.get('priority') or c.get('type') or ''
            lines.append('%2d. [%s] %s' % (i, extra, title))
        else:
            lines.append('%2d. %s' % (i, str(c)[:100]))
else:
    lines.append(raw[:3000])

with open('/tmp/_list_modao_titles.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
