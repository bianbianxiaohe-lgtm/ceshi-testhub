from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0004_appdevice_adb_host_testcase_tags'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AppPipelineRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stages', models.JSONField(blank=True, default=list, verbose_name='执行阶段')),
                ('status', models.CharField(
                    choices=[('pending', '待执行'), ('running', '执行中'), ('success', '成功'), ('failed', '失败')],
                    default='pending', max_length=20, verbose_name='状态')),
                ('log', models.TextField(blank=True, verbose_name='执行日志')),
                ('result_summary', models.TextField(blank=True, verbose_name='结果摘要')),
                ('snapshot_path', models.CharField(blank=True, max_length=500, verbose_name='快照路径')),
                ('report_url', models.CharField(blank=True, max_length=500, verbose_name='报告地址')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('started_at', models.DateTimeField(blank=True, null=True, verbose_name='开始时间')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='结束时间')),
                ('duration', models.FloatField(default=0, verbose_name='耗时(秒)')),
                ('app_config', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='pipeline_runs',
                    to='ui_automation.appconfig', verbose_name='应用配置')),
                ('device', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='pipeline_runs', to='ui_automation.appdevice', verbose_name='设备')),
                ('created_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL, verbose_name='创建人')),
            ],
            options={
                'db_table': 'app_pipeline_runs',
                'verbose_name': 'App流水线运行记录',
                'verbose_name_plural': 'App流水线运行记录',
                'ordering': ['-created_at'],
            },
        ),
    ]
