# -*- coding: utf-8 -*-
"""验证：人工补充采纳入use例库 source='manual'（新路径），测完即清理。"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPrototype  # noqa: E402
from apps.requirement_analysis.modao_views import _adopt_one_case  # noqa: E402
from apps.testcases.models import TestCase  # noqa: E402
from apps.users.models import User  # noqa: E402

out = []
proto = ModaoPrototype.objects.get(pk=65)
u = User.objects.filter(is_superuser=True).first()
data = {'title': 'ZZZ_验证人工来源_勿留', 'module': '升级付费',
        'precondition': '会员过期', 'steps': ['进入付费页'], 'expected': '展示引导',
        'priority': 'P2'}
r = _adopt_one_case(proto, u, data, '升级付费', 99,
                    desc_suffix='人工补充采纳', source='manual')
out.append(f"RESULT={r}")
tc = TestCase.objects.filter(project=proto.project, title='ZZZ_验证人工来源_勿留').first()
out.append(f"SOURCE={tc.source if tc else 'NOT_FOUND'}")
if tc:
    tc.delete()
    out.append('CLEANED=1')

with open('/tmp/_verify_manual_source.out', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('OK')
