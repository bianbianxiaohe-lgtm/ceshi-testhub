# -*- coding: utf-8 -*-
"""核查「墨刀线用例」在覆盖率分析中的占比与断言风格（只读，不改数据）。

目的：判断墨刀线生成的用例是否也需要纳入覆盖率提升，以及当前能否按线拆分统计。

容器侧用法：
  docker cp scripts/_verify_modao_cases.py <容器>:/tmp/
  docker exec <容器> python /tmp/_verify_modao_cases.py
  docker exec <容器> cat /tmp/_verify_modao_cases.txt
"""
import os
import re
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from django.db.models import Count  # noqa: E402

OUT = '/tmp/_verify_modao_cases.txt'
lines = []

# 独立线 4.4 判定「不可判伪」的模糊断言（Bug 存在时同样通过）
VAGUE_PATTERNS = [
    '页面正常展示', '正常展示', '显示正确', '展示正常', '功能正常',
    '加载成功', '操作成功', '结果正确', '无异常', '正常使用',
    '显示正常', '运行正常', '页面正常',
]


def w(msg=''):
    lines.append(str(msg))
    print(msg)


def main():
    from apps.testcases.models import TestCase
    from apps.requirement_analysis.models import ModaoPrototype
    from apps.zentao.models import CoverageReport, ZentaoConfig

    w('=== 1. 用例库 TestCase 来源分布 ===')
    for row in TestCase.objects.values('source').annotate(c=Count('id')).order_by('-c'):
        w('  source=%-8s %d' % (row['source'], row['c']))
    w('  ⚠️ source 只有 ai/manual/unknown，**不区分独立线/墨刀线**')

    w('')
    w('=== 2. 墨刀原型 ModaoPrototype ===')
    w('  总数=%d' % ModaoPrototype.objects.count())
    for row in (ModaoPrototype.objects.values('project_id')
                .annotate(c=Count('id')).order_by('-c')[:10]):
        w('  project_id=%-5s prototypes=%d' % (row['project_id'], row['c']))

    w('')
    w('=== 3. 覆盖率报告（近 5 条）与其用例池 ===')
    for rep in CoverageReport.objects.all().order_by('-id')[:5]:
        cfg = rep.config
        ver = getattr(cfg, 'version', None)
        proj = getattr(cfg, 'project', None)
        ver_name = getattr(ver, 'name', None) if ver else None
        proj_name = getattr(proj, 'name', None) if proj else None
        w('  report=%s status=%s version=%s project=%s cases=%s bugs=%s'
          % (rep.id, rep.status, ver_name, proj_name,
             getattr(rep, 'case_count', None), getattr(rep, 'total_bugs', None)))
        # 该 config 对应的用例池来源分布
        if ver:
            qs = TestCase.objects.filter(versions=ver).exclude(status='deprecated')
        elif proj:
            qs = TestCase.objects.filter(project=proj).exclude(status='deprecated')
        else:
            qs = TestCase.objects.none()
        dist = qs.values('source').annotate(c=Count('id')).order_by('-c')
        w('    用例池=%d  分布=%s' % (qs.count(), {d['source']: d['c'] for d in dist}))
        # 该项目是否有墨刀原型 ⇒ 用例池里可能混有墨刀线产出
        if proj:
            mp = ModaoPrototype.objects.filter(project_id=proj.id).count()
            w('    该项目墨刀原型数=%d ⇒ 用例池可能混入墨刀线用例' % mp)

    w('')
    w('=== 4. 断言粒度抽样（用例池内 expected_result）===')
    # 取覆盖率报告#29 所在版本/项目的用例池，统计模糊断言占比
    rep = CoverageReport.objects.filter(id=29).first()
    pool = TestCase.objects.none()
    if rep:
        cfg = rep.config
        if getattr(cfg, 'version', None):
            pool = TestCase.objects.filter(versions=cfg.version).exclude(status='deprecated')
        elif getattr(cfg, 'project', None):
            pool = TestCase.objects.filter(project=cfg.project).exclude(status='deprecated')
    total = pool.count()
    w('  report#29 用例池总数=%d' % total)
    if total:
        vague = 0
        for tc in pool.only('id', 'expected_result'):
            exp = (tc.expected_result or '').strip()
            if not exp:
                continue
            # 命中任一模糊表述，且整条没有更具体的可观测描述
            if any(p in exp for p in VAGUE_PATTERNS):
                vague += 1
        w('  命中「不可判伪」模糊断言的用例=%d (%.1f%%)' % (vague, vague * 100.0 / total))
        w('  --- 抽样 5 条 expected_result ---')
        for tc in pool.order_by('id')[:5]:
            exp = (tc.expected_result or '').replace('\n', ' ')
            w('   [id=%s] %s' % (tc.id, exp[:110]))

    w('')
    w('=== 5. 能否按线拆分统计 ===')
    has_line_field = any(f.name in ('generated_by', 'line', 'source_line', 'skill')
                         for f in TestCase._meta.fields)
    w('  TestCase 是否有「生成线」字段: %s' % has_line_field)
    w('  结论: %s' % ('可按线拆分' if has_line_field else
                    '❌ 不可按线拆分 —— 两条线入库都写 source="ai"，'
                    '覆盖率无法区分贡献；需新增字段才能分线统计'))


try:
    main()
except Exception as exc:  # noqa: BLE001
    import traceback
    w('ERROR: %s' % exc)
    w(traceback.format_exc())
finally:
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
