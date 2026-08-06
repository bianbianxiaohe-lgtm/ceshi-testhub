import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    # 检查 version 字段是否存在
    cursor.execute("SHOW COLUMNS FROM app_configs LIKE 'version'")
    result = cursor.fetchone()
    if result:
        print("version 字段已存在")
    else:
        cursor.execute("ALTER TABLE app_configs ADD COLUMN version VARCHAR(50) DEFAULT NULL")
        print("version 字段添加成功")
    
    # 检查其他可能缺失的字段
    cursor.execute("SHOW COLUMNS FROM app_configs")
    columns = [row[0] for row in cursor.fetchall()]
    print(f"\napp_configs 表当前字段: {columns}")
    
    cursor.execute("SHOW COLUMNS FROM app_devices")
    columns = [row[0] for row in cursor.fetchall()]
    print(f"app_devices 表当前字段: {columns}")

print("\n完成!")
