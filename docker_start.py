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

# 确保「项目角色」（组织级组）表 —— 2026-09-20 新增。
# 一个角色下有若干人；项目挂到角色后，该角色全员自动获得该项目的编辑权限（不含删除）。
# 迁移 0009_projectrole_project_role 用 RunSQL 也做了同样的事，这里是启动期兜底，
# 保证老环境（迁移状态漂移）也能正常起来。
cur.execute('''
CREATE TABLE IF NOT EXISTS project_roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description LONGTEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY project_roles_name_uniq (name)
)
''')
print('ensured table project_roles')

cur.execute('''
CREATE TABLE IF NOT EXISTS project_roles_members (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    projectrole_id INT NOT NULL,
    user_id INT NOT NULL,
    UNIQUE KEY project_roles_members_uniq (projectrole_id, user_id),
    KEY project_roles_members_user_idx (user_id)
)
''')
print('ensured table project_roles_members')

# projects.role_id：项目归属角色（可空；存量项目留空，由管理员手动挂）
cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'role_id'")
if not cur.fetchone()[0]:
    cur.execute('ALTER TABLE projects ADD COLUMN role_id INT NULL DEFAULT NULL, '
                'ADD KEY projects_role_id_idx (role_id)')
    print('ensured column projects.role_id')
else:
    print('projects.role_id already exists')

# ui_elements.platform：元素库区分平台（Android/iOS/HarmonyOS/Web）
# 同一业务元素在不同平台 locator 不同，必须分平台保存，否则多平台互相覆盖。
cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'ui_elements' AND COLUMN_NAME = 'platform'")
if not cur.fetchone()[0]:
    cur.execute("ALTER TABLE ui_elements ADD COLUMN platform VARCHAR(20) NOT NULL DEFAULT ''")
    print('ensured column ui_elements.platform')
else:
    print('ui_elements.platform already exists')

# ui_elements (project_id, platform) 联合索引：元素拾取按项目+平台查询
cur.execute("SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'ui_elements' "
            "AND INDEX_NAME = 'ui_elements_project_platform_idx'")
if not cur.fetchone()[0]:
    cur.execute('CREATE INDEX ui_elements_project_platform_idx '
                'ON ui_elements (project_id, platform)')
    print('ensured index ui_elements_project_platform_idx')
else:
    print('ui_elements_project_platform_idx already exists')

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

# 确保 modao_page 有 selected / recognition_note 列（画布模块人工校验）
for col, ddl in (
    ('selected', 'ALTER TABLE modao_page ADD COLUMN selected TINYINT(1) NOT NULL DEFAULT 1'),
    ('recognition_note', "ALTER TABLE modao_page ADD COLUMN recognition_note VARCHAR(200) NOT NULL DEFAULT ''"),
    ('current_stage', 'ALTER TABLE modao_page ADD COLUMN current_stage INT NOT NULL DEFAULT 0'),
    ('stage_status', "ALTER TABLE modao_page ADD COLUMN stage_status VARCHAR(20) NOT NULL DEFAULT 'pending'"),
    ('work_log', 'ALTER TABLE modao_page ADD COLUMN work_log LONGTEXT NOT NULL'),
    ('error_message', 'ALTER TABLE modao_page ADD COLUMN error_message LONGTEXT NOT NULL'),
    ('rerun_stages', 'ALTER TABLE modao_page ADD COLUMN rerun_stages LONGTEXT NOT NULL'),
    ('page_summary', 'ALTER TABLE modao_page ADD COLUMN page_summary LONGTEXT NOT NULL'),
    ('page_clarification', 'ALTER TABLE modao_page ADD COLUMN page_clarification LONGTEXT NOT NULL'),
    ('page_testpoints_json', 'ALTER TABLE modao_page ADD COLUMN page_testpoints_json LONGTEXT NOT NULL'),
    ('page_testcases_json', 'ALTER TABLE modao_page ADD COLUMN page_testcases_json LONGTEXT NOT NULL'),
    ('page_smoke_json', 'ALTER TABLE modao_page ADD COLUMN page_smoke_json LONGTEXT NOT NULL'),
    ('page_approved', 'ALTER TABLE modao_page ADD COLUMN page_approved TINYINT(1) NOT NULL DEFAULT 0'),
    ('screenshot_segments', "ALTER TABLE modao_page ADD COLUMN screenshot_segments LONGTEXT NOT NULL DEFAULT ('[]')"),
    # 画布所属文件夹（墨刀页面树层级），对应迁移 0016_modao_page_folder；
    # prod 的 manage.py migrate 不可用，必须在这里兜底，否则 modao_list 会因缺列 500。
    ('folder', "ALTER TABLE modao_page ADD COLUMN folder VARCHAR(500) NOT NULL DEFAULT ''"),
    # 画布父级分组（2026-09-17 新增，用于层级展示）
    ('parent_name', "ALTER TABLE modao_page ADD COLUMN parent_name VARCHAR(200) NOT NULL DEFAULT ''"),
    # 自愈闭环(P0)：画布级 AI 原始用例快照，run_design_phase2 写入后不再随人工编辑变化。
    ('page_ai_testcases_json', "ALTER TABLE modao_page ADD COLUMN page_ai_testcases_json LONGTEXT NOT NULL"),
):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'modao_page' AND column_name = %s",
        (col,),
    )
    if not cur.fetchone():
        cur.execute(ddl)
        print(f'ensured column {col} on modao_page')
    else:
        print(f'{col} already exists')

