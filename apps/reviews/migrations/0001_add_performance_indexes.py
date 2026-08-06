# 手动编写的性能索引迁移
# 为 reviews 应用的 TestCaseReview 模型添加 3 个索引

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reviews', '0002_initial'),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE INDEX `idx_review_status` ON `testcase_reviews` (`status`);",
            reverse_sql="DROP INDEX `idx_review_status` ON `testcase_reviews`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_review_creator` ON `testcase_reviews` (`creator_id`);",
            reverse_sql="DROP INDEX `idx_review_creator` ON `testcase_reviews`;",
        ),
        migrations.RunSQL(
            "CREATE INDEX `idx_review_deadline` ON `testcase_reviews` (`deadline`);",
            reverse_sql="DROP INDEX `idx_review_deadline` ON `testcase_reviews`;",
        ),
    ]
