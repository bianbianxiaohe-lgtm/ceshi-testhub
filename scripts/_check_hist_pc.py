# -*- coding: utf-8 -*-
"""回看历史快照，确认修复前 pass_criteria 是否真的在 P7 阶段被丢弃。

快照结构（`_dump_modao_page.py` 产出）：
  {tag, proto_id, page_id,
   proto: {status, ..., fields: {final_testpoints_json, testcases_json, ...}},
   page:  {page_no, ..., fields: {page_testpoints_json, page_testcases_json, ...}}}

用法（宿主机）：
  python scripts/_check_hist_pc.py <dump1.json> [dump2.json ...]
"""
import json
import sys


def _loads(s):
    try:
        return json.loads(s or '[]')
    except Exception:
        return []


def scan(path):
    with open(path, 'rb') as f:
        raw = f.read()
    data = json.loads(raw.decode('utf-8-sig'))

    pf = (data.get('page') or {}).get('fields') or {}
    tps = _loads(pf.get('page_testpoints_json'))
    cases_raw = _loads(pf.get('page_testcases_json'))
    cases = []
    for c in cases_raw:
        if isinstance(c, dict):
            cases.append(c.get('testcase', c) if isinstance(c.get('testcase'), dict) else c)

    tp_total = len(tps)
    tp_filled = sum(1 for t in tps if isinstance(t, dict) and (t.get('pass_criteria') or '').strip())
    tp_rate = (tp_filled * 100.0 / tp_total) if tp_total else 0.0

    print('--- %s ---' % path)
    print('  testpoints       : %d 条, 带 pass_criteria = %d (%.1f%%)' % (tp_total, tp_filled, tp_rate))
    print('  testcases        : %d 条' % len(cases))
    if tps:
        k = tps[0] if isinstance(tps[0], dict) else {}
        print('  首条字段keys     : %s' % sorted(k.keys()))
        print('  首条pass_criteria: %s' % str(k.get('pass_criteria', '<无此字段>'))[:150])


if __name__ == '__main__':
    for p in sys.argv[1:]:
        try:
            scan(p)
        except Exception as e:
            print('--- %s --- ERROR: %s' % (p, e))
