# -*- coding: utf-8 -*-
"""对比墨刀线「旧提示词 vs 新提示词」生成的用例质量。

输入：两份快照（由 _dump_modao_page.py 导出）
  /tmp/_dump_modao_before.json   旧提示词（2026-08-26 版）产物
  /tmp/_dump_modao_after.json    新提示词（2026-10-13 版）产物

判据（与 report#29 一致口径，见 _verify_modao_cases.py 的 VAGUE_PATTERNS）：
  1. 用例条数
  2. 「不可判伪」模糊断言占比 —— 本次改动的**首要目标**
  3. 历史缺陷高发维度覆盖条数 —— 本次改动的次要目标

用法：
  docker exec testhub-dev-backend-1 python /app/scripts/_compare_modao_cases.py
  docker exec testhub-dev-backend-1 cat /tmp/_compare_modao_cases.txt
"""
import json
import os
import re
import sys

OUT = '/tmp/_compare_modao_cases.txt'
lines = []


def w(msg=''):
    lines.append(str(msg))


# 与 _verify_modao_cases.py 完全一致的模糊断言词表（保持口径）
VAGUE_PATTERNS = [
    '页面正常展示', '正常展示', '显示正确', '展示正常', '功能正常',
    '加载成功', '操作成功', '结果正确', '无异常', '正常使用',
    '显示正常', '运行正常', '页面正常',
]
# 墨刀线特有的兜底句（本次提示词明确禁止"单独成条"的那些）
MODAO_VAGUE = [
    '无白屏', '破图', '资源缺失', '恢复正常状态', '流畅无卡顿',
    '展示正常', '页面展示正常', '各图标与文案展示正确',
]
ALL_VAGUE = VAGUE_PATTERNS + MODAO_VAGUE

# 历史缺陷高发维度（本次新增：再次执行/刷新回撤/权益边界/中断恢复）
# ⚠️ 关键词口径坑（2026-10-13 实测）：第一版写成「重新生成/再次提交/重复打开」这类
#    **固定组合**，结果漏掉了真实存在的覆盖——新用例标题是「支付回调延迟与重复回调」，
#    用的是「重复回调」，属幂等/再次执行场景，但组合词没命中 ⇒ 误判为 0。
#    ⇒ 维度覆盖要用「单/双字根」（重复、再次、二次、连续、过期…）而非固定短语，
#      且**必须用标题列表人工交叉验证**（见 _list_modao_titles.py）。
DIMENSIONS = {
    '① 再次执行': ['重复', '再次', '二次', '多次', '连续', '幂等'],
    '② 刷新与回撤': ['下拉刷新', '返回键', '返回', '快速点击', '防抖', '回撤'],
    '③ 权益边界': ['过期', '到期', '续费', '会员等级', '会员状态'],
    '④ 中断恢复': ['杀进程', '重新登录', '退出重登', '中断', '来电', '切后台',
                   '弱网', '超时', '恢复网络', '断网'],
}
# 功能级可观测断言的正向特征（提示词要求至少含 1 个）
OBSERVABLE = ['跳转', 'URL', '字段', '提示', '显示', '文案', '秒', '%', '条', '接口', '状态']


def load(tag):
    path = '/tmp/_dump_modao_%s.json' % tag
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def try_parse(text):
    """尽力解析用例文本：JSON → YAML-ish → None"""
    if not text or not text.strip():
        return None
    t = text.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    try:
        import yaml
        return yaml.safe_load(t)
    except Exception:
        pass
    return None


def find_case_dicts(obj, depth=0):
    """递归找出所有疑似「一条用例」的 dict。"""
    if depth > 6:
        return []
    out = []
    if isinstance(obj, dict):
        keys = set(obj.keys())
        # 一条用例通常含 预期/expected 或 步骤/steps 或 标题/title
        marker = any(k for k in keys if re.search(
            r'expected|预期|steps|步骤|title|用例标题|用例名称', str(k), re.I))
        if marker:
            out.append(obj)
        for v in obj.values():
            out.extend(find_case_dicts(v, depth + 1))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(find_case_dicts(v, depth + 1))
    return out


def case_text(c):
    """把一条用例拼成可检索的文本。"""
    parts = []
    for k, v in c.items():
        if isinstance(v, (str, int, float)):
            parts.append('%s=%s' % (k, v))
        elif isinstance(v, list):
            parts.append('%s=%s' % (k, ' / '.join(str(x) for x in v)))
        elif isinstance(v, dict):
            parts.append('%s=%s' % (k, ' / '.join('%s:%s' % (a, b) for a, b in v.items())))
    return ' | '.join(parts)


