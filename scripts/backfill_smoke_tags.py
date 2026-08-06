import json
from apps.requirement_analysis.models import ModaoPrototype
from apps.ui_automation.models import TestCase


def _safe_json_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else [v]
        except Exception:
            return []
    return []


def _title_of(sc):
    tc_obj = sc.get('testcase', sc) if isinstance(sc, dict) else sc
    return (tc_obj.get('title') if isinstance(tc_obj, dict) else None) or '未命名用例'


count = 0
for proto in ModaoPrototype.objects.exclude(project=None):
    smoke_raw = _safe_json_list(proto.smoke_json)
    smoke_list = []
    for s in smoke_raw:
        if isinstance(s, dict) and isinstance(s.get('smoke_testcases'), list):
            smoke_list.extend(s['smoke_testcases'])
        else:
            smoke_list.append(s)
    for sc in smoke_list:
        title = _title_of(sc)
        # 用 name 直接匹配 ui_automation.TestCase（用例库实际表）
        tc = TestCase.objects.filter(name=title).first()
        if tc:
            tags = tc.tags or []
            if '冒烟' not in tags:
                tc.tags = tags + ['冒烟']
                tc.save(update_fields=['tags'])
                count += 1
                print('补标签:', title)
print('共补打冒烟标签', count, '条')
