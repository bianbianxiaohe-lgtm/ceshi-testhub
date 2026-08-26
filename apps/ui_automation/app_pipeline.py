"""
App 自动化流水线执行器
=====================
把万年历验证过的本地脚本 (capture → gen_pytest → run_pytest → allure)
封装成可参数化 (app_config / device / stages) 的平台执行逻辑。

阶段说明:
  - capture    : 启动 App, 抓 UI 快照 (page_source.xml + screenshot.png)
  - gen_pytest : 从快照生成 pytest 代码 (tests/)
  - run_pytest : 全量执行测试 (results/)
  - allure     : 生成 Allure HTML 报告 (report/)

执行方式: 由 ViewSet 在后台线程中调用 run_pipeline(record), 避免阻塞 HTTP 请求。
底层复用 .codebuddy/skills/appium-android-* 下已验证的脚本, 工作目录统一为
项目根的 appium_workspace/ (与本地一键脚本一致)。
"""
import os
import sys
import json
import time
import shutil
import subprocess
import threading

from django.utils import timezone
from django.db import close_old_connections

from .models import AppPipelineRun

# 项目根 (c:/TestHub)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 技能脚本目录
SKILL_DIR = os.path.join(BASE_DIR, '.codebuddy', 'skills')
# 统一工作目录
WORKSPACE = os.path.join(BASE_DIR, 'appium_workspace')

# 各阶段对应的脚本相对路径
SCRIPT_CAPTURE = os.path.join('appium-android-capture', 'scripts', 'capture_snapshot.py')
SCRIPT_GEN = os.path.join('appium-android-capture', 'scripts', 'gen_pytest.py')
SCRIPT_RUN = os.path.join('appium-android-run-pytest', 'scripts', 'run_pytest.py')
SCRIPT_ALLURE = os.path.join('appium-android-allure-report', 'scripts', 'gen_allure.py')

# 报告本地服务端口 (与本地一键脚本保持一致)
REPORT_PORT = 8088

STAGE_SCRIPTS = {
    'capture': SCRIPT_CAPTURE,
    'gen_pytest': SCRIPT_GEN,
    'run_pytest': SCRIPT_RUN,
    'allure': SCRIPT_ALLURE,
}

VALID_STAGES = list(STAGE_SCRIPTS.keys())


def log_append(record: AppPipelineRun, text: str) -> None:
    """追加一行日志到 record 并落库 (截断保护)。"""
    if not text:
        return
    record.log = (record.log or '') + text + '\n'
    # 单行过长可能影响性能, 这里直接整体保存
    try:
        close_old_connections()
        record.save(update_fields=['log'])
    except Exception:
        pass


def resolve_launch_activity(package: str):
    """用 adb 兜底获取启动 Activity (当 AppConfig.app_activity 为空时)。"""
    try:
        out = subprocess.run(
            ['adb.exe', 'shell', 'cmd', 'package', 'resolve-activity',
             '--brief', '-c', 'android.intent.category.LAUNCHER', package],
            capture_output=True, text=True, errors='replace', timeout=30
        )
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith(' ') or 'android' in line.lower():
                continue
            if '/' in line:
                # 形如 "com.x/.LauncherActivity" 或 "com.x/com.x.LauncherActivity"
                act = line.split()[-1].lstrip('/')
                return act
    except Exception as e:
        return None
    return None


def write_context(app_config, device) -> dict:
    """写入 context.json 供 capture 脚本使用。"""
    activity = app_config.app_activity or ''
    if not activity and app_config.package_name:
        activity = resolve_launch_activity(app_config.package_name) or ''
    appium_url = 'http://localhost:4723'
    udid = ''
    if device:
        appium_url = device.appium_server_url or appium_url
        udid = device.udid or ''
    ctx = {
        'apk_path': app_config.app_path or '',
        'package': app_config.package_name,
        'activity': activity,
        'device_udid': udid,
        'appium_url': appium_url,
        'pages': {'home': {'name': '首页'}},
    }
    os.makedirs(WORKSPACE, exist_ok=True)
    with open(os.path.join(WORKSPACE, 'context.json'), 'w', encoding='utf-8') as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)
    return ctx


def run_subprocess(script_rel: str, args: str, record: AppPipelineRun, timeout: int = 600) -> None:
    """运行一个技能脚本, 输出写入 record.log, 失败抛异常。"""
    script = os.path.join(SKILL_DIR, script_rel)
    if not os.path.exists(script):
        raise FileNotFoundError(f'脚本不存在: {script}')

    log_append(record, f'\n$ python {os.path.relpath(script, BASE_DIR)} {args}'.strip())
    cmd = [sys.executable, script] + args.split()
    proc = subprocess.run(
        cmd, cwd=BASE_DIR, capture_output=True, text=True, errors='replace', timeout=timeout
    )
    if proc.stdout:
        log_append(record, proc.stdout)
    if proc.returncode != 0:
        if proc.stderr:
            log_append(record, proc.stderr)
        raise RuntimeError(f'{os.path.basename(script)} 失败 (exit={proc.returncode})')


