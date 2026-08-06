# 手动编写的性能索引迁移
# 为 executions 应用的 3 个模型添加 7 个索引

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('executions', '0002_initial'),
    ]

    operations = [
        # --- TestPlan (2 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_testplan_creator` ON `test_plans` (`creator_id`);",
            reverse_sql="DROP INDEX `idx_testplan_creator` ON `test_plans`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_testplan_is_active` ON `test_plans` (`is_active`);",
            reverse_sql="DROP INDEX `idx_testplan_is_active` ON `test_plans`;",
        ),

        # --- TestRun (3 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_testrun_project` ON `test_runs` (`project_id`);",
            reverse_sql="DROP INDEX `idx_testrun_project` ON `test_runs`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_testrun_status` ON `test_runs` (`status`);",
            reverse_sql="DROP INDEX `idx_testrun_status` ON `test_runs`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_testrun_assignee` ON `test_runs` (`assignee_id`);",
            reverse_sql="DROP INDEX `idx_testrun_assignee` ON `test_runs`;",
        ),

        # --- TestRunCase (2 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_testruncase_testcase` ON `test_run_cases` (`testcase_id`);",
            reverse_sql="DROP INDEX `idx_testruncase_testcase` ON `test_run_cases`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_testruncase_status` ON `test_run_cases` (`status`);",
            reverse_sql="DROP INDEX `idx_testruncase_status` ON `test_run_cases`;",
        ),
    ]
