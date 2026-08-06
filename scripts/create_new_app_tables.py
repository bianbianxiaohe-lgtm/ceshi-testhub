"""直接按模型创建 4 个新移植应用的表（绕过 Django 迁移图，避免 reviews/api_testing 的历史冲突）。
仅用于一次性建表；表已存在则跳过。"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.db import connection
from django.apps import apps

NEW_APPS = ['defects', 'data_factory', 'analytics', 'app_automation']


def fk_count(model):
    c = 0
    for f in model._meta.fields:
        if f.is_relation and f.related_model is not None:
            if f.related_model._meta.app_label in NEW_APPS:
                c += 1
    return c


models = []
for app in NEW_APPS:
    for model in apps.get_app_config(app).get_models():
        if model._meta.proxy or not model._meta.managed:
            # 代理模型 / 非托管模型不建表
            continue
        models.append(model)

# 按应用内 FK 依赖数升序，保证父表先建
models.sort(key=fk_count)

created = 0
skipped = 0
failed = []
existing = set(connection.introspection.table_names())
with connection.schema_editor() as se:
    for model in models:
        tbl = model._meta.db_table
        if tbl in existing:
            print(f"  跳过(已存在) {tbl}")
            skipped += 1
            continue
        try:
            se.create_model(model)
            print(f"  创建表 {tbl} (app={model._meta.app_label})")
            created += 1
        except Exception as e:
            msg = str(e)
            if 'already exists' in msg or '1050' in msg:
                print(f"  跳过(已存在) {tbl}")
                skipped += 1
            else:
                print(f"  !! 错误 {tbl} (app={model._meta.app_label}): {msg[:200]}")
                failed.append((tbl, model._meta.app_label))

print(f"\n完成: 新建 {created} 个表, 跳过 {skipped} 个已存在表, 失败 {len(failed)} 个")
for tbl, app in failed:
    print(f"  失败: {app}.{tbl}")
