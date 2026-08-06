# 手动编写的性能索引迁移
# 为 api_testing 应用的 10 个模型添加 24 个索引

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api_testing', '0002_initial'),
    ]

    operations = [
        # --- ApiProject (2 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_apiproj_owner` ON `api_projects` (`owner_id`);",
            reverse_sql="DROP INDEX `idx_apiproj_owner` ON `api_projects`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_apiproj_status` ON `api_projects` (`status`);",
            reverse_sql="DROP INDEX `idx_apiproj_status` ON `api_projects`;",
        ),

        # --- ApiCollection (1 index) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_apicoll_project` ON `api_collections` (`project_id`);",
            reverse_sql="DROP INDEX `idx_apicoll_project` ON `api_collections`;",
        ),

        # --- ApiRequest (2 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_apireq_collection` ON `api_requests` (`collection_id`);",
            reverse_sql="DROP INDEX `idx_apireq_collection` ON `api_requests`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_apireq_method` ON `api_requests` (`method`);",
            reverse_sql="DROP INDEX `idx_apireq_method` ON `api_requests`;",
        ),

        # --- RequestHistory (4 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_reqhist_request` ON `api_request_histories` (`request_id`);",
            reverse_sql="DROP INDEX `idx_reqhist_request` ON `api_request_histories`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_reqhist_executed_by` ON `api_request_histories` (`executed_by_id`);",
            reverse_sql="DROP INDEX `idx_reqhist_executed_by` ON `api_request_histories`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_reqhist_status_code` ON `api_request_histories` (`status_code`);",
            reverse_sql="DROP INDEX `idx_reqhist_status_code` ON `api_request_histories`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_reqhist_executed_at` ON `api_request_histories` (`executed_at` DESC);",
            reverse_sql="DROP INDEX `idx_reqhist_executed_at` ON `api_request_histories`;",
        ),

        # --- TestSuite (1 index) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_testsuite_project` ON `api_test_suites` (`project_id`);",
            reverse_sql="DROP INDEX `idx_testsuite_project` ON `api_test_suites`;",
        ),

        # --- TestExecution (3 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_testexec_test_suite` ON `api_test_executions` (`test_suite_id`);",
            reverse_sql="DROP INDEX `idx_testexec_test_suite` ON `api_test_executions`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_testexec_status` ON `api_test_executions` (`status`);",
            reverse_sql="DROP INDEX `idx_testexec_status` ON `api_test_executions`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_testexec_executed_by` ON `api_test_executions` (`executed_by_id`);",
            reverse_sql="DROP INDEX `idx_testexec_executed_by` ON `api_test_executions`;",
        ),

        # --- ScheduledTask (3 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_schedtask_status` ON `api_scheduled_tasks` (`status`);",
            reverse_sql="DROP INDEX `idx_schedtask_status` ON `api_scheduled_tasks`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_schedtask_next_run` ON `api_scheduled_tasks` (`next_run_time`);",
            reverse_sql="DROP INDEX `idx_schedtask_next_run` ON `api_scheduled_tasks`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_schedtask_created_by` ON `api_scheduled_tasks` (`created_by_id`);",
            reverse_sql="DROP INDEX `idx_schedtask_created_by` ON `api_scheduled_tasks`;",
        ),

        # --- TaskExecutionLog (2 indexes) ---
        migrations.RunSQL(
            "CREATE INDEX `idx_tasklog_task` ON `api_task_execution_logs` (`task_id`);",
            reverse_sql="DROP INDEX `idx_tasklog_task` ON `api_task_execution_logs`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_tasklog_status` ON `api_task_execution_logs` (`status`);",
            reverse_sql="DROP INDEX `idx_tasklog_status` ON `api_task_execution_logs`;",
        ),

        # --- NotificationLog (3 indexes, auto-named by Django) ---
        migrations.RunSQL(
            "CREATE INDEX `api_notifica_status_idx` ON `api_notification_logs` (`status`);",
            reverse_sql="DROP INDEX `api_notifica_status_idx` ON `api_notification_logs`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `api_notifica_notific_idx` ON `api_notification_logs` (`notification_type`);",
            reverse_sql="DROP INDEX `api_notifica_notific_idx` ON `api_notification_logs`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `api_notifica_created_idx` ON `api_notification_logs` (`created_at`);",
            reverse_sql="DROP INDEX `api_notifica_created_idx` ON `api_notification_logs`;",
        ),

        # --- OperationLog (3 indexes, auto-named by Django) ---
        migrations.RunSQL(
            "CREATE INDEX `api_operati_created_idx` ON `api_operation_logs` (`created_at` DESC);",
            reverse_sql="DROP INDEX `api_operati_created_idx` ON `api_operation_logs`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `api_operati_resourc_idx` ON `api_operation_logs` (`resource_type`, `resource_id`);",
            reverse_sql="DROP INDEX `api_operati_resourc_idx` ON `api_operation_logs`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `api_operati_user_idx` ON `api_operation_logs` (`user_id`, `created_at` DESC);",
            reverse_sql="DROP INDEX `api_operati_user_idx` ON `api_operation_logs`;",
        ),
    ]
