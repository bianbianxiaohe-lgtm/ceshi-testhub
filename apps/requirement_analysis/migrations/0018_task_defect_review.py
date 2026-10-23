"""2026-10-22 用例生成任务支持「关联历史缺陷复盘」注入（方案 A：任务级显式开关）。

默认 NULL = 不注入，既有任务行为完全不变。
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('requirement_analysis', '0017_ai_testcases_snapshot'),
        ('zentao', '0002_defect_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='testcasegenerationtask',
            name='defect_review',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='generation_tasks',
                to='zentao.defectreviewreport',
                verbose_name='关联历史缺陷复盘',
            ),
        ),
        migrations.AddField(
            model_name='testcasegenerationtask',
            name='defect_review_detail_level',
            field=models.CharField(
                blank=True, default='', max_length=20, verbose_name='测试点注入详略',
            ),
        ),
    ]