def expected_of(c):
    """取该条用例的「预期结果」文本（字段名不统一，尽量覆盖）。"""
    for k in c.keys():
        if re.search(r'expected|预期结果|预期', str(k), re.I):
            v = c[k]
            if isinstance(v, str):
                return v
            if isinstance(v, list):
                return ' / '.join(str(x) for x in v)
            if isinstance(v, dict):
                return ' / '.join('%s:%s' % (a, b) for a, b in v.items())
    return ''


def analyse(tag, data):
    w('')
    w('=' * 68)
    w('[%s] %s' % (tag.upper(), '旧提示词(2026-08-26版)' if tag == 'before'
                   else '新提示词(2026-10-13版)'))
    w('=' * 68)
    pf = data['page']['fields']
    for f in ('page_testpoints_json', 'page_testcases_json'):
        w('  %-22s len=%d' % (f, len(pf.get(f) or '')))

    raw = pf.get('page_testcases_json') or ''
    w('  --- 原始文本头部 400 字符 ---')
    w('  ' + raw[:400].replace('\n', ' \\n '))

    obj = try_parse(raw)
    w('  解析结果 type=%s' % type(obj).__name__)
    if isinstance(obj, dict):
        w('  顶层 keys=%s' % list(obj.keys())[:15])
    elif isinstance(obj, list):
        w('  顶层为数组，len=%d，首元素 keys=%s'
          % (len(obj), list(obj[0].keys())[:15] if obj and isinstance(obj[0], dict) else '-'))

    cases = find_case_dicts(obj) if obj is not None else []
    # 去重（同一条可能被递归多次命中）
    uniq, seen = [], set()
    for c in cases:
        key = json.dumps(c, sort_keys=True, ensure_ascii=False)[:200]
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    cases = uniq
    w('  识别用例条数 = %d' % len(cases))

    if not cases:
        w('  ⚠️ 结构化解析失败，退化为「整段文本」统计')
        blob = raw
        vague = sum(1 for p in ALL_VAGUE if p in blob)
        w('     文本级命中模糊词种类=%d：%s'
          % (vague, [p for p in ALL_VAGUE if p in blob]))
        return {'n': 0}

    vague_n, obs_n = 0, 0
    dim_hit = {k: 0 for k in DIMENSIONS}
    for c in cases:
        txt = case_text(c)
        exp = expected_of(c)
        if any(p in (exp or txt) for p in ALL_VAGUE):
            vague_n += 1
        if any(p in (exp or txt) for p in OBSERVABLE):
            obs_n += 1
        for d, kws in DIMENSIONS.items():
            if any(kw in txt for kw in kws):
                dim_hit[d] += 1

    n = len(cases)
    w('  --- 指标 ---')
    w('  用例条数                 = %d' % n)
    w('  命中不可判伪断言         = %d (%.1f%%)' % (vague_n, vague_n * 100.0 / n))
    w('  含功能级可观测断言       = %d (%.1f%%)' % (obs_n, obs_n * 100.0 / n))
    for d in DIMENSIONS:
        w('  覆盖 %-14s = %d' % (d, dim_hit[d]))
    w('  --- 预期结果抽样（前 6 条）---')
    for i, c in enumerate(cases[:6], 1):
        exp = expected_of(c) or case_text(c)
        w('   [%d] %s' % (i, exp[:130].replace('\n', ' ')))
    return {'n': n, 'vague': vague_n, 'obs': obs_n, 'dim': dim_hit}


before = load('before')
after = load('after')
rb = analyse('before', before)
ra = analyse('after', after)

w('')
w('=' * 68)
w('汇总对比')
w('=' * 68)
if rb.get('n') and ra.get('n'):
    w('  用例条数           : %d → %d (%+d)' % (rb['n'], ra['n'], ra['n'] - rb['n']))
    vb = rb['vague'] * 100.0 / rb['n']
    va = ra['vague'] * 100.0 / ra['n']
    w('  不可判伪断言占比   : %.1f%% → %.1f%% (%+.1f 个百分点)' % (vb, va, va - vb))
    w('  功能级断言占比     : %.1f%% → %.1f%%' % (
        rb['obs'] * 100.0 / rb['n'], ra['obs'] * 100.0 / ra['n']))
    for d in DIMENSIONS:
        w('  %-16s : %d → %d' % (d, rb['dim'][d], ra['dim'][d]))
else:
    w('  ⚠️ 至少一侧未能解析出用例条目，无法给出量化对比（见上方解析结果）')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