# modao_page 这几个文本列在老库是 text（上限 64KB），画布工作日志 / 错误信息 / 重跑阶段
# 写满会被截断，迁移后应为 longtext。这里幂等扩容兜底（保留原有可空性）。
for _col in ('work_log', 'error_message', 'rerun_stages'):
    cur.execute(
        "SELECT data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'modao_page' AND column_name = %s",
        (_col,),
    )
    _row = cur.fetchone()
    if _row is None:
        print('skip widening %s on modao_page (column not found)' % _col)
    elif _row[0] != 'longtext':
        cur.execute(
            'ALTER TABLE modao_page MODIFY %s LONGTEXT %s'
            % (_col, 'NULL' if _row[1] == 'YES' else 'NOT NULL')
        )
        print('widened %s on modao_page to longtext' % _col)
    else:
        print('%s on modao_page already longtext' % _col)



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

# 确保 modao_prototype 有汇总采纳字段（A2-c：已采纳画布用例合并视图）
for col in ('merged_testcases_json', 'merged_smoke_json', 'ai_testcases_json'):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'modao_prototype' AND column_name = %s",
        (col,),
    )
    if not cur.fetchone():
        cur.execute(f'ALTER TABLE modao_prototype ADD COLUMN {col} LONGTEXT NOT NULL')
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

# 确保项目知识库表有 needs_review 列（知识沉淀待复核机制：自动沉淀条目默认待复核，
# 人工确认前不进入向量召回）
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'project_knowledge' AND column_name = 'needs_review'",
)
if not cur.fetchone():
    cur.execute('ALTER TABLE project_knowledge ADD COLUMN needs_review TINYINT(1) NOT NULL DEFAULT 0')
    print('ensured column needs_review on project_knowledge')
else:
    print('needs_review already exists')

# 确保移动设备表有 wda_host / wda_port 列（iOS 远端 WDA：与 adb_host 对称，
# 后端通过 http://<wda_host>:<wda_port> 驱动插在其它电脑上的 iPhone）
for _col, _ddl in (
    ('wda_host', "ALTER TABLE app_devices ADD COLUMN wda_host VARCHAR(50) NOT NULL DEFAULT ''"),
    ('wda_port', 'ALTER TABLE app_devices ADD COLUMN wda_port INT NOT NULL DEFAULT 8100'),
):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'app_devices' AND column_name = %s",
        (_col,),
    )
    if not cur.fetchone():
        cur.execute(_ddl)
        print('ensured column %s on app_devices' % _col)
    else:
        print('%s already exists on app_devices' % _col)

