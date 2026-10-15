# -*- coding: utf-8 -*-
"""验证自愈闭环(P0)快照字段是否被正确填充：AI 原始用例是否落库。

用法：docker exec <容器> python /app/scripts/_check_ai_snapshot.py [proto_pk]
"""
import json
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype  # noqa: E402


def _n(x):
    try:
        v = json.loads(x or '[]')
        return len(v) if isinstance(v, list) else -1
    except Exception:
        return -1


def main():
    pk = int(sys.argv[1]) if len(sys.argv) > 1 else 65
    proto = ModaoPrototype.objects.get(pk=pk)
    lines = [f"proto={pk}"]
    lines.append(f"  ai_testcases_json(任务级快照) 条数 = {_n(proto.ai_testcases_json)}")
    agg = 0
    per_page = []
    for p in proto.pages.all():
        c = _n(p.page_ai_testcases_json)
        per_page.append((p.page_name, c))
        agg += c
    lines.append(f"  page_ai_testcases_json(画布级聚合) 条数 = {agg}")
    for name, c in per_page:
        lines.append(f"    - {name}: {c}")
    lines.append(f"  merged_testcases_json(最终采纳) 条数 = {_n(proto.merged_testcases_json)}")
    lines.append(f"  page_testcases_json(当前画布用例) 条数 = {agg}")
    out = '\n'.join(lines)
    with open('/tmp/_check_ai_snapshot.txt', 'w', encoding='utf-8') as f:
        f.write(out + '\n')
    print(out)


if __name__ == '__main__':
    main()
