# -*- coding: utf-8 -*-
"""导出 proto 65 画布 718 的结构化结果与原始 text，用于底模降噪核验。"""
import json
import urllib.request

BASE = 'http://localhost:18000'
PAGE_ID = 718


def req(url, data=None, token=None):
    h = {'Content-Type': 'application/json'}
    if token:
        h['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(
        url, data=json.dumps(data).encode() if data else None, headers=h)
    with urllib.request.urlopen(r, timeout=180) as resp:
        return json.loads(resp.read().decode('utf-8'))


tok = req(BASE + '/api/auth/login/',
          {'username': 'admin', 'password': 'admin123'})['access']
d = req(BASE + '/api/requirement-analysis/api/modao/65/', token=tok)
pg = next(x for x in d['pages'] if x['id'] == PAGE_ID)

summary = pg.get('page_summary') or ''
text = pg.get('text') or ''
open('tmp/_p718_summary.txt', 'w', encoding='utf-8').write(summary)
open('tmp/_p718_text.txt', 'w', encoding='utf-8').write(text)

# 把 text 按板块切开，便于对照
segs = {}
cur = '前置'
segs[cur] = []
for line in text.splitlines():
    if line.startswith('[') and line.endswith(']'):
        cur = line
        segs[cur] = []
        continue
    segs[cur].append(line)
open('tmp/_p718_text_seg.txt', 'w', encoding='utf-8').write('\n'.join(
    '=== %s (%d 行) ===\n%s' % (k, len(v), '\n'.join(v)[:2500])
    for k, v in segs.items()))
print('summary_len=%d text_len=%d segs=%s' % (len(summary), len(text), list(segs)))