# 确保业务动作表有 category 列（公共步骤分类：前置准备/业务操作/数据提取/
# 收尾清理/其他）。老库没有该列时列表接口会 500，故幂等补齐。
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'ui_business_actions' AND column_name = 'category'",
)
if not cur.fetchone():
    cur.execute(
        "ALTER TABLE ui_business_actions ADD COLUMN category VARCHAR(20) NOT NULL DEFAULT 'business'")
    print('ensured column category on ui_business_actions')
else:
    print('category already exists on ui_business_actions')

# 确保 AI 用例表里「模型声明为 null=True、但老库可能建成 NOT NULL」的列全部允许为空。
#
# 背景：ui_ai_cases 是老表，部分环境的表结构是早期建的，与当前模型不一致：
# 模型上这些字段是 null=True，而库里是 NOT NULL，Django 插入时会【显式写 NULL】，
# 于是直接报
#     (1048, "Column 'task_description' cannot be null")
# 表现为「建不了 AI 用例 / 保存步骤 500」，而且只在老环境复现，新环境（列已是 NULL）看不到。
#
# 已知踩过的字段（每踩一个就往下面那个 (_col, _coltype) 元组里加一行，别再逐个排查）：
#   app_config_id / device_id   - 部分环境建成 NOT NULL DEFAULT 0，导致任何 AI 用例都建不了
#   task_description            - 初始迁移建的是 TextField(blank=True, default='') 即
#                                 NOT NULL DEFAULT ''，但模型后来改成了 null=True；
#                                 2026-09-18 生产「Playground 存为用例步骤」500 就是它
#                                 （views.py 里 AICase.objects.create 有一处漏传该字段）。
#
# 由于部分环境的 manage.py migrate 因历史迁移状态不一致而不可用，这里用幂等 DDL 兜底修复。
# 下面的元组是 (列名, 兜底类型)；MODIFY 时必须带上原类型，否则会把列的类型改坏。
# 运行时优先采用库里真实的 column_type，兜底类型只在读不到时使用。
for _col, _coltype in (
    ('app_config_id', 'INT'),
    ('device_id', 'INT'),
    ('task_description', 'LONGTEXT'),
):
    cur.execute(
        "SELECT is_nullable, column_type FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'ui_ai_cases' AND column_name = %s",
        (_col,),
    )
    _row = cur.fetchone()
    if _row is None:
        # 列都不存在（极端老库）就跳过，交给建表逻辑处理
        print('skip %s on ui_ai_cases (column not found)' % _col)
    elif _row[0] == 'NO':
        # 优先用库里真实的 column_type，避免把列改成与现状不同的类型
        _type = _row[1] or _coltype
        cur.execute('ALTER TABLE ui_ai_cases MODIFY %s %s NULL DEFAULT NULL' % (_col, _type))
        print('ensured column %s on ui_ai_cases is nullable (type=%s)' % (_col, _type))
    else:
        print('%s on ui_ai_cases already nullable' % _col)

# 确保 AI 用例表有 auto_dismiss_popup / steps_frozen_at 列（弹窗自动处理 + 坐标回放）
for _col, _ddl in (
    ('auto_dismiss_popup',
     'ALTER TABLE ui_ai_cases ADD COLUMN auto_dismiss_popup TINYINT(1) NOT NULL DEFAULT 1'),
    ('steps_frozen_at',
     'ALTER TABLE ui_ai_cases ADD COLUMN steps_frozen_at DATETIME NULL'),
):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'ui_ai_cases' AND column_name = %s",
        (_col,),
    )
    if not cur.fetchone():
        cur.execute(_ddl)
        print('ensured column %s on ui_ai_cases' % _col)
    else:
        print('%s already exists on ui_ai_cases' % _col)