def run_pipeline(record_id: int) -> None:
    """后台线程入口: 按 record 配置执行选中的阶段。"""
    # 延迟导入避免循环
    from .models import AppPipelineRun as _Run

    try:
        record = _Run.objects.get(id=record_id)
    except _Run.DoesNotExist:
        return

    record.status = 'running'
    record.started_at = timezone.now()
    record.log = ''
    record.save(update_fields=['status', 'started_at', 'log'])

    app_config = record.app_config
    device = record.device
    stages = record.stages or VALID_STAGES

    log_append(record, f'开始流水线: app={app_config.name} '
                       f'({app_config.package_name}) device={device.udid if device else "auto"} '
                       f'stages={stages}')

    # 写 context
    try:
        ctx = write_context(app_config, device)
        log_append(record, f'context: package={ctx["package"]} activity={ctx["activity"]} '
                           f'udid={ctx["device_udid"]} appium={ctx["appium_url"]}')
    except Exception as e:
        record.status = 'failed'
        record.finished_at = timezone.now()
        log_append(record, f'[ERROR] 写 context 失败: {e}')
        record.save(update_fields=['status', 'finished_at', 'log'])
        return

    success = True
    try:
        for stage in stages:
            if stage not in STAGE_SCRIPTS:
                log_append(record, f'[SKIP] 未知阶段: {stage}')
                continue
            log_append(record, f'\n=== 阶段 {stage} ===')
            if stage == 'capture':
                run_subprocess(SCRIPT_CAPTURE,
                               f'--context {os.path.join(WORKSPACE, "context.json")} --page home',
                               record)
                snap = os.path.join(WORKSPACE, 'snapshots', 'home')
                if os.path.exists(snap):
                    record.snapshot_path = snap
            elif stage == 'gen_pytest':
                run_subprocess(SCRIPT_GEN, '', record)
            elif stage == 'run_pytest':
                results_dir = os.path.join(WORKSPACE, 'results')
                os.makedirs(results_dir, exist_ok=True)
                run_subprocess(SCRIPT_RUN,
                               f'--tests {os.path.join(WORKSPACE, "tests")}', record)
            elif stage == 'allure':
                report_dir = os.path.join(WORKSPACE, 'report')
                results_dir = os.path.join(WORKSPACE, 'results')
                if not os.path.exists(results_dir):
                    log_append(record, '[WARN] 无测试结果, 跳过报告生成')
                    continue
                run_subprocess(SCRIPT_ALLURE,
                               f'--results {results_dir} --report {report_dir} --no-serve',
                               record)
                record.report_url = f'http://localhost:{REPORT_PORT}/index.html'
            log_append(record, f'[OK] 阶段 {stage} 完成')

        record.result_summary = '全部选中阶段执行完成'
    except Exception as e:
        success = False
        log_append(record, f'\n[FAILED] {e}')

    record.status = 'success' if success else 'failed'
    record.finished_at = timezone.now()
    if record.started_at:
        record.duration = (record.finished_at - record.started_at).total_seconds()
    record.save(update_fields=['status', 'finished_at', 'duration', 'log',
                               'snapshot_path', 'report_url', 'result_summary'])


def rerun_pipeline(record_id: int, user=None) -> AppPipelineRun:
    """基于历史记录复制配置, 创建一条新运行记录并启动后台执行。"""
    src = AppPipelineRun.objects.get(id=record_id)
    new_rec = AppPipelineRun.objects.create(
        app_config=src.app_config,
        device=src.device,
        stages=src.stages,
        status='pending',
        created_by=user,
    )
    t = threading.Thread(target=run_pipeline, args=(new_rec.id,), daemon=True)
    t.start()
    return new_rec


def start_pipeline(app_config, device, stages, user=None) -> AppPipelineRun:
    """创建一条新的运行记录并启动后台执行。"""
    # 规整阶段顺序, 只保留合法阶段
    ordered = [s for s in VALID_STAGES if s in (stages or VALID_STAGES)]
    new_rec = AppPipelineRun.objects.create(
        app_config=app_config,
        device=device,
        stages=ordered,
        status='pending',
        created_by=user,
    )
    t = threading.Thread(target=run_pipeline, args=(new_rec.id,), daemon=True)
    t.start()
    return new_rec
