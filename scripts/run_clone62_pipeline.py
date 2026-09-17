# -*- coding: utf-8 -*-
"""克隆任务62的原始需求为新任务，用新流程跑 阶段1→2→3（收敛效果验证）。
原任务62数据完全不动；新任务标题带「（复测-收敛验证）」后缀。
"""
import os
import sys
import json
import uuid
import traceback

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()

from apps.requirement_analysis.models import ModaoPrototype
from apps.requirement_analysis.modao_views import _build_wf

SRC_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 62
SUFFIX = sys.argv[2] if len(sys.argv) > 2 else '（复测-收敛验证）'


def main():
    src = ModaoPrototype.objects.get(id=SRC_ID)
    clone = ModaoPrototype(
        uuid=uuid.uuid4().hex[:32],
        title=src.title + SUFFIX,
        url=src.url,
        source_type=src.source_type,
        auth_cookie=src.auth_cookie,
        project=src.project,
        created_by=src.created_by,
        extracted_json=src.extracted_json,
        requirement_summary='',
        clarification_log='',
        module_split='',
        risks_json='',
        pci_json='',
        final_testpoints_json='',
        testcases_json='',
        smoke_json='',
        quality_report_json='',
        stage_confirmations='{}',
        status='pending',
        current_stage=0,
        work_log='',
        error_message='',
        dedup_audit_json='[]',
        qa_log='[]',
    )
    clone.save()
    print('CLONE_CREATED id=%s title=%s' % (clone.id, clone.title), flush=True)

    def set_confirm(stage):
        conf = clone.get_confirmations()
        conf['stage%d_confirmed' % stage] = True
        clone.stage_confirmations = json.dumps(conf, ensure_ascii=False)
        clone.save(update_fields=['stage_confirmations'])

    wf = _build_wf(clone)
    try:
        wf.run_struct()
        clone.refresh_from_db()
        print('STAGE1_DONE status=%s summary_len=%s' % (clone.status, len(clone.requirement_summary or '')), flush=True)
        set_confirm(1)

        wf.run_clarify()
        clone.refresh_from_db()
        print('STAGE2_DONE clarification_len=%s' % len(clone.clarification_log or ''), flush=True)
        set_confirm(2)

        wf.run_design_phase1()
        clone.refresh_from_db()
        print('STAGE3_DONE status=%s' % clone.status, flush=True)

        total = 0
        counts = {}
        try:
            pci = json.loads(clone.pci_json or '[]')
            for mod in pci if isinstance(pci, list) else []:
                items = ((mod.get('data') or {}) if isinstance(mod, dict) else {}).get('pci_list') or []
                for it in items:
                    if isinstance(it, dict):
                        total += 1
                        imp = (it.get('impact') or '').lower()
                        counts[imp] = counts.get(imp, 0) + 1
        except Exception as e:
            print('PCI_STAT_ERR %r' % (e,), flush=True)
        print('PCI_TOTAL %s BY_IMPACT %s' % (total, counts), flush=True)
        print('DONE', flush=True)
    except Exception as e:
        traceback.print_exc()
        try:
            clone.refresh_from_db()
            clone.status = 'failed'
            clone.error_message = '复测脚本失败: ' + str(e)[:500]
            clone.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
        print('FAILED %r' % (e,), flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
