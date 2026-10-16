# -*- coding: utf-8 -*-
"""轮询 proto 65 指定画布的结构化进度（单次查询）。

判据不用 page.stage_status（遗留值不可靠），用 proto.status 是否已结束
且目标画布的 page_summary / work_log 是否已产出。
"""
import json
import sys
import urllib.request

BASE = 'http://localhost:18000'
LOGIN = '/api/auth/login/'
DETAIL = '/api/requirement-analysis/api/modao/65/'
PAGE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 718


def req(url, data=None, token=None):
    h = {'Content-Type': 'application/json'}
    if token:
        h['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(
        url, data=json.dumps(data).encode() if data else None, headers=h)
    with urllib.request.urlopen(r, timeout=180) as resp:
        return json.loads(resp.read().decode('utf-8'))


tok = req(BASE + LOGIN, {'username': 'admin', 'password': 'admin123'})['access']
d = req(BASE + DETAIL, token=tok)
pg = next((x for x in d.get('pages', []) if x.get('id') == PAGE_ID), {})

out = [
    'proto.status=%s current_stage=%s' % (d.get('status'), d.get('current_stage')),
    'page %s name=%s stage=%s stage_status=%s' % (
        PAGE_ID, pg.get('page_name'), pg.get('current_stage'), pg.get('stage_status')),
    '  page_summary len=%d' % len(pg.get('page_summary') or ''),
    '  work_log len=%d' % len(pg.get('work_log') or ''),
    '  page_clarification len=%d' % len(pg.get('page_clarification') or ''),
    '  selected=%s' % pg.get('selected'),
]
if pg.get('error_message'):
    out.append('  ERROR: %s' % pg['error_message'])
open('tmp/_poll_struct.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('\n'.join(out))
