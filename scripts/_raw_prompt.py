# -*- coding: utf-8 -*-
"""PromptConfig 单条内容的原始导出/导入（不经过 stdout，避免编码与转义问题）。

导出（在源环境跑）：
  docker cp scripts/_raw_prompt.py <容器>:/tmp/
  docker exec <容器> python /tmp/_raw_prompt.py dump analyzer /tmp/_raw_analyzer.txt

导入（在目标环境跑）：
  docker exec <容器> python /tmp/_raw_prompt.py load analyzer /tmp/_raw_analyzer.txt
"""
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from django.apps import apps as django_apps  # noqa: E402


def get_model():
    for cfg in django_apps.get_models():
        if cfg.__name__ == 'PromptConfig':
            return cfg
    raise RuntimeError('未找到 PromptConfig')


def main():
    mode, ptype, path = sys.argv[1], sys.argv[2], sys.argv[3]
    model = get_model()
    obj = model.objects.filter(prompt_type=ptype).order_by('id').first()
    if not obj:
        print('NO_RECORD')
        return
    if mode == 'dump':
        with open(path, 'w', encoding='utf-8') as f:
            f.write(obj.content or '')
        print('DUMPED len=%d -> %s' % (len(obj.content or ''), path))
    elif mode == 'load':
        with open(path, encoding='utf-8') as f:
            text = f.read()
        obj.content = text
        obj.save(update_fields=['content'])
        print('LOADED len=%d <- %s' % (len(text), path))
    else:
        print('未知模式: %s' % mode)


main()
