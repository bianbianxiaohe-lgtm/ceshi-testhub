# -*- coding: utf-8 -*-
"""墨刀线自愈闭环(P0)：逐任务 diff「AI 原始生成」vs「最终采纳(含人工新增/修改)」。

目的：在人工确认/采纳结束后，量化 AI 生成的偏差，为后续自愈（知识库/提示词调优）积累信号。
  - 冗余(redundant)：AI 生成、最终采纳里没有（被人工删除/合并）
  - 疏漏(missing)：最终采纳里有、AI 没生成（人工新增，可细分业务理解/场景/补充）
  - 改写(rewritten)：两边都能匹配上、但 expected/steps 文本差异大（措辞/断言粒度偏好）

对比素材（已分开存储）：
  - AI 原始：proto.ai_testcases_json（任务级快照，P3 完成后一次性写入，不随人工编辑变化）；
            若该字段为空则回退聚合各画布 page_ai_testcases_json。
  - 最终采纳：proto.merged_testcases_json（approve_pages 汇总已采纳画布，含人工编辑/新增）。

匹配策略：用例以 (title + description) 拼接做字符 2-gram Jaccard 相似度；
  ≥ SIM_THRESHOLD(0.6) 视为同一用例，避免措辞变化误判为疏漏。

容器侧用法：
  docker cp scripts/_diff_ai_vs_adopted.py <容器>:/app/scripts/
  docker exec <容器> python /app/scripts/_diff_ai_vs_adopted.py [proto_pk ...]
  docker cp <容器>:/tmp/_diff_ai_vs_adopted.txt <宿主路径>

输出：/tmp/_diff_ai_vs_adopted.txt
"""
import json
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype  # noqa: E402

SIM_THRESHOLD = 0.6


def _norm(s):
    return (s or '').strip().lower()


def _case_inner(c):
    """用例可能是 {testcase:{...}, module, _raw} 嵌套结构，统一展开取真实用例体。"""
    if not isinstance(c, dict):
        return {}
    inner = c.get('testcase', c)
    return inner if isinstance(inner, dict) else c


def _bigrams(s):
    s = _norm(s)
    if len(s) <= 1:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _jaccard(a, b):
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga and not gb:
        return 1.0
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _key(tc):
    inner = _case_inner(tc)
    return _norm(inner.get('title', '')) + '\n' + _norm(inner.get('description', ''))


def _load_list(raw):
    try:
        v = json.loads(raw or '[]')
    except Exception:
        return []
    return v if isinstance(v, list) else []


def _best_sim(key, others):
    best = 0.0
    for o in others:
        s = _jaccard(key, _key(o))
        if s > best:
            best = s
    return best


def diff_one(proto):
    # AI 原始：优先任务级快照，否则聚合画布级
    ai = _load_list(proto.ai_testcases_json)
    if not ai:
        ai = []
        for p in proto.pages.all():
            ai.extend(_load_list(p.page_ai_testcases_json))
    merged = _load_list(proto.merged_testcases_json)

    if not ai:
        return {'proto': proto, 'skipped': True, 'reason': '无 AI 原始快照(老任务或未跑 P3)',
                'ai_n': 0, 'merged_n': len(merged)}
    if not merged:
        return {'proto': proto, 'skipped': True, 'reason': '无最终采纳(未 approve_pages)',
                'ai_n': len(ai), 'merged_n': 0}

    ai_keys = [_key(t) for t in ai]
    merged_keys = [_key(t) for t in merged]

    redundant, missing, rewritten = [], [], []
    for i, t in enumerate(ai):
        sim = _best_sim(ai_keys[i], merged)
        if sim < SIM_THRESHOLD:
            redundant.append(t)
        else:
            # 找最匹配的 merged 用例，比较 expected/steps 文本差异
            best_j, best_s = -1, 0.0
            for j, mk in enumerate(merged_keys):
                s = _jaccard(ai_keys[i], mk)
                if s > best_s:
                    best_s, best_j = s, j
            if best_j >= 0:
                a_exp = _norm(_case_inner(t).get('expected', ''))
                m_exp = _norm(_case_inner(merged[best_j]).get('expected', ''))
                if a_exp and m_exp and _jaccard(a_exp, m_exp) < 0.6:
                    rewritten.append({'ai': t, 'adopted': merged[best_j]})

    for j, t in enumerate(merged):
        sim = _best_sim(merged_keys[j], ai)
        if sim < SIM_THRESHOLD:
            missing.append(t)

    return {
        'proto': proto, 'skipped': False,
        'ai_n': len(ai), 'merged_n': len(merged),
        'redundant': redundant, 'missing': missing, 'rewritten': rewritten,
    }


def main():
    pks = [int(x) for x in sys.argv[1:] if x.isdigit()]
    qs = ModaoPrototype.objects.all()
    if pks:
        qs = qs.filter(pk__in=pks)
    lines = []
    total = {'task': 0, 'skipped': 0, 'ai': 0, 'merged': 0,
             'redundant': 0, 'missing': 0, 'rewritten': 0}
    for proto in qs.order_by('-pk'):
        r = diff_one(proto)
        total['task'] += 1
        if r['skipped']:
            total['skipped'] += 1
            lines.append(f"[{proto.pk}] SKIP({r['reason']}) ai={r['ai_n']} merged={r['merged_n']}")
            continue
        total['ai'] += r['ai_n']
        total['merged'] += r['merged_n']
        total['redundant'] += len(r['redundant'])
        total['missing'] += len(r['missing'])
        total['rewritten'] += len(r['rewritten'])
        lines.append('=' * 70)
        lines.append(f"[{proto.pk}] 模块={proto.feature_module_id} 状态={proto.status}")
        lines.append(f"  AI原始={r['ai_n']}  最终采纳={r['merged_n']}")
        lines.append(f"  冗余(被删/合并)={len(r['redundant'])}  疏漏(人工新增)={len(r['missing'])}  "
                     f"改写(断言差异)={len(r['rewritten'])}")
        if r['redundant']:
            lines.append('  -- 冗余(示例最多5) --')
            for t in r['redundant'][:5]:
                lines.append(f"    · {t.get('title', '')[:40]} | {_norm(t.get('description', ''))[:50]}")
        if r['missing']:
            lines.append('  -- 疏漏/人工新增(示例最多5) --')
            for t in r['missing'][:5]:
                lines.append(f"    + {t.get('title', '')[:40]} | {_norm(t.get('description', ''))[:50]}")
        if r['rewritten']:
            lines.append('  -- 改写(断言差异示例最多3) --')
            for w in r['rewritten'][:3]:
                lines.append(f"    ~ {w['ai'].get('title', '')[:40]}")
                lines.append(f"      AI.expected : {_norm(w['ai'].get('expected', ''))[:60]}")
                lines.append(f"      采纳.expected: {_norm(w['adopted'].get('expected', ''))[:60]}")

    lines.append('=' * 70)
    lines.append(f"汇总：任务={total['task']} 跳过={total['skipped']} "
                 f"AI合计={total['ai']} 采纳合计={total['merged']}")
    lines.append(f"  冗余合计={total['redundant']}  疏漏合计={total['missing']}  改写合计={total['rewritten']}")
    if total['ai']:
        lines.append(f"  冗余率={total['redundant'] / total['ai'] * 100:.1f}%  "
                     f"疏漏率={total['missing'] / max(total['merged'], 1) * 100:.1f}%")
    out = '\n'.join(lines)
    with open('/tmp/_diff_ai_vs_adopted.txt', 'w', encoding='utf-8') as f:
        f.write(out + '\n')
    print(out)


if __name__ == '__main__':
    main()
