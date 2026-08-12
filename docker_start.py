import subprocess
import sys
import time
import os

def wait_for_mysql(host, port, user, password, db, max_retries=30):
    """等待MySQL就绪"""
    import pymysql
    print(f"Waiting for MySQL at {host}:{port}...")
    for i in range(max_retries):
        try:
            conn = pymysql.connect(host=host, port=int(port), user=user, password=password, db=db)
            conn.close()
            print("MySQL is ready!")
            return True
        except Exception as e:
            print(f"  Attempt {i+1}/{max_retries}: {e}")
            time.sleep(2)
    return False

if __name__ == "__main__":
    from decouple import config

    host = config('DB_HOST', default='127.0.0.1')
    port = config('DB_PORT', default='3306')
    user = config('DB_USER', default='root')
    password = config('DB_PASSWORD', default='')
    db = config('DB_NAME', default='testhub')

    if not wait_for_mysql(host, port, user, password, db):
        print("ERROR: MySQL did not become ready in time.")
        sys.exit(1)

    # 本项目初始迁移是空占位 0001_initial（表已存在于库中，靠 runserver 直接起来）。
    # 为避免 admin 等内置 app 对 users/versions 的依赖在部分记录被删除后触发
    # InconsistentMigrationHistory，这里直接清空 django_migrations 记录，再由下面的
    # --fake-initial 在空表上按依赖顺序重新“假应用”所有初始迁移，使迁移状态自洽。
    print("Resetting migration records for consistent fake-initial...")
    subprocess.run([sys.executable, "-c",
        "import os, django; "
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings'); "
        "django.setup(); "
        "from django.db import connection; "
        "cur = connection.cursor(); "
        "cur.execute(\"DELETE FROM django_migrations\"); "
        "print('reset migration records')"], check=False)

    # 直接幂等地确保录制坐标列存在（不依赖迁移系统执行，规避迁移图断裂导致漏加列）。
    # 使用三引号多行字符串避免 -c 模式下的复合语句语法错误。
    ensure_script = """
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()
from django.db import connection
cur = connection.cursor()
created = []
for col in ('center_x', 'center_y'):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'ui_test_case_steps' AND column_name = %s",
        (col,),
    )
    if not cur.fetchone():
        cur.execute('ALTER TABLE ui_test_case_steps ADD COLUMN ' + col + ' INT NULL')
        created.append(col)
print('ensured columns; newly added:', created)

# 确保 ui_test_case_executions.step_results (JSON) 列存在，用于前端展示每步失败详情
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'ui_test_case_executions' AND column_name = 'step_results'",
)
if not cur.fetchone():
    cur.execute('ALTER TABLE ui_test_case_executions ADD COLUMN step_results JSON NULL')
    print('ensured column step_results on ui_test_case_executions')
else:
    print('step_results already exists')

# 确保需求拆解结果历史表存在（新功能：拆解结果历史记录）
cur.execute('''
CREATE TABLE IF NOT EXISTS requirement_analysis_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(300) NOT NULL,
    requirement_text LONGTEXT,
    result_content LONGTEXT,
    content_preview LONGTEXT,
    project_id INT NULL,
    created_by_id INT NOT NULL,
    created_at DATETIME NOT NULL
)
''')
print('ensured table requirement_analysis_results')

# 确保深度追问清单表存在（需求拆解结果下的追问项持久化）
cur.execute('''
CREATE TABLE IF NOT EXISTS clarification_questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    analysis_result_id INT NOT NULL,
    question LONGTEXT,
    answer LONGTEXT,
    category VARCHAR(50) NOT NULL DEFAULT '其他',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    order_idx INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT fk_clarification_result
        FOREIGN KEY (analysis_result_id)
        REFERENCES requirement_analysis_results (id)
        ON DELETE CASCADE
)
''')
print('ensured table clarification_questions')

# 确保墨刀技能 - 原型表（新功能：墨刀需求读取与用例生成）
cur.execute('''
CREATE TABLE IF NOT EXISTS modao_prototype (
    id INT AUTO_INCREMENT PRIMARY KEY,
    uuid VARCHAR(32) NOT NULL,
    title VARCHAR(200) NOT NULL DEFAULT '墨刀需求梳理',
    url LONGTEXT,
    source_type VARCHAR(10) NOT NULL DEFAULT 'modao',
    auth_cookie LONGTEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    current_stage INT NOT NULL DEFAULT 0,
    extracted_json LONGTEXT,
    requirement_summary LONGTEXT,
    clarification_log LONGTEXT,
    module_split LONGTEXT,
    risks_json LONGTEXT,
    pci_json LONGTEXT,
    final_testpoints_json LONGTEXT,
    testcases_json LONGTEXT,
    smoke_json LONGTEXT,
    quality_report_json LONGTEXT,
    excel_path VARCHAR(500),
    stage_confirmations LONGTEXT,
    stage4_decision VARCHAR(20),
    error_message LONGTEXT,
    project_id INT NULL,
    created_by_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uniq_uuid (uuid),
    KEY idx_prototype_created (created_by_id)
)
''')
print('ensured table modao_prototype')

# 确保墨刀技能 - 页面表
cur.execute('''
CREATE TABLE IF NOT EXISTS modao_page (
    id INT AUTO_INCREMENT PRIMARY KEY,
    prototype_id INT NOT NULL,
    page_no INT NOT NULL,
    page_name VARCHAR(200),
    text LONGTEXT,
    annotations LONGTEXT,
    screenshot VARCHAR(500),
    KEY idx_page_prototype (prototype_id)
)
''')
print('ensured table modao_page')

# 确保墨刀原型表有 work_log 列（工作日志：各阶段进度记录）
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'modao_prototype' AND column_name = 'work_log'",
)
if not cur.fetchone():
    cur.execute('ALTER TABLE modao_prototype ADD COLUMN work_log LONGTEXT')
    print('ensured column work_log on modao_prototype')
else:
    print('work_log already exists')

# 确保墨刀原型表有 qa_log 列（人工答疑记录）
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'modao_prototype' AND column_name = 'qa_log'",
)
if not cur.fetchone():
    cur.execute('ALTER TABLE modao_prototype ADD COLUMN qa_log LONGTEXT')
    print('ensured column qa_log on modao_prototype')
else:
    print('qa_log already exists')

# 确保 modao_prototype 有 feature_module_id / version_id 列（阶段确认时同步功能模块）
for col in ('feature_module_id', 'version_id'):
    cur.execute(
        f"SELECT 1 FROM information_schema.columns "
        f"WHERE table_schema = DATABASE() AND table_name = 'modao_prototype' AND column_name = '{col}'",
    )
    if not cur.fetchone():
        cur.execute(f'ALTER TABLE modao_prototype ADD COLUMN {col} INT')
        print(f'ensured column {col} on modao_prototype')
    else:
        print(f'{col} already exists')

# 去重审计：保留每次向量去重的保留项、删除项、相似度和原因。
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'modao_prototype' AND column_name = 'dedup_audit_json'",
)
if not cur.fetchone():
    cur.execute("ALTER TABLE modao_prototype ADD COLUMN dedup_audit_json LONGTEXT NOT NULL DEFAULT ('[]')")
    print('ensured column dedup_audit_json on modao_prototype')

# 确保 feature_modules 有 parent_id 列（功能模块层级：阶段3 子模块挂在阶段1 顶层模块下）
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'feature_modules' AND column_name = 'parent_id'",
)
if not cur.fetchone():
    cur.execute('ALTER TABLE feature_modules ADD COLUMN parent_id INT NULL')
    print('ensured column parent_id on feature_modules')
else:
    print('parent_id already exists')

# 确保需求拆解结果表有 req_doc_id 列（关联需求文档，用于拆解结果持久化关联，刷新后重建）
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'requirement_analysis_results' AND column_name = 'req_doc_id'",
)
if not cur.fetchone():
    cur.execute('ALTER TABLE requirement_analysis_results ADD COLUMN req_doc_id INT NULL')
    print('ensured column req_doc_id on requirement_analysis_results')
else:
    print('req_doc_id already exists')

# 确保测试用例生成任务表有 confirmed_answers 列（存储拆解确认的问答对，用于用例生成上下文注入）
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'testcase_generation_task' AND column_name = 'confirmed_answers'",
)
if not cur.fetchone():
    cur.execute('ALTER TABLE testcase_generation_task ADD COLUMN confirmed_answers TEXT')
    print('ensured column confirmed_answers on testcase_generation_task')
else:
    print('confirmed_answers already exists')

# 确保 App 自动化流水线运行记录表存在（新功能：选应用 + 自定义阶段 + 运行记录重跑）。
# 注意：app_configs / app_devices 库内主键实际为 INT（与模型 BigAutoField 存在漂移），
# 因此外键列必须显式用 INT，避免 MySQL 3780 外键类型不兼容。
cur.execute('''
CREATE TABLE IF NOT EXISTS app_pipeline_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stages JSON,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    log LONGTEXT,
    result_summary LONGTEXT,
    snapshot_path VARCHAR(500),
    report_url VARCHAR(500),
    created_at DATETIME NOT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    duration DOUBLE NOT NULL DEFAULT 0,
    app_config_id INT NOT NULL,
    device_id INT NULL,
    created_by_id INT NULL,
    CONSTRAINT fk_pipeline_app_config FOREIGN KEY (app_config_id) REFERENCES app_configs (id),
    CONSTRAINT fk_pipeline_device FOREIGN KEY (device_id) REFERENCES app_devices (id),
    CONSTRAINT fk_pipeline_created_by FOREIGN KEY (created_by_id) REFERENCES auth_user (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
''')
print('ensured table app_pipeline_runs')
"""
    print("Ensuring center_x/center_y columns exist on ui_test_case_steps...")
    subprocess.run([sys.executable, "-c", ensure_script], check=False)

    # 库实际已完成全部 schema 迁移（本项目初始迁移是空占位，表已存在）。
    # 用 --fake 把所有迁移标记为已应用，不执行任何 SQL，避免对已存在的索引/
    # 表重复执行导致 “Duplicate key/Table already exists”。这让 django_migrations
    # 记录与库的真实状态一致，迁移检查通过、runserver 干净启动。
    print("Running migrations (fake all, no SQL executed)...")
    subprocess.run([sys.executable, "manage.py", "migrate", "--fake", "--no-input"], check=False)

    # 为移植进来的新应用(defects/data_factory/analytics/app_automation)建表。
    # 这些应用没有历史迁移占位，上面的 --fake 不会真正建表；用 schema_editor
    # 直接按模型建表（幂等：已存在的表跳过），保证容器重启/全新部署后表存在。
    print("Ensuring tables for ported apps (defects/data_factory/analytics/app_automation)...")
    subprocess.run(
        [sys.executable, "scripts/create_new_app_tables.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.abspath(__file__))},
        check=False,
    )

    print("Initializing locator strategies...")
    try:
        subprocess.run([sys.executable, "manage.py", "init_locator_strategies"], check=False)
    except Exception as e:
        print(f"init_locator_strategies skipped: {e}")

    print("Creating superuser if not exists...")
    create_su_script = """
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@testhub.local', 'Admin@123456')
    print('Superuser created: admin / Admin@123456')
else:
    print('Superuser already exists')
"""
    subprocess.run([sys.executable, "-c", create_su_script], check=True)

    print("==> Starting Django server on 0.0.0.0:8000 ...")
    os.execvp(sys.executable, [sys.executable, "manage.py", "runserver", "0.0.0.0:8000"])
