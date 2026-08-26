from django.db import migrations


def _add_column(col_name, col_def):
    return migrations.RunSQL(
        sql=f"""
        SET @db = DATABASE();
        SET @exists = (SELECT COUNT(*) FROM information_schema.columns
                       WHERE table_schema = @db AND table_name = 'modao_page'
                         AND column_name = '{col_name}');
        SET @sql = IF(@exists = 0,
            'ALTER TABLE modao_page ADD COLUMN {col_name} {col_def}',
            'SELECT 1');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        """,
        reverse_sql="SELECT 1",
    )


class Migration(migrations.Migration):
    dependencies = [
        ('requirement_analysis', '0014_modao_page_selected'),
    ]

    operations = [
        # 画布级独立流水线状态（A2-b）
        _add_column('current_stage', 'int NOT NULL DEFAULT 0'),
        _add_column('stage_status', "varchar(20) NOT NULL DEFAULT 'pending'"),
        _add_column('work_log', "text NOT NULL"),
        _add_column('error_message', "text NOT NULL"),
        _add_column('rerun_stages', "text NOT NULL"),
    ]
