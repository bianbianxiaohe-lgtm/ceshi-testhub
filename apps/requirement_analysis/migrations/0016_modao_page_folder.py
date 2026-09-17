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
        ('requirement_analysis', '0015_modao_page_pipeline_state'),
    ]

    operations = [
        # 画布文件夹路径（A2-d：按文件夹分组展示与整组选择）
        _add_column('folder', "varchar(500) NOT NULL DEFAULT ''"),
    ]
