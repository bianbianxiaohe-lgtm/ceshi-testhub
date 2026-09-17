"""comprehensive 模式用例去冗余后处理器（方案2 工程化兜底）。

背景：纯 prompt 约束无法稳定控制 LLM 的组合爆炸（真实需求下 comprehensive 模式
曾产生约 250 条「贴纸数量为0张时分享图片生成X无异常」式同义反复枚举）。
本模块在 LLM 生成完成后做确定性后处理，把同义反复族折叠为代表性用例。

策略：
  1. 解析 8 列 markdown 用例表。
  2. 完全重复测试目标去重（忽略 ID 与空白）。
  3. 同义反复族折叠：收集所有「以尾标记结尾（无异常/正常/无问题…）」的用例，
     按「关联需求」分组；组内用连通分量（两两最长公共前缀 >=5 字即连边）聚类，
     分量 >=3 折叠为 1 条代表性用例（取目标最长者），并在预期后追加合并说明。
  4. 重新编号（保持 ID 前缀）。

设计目标：确定性、可解释、不依赖具体业务名词表，能稳定收敛名词全排列式爆炸。
"""
import re
from collections import defaultdict

CASE_RE = re.compile(
    r'^\|\s*([A-Za-z0-9_]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$'
)
SEP_RE = re.compile(r'^\s*\|[\s:|-]+\|\s*$')

# 同义反复尾标记：测试目标以这些词结尾且前缀相同，中间差异视为枚举值
SUFFIX_MARKERS = ('无异常', '正常', '无问题', '不报错', '无越界', '无错误', '一致', '不卡顿')


def _common_prefix(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return a[:i]


def _normalize(text):
    return re.sub(r'\s+', '', text or '')


def parse_cases(text):
    """返回 (header_line, sep_line, [case_dict,...], other_lines)。"""
    lines = text.splitlines()
    cases = []
    header = None
    sep = None
    other = []
    for ln in lines:
        if CASE_RE.match(ln):
            m = CASE_RE.match(ln)
            gid, goal, pre, step, exp, prio, ctype, rel = [m.group(i).strip() for i in range(1, 9)]
            cases.append({
                'raw': ln, 'id': gid, 'goal': goal, 'pre': pre,
                'step': step, 'exp': exp, 'prio': prio,
                'ctype': ctype, 'rel': rel, 'keep': True, 'merged_from': []
            })
        elif SEP_RE.match(ln):
            sep = ln
        elif re.match(r'^\|\s*用例ID', ln):
            header = ln
        else:
            other.append(ln)
    return header, sep, cases, other


def dedupe_comprehensive(text):
    """对 comprehensive 模式输出做确定性去冗余，返回 (处理后文本, 原始数, 保留数, 删除数)。"""
    header, sep, cases, other = parse_cases(text)
    if not cases:
        return text, 0, 0, 0

    # 1) 完全重复目标去重（忽略 ID 与空白）
    seen = {}
    for c in cases:
        key = _normalize(c['goal'])
        if key in seen:
            c['keep'] = False
            seen[key]['merged_from'].append(c['id'])
        else:
            seen[key] = c

    # 2) 同义反复族折叠（连通分量）
    by_rel = {}
    for c in cases:
        if not c['keep']:
            continue
        by_rel.setdefault(c['rel'] or '__none__', []).append(c)

    for rel, group in by_rel.items():
        marked = [(c, next(sm for sm in SUFFIX_MARKERS if c['goal'].endswith(sm)))
                  for c in group if any(c['goal'].endswith(sm) and len(c['goal']) > len(sm) for sm in SUFFIX_MARKERS)]
        n = len(marked)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(n):
            for j in range(i + 1, n):
                if len(_common_prefix(marked[i][0]['goal'], marked[j][0]['goal'])) >= 5:
                    union(i, j)

        comps = defaultdict(list)
        for i in range(n):
            comps[find(i)].append(marked[i])

        for comp in comps.values():
            if len(comp) >= 3:
                members = [c for c, _ in comp]
                sm = comp[0][1]
                anchor = members[0]['goal']
                mids = [x['goal'][len(_common_prefix(anchor, x['goal'])): len(x['goal']) - len(sm)] for x in members]
                rep = max(members, key=lambda x: len(x['goal']))
                for c in members:
                    if c is not rep:
                        c['keep'] = False
                        rep['merged_from'].append(c['id'])
                rep['exp'] = rep['exp'].rstrip('。') + \
                    f'。（已合并 {len(members)} 条同构枚举：' + '/'.join(mids[:12]) + ('…' if len(mids) > 12 else '') + '）'

    kept = [c for c in cases if c['keep']]
    removed = len(cases) - len(kept)

    # 3) 重新编号（按原 ID 前缀分组各自从 001 续编，保留模块归类）
    out_lines = list(other)
    if header:
        out_lines.append(header)
    if sep:
        out_lines.append(sep)

    # 解析每条保留用例的原始前缀，按前缀独立计数
    def _prefix_of(cid):
        m = re.match(r'^([A-Za-z]+)_', cid)
        return m.group(1) if m else 'CASE'

    counters = defaultdict(int)
    for c in kept:
        pfx = _prefix_of(c['id'])
        counters[pfx] += 1
        new_id = f'{pfx}_{counters[pfx]:03d}'
        out_lines.append(
            f'| {new_id} | {c["goal"]} | {c["pre"]} | {c["step"]} | {c["exp"]} | {c["prio"]} | {c["ctype"]} | {c["rel"]} |'
        )
    return '\n'.join(out_lines), len(cases), len(kept), removed
