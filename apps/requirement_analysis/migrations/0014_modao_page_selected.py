from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('requirement_analysis', '0013_modaoprototype_dedup_audit_json'),
    ]

    operations = [
        # selected 列：默认 True（纳入后续流程）
        migrations.RunSQL(
            sql="""
            SET @db = DATABASE();
            SET @exists = (SELECT COUNT(*) FROM information_schema.columns
                          WHERE table_schema = @db AND table_name = 'modao_page'
                            AND column_name = 'selected');
            SET @sql = IF(@exists = 0,
                'ALTER TABLE modao_page ADD COLUMN selected tinyint(1) NOT NULL DEFAULT 1',
                'SELECT 1');
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
            """,
            reverse_sql="SELECT 1",
        ),
        # recognition_note 列
        migrations.RunSQL(
            sql="""
            SET @db = DATABASE();
            SET @exists = (SELECT COUNT(*) FROM information_schema.columns
                          WHERE table_schema = @db AND table_name = 'modao_page'
                            AND column_name = 'recognition_note');
            SET @sql = IF(@exists = 0,
                'ALTER TABLE modao_page ADD COLUMN recognition_note varchar(200) NOT NULL DEFAULT ''''',
                'SELECT 1');
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
            """,
            reverse_sql="SELECT 1",
        ),
    ]
