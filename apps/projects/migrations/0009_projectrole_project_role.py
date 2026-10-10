"""
新增「项目角色」（组织级组）并把 Project 关联到角色。

背景（2026-09-20 用户需求）：
    在用户管理里维护"角色"，一个角色下有若干人；创建项目时选一个角色，
    该角色全员自动获得该项目的编辑权限（查看本来就已全员放开），但**不能删除项目**。
    一个项目最多挂 1 个角色；存量项目 role 留空，由管理员后续手动挂。

⚠️ 本迁移用 RunSQL + information_schema 判断做成**幂等**：
   本项目历史上存在"迁移状态与实际库结构漂移"的情况（见 docker_start.py 的幂等 DDL），
   直接 CreateModel/AddField 在表或列已存在的库上会报错并中断所有 app 的 migrate。
"""

from django.db import migrations


CREATE_ROLE_TABLE = """
CREATE TABLE IF NOT EXISTS `project_roles` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `description` longtext NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `project_roles_name_uniq` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

CREATE_ROLE_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS `project_roles_members` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `projectrole_id` int NOT NULL,
  `user_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `project_roles_members_uniq` (`projectrole_id`, `user_id`),
  KEY `project_roles_members_user_idx` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

ADD_PROJECT_ROLE_COL = """
SET @has_col := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'role_id'
);
SET @sql := IF(@has_col = 0,
  'ALTER TABLE `projects` ADD COLUMN `role_id` int NULL DEFAULT NULL, ADD KEY `projects_role_id_idx` (`role_id`)',
  'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
"""

DROP_PROJECT_ROLE_COL = """
SET @has_col := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'role_id'
);
SET @sql := IF(@has_col = 1,
  'ALTER TABLE `projects` DROP COLUMN `role_id`',
  'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0008_projectknowledge_needs_review'),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_ROLE_TABLE,
            reverse_sql='DROP TABLE IF EXISTS `project_roles`;',
        ),
        migrations.RunSQL(
            sql=CREATE_ROLE_MEMBERS_TABLE,
            reverse_sql='DROP TABLE IF EXISTS `project_roles_members`;',
        ),
        migrations.RunSQL(
            sql=ADD_PROJECT_ROLE_COL,
            reverse_sql=DROP_PROJECT_ROLE_COL,
        ),
    ]
