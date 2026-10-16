# -*- coding: utf-8 -*-
"""自愈闭环(P0) diff 分类逻辑自测（不碰 DB，构造样本直接调 diff_one）。

验证三类分类是否正确：
  - 冗余(redundant)：AI 有、采纳无（被删/合并）
  - 疏漏(missing)：采纳有、AI 无（人工新增）
  - 改写(rewritten)：两边匹配但 expected 文本差异大
"""
import json
import os
import sys

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/scripts')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

import _diff_ai_vs_adopted as M  # noqa: E402


class FakeProto:
    """ai_testcases_json 非空时 diff_one 不会访问 pages，故无需实现。"""
    ai_testcases_json = ''
    merged_testcases_json = ''


def _case(title, desc, expected):
    return {'title': title, 'description': desc, 'expected': expected, 'steps': '1.操作'}


def main():
    A = _case('登录成功', '输入正确账号密码', '进入首页')
    B = _case('登录失败', '密码错误', '提示错误')
    C = _case('退出登录', '点击退出', '回到登录页')
    D = _case('异地登录', '新设备登录', '要求短信验证')
    A_edited = _case('登录成功', '输入正确账号密码', '进入首页并刷新 token')  # expected 被人工改写

    ai = [A, B, C]
    merged = [A_edited, C, D]  # B 被删(冗余), D 新增(疏漏), A expected 改(改写)

    p = FakeProto()
    p.ai_testcases_json = json.dumps(ai, ensure_ascii=False)
    p.merged_testcases_json = json.dumps(merged, ensure_ascii=False)
    r = M.diff_one(p)

    red_titles = {t.get('title') for t in r['redundant']}
    mis_titles = {t.get('title') for t in r['missing']}
    rew_titles = {w['ai'].get('title') for w in r['rewritten']}

    checks = []
    checks.append(('冗余=B', '登录失败' in red_titles))
    checks.append(('疏漏=D', '异地登录' in mis_titles))
    checks.append(('改写=A', '登录成功' in rew_titles))
    checks.append(('冗余不含A/C', not ('登录成功' in red_titles or '退出登录' in red_titles)))
    checks.append(('疏漏不含A/C', not ('登录成功' in mis_titles or '退出登录' in mis_titles)))

    ok = all(passed for _, passed in checks)
    lines = ['自测结果：' + ('PASS' if ok else 'FAIL')]
    for name, passed in checks:
        lines.append(f"  [{'OK' if passed else 'XX'}] {name}")
    lines.append(f"  redundant={red_titles} missing={mis_titles} rewritten={rew_titles}")
    out = '\n'.join(lines)
    with open('/tmp/_selftest_diff.txt', 'w', encoding='utf-8') as f:
        f.write(out + '\n')
    print(out)


if __name__ == '__main__':
    main()