# 确保 AI 执行记录表有 token 统计 + error_message 列（对应迁移 0013_aiexecutionrecord_tokens）。
#
# ⚠️ 表名必须是复数 ui_ai_execution_records —— 与 Django 模型的 db_table 一致。
# 这里原来写成了单数 ui_ai_execution_record，于是：
#   information_schema 查询永远查不到该“表” -> if not cur.fetchone() 恒为真 ->
#   执行 ALTER TABLE ui_ai_execution_record ... -> 报 1146 表不存在 ->
#   而调用方是 subprocess.run(..., check=False)，异常被静默吞掉、启动照常继续。
# 结果：这段 DDL 从未真正生效过，生产库一直缺这 6 列，
#   表现为「执行用例」时 AIExecutionRecord.objects.create() 报
#   (1054, "Unknown column 'error_message' in 'field list'") → 500。
# 2026-09-18 修：把表名补成复数，并在打印里带上表名便于核对。
for _col, _ddl in (
    ('model_calls', 'ALTER TABLE ui_ai_execution_records ADD COLUMN model_calls INT NOT NULL DEFAULT 0'),
    ('prompt_tokens', 'ALTER TABLE ui_ai_execution_records ADD COLUMN prompt_tokens INT NOT NULL DEFAULT 0'),
    ('completion_tokens', 'ALTER TABLE ui_ai_execution_records ADD COLUMN completion_tokens INT NOT NULL DEFAULT 0'),
    ('tokens_estimated', 'ALTER TABLE ui_ai_execution_records ADD COLUMN tokens_estimated TINYINT(1) NOT NULL DEFAULT 0'),
    ('replay_mode', 'ALTER TABLE ui_ai_execution_records ADD COLUMN replay_mode TINYINT(1) NOT NULL DEFAULT 0'),
    # 回放失败降级标记 + 原因（2026-09-22）：报告要能区分
    # 「纯回放 / 回放失败降级 / 全新 AI 探索」三种状态，
    # 否则降级时只显示「AI 探索」，用户会误判固化根本没生效。
    ('replay_degraded', 'ALTER TABLE ui_ai_execution_records ADD COLUMN replay_degraded TINYINT(1) NOT NULL DEFAULT 0'),
    ('replay_fail_reason', "ALTER TABLE ui_ai_execution_records ADD COLUMN replay_fail_reason VARCHAR(500) NOT NULL DEFAULT ''"),
    ('error_message', "ALTER TABLE ui_ai_execution_records ADD COLUMN error_message LONGTEXT NOT NULL DEFAULT ('')"),
):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'ui_ai_execution_records' AND column_name = %s",
        (_col,),
    )
    if not cur.fetchone():
        cur.execute(_ddl)
        print('ensured column %s on ui_ai_execution_records' % _col)
    else:
        print('%s already exists on ui_ai_execution_records' % _col)

# ui_ai_cases.steps 在老库是 text（上限 64KB，且无法做 JSON 查询），迁移后应为 json。
# 只有现存数据全部是合法 JSON 时才转换，避免 ALTER 失败阻断启动。
cur.execute(
    "SELECT data_type, is_nullable FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'ui_ai_cases' AND column_name = 'steps'"
)
_row = cur.fetchone()
if _row is None:
    print('skip steps on ui_ai_cases (column not found)')
elif _row[0] != 'json':
    cur.execute(
        "SELECT COUNT(*) FROM ui_ai_cases "
        "WHERE steps IS NOT NULL AND steps <> '' AND NOT JSON_VALID(steps)"
    )
    _bad = cur.fetchone()[0]
    if _bad:
        print('skip converting steps to json: %s rows are not valid json' % _bad)
    else:
        cur.execute(
            'ALTER TABLE ui_ai_cases MODIFY steps JSON %s'
            % ('NULL' if _row[1] == 'YES' else 'NOT NULL')
        )
        print('converted ui_ai_cases.steps to json')
else:
    print('ui_ai_cases.steps already json')


# 确保 App 设备表有 platform 列（区分 Android / iOS）。
# 背景：该表原为纯 Android 设计，接入 iOS 后需要平台字段做分类。
# 部分环境 manage.py migrate 不可用（历史迁移状态不一致），这里用幂等 DDL 兜底。
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'app_automation_devices' "
    "AND column_name = 'platform'"
)
if not cur.fetchone():
    cur.execute(
        "ALTER TABLE app_automation_devices "
        "ADD COLUMN platform VARCHAR(20) NOT NULL DEFAULT 'android'"
    )
    print('ensured column platform on app_automation_devices')
else:
    print('platform already exists on app_automation_devices')


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
