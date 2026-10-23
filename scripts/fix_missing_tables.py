import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from django.apps import apps
from django.db import connection

print("=== 1. 修复 projects 相关旧表名与缺失字段 ===")
with connection.cursor() as cur:
    cur.execute("SHOW TABLES LIKE 'projects_project'")
    if cur.fetchone():
        print("发现 projects_project，正在补齐字段并重命名为 projects...")
        cur.execute("SHOW COLUMNS FROM projects_project LIKE 'updated_at'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects_project ADD COLUMN updated_at DATETIME(6) NULL")
            cur.execute("UPDATE projects_project SET updated_at = created_at WHERE updated_at IS NULL")
            print("  ✓ 添加 updated_at 列")

        cur.execute("SHOW COLUMNS FROM projects_project LIKE 'knowledge_base_path'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE projects_project ADD COLUMN knowledge_base_path VARCHAR(500) DEFAULT ''")
            print("  ✓ 添加 knowledge_base_path 列")

        cur.execute("RENAME TABLE projects_project TO projects")
        print("  ✓ 重命名 projects_project -> projects")

    cur.execute("SHOW TABLES LIKE 'projects_projectmember'")
    if cur.fetchone():
        cur.execute("RENAME TABLE projects_projectmember TO project_members")
        print("  ✓ 重命名 projects_projectmember -> project_members")

    cur.execute("SHOW TABLES LIKE 'projects_projectenvironment'")
    if cur.fetchone():
        cur.execute("RENAME TABLE projects_projectenvironment TO project_environments")
        print("  ✓ 重命名 projects_projectenvironment -> project_environments")

    cur.execute("SHOW TABLES LIKE 'projects_projectknowledge'")
    if cur.fetchone():
        cur.execute("RENAME TABLE projects_projectknowledge TO project_knowledge")
        print("  ✓ 重命名 projects_projectknowledge -> project_knowledge")

print("\n=== 2. 补全模型缺失的数据表 ===")
with connection.cursor() as cur:
    cur.execute("SHOW TABLES")
    existing_tables = set(r[0] for r in cur.fetchall())

with connection.schema_editor() as editor:
    for model in apps.get_models():
        tbl = model._meta.db_table
        if tbl not in existing_tables:
            try:
                print(f"正在为 {model._meta.label} 创建数据表: {tbl} ...")
                editor.create_model(model)
                existing_tables.add(tbl)
                print(f"  ✓ 创建成功: {tbl}")
            except Exception as e:
                print(f"  ✗ 创建失败: {tbl} - {e}")

print("\n=== 3. 补全已有数据表中缺失的字段 ===")
with connection.schema_editor() as editor:
    for model in apps.get_models():
        tbl = model._meta.db_table
        if tbl not in existing_tables:
            continue
        with connection.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM `{tbl}`")
            existing_cols = set(r[0] for r in cur.fetchall())

        for field in model._meta.fields:
            col = field.column
            if col and col not in existing_cols:
                try:
                    print(f"正在向 {tbl} 添加缺失字段: {col} ...")
                    editor.add_field(model, field)
                    print(f"  ✓ 添加成功: {col}")
                except Exception as e:
                    print(f"  ✗ 添加失败: {col} - {e}")

print("\n=== 4. 验证接口连通性 ===")
from apps.projects.models import Project
all_proj = list(Project.objects.all().values('id', 'name', 'status'))
print("项目列表查询成功:", all_proj)
print("\n所有缺失表与字段修复完成！")
