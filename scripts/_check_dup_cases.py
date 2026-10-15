# -*- coding: utf-8 -*-
"""检测墨刀线用例快照内部的重复 / 高度相似条目。

背景（2026-10-14 生产实测）：
  新提示词跑完后用例 35 → 34，但测试点 34 → 24。
  测试点少了 10 条、用例只少 1 条 ⇒ 怀疑「三路合并去重」在新提示词下
  去重失效，产生了重复条目。本脚本用于量化验证这个怀疑。

输入：/tmp/_dump_modao_{before,after}.json（由 _dump_modao_page.py 导出）
输出：/tmp/_check_dup_cases.txt

用法：
  docker exec testhub-backend python /app/scripts/_check_dup_cases.py
  docker exec testhub-backend cat /tmp/_check_dup_cases.txt
"""
import json
import re

OUT = '/tmp/_check_dup_cases.txt'
lines = []


def w(m=''):
    lines.append(str(m))


def load(tag):
    with open('/tmp/_dump_modao_%s.json' % tag, encoding='utf-8') as f:
        return json.load(f)


def parse(text):
    if not text or not text.strip():
        return []
    try:
        p = json.loads(text.strip())
        return p if isinstance(p, list) else []
    except Exception:
        return []


def fields_of(data):
    pg = data.get('page') or {}
    return pg.get('fields') or {}


def title_of(c):
    if not isinstance(c, dict):
        return ''
    for k in ('title', '用例标题', '用例名称', 'name'):
        v = c.get(k)
        if isinstance(v, str):
            return v.strip()
    return ''


def norm(s):
    return re.sub(r'[\s「」《》（）()【】\[\]、，,。.：:；;"\']', '', s)


def grams(s, n=2):
    return set(s[i:i + n] for i in range(len(s) - n + 1)) or {s}


def pairs(titles, threshold=0.6):
    n = len(titles)
    out = []
    for i in range(n):
        for j in range(i + 1, n):
            gi, gj = grams(norm(titles[i])), grams(norm(titles[j]))
            union = gi | gj
            s = (len(gi & gj) / len(union)) if union else 0.0
            if s >= threshold and norm(titles[i]) != norm(titles[j]):
                out.append((i + 1, j + 1, s, titles[i], titles[j]))
    out.sort(key=lambda x: -x[2])
    return out


for tag in ('before', 'after'):
    f = fields_of(load(tag))
    cases = parse(f.get('page_testcases_json'))
    titles = [title_of(c) for c in cases]

    w('=' * 70)
    w('[%s] 用例条数 = %d' % (tag, len(titles)))
    w('=' * 70)

    seen, exact = {}, []
    for i, t in enumerate(titles):
        key = norm(t)
        if not key:
            continue
        if key in seen:
            exact.append((seen[key] + 1, i + 1, t))
        else:
            seen[key] = i
    w('  完全重复（归一化后相同） = %d' % len(exact))
    for a, b, t in exact:
        w('      #%-2d == #%-2d  %s' % (a, b, t[:50]))

    sim = pairs(titles)
    w('  高度相似（字符 2-gram Jaccard >= 0.60） = %d 对' % len(sim))
    for a, b, s, ta, tb in sim[:15]:
        w('      #%-2d ~ #%-2d  %.2f' % (a, b, s))
        w('           A: %s' % ta[:56])
        w('           B: %s' % tb[:56])
    w('')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print('written: ' + OUT)
