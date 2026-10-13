# -*- coding: utf-8 -*-
"""只读导出 PromptConfig 记录（用于跨环境恢复/比对）。

用法：docker cp ... ; docker exec <容器> python /tmp/_dump_prompt_configs.py [类型...]
输出：/tmp/_dump_prompt_configs.txt
"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from django.apps import apps as django_apps  # noqa: E402

lines = []
w = lines.append

model = None
for cfg in django_apps.get_models():
    if cfg.__name__ == 'PromptConfig':
        model = cfg
        break

w('db_table=%s' % model._meta.db_table)
only = [t.strip() for t in sys.argv[1:] if t.strip()]
qs = model.objects.all().order_by('id')
if only:
    qs = qs.filter(prompt_type__in=only)
for obj in qs:
    w('')
    w('=== id=%s type=%s active=%s name=%s len=%d ==='
      % (obj.id, obj.prompt_type, obj.is_active, obj.name, len(obj.content or '')))
    w(obj.content or '')

open('/tmp/_dump_prompt_configs.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('DONE')
