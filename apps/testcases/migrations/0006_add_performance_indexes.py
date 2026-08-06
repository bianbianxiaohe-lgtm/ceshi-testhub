# Generated manually - Add performance indexes for testcases app

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testcases', '0005_testcaseexecution'),
    ]

    operations = [
        # TestCase indexes
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['project'], name='idx_testcase_project'),
        ),
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['status'], name='idx_testcase_status'),
        ),
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['priority'], name='idx_testcase_priority'),
        ),
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['author'], name='idx_testcase_author'),
        ),
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['test_type'], name='idx_testcase_test_type'),
        ),
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['-created_at'], name='idx_testcase_created_at'),
        ),
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['project', 'status'], name='idx_testcase_project_status'),
        ),
        migrations.AddIndex(
            model_name='testcase',
            index=models.Index(fields=['project', 'priority'], name='idx_testcase_project_priority'),
        ),
        # TestCaseExecution indexes
        migrations.AddIndex(
            model_name='testcaseexecution',
            index=models.Index(fields=['testcase'], name='idx_tc_exec_testcase'),
        ),
        migrations.AddIndex(
            model_name='testcaseexecution',
            index=models.Index(fields=['executed_by'], name='idx_tc_exec_executed_by'),
        ),
        migrations.AddIndex(
            model_name='testcaseexecution',
            index=models.Index(fields=['-executed_at'], name='idx_tc_exec_executed_at'),
        ),
    ]
