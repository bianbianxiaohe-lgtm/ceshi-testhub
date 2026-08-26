# Generated manually (项目以直建表方式管理 schema，此迁移用于版本库留档)
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '0007_remove_project_idx_project_owner_and_more'),
        ('versions', '0002_initial'),
        ('testcases', '0010_alter_testcase_options_testcase_sort_order'),
        ('users', '0002_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ZentaoConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='禅道', max_length=100, verbose_name='配置名称')),
                ('base_url', models.CharField(max_length=300, verbose_name='禅道地址')),
                ('account', models.CharField(max_length=100, verbose_name='账号')),
                ('password', models.CharField(max_length=200, verbose_name='密码')),
                ('product_id', models.CharField(blank=True, default='', max_length=30, verbose_name='禅道产品ID')),
                ('execution_id', models.CharField(blank=True, default='', max_length=30, verbose_name='禅道执行ID')),
                ('build_id', models.CharField(blank=True, default='', max_length=30, verbose_name='禅道Build ID')),
                ('opened_build_keyword', models.CharField(blank=True, default='', max_length=100, verbose_name='版本关键字', help_text='用于按 openedBuild 精确过滤，如 1.1.4')),
                ('is_enabled', models.BooleanField(default=True, verbose_name='是否启用')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='zentao_configs', to='projects.project', verbose_name='TestHub项目')),
                ('version', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='zentao_configs', to='versions.version', verbose_name='TestHub版本')),
            ],
            options={
                'verbose_name': '禅道配置',
                'verbose_name_plural': '禅道配置',
                'db_table': 'zentao_configs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='CoverageReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('running', '分析中'), ('success', '完成'), ('failed', '失败')], default='running', max_length=20, verbose_name='状态')),
                ('total_bugs', models.IntegerField(default=0, verbose_name='Bug总数')),
                ('covered_bugs', models.IntegerField(default=0, verbose_name='已覆盖')),
                ('uncovered_bugs', models.IntegerField(default=0, verbose_name='未覆盖')),
                ('coverage_rate', models.FloatField(default=0.0, verbose_name='覆盖率')),
                ('matched_by', models.CharField(blank=True, default='', max_length=100, verbose_name='匹配方式')),
                ('case_count', models.IntegerField(default=0, verbose_name='参与比对的用例数')),
                ('error_message', models.TextField(blank=True, default='', verbose_name='错误信息')),
                ('detail', models.JSONField(default=dict, verbose_name='明细')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='完成时间')),
                ('config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='coverage_reports', to='zentao.ZentaoConfig', verbose_name='禅道配置')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='zentao_coverage_reports', to='users.user', verbose_name='触发人')),
                ('version', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='zentao_coverage_reports', to='versions.version', verbose_name='TestHub版本')),
            ],
            options={
                'verbose_name': '禅道覆盖率报告',
                'verbose_name_plural': '禅道覆盖率报告',
                'db_table': 'zentao_coverage_reports',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ZentaoBug',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('zentao_id', models.CharField(max_length=30, verbose_name='禅道Bug ID')),
                ('title', models.CharField(max_length=500, verbose_name='标题')),
                ('steps', models.TextField(blank=True, default='', verbose_name='复现步骤(纯文本)')),
                ('severity', models.CharField(blank=True, default='', max_length=20, verbose_name='严重程度')),
                ('pri', models.CharField(blank=True, default='', max_length=20, verbose_name='优先级')),
                ('status', models.CharField(blank=True, default='', max_length=30, verbose_name='状态')),
                ('bug_type', models.CharField(blank=True, default='', max_length=50, verbose_name='Bug类型')),
                ('execution', models.CharField(blank=True, default='', max_length=30, verbose_name='禅道执行ID')),
                ('product', models.CharField(blank=True, default='', max_length=30, verbose_name='禅道产品ID')),
                ('opened_build', models.CharField(blank=True, default='', max_length=100, verbose_name='发现版本')),
                ('opened_by', models.CharField(blank=True, default='', max_length=100, verbose_name='创建人')),
                ('opened_date', models.DateTimeField(blank=True, null=True, verbose_name='创建时间')),
                ('assigned_to', models.CharField(blank=True, default='', max_length=100, verbose_name='指派给')),
                ('resolved_by', models.CharField(blank=True, default='', max_length=100, verbose_name='解决人')),
                ('resolution', models.CharField(blank=True, default='', max_length=100, verbose_name='解决方案')),
                ('resolved_date', models.DateTimeField(blank=True, null=True, verbose_name='解决时间')),
                ('raw_data', models.JSONField(default=dict, verbose_name='原始数据')),
                ('is_active', models.BooleanField(default=True, verbose_name='是否在禅道仍存在')),
                ('first_seen_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='首次入库时间')),
                ('last_seen_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='最近同步时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bugs', to='zentao.ZentaoConfig', verbose_name='禅道配置')),
                ('version', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='zentao_bugs', to='versions.version', verbose_name='关联TestHub版本')),
            ],
            options={
                'verbose_name': '禅道Bug',
                'verbose_name_plural': '禅道Bug',
                'db_table': 'zentao_bugs',
                'ordering': ['-opened_date', '-id'],
                'indexes': [
                    models.Index(fields=['config', 'is_active'], name='zentao_bug_conf_act_1bf3b1_idx'),
                    models.Index(fields=['version'], name='zentao_bug_version_4a1b2c_idx'),
                ],
                'unique_together': {('config', 'zentao_id')},
            },
        ),
        migrations.CreateModel(
            name='ZentaoSyncLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('running', '同步中'), ('success', '成功'), ('failed', '失败')], default='running', max_length=20, verbose_name='状态')),
                ('total_count', models.IntegerField(default=0, verbose_name='禅道Bug总数')),
                ('new_count', models.IntegerField(default=0, verbose_name='新增')),
                ('updated_count', models.IntegerField(default=0, verbose_name='更新')),
                ('deactivated_count', models.IntegerField(default=0, verbose_name='失效(已删除)')),
                ('message', models.TextField(blank=True, default='', verbose_name='说明')),
                ('detail', models.JSONField(default=dict, verbose_name='明细')),
                ('started_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='开始时间')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='结束时间')),
                ('config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sync_logs', to='zentao.ZentaoConfig', verbose_name='禅道配置')),
            ],
            options={
                'verbose_name': '禅道同步记录',
                'verbose_name_plural': '禅道同步记录',
                'db_table': 'zentao_sync_logs',
                'ordering': ['-started_at'],
            },
        ),
        migrations.CreateModel(
            name='CoverageItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('covered', models.BooleanField(default=False, verbose_name='是否覆盖')),
                ('matched_case_title', models.CharField(blank=True, default='', max_length=300, verbose_name='匹配用例标题')),
                ('match_score', models.FloatField(blank=True, null=True, verbose_name='语义相似度')),
                ('candidates', models.JSONField(default=list, verbose_name='候选用例')),
                ('reason', models.TextField(blank=True, default='', verbose_name='判定理由')),
                ('suggestion', models.TextField(blank=True, default='', verbose_name='覆盖建议')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('bug', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='coverage_items', to='zentao.ZentaoBug', verbose_name='禅道Bug')),
                ('matched_testcase', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='zentao_coverage_items', to='testcases.testcase', verbose_name='匹配用例')),
                ('report', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='zentao.CoverageReport', verbose_name='覆盖率报告')),
            ],
            options={
                'verbose_name': '覆盖判定明细',
                'verbose_name_plural': '覆盖判定明细',
                'db_table': 'zentao_coverage_items',
                'ordering': ['id'],
            },
        ),
    ]
