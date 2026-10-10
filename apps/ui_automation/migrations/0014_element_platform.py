"""
给 Element 增加 platform 字段（元素库区分平台）。

为什么需要（2026-09-21）：
  同一个业务元素在 Android / iOS / 鸿蒙上的 locator 完全不同
  （Android 是 resource-id 或 xpath，iOS 是 accessibility 文案，鸿蒙是 component id），
  原 Element 模型没有平台字段，无法按平台保存/查询，多平台会互相覆盖。

为什么用 RunPython 而不是 AddField：
  `ui_elements` 建表迁移不在本 app 的 migrations 历史 state 里（历史手工建表），
  用 AddField 会报 `KeyError: ('ui_automation','element')` 并中断**所有 app** 的 migrate。

⚠️ 不用 MySQL 的 PREPARE/@var 动态 SQL：
  Django 的 RunSQL 一次只吃一条语句，而 `SET @var` + `PREPARE` 必须同会话，
  按分号拆开后语法必然出错（实测 1064）。列名是固定的，直接用 Python 判断 + 裸 ALTER。
"""
from django.db import migrations

COLUMN = 'platform'
INDEX = 'ui_elements_project_platform_idx'


def _column_exists(cursor, table, column):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        [table, column])
    return cursor.fetchone()[0] > 0


def _index_exists(cursor, table, index):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s",
        [table, index])
    return cursor.fetchone()[0] > 0


def forwards(apps, schema_editor):
    from django.db import connection
    with connection.cursor() as cursor:
        if not _column_exists(cursor, 'ui_elements', COLUMN):
            # NOT NULL + DEFAULT ''：历史数据自动落成"通用元素"（不限定平台）
            cursor.execute(
                "ALTER TABLE ui_elements "
                "ADD COLUMN platform VARCHAR(20) NOT NULL DEFAULT ''")
        if not _index_exists(cursor, 'ui_elements', INDEX):
            cursor.execute(
                "CREATE INDEX %s ON ui_elements (project_id, platform)" % INDEX)


def backwards(apps, schema_editor):
    from django.db import connection
    with connection.cursor() as cursor:
        if _index_exists(cursor, 'ui_elements', INDEX):
            cursor.execute("DROP INDEX %s ON ui_elements" % INDEX)
        if _column_exists(cursor, 'ui_elements', COLUMN):
            cursor.execute("ALTER TABLE ui_elements DROP COLUMN platform")


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0013_aiexecutionrecord_tokens'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
