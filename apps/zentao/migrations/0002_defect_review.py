# 2026-10-22 历史缺陷复盘功能
#   1) ZentaoConfig 增加禅道 MySQL 只读连接字段（历史 Bug 全量取数）
#   2) 新增 DefectReviewReport（复盘报告，产物核心是 testpoints_json）
#
# 说明：本项目部分环境以直建表方式管理 schema，同时提供 docker_start.py 幂等 DDL，
# 此迁移用于版本库留档与标准 migrate 流程。
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('zentao', '0001_initial'),
        ('projects', '0009_projectrole_project_role'),
        ('versions', '0002_initial'),
        ('users', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='zetaoconfig',
            name='db_host',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='数据库地址'),
        ),
        migrations.AddField(
            model_name='zetaoconfig',
            name='db_port',
            field=models.CharField(blank=True, default='', max_length=10, verbose_name='数据库端口'),
        ),
        migrations.AddField(
            model_name='zetaoconfig',
            name='db_name',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='数据库名'),
        ),
        migrations.AddField(
            model_name='zetaoconfig',
            name='db_user',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='数据库只读账号'),
        ),
        migrations.AddField(
            model_name='zetaoconfig',
            name='db_password',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='数据库密码'),
        ),
        migrations.AddField(
            model_name='zetaoconfig',
            name='db_prefix',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='表前缀'),
        ),
        migrations.CreateModel(
            name='DefectReviewReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, default='', max_length=200, verbose_name='报告名称')),
                ('status', models.CharField(
                    choices=[('running', '分析中'), ('success', '完成'), ('failed', '失败')],
                    default='running', max_length=20, verbose_name='状态',
                )),
                ('product_ids', models.JSONField(default=list, verbose_name='禅道产品ID列表')),
                ('date_from', models.DateField(blank=True, null=True, verbose_name='缺陷起始日期')),
                ('date_to', models.DateField(blank=True, null=True, verbose_name='缺陷截止日期')),
                ('excluded_types', models.JSONField(default=list, verbose_name='排除的缺陷类型')),
                ('bug_total', models.IntegerField(default=0, verbose_name='纳入的缺陷数')),
                ('domain_count', models.IntegerField(default=0, verbose_name='功能域数')),
                ('testpoint_count', models.IntegerField(default=0, verbose_name='测试点数')),
                ('stats_json', models.JSONField(default=dict, verbose_name='统计结果')),
                ('testpoints_json', models.JSONField(default=list, verbose_name='测试点')),
                ('error_message', models.TextField(blank=True, default='', verbose_name='错误信息')),
                ('llm_model', models.CharField(blank=True, default='', max_length=100, verbose_name='使用的模型')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='完成时间')),
                ('config', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='defect_reviews', to='zentao.zentaoconfig', verbose_name='禅道配置',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='defect_reviews', to='users.user', verbose_name='创建人',
                )),
                ('project', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='defect_reviews', to='projects.project', verbose_name='TestHub项目',
                )),
                ('version', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='defect_reviews', to='versions.version', verbose_name='TestHub版本',
                )),
            ],
            options={
                'verbose_name': '历史缺陷复盘报告',
                'verbose_name_plural': '历史缺陷复盘报告',
                'db_table': 'zentao_defect_reviews',
                'ordering': ['-created_at'],
            },
        ),
    ]
