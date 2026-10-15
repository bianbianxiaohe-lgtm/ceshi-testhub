# -*- coding: utf-8 -*-
"""检查墨刀线 pass_criteria 判据在 P2 → P7 → P3 管道中的传递情况。

修复背景（2026-10-14）：
  P2 会产出 `pass_criteria`（功能级可观测判据），但 `modao_workflow.py` 在
  P7 三路合并构造 `combined` 时**只透传了 5 个字段**，导致该字段被静默丢弃；
  P7 输出 schema 里也没有该字段 ⇒ P3 拿到的是残缺输入，只能自行编造断言，
  最终回退成「页面展示正常」这类不可判伪的兜底句。

本脚本用于验证修复是否生效，输出两类判据：
  ① 管道打通性（二值，不需要多轮）：测试点里是否带有非空 pass_criteria；
  ② 断言质量（需多轮取均值）：不可判伪占比 / 功能级断言占比。

容器侧用法：
  docker cp scripts/_check_pass_criteria.py <容器>:/app/scripts/
  docker exec <容器> python /app/scripts/_check_pass_criteria.py <proto_pk> <page_id> [tag]
  docker cp <容器>:/tmp/_check_pass_criteria.txt <宿主路径>
"""
import json
import os
import re
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype  # noqa: E402

OUT = '/tmp/_check_pass_criteria.txt'
lines = []


def w(s=''):
    lines.append(s)


# 与 _compare_modao_cases.py 保持一致的口径
NOT_FALSIFIABLE = [
    '页面展示正常', '各图标与文案展示正确', '页面恢复正常状态',
    '无白屏', '破图', '资源缺失', '展示正确', '显示正常', '样式正常',
]
FUNCTIONAL = [
    '跳转', 'toast', '提示', '显示', '消失', '出现', '增加', '减少',
    '成功', '失败', '错误', '接口', '字段', '返回', '状态', '列表',
]

FILLER_ONLY = re.compile(r'^(页面展示正常|显示正常|展示正确|恢复正常|无异常|正常显示)[。．、\s]*$')


def case_text(c):
    return json.dumps(c, ensure_ascii=False)


def main():
    if len(sys.argv) < 3:
        w('usage: _check_pass_criteria.py <proto_pk> <page_id> [tag]')
        return
    pk = int(sys.argv[1])
    page_id = int(sys.argv[2])
    tag = sys.argv[3] if len(sys.argv) > 3 else 'current'

    proto = ModaoPrototype.objects.filter(pk=pk).first()
    if not proto:
        w(f'proto {pk} NOT FOUND')
        return
    page = proto.pages.filter(id=page_id).first()
    if not page:
        w(f'page {page_id} NOT FOUND in proto {pk}')
        return

    w('=' * 70)
    w(f'pass_criteria 管道传递检查   proto={pk} page={page_id} tag={tag}')
    w('=' * 70)

    # ---- ① 测试点层：pass_criteria 填充率 ----
    tps = json.loads(page.page_testpoints_json or '[]')
    tp_total = len(tps)
    tp_filled = 0
    tp_filler = 0
    for t in tps:
        if not isinstance(t, dict):
            continue
        pc = (t.get('pass_criteria') or '').strip()
        if not pc:
            continue
        tp_filled += 1
        if FILLER_ONLY.match(pc):
            tp_filler += 1

    w('')
    w('[测试点层 page_testpoints_json]')
    w(f'  条数                : {tp_total}')
    w(f'  带 pass_criteria    : {tp_filled}  ({_pct(tp_filled, tp_total)})')
    w(f'  其中仅为兜底句      : {tp_filler}  ({_pct(tp_filler, tp_filled)})')

    # ---- ② 用例层：断言质量 ----
    cases_raw = json.loads(page.page_testcases_json or '[]')
    cases = []
    for c in cases_raw:
        if not isinstance(c, dict):
            continue
        cases.append(c.get('testcase', c) if isinstance(c.get('testcase'), dict) else c)

    c_total = len(cases)
    c_notf = 0
    c_func = 0
    c_carries = 0
    for c in cases:
        txt = case_text(c)
        low = txt.lower()
        if any(k in txt for k in NOT_FALSIFIABLE):
            c_notf += 1
        if any(k in low for k in FUNCTIONAL):
            c_func += 1
        exp = str(c.get('expected') or '')
        # 判据继承痕迹：expected 中含「跳转/接口/字段/文案/数值」类功能级写法
        if re.search(r'跳转|接口|字段|toast|提示|第\s*\d+\s*项|一致', exp):
            c_carries += 1

    w('')
    w('[用例层 page_testcases_json]')
    w(f'  条数                : {c_total}')
    if c_total:
        w(f'  不可判伪断言占比    : {c_notf}/{c_total} = {c_notf * 100.0 / c_total:.1f}%')
        w(f'  功能级断言占比      : {c_func}/{c_total} = {c_func * 100.0 / c_total:.1f}%')
        w(f'  继承上游判据迹象    : {c_carries}/{c_total} = {c_carries * 100.0 / c_total:.1f}%')

    verdict = 'PASS' if tp_total and tp_filled == tp_total else (
        'PARTIAL' if tp_filled else 'FAIL')
    w('')
    w(f'管道打通性 = {verdict}   (期望：全部测试点均带非空 pass_criteria)')


def _pct(a, b):
    return f'{a * 100.0 / b:.1f}%' if b else 'n/a'


try:
    main()
except Exception as e:
    w('')
    w(f'ERROR: {e}')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
