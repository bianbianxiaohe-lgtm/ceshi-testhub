from django.db import migrations


def _add_page_column(col_name, col_def):
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


def _add_proto_column(col_name, col_def):
    return migrations.RunSQL(
        sql=f"""
        SET @db = DATABASE();
        SET @exists = (SELECT COUNT(*) FROM information_schema.columns
                       WHERE table_schema = @db AND table_name = 'modao_prototype'
                         AND column_name = '{col_name}');
        SET @sql = IF(@exists = 0,
            'ALTER TABLE modao_prototype ADD COLUMN {col_name} {col_def}',
            'SELECT 1');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        """,
        reverse_sql="SELECT 1",
    )


class Migration(migrations.Migration):
    dependencies = [
        ('requirement_analysis', '0016_modao_page_folder'),
    ]

    operations = [
        # 自愈闭环(P0)：AI 原始用例快照，供「AI 生成 vs 最终采纳」偏差对比。
        # 与 docker_start.py 幂等 DDL 双写，保证 prod/dev 在 migrate 不可用时也能建列。
        _add_proto_column('ai_testcases_json', "LONGTEXT NOT NULL"),
        _add_page_column('page_ai_testcases_json', "LONGTEXT NOT NULL"),
    ]
