"""2026-10-23 记录「本次实际注入的历史测试点」审计快照。

背景：生成侧此前只把「注入了 N 条 / 多少字符」写进 logger，用户无法知道
到底命中了哪几条历史测试点，日志重启还会丢。此字段把真正进入 prompt 的
测试点快照落到任务上，供任务详情页展示、报告页反查。

默认 NULL 表示「未关联复盘」或「任务尚未执行到注入环节」，既有任务行为不变。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('requirement_analysis', '0018_task_defect_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='testcasegenerationtask',
            name='defect_review_used',
            field=models.JSONField(
                blank=True,
                null=True,
                verbose_name='历史测试点注入审计',
                help_text='本次实际注入的历史测试点快照；NULL 表示未关联复盘或尚未执行',
            ),
        ),
    ]
