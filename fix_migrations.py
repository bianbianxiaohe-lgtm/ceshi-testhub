import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from django.db import connection

# 查看已应用的迁移
with connection.cursor() as cursor:
    cursor.execute("SELECT id, app, name FROM django_migrations WHERE app='ui_automation' ORDER BY id")
    rows = cursor.fetchall()
    print("已应用的 ui_automation 迁移:")
    for row in rows:
        print(f"  {row[0]}: {row[1]} - {row[2]}")

# 查看表是否存在
with connection.cursor() as cursor:
    cursor.execute("SHOW TABLES LIKE 'app_devices'")
    result = cursor.fetchone()
    print(f"\napp_devices 表存在: {result is not None}")
    
    cursor.execute("SHOW TABLES LIKE 'app_configs'")
    result = cursor.fetchone()
    print(f"app_configs 表存在: {result is not None}")

# 伪造迁移记录（如果表存在但迁移记录缺失）
with connection.cursor() as cursor:
    # 检查是否已有 0003 迁移
    cursor.execute("SELECT COUNT(*) FROM django_migrations WHERE app='ui_automation' AND name='0003_appdevice_appconfig'")
    count = cursor.fetchone()[0]
    if count == 0:
        # 获取最大 id
        cursor.execute("SELECT MAX(id) FROM django_migrations")
        max_id = cursor.fetchone()[0] or 0
        new_id = max_id + 1
        cursor.execute(
            "INSERT INTO django_migrations (id, app, name, applied) VALUES (%s, %s, %s, NOW())",
            [new_id, 'ui_automation', '0003_appdevice_appconfig']
        )
        print(f"\n已插入伪造迁移记录: id={new_id}, name=0003_appdevice_appconfig")
    else:
        print("\n迁移记录 0003_appdevice_appconfig 已存在")

print("\n完成!")
