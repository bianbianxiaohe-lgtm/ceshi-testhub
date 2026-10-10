"""给执行记录加「回放失败降级」标记与原因。

背景（2026-09-22 生产实测）：
    回放失败会自动降级成 AI 探索重跑，而旧代码把 replay_mode 直接置 False，
    报告里只显示「AI 探索」—— 用户完全看不出这次曾经试过回放，
    反复重跑都是这个标签，就会得出"固化没生效、省不了 token"的错误结论。

两个字段配合，报告可区分三种状态：
    纯回放        replay_mode=True
    回放失败降级  replay_mode=False + replay_degraded=True（附原因）
    全新 AI 探索  replay_mode=False + replay_degraded=False

⚠️ 用 RunSQL + information_schema 判断，不用 AddField ——
   本项目的迁移历史里 AddField 会因模型不在 state 里报
   `KeyError: ('ui_automation', 'aiexecutionrecord')`。
⚠️ RunSQL 一次只执行一条语句，所以拆成两个独立操作。
"""
from django.db import migrations


def _add_columns(apps, schema_editor):
    """按 information_schema 判断后逐条 ALTER（幂等，可重复执行）。"""
    from django.db import connection

    targets = [
        ('replay_degraded',
         'ALTER TABLE ui_ai_execution_records '
         'ADD COLUMN replay_degraded TINYINT(1) NOT NULL DEFAULT 0'),
        ('replay_fail_reason',
         'ALTER TABLE ui_ai_execution_records '
         "ADD COLUMN replay_fail_reason VARCHAR(500) NOT NULL DEFAULT ''"),
    ]
    with connection.cursor() as cur:
        for col, ddl in targets:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'ui_ai_execution_records' "
                "AND column_name = %s",
                (col,),
            )
            if cur.fetchone():
                continue
            cur.execute(ddl)


def _noop(apps, schema_editor):
    """回滚不删列：老代码忽略多余列，保留数据比删干净更重要。"""


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0014_element_platform'),
    ]

    operations = [
        migrations.RunPython(_add_columns, _noop),
    ]
