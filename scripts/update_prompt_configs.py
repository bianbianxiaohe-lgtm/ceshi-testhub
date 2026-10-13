# -*- coding: utf-8 -*-
"""把容器内的提示词文件同步进 PromptConfig 的 active 记录。

容器侧用法：
  docker cp scripts/update_prompt_configs.py <容器>:/tmp/
  docker exec <容器> python /tmp/update_prompt_configs.py
  docker exec <容器> cat /tmp/update_prompt_configs.txt

脚本会先做模型自发现（不强假设字段名），打印 what/how，再执行更新。
"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from django.apps import apps as django_apps  # noqa: E402

OUT = '/tmp/update_prompt_configs.txt'
lines = []


def w(msg=''):
    lines.append(str(msg))
    print(msg)


FILE_MAP = {
    'writer': 'tester.md',
    'reviewer': 'tester_pro.md',
    'analyzer': 'tester_analyzer.md',
}
SEARCH_DIRS = [
    '/app/apps/requirement_analysis/independent_skill/prompts/',
    '/app/',
]


def find_file(name):
    for d in SEARCH_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def main():
    model = None
    for cfg in django_apps.get_models():
        if cfg.__name__ == 'PromptConfig':
            model = cfg
            break
    if model is None:
        w('未找到 PromptConfig 模型')
        return
    w('模型: %s (%s)' % (model.__name__, model._meta.db_table))
    w('字段: %s' % [f.name for f in model._meta.fields])

    field_names = {f.name for f in model._meta.fields}
    pt_field = 'prompt_type' if 'prompt_type' in field_names else None
    content_field = None
    for candidate in ('content', 'prompt_content', 'prompt'):
        if candidate in field_names:
            content_field = candidate
            break
    active_field = 'is_active' if 'is_active' in field_names else (
        'status' if 'status' in field_names else None)
    w('判定: 类型字段=%s 内容字段=%s 生效字段=%s' % (pt_field, content_field, active_field))
    if not content_field:
        w('无法确定内容字段，终止')
        return

    w('')
    w('--- 现有记录 ---')
    for obj in model.objects.all().order_by('id')[:20]:
        w('[id=%s] type=%s active=%s len=%s name=%s' % (
            obj.id,
            getattr(obj, pt_field, None) if pt_field else '?',
            getattr(obj, active_field, None) if active_field else '?',
            len(getattr(obj, content_field) or ''),
            getattr(obj, 'name', '?'),
        ))

    w('')
    w('--- 执行同步 ---')
    only = [t.strip() for t in sys.argv[1:] if t.strip()]
    for ptype, fname in FILE_MAP.items():
        if only and ptype not in only:
            w('%s: 跳过（未在指定类型 %s 中）' % (ptype, only))
            continue
        path = find_file(fname)
        if not path:
            w('%s: 未找到文件 %s' % (ptype, fname))
            continue
        text = open(path, encoding='utf-8').read()
        qs = model.objects.all()
        if pt_field:
            qs = qs.filter(**{pt_field: ptype})
        if active_field == 'is_active':
            qs = qs.filter(is_active=True)
        cnt = qs.count()
        for obj in qs:
            setattr(obj, content_field, text)
            obj.save(update_fields=[content_field])
        w('%s <- %s len=%d 条数=%d' % (ptype, path, len(text), cnt))


try:
    main()
except Exception as exc:  # noqa: BLE001
    import traceback
    w('ERROR: %s' % exc)
    w(traceback.format_exc())
finally:
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
