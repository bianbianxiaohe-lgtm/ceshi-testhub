from django.db import migrations, models


class Migration(migrations.Migration):
    """给 modao_prototype 加 dedup_audit_json 列。

    注意：这里刻意用 RunSQL 而不是 AddField。
    AddField(model_name='modaoprototype') 会让 Django 在 migrate 时抛
    KeyError: ('requirement_analysis', 'modaoprototype') —— 该模型不在
    migrations 的历史状态里，整个 migrate 会直接中断，连其它 app 的迁移
    都跑不了。RunSQL 只碰数据库、不参与 state 构建，绕开了这个问题。
    建列语句写成幂等的，重复执行不会报错。
    """

    dependencies = [
        ('requirement_analysis', '0012_requirementanalysisresult_created_by_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            SET @db = DATABASE();
            SET @exists = (SELECT COUNT(*) FROM information_schema.columns
                          WHERE table_schema = @db AND table_name = 'modao_prototype'
                            AND column_name = 'dedup_audit_json');
            SET @sql = IF(@exists = 0,
                'ALTER TABLE modao_prototype ADD COLUMN dedup_audit_json longtext NOT NULL',
                'SELECT 1');
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
            """,
            reverse_sql="SELECT 1",
        ),
    ]
