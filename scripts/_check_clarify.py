# -*- coding: utf-8 -*-
"""核验跨画布澄清串台是否修复：联合澄清后各画布是否只保留归属自己的条目。"""
import json
import urllib.request

BASE = 'http://localhost:18000'
NAMES = {718: '引导-身体数据', 720: '引导-饮食情况'}


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
pages = {p['id']: p for p in d['pages']}

data = {}
for pid in NAMES:
    raw = (pages[pid].get('page_clarification') or '').strip()
    items = None
    if raw:
        try:
            items = json.loads(raw)
        except Exception:
            items = None
    data[pid] = items if isinstance(items, list) else []

out = []
for pid, name in NAMES.items():
    out.append('=== page %s (%s) 澄清条目数 = %d' % (pid, name, len(data[pid])))
    for it in data[pid]:
        loc = it.get('location', '') if isinstance(it, dict) else str(it)
        typ = it.get('type', '') if isinstance(it, dict) else ''
        out.append('    [%s] location=%s' % (typ, loc))
    out.append('')


def cross(pid, other_name):
    bad = []
    for it in data[pid]:
        loc = str(it.get('location', '')) if isinstance(it, dict) else ''
        if other_name in loc:
            bad.append(loc)
    return bad


out.append('=== 串台检测 ===')
c718 = cross(718, NAMES[720])
c720 = cross(720, NAMES[718])
out.append('  718 中出现 720 画布名的条目数 = %d  %s' % (len(c718), c718[:3]))
out.append('  720 中出现 718 画布名的条目数 = %d  %s' % (len(c720), c720[:3]))
if data[718] and data[720]:
    same = json.dumps(data[718], ensure_ascii=False) == json.dumps(data[720], ensure_ascii=False)
    out.append('  两画布清单是否完全相同（广播赋值特征）= %s' % same)
open('tmp/_check_clarify.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('OK')
