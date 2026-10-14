# -*- coding: utf-8 -*-
"""导出墨刀 proto / page 的产物快照，用于「新旧提示词对比」与回滚。

用法（容器内）：
  python /app/scripts/_dump_modao_page.py <proto_id> <page_id> <tag>
例：
  python /app/scripts/_dump_modao_page.py 65 722 before

输出：/tmp/_dump_modao_<tag>.json
之后在宿主机取回：
  docker cp testhub-dev-backend-1:/tmp/_dump_modao_before.json <本地目录>
"""
import json
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype, ModaoPage  # noqa: E402

proto_id = int(sys.argv[1])
page_id = int(sys.argv[2])
tag = sys.argv[3] if len(sys.argv) > 3 else 'snap'

PAGE_FIELDS = [
    'page_summary', 'page_clarification', 'page_testpoints_json',
    'page_testcases_json', 'page_smoke_json',
]
PROTO_FIELDS = [
    'extracted_json', 'requirement_summary', 'clarification_log', 'module_split',
    'risks_json', 'pci_json', 'final_testpoints_json', 'dedup_audit_json',
    'testcases_json', 'smoke_json', 'quality_report_json',
    'merged_testcases_json', 'merged_smoke_json',
]

out = {'tag': tag, 'proto_id': proto_id, 'page_id': page_id}

p = ModaoPrototype.objects.get(pk=proto_id)
out['proto'] = {
    'status': p.status,
    'current_stage': p.current_stage,
    'updated_at': str(p.updated_at),
    'fields': {f: getattr(p, f, '') or '' for f in PROTO_FIELDS},
}

pg = ModaoPage.objects.get(pk=page_id)
out['page'] = {
    'page_no': pg.page_no,
    'page_name': pg.page_name,
    'current_stage': pg.current_stage,
    'stage_status': pg.stage_status,
    'fields': {f: getattr(pg, f, '') or '' for f in PAGE_FIELDS},
}

path = '/tmp/_dump_modao_%s.json' % tag
with open(path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print('written: %s (%d bytes)' % (path, os.path.getsize(path)))
for k, v in out['page']['fields'].items():
    print('  page.%-22s len=%d' % (k, len(v)))
