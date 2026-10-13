# -*- coding: utf-8 -*-
"""禅道覆盖率 -> 知识库闭环（幂等，可重复跑）

用法（宿主机）：
  docker cp scripts/zentao_kb_loop.py <容器>:/tmp/
  docker exec <容器> python /tmp/zentao_kb_loop.py <report_id>            # 只写入知识库
  docker exec <容器> python /tmp/zentao_kb_loop.py <report_id> promote    # 写入并升级为跨版本通用
  docker exec <容器> python /tmp/zentao_kb_loop.py <report_id> promote all # 升级全部（含本版本专属）

说明：
  - 写操作前自动把将要变更的条目快照到 /tmp/kb_before.json，便于回滚；
  - push_report_to_knowledge 会调用 LLM 蒸馏（耗时数十秒~几分钟）；
  - 本脚本等价于前端「写入知识库」「升级为跨版本通用」两个按钮。
"""
import os, sys, json, datetime

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402
from apps.zentao.models import CoverageReport  # noqa: E402
from apps.zentao.services import (  # noqa: E402
    push_report_to_knowledge,
    promote_report_knowledge_to_global,
)
from apps.projects.models import ProjectKnowledge  # noqa: E402

LOG_PATH = '/tmp/zentao_kb_loop.txt'
lines = []


def w(msg=''):
    lines.append(str(msg))
    print(msg)


def dump_snapshot(project, path='/tmp/kb_before.json'):
    """把受影响的知识条目做 Before 快照，便于回滚。"""
    rows = []
    for e in ProjectKnowledge.objects.filter(project=project, source='zentao_coverage'):
        rows.append({
            'id': e.id,
            'title': e.title,
            'category': e.category,
            'version': (e.version.name if e.version else None),
            'version_id': e.version_id,
            'needs_review': e.needs_review,
            'is_active': e.is_active,
            'content_len': len(e.content or ''),
            'updated_at': e.updated_at.isoformat() if e.updated_at else None,
        })
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    w('快照已写入 %s（条目数=%d）' % (path, len(rows)))


def main():
    if len(sys.argv) < 2:
        w('用法: python zentao_kb_loop.py <report_id> [promote] [all]')
        return
    report_id = int(sys.argv[1])
    do_promote = 'promote' in sys.argv
    promote_all = 'all' in sys.argv

    report = CoverageReport.objects.filter(id=report_id).first()
    if not report:
        w('report %s 不存在' % report_id)
        return
    if report.status != 'success':
        w('report %s status=%s，仅成功报告可写入知识库' % (report_id, report.status))
        return

    project = report.config.project
    w('report=%s project=%s version=%s 覆盖率=%.1f%% 未覆盖=%s'
      % (report.id, project, report.version, report.coverage_rate, report.uncovered_bugs))

    before = ProjectKnowledge.objects.filter(
        project=project, source='zentao_coverage').count()
    w('写入前 zentao_coverage 条目数=%d' % before)
    dump_snapshot(project)

    w('--- 开始写入知识库（LLM 蒸馏中，请稍候） ---')
    res = push_report_to_knowledge(report)
    w('push 结果: %s' % res)

    after = ProjectKnowledge.objects.filter(
        project=project, source='zentao_coverage')
    w('写入后 zentao_coverage 条目数=%d' % after.count())
    w('')
    w('--- 本次涉及条目（title | needs_review | version | 长度） ---')
    for e in after.order_by('-updated_at'):
        flag = ''
        if e.updated_at and timezone.now() - e.updated_at < datetime.timedelta(minutes=30):
            flag = '  <= 本次更新'
        w('[id=%s] rev=%s ver=%s len=%d | %s%s'
          % (e.id, e.needs_review, (e.version.name if e.version else None),
             len(e.content or ''), e.title[:70], flag))

    if not do_promote:
        w('')
        w('未执行升级：条目仍为 needs_review=True，不会被 RAG 召回（需人工在项目知识库确认）。')
        return

    w('')
    w('--- 升级为跨版本通用（only_universal=%s） ---' % (not promote_all))
    p = promote_report_knowledge_to_global(report, only_universal=(not promote_all))
    w('promote 结果: %s' % p.get('message'))
    for t in p.get('promoted_titles', []):
        w('  [通用] %s' % t[:70])
    if p.get('skipped_version_only'):
        w('  另有 %d 条被判定为「本版本专属」未升级（可用 all 参数强制升级）'
          % p['skipped_version_only'])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        w('ERROR: %s' % exc)
        w(traceback.format_exc())
    finally:
        with open(LOG_PATH, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
