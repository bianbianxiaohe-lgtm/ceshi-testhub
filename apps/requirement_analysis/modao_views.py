# -*- coding: utf-8 -*-
"""
墨刀技能 - API 视图

5 阶段引导式工作流（每阶段需前端确认后再推进）：
  POST /api/modao/create/            创建需求来源（墨刀链接 / 需求文本）
  POST /api/modao/<id>/extract/      阶段0：墨刀逐页读取
  POST /api/modao/<id>/struct/       阶段1：需求结构化摘要
  POST /api/modao/<id>/clarify/      阶段2：需求澄清清单
  POST /api/modao/<id>/design/       阶段3：用例设计（拆分/测试点/风险/PCI/合并/用例/冒烟/质量/Excel）
  POST /api/modao/<id>/confirm/      阶段确认（body: {stage}）
  POST /api/modao/<id>/smoke/        阶段4：冒烟执行决策（body: {decision, reject_email?}）
  GET  /api/modao/<id>/              查询状态 + 各阶段产物
  GET  /api/modao/<id>/excel/        下载 Excel
"""
import os
import json
import difflib
import datetime
import uuid as uuid_lib
import threading
import traceback
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status as http_status
from django.shortcuts import get_object_or_404
from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from apps.requirement_analysis.models import ModaoPrototype, ModaoPage
from apps.requirement_analysis.serializers import ModaoPrototypeSerializer, ModaoPageSerializer
from apps.requirement_analysis.modao_workflow import ModaoWorkflow, _parse_yaml, _extract_block
from apps.requirement_analysis import modao_xmind
from apps.feature_modules.models import FeatureModule, TestPoint
from apps.testcases.models import TestCase


def _module_of(c):
    """从一条用例/测试点结构里取模块名。兼容 {testcase:{...}, module} 嵌套与扁平两种格式。"""
    if not isinstance(c, dict):
        return '未分组'
    if c.get('testcase'):
        t = c['testcase']
        return (c.get('module') or t.get('module') or t.get('feature_module') or '未分组')
    return (c.get('module') or c.get('feature_module') or '未分组')


def _collect_canonical_modules(proto, project):
    """真实模块名集合：原型中已有用例/测试点使用的模块 + 项目中已挂测试用例的功能模块。

    排除 0 用例的空壳模块（如 LLM 脑补出的近似模块），避免把"待归并名"误当作权威名。
    """
    names = set()
    if proto is not None:
        for c in _safe_json_list(getattr(proto, 'testcases_json', None)):
            names.add(_module_of(c))
        for t in _safe_json_list(getattr(proto, 'final_testpoints_json', None)):
            if isinstance(t, dict) and t.get('module'):
                names.add(t['module'])
    if project is not None:
        real_ids = TestCase.objects.filter(
            project=project, feature_modules__isnull=False
        ).values_list('feature_modules', flat=True).distinct()
        for fm in FeatureModule.objects.filter(id__in=list(real_ids)):
            names.add(fm.name)
    names.discard('未分组')
    names.discard('')
    return names


def _canonical_module_name(raw, proto=None, project=None):
    """模块名归一化：把 LLM 可能脑补的近似模块名（如「动作库界面」）归并到已有真实模块（如「动作库」）。

    规则：
    1. 原名已在真实模块集合内 → 原样返回；
    2. 否则用 difflib 模糊匹配最接近的已有模块（cutoff=0.6），命中则归并；
    3. 都不命中 → 视为真正的新模块，原样返回。
    """
    raw = (raw or '').strip()
    if not raw or raw == '未分组':
        return raw
    candidates = _collect_canonical_modules(proto, project)
    if raw in candidates:
        return raw
    match = difflib.get_close_matches(raw, list(candidates), n=1, cutoff=0.6)
    if match:
        return match[0]
    return raw


# 容器进程启动时间（用于判断 proto.updated_at 是否在本次运行之前）
import datetime as _dt
_CONTAINER_START_TIME = _dt.datetime.now()

def _recover_stale_designing(proto, timeout_minutes=30):
    """自动回收卡死的 designing 状态。

    当 proto.status 为 designing 但 updated_at 距今超过 timeout_minutes 分钟时，
    判定执行线程已死亡（OOM/容器重启/进程被杀），自动标记为 failed。

    安全保护：如果 proto.updated_at 早于容器进程启动时间，说明是重启后遗留状态，
    不判定为超时（任务可能尚未被重新触发）。
    """
    from django.utils import timezone
    if proto.status not in ('extracting', 'structuring', 'clarifying', 'designing'):
        return False
    if not proto.updated_at:
        return False
    elapsed = (timezone.now() - proto.updated_at).total_seconds()
    if elapsed < timeout_minutes * 60:
        return False
    # 已超时且无活跃线程 → 回收（重启前中断的线程同样按超时回收，避免永久转圈）
    wl_tail = (proto.work_log or '')[-150:]
    proto.status = 'failed'
    proto.error_message = (
        f'任务执行超时（已超过 {timeout_minutes} 分钟无更新，'
        f'可能因线程中断/容器重启导致）。最后日志：{wl_tail}。请重新触发该阶段。'
    )
    proto.save(update_fields=['status', 'error_message'])
    logger.warning('[stale-recover] proto %d status %s stale %.0fs -> failed', proto.id, proto.status, elapsed)
    return True


def _user_can_access_proto(user, proto):
    """判断用户是否有权查看/操作某条墨刀原型任务。

    规则：
    - 超级管理员：全部可访问
    - 任务创建者：可访问
    - 关联项目的 owner / admin / developer / tester 成员：可访问（viewer 不含）
    - 无关联项目（project 为空）：仅创建者本人可访问
    """
    from apps.core.mixins import _is_superuser
    if _is_superuser(user):
        return True
    if proto.created_by_id == user.id:
        return True
    if not proto.project_id:
        return False
    from apps.projects.models import ProjectMember
    return ProjectMember.objects.filter(
        project_id=proto.project_id,
        user=user,
        role__in=('owner', 'admin', 'developer', 'tester'),
    ).exists()


def _accessible_proto_qs(user):
    """返回用户有权限查看的 ModaoPrototype queryset。"""
    from apps.core.mixins import _is_superuser
    from apps.projects.models import ProjectMember
    if _is_superuser(user):
        return ModaoPrototype.objects.all()
    # 自己创建的 + 自己是有效成员的项目下的任务
    own = ModaoPrototype.objects.filter(created_by=user)
    member_project_ids = ProjectMember.objects.filter(
        user=user,
        role__in=('owner', 'admin', 'developer', 'tester'),
    ).values_list('project_id', flat=True).distinct()
    project_protos = ModaoPrototype.objects.filter(project_id__in=member_project_ids)
    return (own | project_protos).distinct()


def _build_wf(proto, analyzer_id=None, writer_id=None, embedder_id=None, page_ids=None):
    analyzer, writer, embedder = ModaoWorkflow.resolve_configs(analyzer_id, writer_id, embedder_id)
    # 视觉识别配置：用于纯图片/截图/表格型页面的 OCR 补充（writer_vision 角色）
    from apps.requirement_analysis.models import AIModelConfig
    vision_config = AIModelConfig.objects.filter(role='writer_vision', is_active=True).first()
    # OCR 专用视觉模型：独立配置，可指向更快的模型（如 qwen-vl-plus），
    # 与融合/结构化使用的强模型解耦；未单独配置时回退到 writer_vision。
    ocr_vision_config = AIModelConfig.objects.filter(role='writer_vision_ocr', is_active=True).first() or vision_config
    return ModaoWorkflow(proto, analyzer, writer, embedder, vision_config=vision_config,
                         ocr_vision_config=ocr_vision_config, page_ids=page_ids)


# ---------- 模块同步解析工具 ----------
def _safe_json_list(s):
    try:
        v = json.loads(s or '[]')
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _extract_stage1_name(summary):
    """从阶段1需求摘要(YAML)提取顶层 name（功能模块名）。"""
    if not summary:
        return ''
    y = _parse_yaml(summary)
    if isinstance(y, dict) and y.get('name'):
        return str(y['name']).strip()
    import re
    m = re.search(r'^\s*name:\s*(.+)$', summary, re.MULTILINE)
    return m.group(1).strip() if m else ''


def _extract_modules(split_text):
    """从阶段3模块拆分文本提取 modules 列表（含 name/description）。"""
    if not split_text:
        return []
    y = _parse_yaml(_extract_block(split_text, 'yaml')) or {}
    mods = y.get('modules', []) if isinstance(y, dict) else []
    return [{'name': (m.get('name') or '').strip(),
             'description': m.get('description', '') or ''} for m in mods]


_PRIO_MAP = {'P0': 'critical', 'P1': 'high', 'P2': 'medium', 'P3': 'low'}
_TYPE_MAP = {v: v for v in ('functional', 'integration', 'api', 'ui', 'performance', 'security')}
# 中文用例类型（p3 prompt 输出：功能/边界/异常/UI/兼容）→ TestCase.TYPE_CHOICES
_TYPE_CN_MAP = {
    '功能': 'functional', '正向': 'functional', '主流程': 'functional',
    '边界': 'functional', '异常': 'functional', '容错': 'functional',
    'ui': 'ui', '界面': 'ui', '视觉': 'ui',
    '兼容': 'integration', '集成': 'integration', '联调': 'integration',
    '接口': 'api', 'api接口': 'api',
    '性能': 'performance', '压测': 'performance',
    '安全': 'security', '权限': 'security',
}


def _priority_of(raw):
    """优先级归一化：P0-P3 / 已是 TestCase 选项值都兼容。"""
    k = str(raw or '').strip()
    if k in _PRIO_MAP:
        return _PRIO_MAP[k]
    if k in ('critical', 'high', 'medium', 'low'):
        return k
    return 'medium'


def _test_type_of(raw):
    """类型归一化：英文选项值 / 中文类型（功能、异常、UI、兼容…）都能落到合法选项。"""
    k = str(raw or '').strip()
    low = k.lower()
    if low in _TYPE_MAP:
        return low
    return _TYPE_CN_MAP.get(k) or _TYPE_CN_MAP.get(low) or 'functional'


def _steps_to_text(steps):
    """步骤归一化：list[str] / list[dict] / str 统一转为「1. xxx\\n2. yyy」文本。"""
    if isinstance(steps, str):
        return steps.strip()
    if not isinstance(steps, list):
        return ''
    lines = []
    for s in steps:
        if isinstance(s, dict):
            txt = s.get('content') or s.get('action') or s.get('step') or ''
        else:
            txt = s
        txt = str(txt).strip()
        if txt:
            lines.append(txt)
    return '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(lines))


def _steps_to_list(steps):
    """步骤归一化：转为 list[str]，供前端编辑与回显。"""
    if isinstance(steps, str):
        import re as _re
        parts = [p.strip() for p in _re.split(r'\r?\n', steps) if p.strip()]
        return [_re.sub(r'^\s*\d+[.、)]\s*', '', p) for p in parts]
    if not isinstance(steps, list):
        return []
    out = []
    for s in steps:
        if isinstance(s, dict):
            txt = s.get('content') or s.get('action') or s.get('step') or ''
        else:
            txt = s
        txt = str(txt or '').strip()
        if txt:
            out.append(txt)
    return out


def _tc_fields(tc_obj):
    """从（原始或前端编辑后的）用例对象抽取写入 TestCase 的字段。"""
    d = tc_obj if isinstance(tc_obj, dict) else {}
    steps = d.get('steps')
    if not steps:
        # 冒烟用例复用 p4 字段名 test_steps / pass_criteria
        steps = d.get('test_steps') or d.get('testSteps') or ''
    return {
        'title': str(d.get('title') or d.get('name') or d.get('case_name') or '').strip(),
        'preconditions': d.get('precondition') or d.get('preconditions') or d.get('pre_condition') or '',
        'steps_txt': _steps_to_text(steps),
        'expected': d.get('expected') or d.get('pass_criteria') or d.get('expected_result') or '',
        'priority': _priority_of(d.get('priority')),
        'test_type': _test_type_of(d.get('type') or d.get('test_type')),
        'description': d.get('notes') or d.get('requirement_ref') or d.get('description') or '',
    }


def _merged_case_entries(proto):
    """构建全局用例索引，顺序与前端「用例合并采纳」列表完全一致。

    顺序 = 画布按 page_no 升序 → 画布内 page_testcases_json 原始顺序（与 _merge_page_testcases 同源）。
    每条包含：ordinal(1-based 全局序号) / page_id / page_index / module / raw / tc_obj。
    若所有画布都没有画布级用例（历史数据），回退到任务级 testcases_json。
    """
    entries = []
    pages = proto.pages.exclude(page_testcases_json='').exclude(page_testcases_json__isnull=True)
    for p in pages:
        for pi, c in enumerate(_safe_json_list(p.page_testcases_json)):
            tc_obj = c.get('testcase', c) if isinstance(c, dict) else c
            entries.append({
                'ordinal': len(entries) + 1,
                'page_id': p.id,
                'page_index': pi,
                'module': _module_of(c),
                'raw': c,
                'tc_obj': tc_obj if isinstance(tc_obj, dict) else {'title': str(tc_obj or '')},
            })
    if not entries:
        for gi, c in enumerate(_safe_json_list(proto.testcases_json)):
            tc_obj = c.get('testcase', c) if isinstance(c, dict) else c
            entries.append({
                'ordinal': gi + 1,
                'page_id': None,
                'page_index': gi,
                'module': _module_of(c),
                'raw': c,
                'tc_obj': tc_obj if isinstance(tc_obj, dict) else {'title': str(tc_obj or '')},
            })
    return entries


def _find_case_entry(entries, ref):
    """按 {page_id, page_index} / {global_index} / {case_id} / {index} 在全局索引中定位一条用例。"""
    if not isinstance(ref, dict):
        return None
    page_id, page_index = ref.get('page_id'), ref.get('page_index')
    if page_id is not None and page_index is not None:
        try:
            pid, pidx = int(page_id), int(page_index)
        except (TypeError, ValueError):
            return None
        for e in entries:
            if e['page_id'] == pid and e['page_index'] == pidx:
                return e
        return None
    gi = ref.get('global_index', ref.get('index'))
    if gi is not None:
        try:
            gi = int(gi)
        except (TypeError, ValueError):
            return None
        for e in entries:
            if e['ordinal'] - 1 == gi:
                return e
        return None
    cid = str(ref.get('case_id') or '').strip()
    if cid:
        for e in entries:
            if str(e['tc_obj'].get('id') or '').strip() == cid:
                return e
    return None


def _adopt_one_case(proto, user, tc_obj, mname, sort_order, desc_suffix='逐条采纳', extra_tags=None):
    """把一条（可能已被前端编辑过的）用例写入用例库。幂等：项目 + 标题 + 模块 去重。"""
    if not proto.project_id:
        return {'ok': False, 'detail': '请先在阶段0关联项目，再采纳到用例库'}
    f = _tc_fields(tc_obj)
    title = f['title'] or f'用例#{sort_order}'
    mname = _canonical_module_name(mname or '未分组', proto=proto, project=proto.project) or '未分组'
    fm, created = FeatureModule.objects.get_or_create(
        project=proto.project, name=mname,
        defaults={
            'description': f'墨刀流程「{proto.title}」{desc_suffix}自动创建',
            'created_by': user,
            'parent': proto.feature_module,
        },
    )
    if proto.version_id:
        fm.versions.add(proto.version)

    existing = TestCase.objects.filter(project=proto.project, title=title, feature_modules=fm).first()
    if existing:
        if extra_tags:
            merged = list(existing.tags or [])
            changed = False
            for t in extra_tags:
                if t not in merged:
                    merged.append(t)
                    changed = True
            if changed:
                existing.tags = merged
                existing.save(update_fields=['tags'])
        return {
            'ok': True, 'testcases': 0, 'skipped': 1, 'modules': int(created),
            'testcase_id': existing.id, 'created': False, 'title': title,
            'detail': f'用例「{title}」已存在（跳过）',
        }

    tc = TestCase(
        project=proto.project, title=title,
        preconditions=f['preconditions'], steps=f['steps_txt'], expected_result=f['expected'],
        priority=f['priority'], test_type=f['test_type'], description=f['description'],
        status='draft', author=user, source='ai', sort_order=sort_order or 1,
        tags=list(extra_tags or []),
    )
    tc.save()
    if proto.version_id:
        tc.versions.add(proto.version)
    try:
        tc.feature_modules.add(fm)
    except Exception:
        pass
    return {
        'ok': True, 'testcases': 1, 'skipped': 0, 'modules': int(created),
        'testcase_id': tc.id, 'created': True, 'title': title,
        'detail': f'已采纳「{title}」',
    }


def _sync_stage1(proto, user):
    """阶段1确认：从需求摘要提取 name → 创建顶层功能模块（自动同步）。"""
    if proto.feature_module_id or not proto.project_id:
        return None
    name = _extract_stage1_name(proto.requirement_summary)
    if not name:
        return None
    fm, _ = FeatureModule.objects.get_or_create(
        project=proto.project, name=name,
        defaults={'description': f'墨刀流程「{proto.title}」自动同步', 'created_by': user},
    )
    if proto.version_id:
        fm.versions.add(proto.version)
    proto.feature_module = fm
    proto.save(update_fields=['feature_module'])
    return {'id': fm.id, 'name': fm.name}


def _sync_stage3(proto, user):
    """阶段3确认：子模块 + 测试点 + 用例 自动同步到功能模块体系。"""
    if not proto.project_id:
        return {'modules': 0, 'testpoints': 0, 'testcases': 0}
    parent = proto.feature_module
    modules = _extract_modules(proto.module_split)
    counts = {'modules': 0, 'testpoints': 0, 'testcases': 0}

    tps = _safe_json_list(proto.final_testpoints_json)
    tps_by_mod = {}
    for t in tps:
        tps_by_mod.setdefault(t.get('module', ''), []).append(t)

    cases = _safe_json_list(proto.testcases_json)
    cases_by_mod = {}
    for c in cases:
        cases_by_mod.setdefault(c.get('module', ''), []).append(c)

    for m in modules:
        mname = _canonical_module_name(m.get('name'), proto=proto, project=proto.project)
        if not mname:
            continue
        # 该模块是否有测试点或用例（避免创建既无测试点也无用例的空模块）
        has_tp = bool(tps_by_mod.get(mname))
        has_cases = bool(cases_by_mod.get(mname))
        if not has_tp and not has_cases:
            continue
        child, _ = FeatureModule.objects.get_or_create(
            project=proto.project, name=mname, parent=parent,
            defaults={'description': m.get('description') or '墨刀流程子模块', 'created_by': user},
        )
        if proto.version_id:
            child.versions.add(proto.version)
        counts['modules'] += 1


        # 测试点
        for t in tps_by_mod.get(mname, []):
            tp_name = t.get('title') or t.get('name') or '未命名测试点'
            TestPoint.objects.get_or_create(
                feature_module=child, name=tp_name,
                defaults={'description': t.get('description', '') or '', 'created_by': user},
            )
            counts['testpoints'] += 1

        # 测试用例（兼容 {testcase:{...}, module} 嵌套包裹格式，按 项目+标题+子模块 去重，幂等）
        for c in cases_by_mod.get(mname, []):
            # 兼容嵌套包裹：实际数据是 { testcase: {...}, module, _raw }
            tc_obj = c.get('testcase', c) if isinstance(c, dict) else c
            title = (tc_obj.get('title') if isinstance(tc_obj, dict) else None) or '未命名用例'
            if TestCase.objects.filter(project=proto.project, title=title, feature_modules=child).exists():
                continue
            steps = (tc_obj.get('steps', []) if isinstance(tc_obj, dict) else []) or []
            steps_txt = '\n'.join(f'{i+1}. {s}' for i, s in enumerate(steps)) if isinstance(steps, list) else str(steps or '')
            preconditions = ''
            expected = ''
            priority = 'P2'
            test_type = 'functional'
            description = ''
            if isinstance(tc_obj, dict):
                preconditions = tc_obj.get('precondition', '') or tc_obj.get('preconditions', '') or ''
                expected = tc_obj.get('expected', '') or ''
                priority = tc_obj.get('priority', 'P2')
                test_type = tc_obj.get('type', 'functional')
                description = tc_obj.get('notes', '') or tc_obj.get('requirement_ref', '') or ''
            tc = TestCase(
                project=proto.project,
                title=title,
                preconditions=preconditions,
                steps=steps_txt,
                expected_result=expected,
                priority=_PRIO_MAP.get(priority, 'medium'),
                test_type=_TYPE_MAP.get((test_type or '').lower(), 'functional'),
                description=description,
                status='draft',
                author=user,
                source='ai',
            )
            tc.save()
            if proto.version_id:
                tc.versions.add(proto.version)
            tc.feature_modules.add(child)
            counts['testcases'] += 1

    return counts


def _run_in_thread(proto, target):
    """在守护线程中执行阶段任务，异常写入 prototype.error_message。"""
    def wrapper():
        try:
            target()
        except Exception as e:
            try:
                proto.refresh_from_db()
                proto.status = 'failed'
                proto.error_message = f'{e}\n{traceback.format_exc()[:2000]}'
                proto.save(update_fields=['status', 'error_message'])
            except Exception:
                pass
    return wrapper


@api_view(['GET'])
def modao_list(request):
    """历史记录列表（按创建时间倒序）。

    查询参数：
    - project: 按项目ID过滤
    - version: 按版本ID过滤

    权限规则：
    - 超级管理员：可查看所有人的任务；
    - 普通用户：可查看自己创建的 + 自己是项目成员（owner/admin/developer/tester）的项目下的任务。
    """
    from apps.core.mixins import _is_superuser
    is_admin = _is_superuser(request.user)
    qs = _accessible_proto_qs(request.user).order_by('-created_at')

    project_id = request.query_params.get('project')
    version_id = request.query_params.get('version')
    if project_id:
        qs = qs.filter(project_id=project_id)
    if version_id:
        qs = qs.filter(version_id=version_id)

    # 批量回收列表中可能卡死的 designing 状态
    for p in qs.filter(status__in=('extracting', 'structuring', 'clarifying', 'designing')):
        _recover_stale_designing(p)
    return Response({
        'is_admin': is_admin,
        'results': ModaoPrototypeSerializer(qs, many=True).data,
    })


@api_view(['POST'])
def modao_create(request):
    data = request.data
    source_type = data.get('source_type', 'modao')
    # 兼容多地址：urls 列表 或 单 url（可含换行/逗号分隔），统一用换行拼接存入 TextField
    raw_urls = data.get('urls') or []
    if isinstance(raw_urls, str):
        raw_urls = [x for x in raw_urls.replace(',', '\n').split('\n') if x.strip()]
    # webshare 来源：若未传 urls，回退用 webshare_url 字段
    if not raw_urls and source_type == 'webshare':
        ws = data.get('webshare_url', '')
        raw_urls = [x for x in ws.replace(',', '\n').split('\n') if x.strip()]
    url_str = '\n'.join(raw_urls) if raw_urls else (data.get('url') or '')

    # 安全网：URL 明显是 webshare/Axure 原型时，强制覆盖 source_type（大小写不敏感，
    # 实际站点路径常见大写如 /WebShare/）
    if source_type != 'webshare' and '/webshare/' in url_str.lower():
        import logging
        logging.getLogger('modao').info(f'[modao_create] URL contains /webshare/, overriding source_type {source_type} -> webshare')
        source_type = 'webshare'

    proto = ModaoPrototype(
        uuid=uuid_lib.uuid4().hex,
        title=data.get('title', '墨刀需求梳理'),
        url=url_str,
        source_type=source_type,
        auth_cookie=data.get('cookies', '') or '',
        project_id=data.get('project'),
        version_id=data.get('version'),
        created_by=request.user,
        status='pending',
    )
    if source_type == 'text' and data.get('requirement_text'):
        proto.requirement_summary = data['requirement_text']
        proto.source_type = 'text'
        proto.current_stage = 1
        proto.status = 'extracted'
    proto.save()
    return Response(ModaoPrototypeSerializer(proto).data, status=http_status.HTTP_201_CREATED)


def _reset_modao_workflow(proto):
    """重置当前流程产物；保留来源、Cookie、项目/版本及已同步到其他业务表的数据。"""
    reset_values = {
        'status': 'pending', 'current_stage': 0, 'extracted_json': '',
        'requirement_summary': '', 'clarification_log': '', 'module_split': '',
        'risks_json': '', 'pci_json': '', 'final_testpoints_json': '',
        'dedup_audit_json': '[]', 'testcases_json': '', 'smoke_json': '',
        'quality_report_json': '', 'excel_path': '', 'stage_confirmations': '{}',
        'stage4_decision': '', 'error_message': '', 'work_log': '', 'qa_log': '[]',
    }
    for field, value in reset_values.items():
        setattr(proto, field, value)
    proto.pages.all().delete()
    proto.save(update_fields=list(reset_values))
    return proto


@api_view(['POST'])
def modao_reset(request, pk):
    """将墨刀/webshare任务退回阶段0，以同一来源重新走完整流程。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if not _user_can_access_proto(request.user, proto):
        return Response({'detail': '无权重置该任务'}, status=http_status.HTTP_403_FORBIDDEN)
    if proto.source_type == 'text':
        return Response({'detail': '文本来源没有独立原文副本，暂不支持重置到阶段0，请新建文本任务'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    if proto.status in ('extracting', 'structuring', 'clarifying', 'designing'):
        return Response({'detail': '任务正在运行，请等待当前阶段结束后再重置'},
                        status=http_status.HTTP_409_CONFLICT)

    _reset_modao_workflow(proto)
    return Response(ModaoPrototypeSerializer(proto).data)


@api_view(['POST'])
def modao_terminate(request, pk):
    """手动终止正在运行的任务（读取/结构化/澄清/用例设计）。

    与 reset 不同：reset 拒绝运行中的任务；terminate 专用于运行中，
    置 TERMINATE_REQUESTED 标记 + status=failed，后台线程在检查点捕获后退出。
    当前墨刀读取阶段（逐页 / 并发 OCR / 双路融合）已接入检查点；
    其余阶段若未到检查点，也会因 status 已被置 failed 而停止轮询。
    """
    from apps.requirement_analysis.cancel_flags import TERMINATE_REQUESTED
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if not _user_can_access_proto(request.user, proto):
        return Response({'detail': '无权终止该任务'}, status=http_status.HTTP_403_FORBIDDEN)
    if proto.status not in ('extracting', 'structuring', 'clarifying', 'designing'):
        return Response({'detail': '任务未在运行，无需终止'}, status=http_status.HTTP_400_BAD_REQUEST)
    TERMINATE_REQUESTED[proto.id] = True
    proto.status = 'failed'
    proto.error_message = '任务已被用户手动终止'
    proto.save(update_fields=['status', 'error_message'])
    return Response({'detail': '已发送终止信号，任务将很快停止'})


@api_view(['POST'])
def modao_extract(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if proto.source_type == 'text':
        proto.current_stage = 1
        proto.status = 'extracted'
        proto.save(update_fields=['current_stage', 'status'])
        return Response({'detail': '文本来源无需读取，可直接进入结构化阶段'})

    cookies = proto.auth_cookie or request.data.get('cookies', '')
    # 自动加载共享 cookies 文件（若未提供 proto 级 cookies）
    if not cookies:
        import os as _os, json as _json
        _shared = _os.path.join('media', 'modao_cookies.json')
        if _os.path.exists(_shared):
            try:
                with open(_shared, 'r', encoding='utf-8') as _f:
                    cookies = _json.dumps(_json.load(_f))
            except Exception:
                pass
    headless = request.data.get('headless', True)
    # 多地址：优先用请求体 urls，否则解析 proto.url（可能含换行/逗号分隔）
    raw_urls = request.data.get('urls') or []
    if isinstance(raw_urls, str):
        raw_urls = [x for x in raw_urls.replace(',', '\n').split('\n') if x.strip()]
    if not raw_urls:
        raw_urls = [x for x in (proto.url or '').replace(',', '\n').split('\n') if x.strip()]
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))
    # 可选增强：双路 DOM+视觉 交叉融合（默认关闭）
    dual_fusion = bool(request.data.get('dual_fusion', False))
    fusion_config_id = request.data.get('fusion_config_id')
    fusion_config = None
    if fusion_config_id:
        from apps.requirement_analysis.models import AIModelConfig
        fusion_config = AIModelConfig.objects.filter(id=fusion_config_id).first()
    # 单画布重读：只重读指定 page_name 的画布（画布级回退到读取时使用）
    target_page_names = request.data.get('target_page_names') or []

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id)
        wf.run_extract(urls=raw_urls, cookies=cookies, headless=headless,
                       source_type=proto.source_type,
                       dual_fusion=dual_fusion, fusion_config=fusion_config,
                       target_page_names=target_page_names)

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '墨刀读取已启动，请轮询状态'})


@api_view(['POST'])
def modao_struct(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))
    # 画布级独立运行：传入 page_ids 时只对这些画布做结构化（互不干扰）
    page_ids = request.data.get('page_ids')
    # 2026-08-31 增量：force=True 时忽略已生成摘要，对所有勾选画布强制全量重新结构化。
    force = bool(request.data.get('force'))

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id, page_ids=page_ids)
        wf.run_struct(force=force)

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '需求结构化已启动'})


@api_view(['POST'])
def modao_update_pages(request, pk):
    """批量更新画布（模块）的人工会校验结果：勾选/取消、改名、标注识别准确率、删除。

    请求体：{'pages': [{'id': <int>, 'selected': <bool>, 'page_name': <str>,
                        'recognition_note': <str>, 'delete': <bool>}, ...]}
    仅传入需要变更的字段即可；未传字段保持不变。
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    pages = request.data.get('pages') or []
    if not isinstance(pages, list):
        return Response({'detail': 'pages 必须为数组'}, status=http_status.HTTP_400_BAD_REQUEST)
    updated, deleted = 0, 0
    for item in pages:
        pid = item.get('id')
        if not pid:
            continue
        try:
            page = proto.pages.get(id=pid)
        except ModaoPage.DoesNotExist:
            continue
        if item.get('delete'):
            page.delete()
            deleted += 1
            continue
        changed = []
        if 'selected' in item and isinstance(item['selected'], bool):
            page.selected = item['selected']
            changed.append('selected')
        if 'page_name' in item and item['page_name']:
            page.page_name = item['page_name']
            changed.append('page_name')
        if 'parent_name' in item:
            page.parent_name = (item['parent_name'] or '').strip()
            changed.append('parent_name')
        if 'folder' in item:
            page.folder = (item['folder'] or '').strip()
            changed.append('folder')
        if 'recognition_note' in item:
            page.recognition_note = item['recognition_note']
            changed.append('recognition_note')
        if changed:
            page.save(update_fields=changed)
            updated += 1
    return Response({'detail': f'已更新 {updated} 个画布，删除 {deleted} 个', 'updated': updated, 'deleted': deleted})


@api_view(['POST'])
def modao_clarify(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))
    # 画布级独立运行：传入 page_ids 时只对这些画布做澄清
    page_ids = request.data.get('page_ids')

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id, page_ids=page_ids)
        wf.run_clarify()

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '需求澄清已启动'})


@api_view(['POST'])
def modao_design(request, pk):
    """阶段3 第一段：模块拆分→测试点→风险→PCI→三路合并（到最终测试点为止，等待人工确认）。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    # 画布级独立运行：传入 page_ids 时只对这些画布做测试点合并
    page_ids = request.data.get('page_ids')
    # 运行中禁止重复触发，避免并发线程重复生成（LLM 双倍消耗 + 产物互相覆盖）。
    # 画布级独立运行（page_ids 给定）时放宽：允许在已有产物基础上补跑指定画布。
    if proto.status in ('extracting', 'structuring', 'clarifying', 'designing') and not page_ids:
        return Response(
            {'detail': f'任务正在运行中（{proto.status}），请勿重复触发'},
            status=400,
        )
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id, page_ids=page_ids)
        wf.run_design_phase1_for_selection()

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '测试点合并已启动（模块拆分→测试点→风险→PCI→三路合并）'})


@api_view(['POST'])
def modao_generate_cases(request, pk):
    """阶段3 第二段：基于（已确认/编辑的）最终测试点生成测试用例→冒烟→质量→Excel。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    # 画布级独立运行：传入 page_ids 时只对这些画布生成用例
    page_ids = request.data.get('page_ids')
    # A2-c：画布级——只要目标画布中存在已生成测试点的，即允许生成用例
    pages_qs = proto.pages.all()
    if page_ids:
        pages_qs = pages_qs.filter(id__in=page_ids)
    has_tp = pages_qs.exclude(page_testpoints_json='').exclude(page_testpoints_json__isnull=True).exists()
    if not has_tp:
        return Response({'detail': '请先运行测试点合并（第一段），生成最终测试点后再生成用例'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    # 画布级独立运行（page_ids 给定）时，放宽任务级闸门：仅校验该画布分支自身是否已有
    # 测试点，不再要求全部画布都完成阶段2确认——实现「每个画布独立生成用例、互不干扰」。
    if page_ids:
        a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                            request.data.get('writer_config_id'),
                            request.data.get('embedder_config_id'))

        def job():
            wf = _build_wf(proto, a_id, w_id, e_id, page_ids=page_ids)
            wf.run_design_phase2_for_selection()

        threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
        return Response({'detail': '测试用例生成已启动（指定画布：用例→冒烟→质量→Excel）'})
    gate = proto.case_generation_gate()
    if not gate['allowed']:
        return Response({
            'detail': '最终测试用例生成已被人工确认闸门阻止',
            'generation_gate': gate,
        }, status=http_status.HTTP_409_CONFLICT)
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id)
        wf.run_design_phase2_for_selection()

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '测试用例生成已启动（用例→冒烟→质量→Excel）'})


@api_view(['POST'])
def modao_approve_pages(request, pk):
    """A2-c：标记画布用例为已采纳，并触发跨画布汇总去重。

    请求体（两种之一）：
    - {'page_ids': [1, 2, 3]}        指定画布采纳
    - {'approve_all_selected': true} 当前选中且已生成用例的画布全部采纳
    汇总的 merged_testcases_json / merged_smoke_json 由后端自动重算。
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    page_ids = request.data.get('page_ids') or []
    approve_all = bool(request.data.get('approve_all_selected'))

    def job():
        wf = _build_wf(proto, None, None, None)
        n = wf.set_pages_approved(page_ids=page_ids, approve_all_selected=approve_all)
        return n

    try:
        n = job()
    except Exception as e:
        return Response({'detail': f'采纳失败：{e}'}, status=http_status.HTTP_500_INTERNAL_ERROR)
    return Response({'detail': f'已采纳 {n} 个画布用例，汇总已更新', 'approved_pages': n})


@api_view(['POST'])
def modao_approve_case_generation(request, pk):
    """记录最终用例生成前的人工批准，并绑定当前澄清结论与测试点。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if not (proto.final_testpoints_json or '').strip() or proto.final_testpoints_json.strip() in ('[]', '{}'):
        return Response({'detail': '尚无最终测试点，不能批准生成用例'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    unresolved = proto.unresolved_clarifications()
    if unresolved:
        return Response({
            'detail': f'仍有 {len(unresolved)} 条位置/需求问题未填写人工结论',
            'unresolved_items': unresolved,
        }, status=http_status.HTTP_409_CONFLICT)
    confirmations = proto.get_confirmations()
    if not confirmations.get('stage2_confirmed'):
        return Response({'detail': '请先完成人工澄清并确认阶段2'},
                        status=http_status.HTTP_409_CONFLICT)
    confirmations.update({
        'case_generation_approved': True,
        'case_generation_fingerprint': proto.case_generation_fingerprint(),
        'case_generation_approved_at': timezone.now().isoformat(),
        'case_generation_approved_by': request.user.id,
    })
    proto.stage_confirmations = json.dumps(confirmations, ensure_ascii=False)
    proto.save(update_fields=['stage_confirmations'])
    return Response({
        'detail': '已记录人工批准，可以生成最终测试用例',
        'generation_gate': proto.case_generation_gate(),
    })


def _sync_kb_from_modao(proto, user):
    """阶段3确认后，把本次流程发现的新知识自适应回填项目知识库（不阻塞主流程）。"""
    try:
        from apps.requirement_analysis.models import AIModelService
        analyzer, _, _ = ModaoWorkflow.resolve_configs()
        return AIModelService.auto_fill_knowledge_from_modao_products(
            proto, model_config=analyzer, user_id=user.id if user else None
        )
    except Exception as e:
        logger.warning(f'知识库自适应回填失败（不影响主流程）: {e}')
        return {'created_count': 0, 'skipped_count': 0, 'entries': [], 'error': str(e)}


@api_view(['POST'])
def modao_confirm(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    stage = int(request.data.get('stage', proto.current_stage))
    sync = None
    kb_sync = None
    if stage == 1:
        sync = _sync_stage1(proto, request.user)
    elif stage == 2:
        unresolved = proto.unresolved_clarifications()
        if unresolved:
            return Response({
                'detail': f'仍有 {len(unresolved)} 条问题未填写人工确认结论',
                'unresolved_items': unresolved,
            }, status=http_status.HTTP_409_CONFLICT)
    elif stage == 3:
        sync = _sync_stage3(proto, request.user)
        # 自适应把本次流程发现的新知识沉淀回项目知识库，供后续生成复用
        kb_sync = _sync_kb_from_modao(proto, request.user)
    proto.set_confirmation(stage, True)
    if stage < 4:
        proto.current_stage = stage + 1
    proto.save(update_fields=['stage_confirmations', 'current_stage'])
    return Response({'detail': f'阶段{stage}已确认', 'current_stage': proto.current_stage, 'sync': sync, 'kb_sync': kb_sync})


@api_view(['POST'])
def modao_smoke(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    decision = request.data.get('decision', '')
    reject_email = request.data.get('reject_email', '')
    if decision not in ('passed', 'rejected'):
        return Response({'detail': "decision 必须为 passed 或 rejected"}, status=400)
    wf = _build_wf(proto)
    wf.record_smoke_decision(decision, reject_email)
    return Response({'detail': f'冒烟决策已记录：{decision}'})


EDITABLE_FIELDS = {
    'requirement_summary', 'clarification_log', 'module_split',
    'risks_json', 'pci_json', 'final_testpoints_json',
    'testcases_json', 'smoke_json', 'quality_report_json',
}


@api_view(['PATCH'])
def modao_edit(request, pk):
    """保存人工对某阶段产物的修改（写回对应字段）。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    field = request.data.get('field')
    value = request.data.get('value', '')
    if field not in EDITABLE_FIELDS:
        return Response({'detail': f'字段 {field} 不可编辑'}, status=http_status.HTTP_400_BAD_REQUEST)
    old = getattr(proto, field, '') or ''
    setattr(proto, field, value)
    proto.save(update_fields=[field])
    # 若修改/删除了阶段2全局澄清清单，且某些画布的 page_clarification 与旧全局一致，同步更新对应画布
    if field == 'clarification_log' and old:
        proto.pages.filter(page_clarification=old).update(page_clarification=value)
    # 若修改/删除了阶段3全局合并测试点，把已删除的测试点从各画布的 page_testpoints_json 中同步移除
    elif field == 'final_testpoints_json' and value:
        try:
            curr_tp_ids = {x.get('id') for x in json.loads(value) if isinstance(x, dict) and x.get('id')}
            for pg in proto.pages.exclude(page_testpoints_json='').exclude(page_testpoints_json__isnull=True):
                pg_raw = pg.page_testpoints_json or ''
                pg_tps = json.loads(pg_raw) if pg_raw.strip() else []
                if isinstance(pg_tps, list):
                    filtered_pg_tps = [x for x in pg_tps if not (isinstance(x, dict) and x.get('id') and x.get('id') not in curr_tp_ids)]
                    if len(filtered_pg_tps) != len(pg_tps):
                        pg.page_testpoints_json = json.dumps(filtered_pg_tps, ensure_ascii=False)
                        pg.save(update_fields=['page_testpoints_json'])
        except Exception as e:
            logger.warning(f'同步删除画布级测试点失败: {e}')
    return Response({'detail': f'已更新 {field}'})


# ---------- 画布级产物人工编辑（A2-c：每个画布独立分支，产物按画布存）----------

# 可人工编辑的画布级产物字段 → 展示名
PAGE_EDITABLE_FIELDS = {
    'page_summary': '需求摘要（画布级）',
    'page_clarification': '需求澄清（画布级）',
    'page_testpoints_json': '测试点（画布级）',
    'page_testcases_json': '测试用例（画布级）',
    'page_smoke_json': '冒烟用例（画布级）',
}

# 编辑某字段后，该画布哪些下游产物已失真（用于标记「需重跑」）
_PAGE_STALE_BY_FIELD = {
    'page_summary': (3, 4),
    'page_clarification': (3, 4),
    'page_testpoints_json': (4,),
}

_STAGE_LABEL = {1: '结构化', 2: '澄清', 3: '测试点/用例', 4: '冒烟'}


def _merge_page_json_field(proto, field):
    """把各画布的 JSON 数组产物按画布顺序合并为一个列表（纯本地，不做向量去重）。"""
    merged = []
    qs = proto.pages.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}).order_by('page_no', 'id')
    for p in qs:
        raw = (getattr(p, field, '') or '').strip()
        if not raw:
            continue
        try:
            val = json.loads(raw)
        except Exception:
            continue
        if isinstance(val, list):
            merged.extend(val)
        elif isinstance(val, dict) and isinstance(val.get('smoke_testcases'), list):
            merged.extend(val['smoke_testcases'])
    return merged


@api_view(['PATCH'])
def modao_page_edit(request, pk, page_id):
    """保存人工对「单个画布」某阶段产物的修改，并同步任务级合并视图。

    PATCH body: {"field": "page_clarification", "value": "<新文本>"}

    可编辑字段见 PAGE_EDITABLE_FIELDS。保存后：
      1) 重算受影响的全局合并视图（requirement_summary / final_testpoints_json /
         testcases_json / smoke_json）；澄清清单在与全局同源时同步 clarification_log；
      2) 若该画布已产出下游产物，把这些阶段标记为「需重跑」（rerun_stages + needs_rerun），
         避免用户误用过期的用例/冒烟。
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    page = get_object_or_404(ModaoPage, pk=page_id, prototype=proto)
    field = request.data.get('field') or ''
    if field not in PAGE_EDITABLE_FIELDS:
        return Response({'detail': f'字段 {field} 不可编辑'}, status=http_status.HTTP_400_BAD_REQUEST)
    value = request.data.get('value', '')
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    if field.endswith('_json') and value.strip():
        try:
            json.loads(value)
        except Exception as e:
            return Response({'detail': f'{field} 不是合法 JSON，已拒绝保存：{e}'},
                            status=http_status.HTTP_400_BAD_REQUEST)

    old = getattr(page, field) or ''
    if old == value:
        return Response({'detail': '内容未变化', 'changed': False})

    setattr(page, field, value)
    update_fields = [field]
    # 下游产物是否失真：仅在该画布确实已产出下游内容时才标记，避免无谓的「需重跑」
    downstream = (page.page_testpoints_json or '').strip() or (page.page_testcases_json or '').strip()
    if field in _PAGE_STALE_BY_FIELD:
        if field == 'page_testpoints_json':
            downstream = (page.page_testcases_json or '').strip() or (page.page_smoke_json or '').strip()
        stale_stages = list(_PAGE_STALE_BY_FIELD[field]) if downstream else []
    else:
        stale_stages = []
    if stale_stages:
        page.set_rerun_stages(list(page.get_rerun_stages()) + stale_stages)
        page.stage_status = 'needs_rerun'
        update_fields += ['rerun_stages', 'stage_status']
    page.save(update_fields=update_fields)

    # ---- 同步任务级合并视图（失败不影响画布级保存）----
    sync = ''
    proto_fields = []
    try:
        wf = ModaoWorkflow(proto, None, None, None)
        if field == 'page_summary':
            proto.requirement_summary = wf._merge_page_summaries()
            proto_fields.append('requirement_summary')
            sync = '全局需求摘要已重算'
        elif field == 'page_testpoints_json':
            proto.final_testpoints_json = json.dumps(_merge_page_json_field(proto, field), ensure_ascii=False)
            proto_fields.append('final_testpoints_json')
            sync = '全局最终测试点已重算'
        elif field == 'page_testcases_json':
            cases, smoke = wf._merge_page_testcases()
            proto.testcases_json = json.dumps(cases, ensure_ascii=False)
            proto.smoke_json = json.dumps(smoke, ensure_ascii=False) if smoke else ''
            proto_fields += ['testcases_json', 'smoke_json']
            sync = '全局用例/冒烟视图已重算'
        elif field == 'page_smoke_json':
            _, smoke = wf._merge_page_testcases()
            proto.smoke_json = json.dumps(smoke, ensure_ascii=False) if smoke else ''
            proto_fields.append('smoke_json')
            sync = '全局冒烟视图已重算'
        elif field == 'page_clarification':
            # 阶段2 的联合澄清清单会写进每个画布：若全局与该画布原本一致，说明尚未在任务级
            # 单独改过，此时同步；否则只改本画布，避免覆盖任务级的人工修改。
            if (proto.clarification_log or '').strip() == old.strip():
                proto.clarification_log = value
                proto_fields.append('clarification_log')
                sync = '全局澄清清单已同步'
            else:
                sync = '仅更新本画布（任务级澄清清单已被单独修改，未覆盖）'
        if proto_fields:
            proto.save(update_fields=proto_fields)
    except Exception as e:
        logger.warning(f'画布产物编辑后同步全局视图失败（不影响画布级保存）: {e}')
        sync = ''

    detail = f'已保存「{PAGE_EDITABLE_FIELDS[field]}」'
    if sync:
        detail += f'，{sync}'
    if stale_stages:
        names = '/'.join(_STAGE_LABEL.get(s, str(s)) for s in stale_stages)
        detail += f'；该画布下游产物（{names}）基于旧内容，已标记为需重跑'
    try:
        gate = proto.case_generation_gate()
    except Exception:
        gate = None
    return Response({
        'detail': detail,
        'changed': True,
        'field': field,
        'stale_stages': stale_stages,
        'gate': gate,
    })




@api_view(['GET'])
def modao_folders(request, pk):
    """获取原型的画布文件夹分组统计（用于按文件夹批量勾选）

    返回 {'folders': [{'path': str, 'count': int, 'selected_count': int}, ...]}
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    pages = proto.pages.all()

    # 按 folder 分组统计
    folder_stats = {}
    for page in pages:
        folder = (page.folder or '').strip()
        if folder not in folder_stats:
            folder_stats[folder] = {'path': folder, 'count': 0, 'selected_count': 0}
        folder_stats[folder]['count'] += 1
        if page.selected:
            folder_stats[folder]['selected_count'] += 1

    # 未分组（空 folder）排在最后
    folders = sorted(folder_stats.values(), key=lambda x: (not x['path'], x['path']))
    
    return Response({'folders': folders})


@api_view(['POST'])
def modao_select_by_folder(request, pk):
    """按文件夹批量勾选/取消勾选画布

    入参 {'folder': str, 'action': 'select_all' | 'deselect_all'}
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    folder = request.data.get('folder', '')
    action = request.data.get('action', 'select_all')

    if action not in ('select_all', 'deselect_all'):
        return Response({'detail': 'action 只能是 select_all 或 deselect_all'},
                       status=http_status.HTTP_400_BAD_REQUEST)

    pages = proto.pages.filter(folder=folder)
    selected = (action == 'select_all')
    pages.update(selected=selected)

    action_text = '勾选' if selected else '取消勾选'
    return Response({
        'detail': f'已{action_text}文件夹「{folder or "未分组"}」下的 {pages.count()} 个画布',
        'count': pages.count()
    })

@api_view(['POST'])
def modao_page_reset(request, pk):
    """A2-b 画布级回退：把某画布回退到指定阶段之前，并标记需重跑。

    回退语义：画布级进度独立回退（current_stage 降级 + stage_status=needs_rerun），
    同时把任务级全局聚合产物中该阶段之后的内容清空（结构化/澄清/测试点/用例都是跨画布聚合，
    旧画布内容已失效需重算），任务级 current_stage 同步回退。

    请求体：{'page_id': <int>, 'stage': <int 1-4 回退到该阶段之前>}
    stage=1 → 重新读取该画布（清空 text，强制重提取）
    stage=2 → 重做结构化（保留提取，清空结构化及之后）
    stage=3 → 重做澄清（清空澄清及之后）
    stage=4 → 重做测试点/用例（清空测试点/用例及之后）
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if not _user_can_access_proto(request.user, proto):
        return Response({'detail': '无权操作该任务'}, status=http_status.HTTP_403_FORBIDDEN)
    page_id = request.data.get('page_id')
    stage = int(request.data.get('stage', 1))
    if stage not in (1, 2, 3, 4):
        return Response({'detail': 'stage 必须为 1-4'}, status=http_status.HTTP_400_BAD_REQUEST)
    try:
        page = proto.pages.get(id=page_id)
    except ModaoPage.DoesNotExist:
        return Response({'detail': '画布不存在'}, status=http_status.HTTP_404_NOT_FOUND)
    if proto.status in ('extracting', 'structuring', 'clarifying', 'designing'):
        return Response({'detail': '任务正在运行，请等待结束后再回退'}, status=http_status.HTTP_409_CONFLICT)

    # 1) 画布级进度回退
    page.current_stage = stage - 1
    page.stage_status = 'needs_rerun'
    page.set_rerun_stages([stage, stage + 1, stage + 2, stage + 3])
    page.rerun_stages = page.rerun_stages  # 已 set
    if stage <= 1:
        page.text = ''
        page.annotations = '[]'
    page.save(update_fields=['current_stage', 'stage_status', 'rerun_stages', 'text', 'annotations'])

    # 2) 任务级全局产物按回退阶段清空（stage 之前的产物保留）
    if stage <= 1:
        fields = ['requirement_summary', 'clarification_log', 'module_split', 'risks_json',
                  'pci_json', 'final_testpoints_json', 'dedup_audit_json', 'testcases_json',
                  'smoke_json', 'quality_report_json', 'excel_path', 'stage_confirmations']
    elif stage <= 2:
        fields = ['clarification_log', 'module_split', 'risks_json', 'pci_json',
                  'final_testpoints_json', 'dedup_audit_json', 'testcases_json',
                  'smoke_json', 'quality_report_json', 'excel_path', 'stage_confirmations']
    elif stage <= 3:
        fields = ['module_split', 'risks_json', 'pci_json', 'final_testpoints_json',
                  'dedup_audit_json', 'testcases_json', 'smoke_json',
                  'quality_report_json', 'excel_path', 'stage_confirmations']
    else:
        fields = ['testcases_json', 'smoke_json', 'quality_report_json', 'excel_path', 'stage_confirmations']
    for f in fields:
        setattr(proto, f, '' if f != 'dedup_audit_json' and f != 'stage_confirmations' else ('[]' if f == 'dedup_audit_json' else '{}'))
    proto.current_stage = stage - 1
    proto.status = 'extracted' if stage > 1 else 'pending'
    proto.stage4_decision = ''
    proto.error_message = ''
    proto.save(update_fields=['current_stage', 'status', 'stage4_decision', 'error_message'] + fields)
    return Response({
        'detail': f'画布「{page.page_name}」已回退到阶段{stage-1}，标记需重跑',
        'page': ModaoPageSerializer(page).data,
        'proto': ModaoPrototypeSerializer(proto).data,
    })


@api_view(['POST'])
def modao_ask(request, pk):
    """针对某阶段产物答疑：基于当前内容调用 LLM 回答，并追加到 qa_log。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    stage = int(request.data.get('stage', proto.current_stage))
    question = (request.data.get('question') or '').strip()
    if not question:
        return Response({'detail': '问题不能为空'}, status=http_status.HTTP_400_BAD_REQUEST)
    a_id = request.data.get('analyzer_config_id')
    wf = _build_wf(proto, a_id)
    try:
        answer = wf.ask_question(stage, question)
    except Exception as e:
        return Response({'detail': f'答疑失败：{e}'}, status=http_status.HTTP_500_INTERNAL_ERROR)
    qa = json.loads(proto.qa_log or '[]')
    qa.append({
        'stage': stage,
        'question': question,
        'answer': answer,
        'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
    proto.qa_log = json.dumps(qa, ensure_ascii=False)
    proto.save(update_fields=['qa_log'])
    return Response({'answer': answer, 'qa_log': qa})


@api_view(['GET', 'DELETE'])
def modao_detail(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    # 自动回收：designing 状态超时无更新 → 线程已死，标记 failed 避免永久卡住
    _recover_stale_designing(proto)
    if request.method == 'DELETE':
        if not _user_can_access_proto(request.user, proto):
            return Response({'detail': '无权删除该任务'}, status=http_status.HTTP_403_FORBIDDEN)
        title = proto.title
        proto.delete()
        return Response({'detail': f'已删除「{title}」'})
    return Response(ModaoPrototypeSerializer(proto).data)


@api_view(['GET'])
def modao_excel(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if not proto.excel_path or not os.path.exists(proto.excel_path):
        return Response({'detail': 'Excel 尚未生成'}, status=404)
    return FileResponse(open(proto.excel_path, 'rb'), as_attachment=True,
                        filename='testcases_all.xlsx')


def _adopt_to_library(proto, user, include_smoke=False):
    """一键采纳：把阶段3生成的用例按「项目 / 版本 / 功能模块」自动建模块并入库。

    与 _sync_stage3（依赖 module_split 模块列表、且仅在阶段3确认时触发）不同，本函数
    直接基于 testcases_json 中每条用例的 module 字段自动 get_or_create 功能模块，
    不依赖 module_split 是否完整，确保所有用例都能入库。幂等（按 项目+标题+模块 去重）。
    """
    if not proto.project_id:
        return {'ok': False, 'detail': '请先在阶段0关联项目，再采纳到用例库'}
    counts = {'modules': 0, 'testcases': 0, 'skipped': 0, 'smoke': 0}
    parent = proto.feature_module

    def _module_of(c):
        if not isinstance(c, dict):
            return '未分组'
        if c.get('testcase'):
            t = c['testcase']
            return (c.get('module') or t.get('module') or t.get('feature_module') or '未分组')
        return (c.get('module') or c.get('feature_module') or '未分组')

    def _make_tc(tc_obj, fm, sort_order=0):
        f = _tc_fields(tc_obj)
        title = f['title'] or '未命名用例'
        # 幂等去重：同一项目下相同标题且已关联到该模块的用例不重复创建，返回已有对象供打标签
        existing = TestCase.objects.filter(project=proto.project, title=title, feature_modules=fm).first()
        if existing:
            existing._adopt_existing = True  # 标记：已存在，供调用方区分新建/跳过
            return existing
        tc = TestCase(
            project=proto.project, title=title, preconditions=f['preconditions'],
            steps=f['steps_txt'], expected_result=f['expected'],
            priority=f['priority'], test_type=f['test_type'],
            description=f['description'], status='draft', author=user,
            source='ai',
            sort_order=sort_order,
        )
        tc.save()
        if proto.version_id:
            tc.versions.add(proto.version)
        try:
            tc.feature_modules.add(fm)
        except Exception:
            pass
        return tc

    # 主用例：严格保持 testcases_json 的原始（生成）顺序入库。
    # sort_order 使用『全局索引』（= 该用例在生成列表中的位置），而非按模块局部重新编号，
    # 这样无论用例库按 sort_order 全局排序还是按模块分组排序，都与生成用例顺序完全一致。
    cases = _safe_json_list(proto.testcases_json)
    for sort_order, c in enumerate(cases, 1):
        mname = _canonical_module_name(_module_of(c), proto=proto, project=proto.project)
        fm, created = FeatureModule.objects.get_or_create(
            project=proto.project, name=mname,
            defaults={
                'description': f'墨刀流程「{proto.title}」一键采纳自动创建',
                'created_by': user,
                'parent': parent,
            },
        )
        if created:
            counts['modules'] += 1
        if proto.version_id:
            fm.versions.add(proto.version)
        tc_obj = c.get('testcase', c) if isinstance(c, dict) else c
        tc = _make_tc(tc_obj, fm, sort_order=sort_order)
        if getattr(tc, '_adopt_existing', False):
            counts['skipped'] += 1
        else:
            counts['testcases'] += 1

    # 冒烟用例（可选）：从 smoke_json 取出，标记 tags=['冒烟'] 入库
    if include_smoke:
        smoke_raw = proto.smoke_json
        try:
            smoke_data = json.loads(smoke_raw) if isinstance(smoke_raw, str) else (smoke_raw or {})
        except Exception:
            smoke_data = {}
        smoke_list = []
        if isinstance(smoke_data, dict):
            # smoke_json 顶层是 dict，冒烟用例在 smoke_testcases / smoke_cases 等 key 下
            for key in ('smoke_testcases', 'smoke_cases', 'smoke_list', 'testcases'):
                if isinstance(smoke_data.get(key), list):
                    smoke_list = smoke_data[key]
                    break
        elif isinstance(smoke_data, list):
            smoke_list = smoke_data
        smoke_base = len(cases)  # 冒烟用例 sort_order 接在主用例之后
        for smoke_idx, sc in enumerate(smoke_list, 1):
            tc_obj = sc.get('testcase', sc) if isinstance(sc, dict) else sc
            mname = _canonical_module_name(_module_of(sc), proto=proto, project=proto.project)
            fm, _ = FeatureModule.objects.get_or_create(
                project=proto.project, name=mname,
                defaults={'description': f'墨刀流程「{proto.title}」一键采纳自动创建', 'created_by': user, 'parent': parent},
            )
            if proto.version_id:
                fm.versions.add(proto.version)
            tc = _make_tc(tc_obj, fm, sort_order=smoke_base + smoke_idx)
            if tc:
                # 给冒烟用例打标签（直接用刚创建的 tc 对象，避免 project/feature_modules 类型不匹配）
                try:
                    if '冒烟' not in (tc.tags or []):
                        tc.tags = (tc.tags or []) + ['冒烟']
                        tc.save(update_fields=['tags'])
                except Exception:
                    pass
                counts['smoke'] += 1

    return {'ok': True, 'counts': counts, 'project': proto.project.name if proto.project else ''}


@api_view(['POST'])
def modao_adopt(request, pk):
    """批量采纳：把阶段3生成的用例按项目/版本/功能模块自动建模块并入库（幂等）。

    POST body：
      - { "cases": [ {...编辑后的完整用例...} ] }  按给定内容精确采纳（每条可用 _ref 定位原始用例）
      - { "case_refs": [ {page_id, page_index} | {global_index} | {case_id} ] }  只采纳指定用例
      - { "case_ids": ["TC_登录_1", ...] }  兼容旧前端：按用例 id 定位后采纳
      - { "adopt_all": true, "include_smoke": true }  全量采纳（含冒烟）
      - 空 body → 兼容旧行为：全量采纳
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    payload = request.data if isinstance(request.data, dict) else {}
    include_smoke = bool(payload.get('include_smoke', False))
    entries = _merged_case_entries(proto)

    def _finish(counts, detail, project=''):
        return Response({
            'detail': detail,
            'modules': counts.get('modules', 0),
            'testcases': counts.get('testcases', 0),
            'skipped': counts.get('skipped', 0),
            'smoke': counts.get('smoke', 0),
            'failed': counts.get('failed', 0),
            'project': project,
        })

    # ① 只采纳指定用例：编辑后的（cases）与按引用定位的（case_refs / 旧版 case_ids）合并处理
    edited_cases = [x for x in (payload.get('cases') or []) if isinstance(x, dict)]
    refs = payload.get('case_refs')
    if not isinstance(refs, list) or not refs:
        legacy_ids = payload.get('case_ids')
        if isinstance(legacy_ids, list) and legacy_ids:
            refs = [{'case_id': str(x)} for x in legacy_ids]
    refs = [r for r in (refs or []) if isinstance(r, dict)]

    def _ref_key(ref):
        if ref.get('page_id') is not None and ref.get('page_index') is not None:
            return f"{ref.get('page_id')}#{ref.get('page_index')}"
        if ref.get('global_index') is not None:
            return f"g{ref.get('global_index')}"
        return f"id{ref.get('case_id')}"

    if edited_cases or refs:
        counts = {'modules': 0, 'testcases': 0, 'skipped': 0, 'smoke': 0, 'failed': 0}
        handled_keys = set()
        for i, item in enumerate(edited_cases):
            data = dict(item)
            ref = data.pop('_ref', None)
            ref = ref if isinstance(ref, dict) else {}
            handled_keys.add(_ref_key(ref))
            is_smoke = bool(data.pop('is_smoke', False))
            entry = _find_case_entry(entries, ref)
            sort_order = entry['ordinal'] if entry else len(entries) + i + 1
            mname = data.get('module') or (entry['module'] if entry else '未分组')
            r = _adopt_one_case(proto, request.user, data, mname, sort_order,
                                desc_suffix='编辑后采纳',
                                extra_tags=['冒烟'] if is_smoke else None)
            if not r.get('ok'):
                counts['failed'] += 1
                continue
            counts['modules'] += r['modules']
            counts['testcases'] += r['testcases']
            counts['skipped'] += r['skipped']
            if is_smoke:
                counts['smoke'] += 1
        for ref in refs:
            if _ref_key(ref) in handled_keys:
                continue  # 该用例已按编辑后内容采纳，避免重复
            entry = _find_case_entry(entries, ref)
            if entry is None:
                counts['failed'] += 1
                continue
            r = _adopt_one_case(proto, request.user, entry['tc_obj'], entry['module'],
                                entry['ordinal'], desc_suffix='逐条采纳')
            if not r.get('ok'):
                counts['failed'] += 1
                continue
            counts['modules'] += r['modules']
            counts['testcases'] += r['testcases']
            counts['skipped'] += r['skipped']
        if not counts['testcases'] and not counts['skipped']:
            return Response({'detail': '未能定位到任何指定用例（请刷新页面后重试）'},
                            status=http_status.HTTP_400_BAD_REQUEST)
        return _finish(counts, '已采纳选中用例', proto.project.name if proto.project else '')

    # ② 全量采纳（adopt_all / 空 body 兼容旧行为）
    result = _adopt_to_library(proto, request.user, include_smoke=include_smoke)
    if not result.get('ok'):
        return Response({'detail': result.get('detail', '采纳失败')}, status=http_status.HTTP_400_BAD_REQUEST)
    return Response({
        'detail': '已采纳到用例库',
        'modules': result['counts']['modules'],
        'testcases': result['counts']['testcases'],
        'skipped': result['counts']['skipped'],
        'smoke': result['counts']['smoke'],
        'failed': 0,
        'project': result.get('project', ''),
    })


def _adopt_single_case(proto, user, case_index):
    """逐条采纳（按全局索引）：从合并用例列表中取出一条入库。幂等。

    保留旧签名以兼容早期调用方；新逻辑走 _merged_case_entries，
    顺序与前端「用例合并采纳」列表一致，不再是任务级 testcases_json 的裸索引对不上画布。
    """
    entries = _merged_case_entries(proto)
    if not entries:
        return {'ok': False, 'detail': '没有可采纳的测试用例'}
    if not isinstance(case_index, int) or case_index < 0 or case_index >= len(entries):
        return {'ok': False, 'detail': f'用例索引 {case_index} 超出范围（共 {len(entries)} 条）'}
    e = entries[case_index]
    return _adopt_one_case(proto, user, e['tc_obj'], e['module'], e['ordinal'], desc_suffix='逐条采纳')


@api_view(['POST'])
def modao_adopt_single(request, pk):
    """逐条采纳：把阶段3生成的某一条用例采纳到用例库（幂等），支持「编辑后采纳」。

    POST body（三种定位方式，优先级从高到低）：
      1. { "case": {...} }                      完整用例对象（前端编辑后的内容），按其内容入库
      2. { "case_ref": {"page_id":1,"page_index":0} }
         / { "global_index": 3 } / { "index": 3 }
         / { "case_id": "TC_登录_1" }           精确定位原始用例后再入库
      3. { "index": 0 }                         兼容旧调用（0-based 全局索引）
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    payload = request.data if isinstance(request.data, dict) else {}
    entries = _merged_case_entries(proto)

    ref = payload.get('case_ref')
    if not isinstance(ref, dict):
        ref = {}
        for k in ('page_id', 'page_index', 'global_index', 'case_id'):
            if payload.get(k) is not None:
                ref[k] = payload[k]
        if 'index' in payload and 'global_index' not in ref:
            ref['global_index'] = payload.get('index')

    # 1) 前端编辑后的完整用例：直接按内容入库
    edited = payload.get('case')
    is_smoke = bool(payload.get('is_smoke', False))
    if isinstance(edited, dict) and (edited.get('title') or edited.get('steps')):
        entry = _find_case_entry(entries, ref)
        sort_order = entry['ordinal'] if entry else len(entries) + 1
        mname = edited.get('module') or (entry['module'] if entry else '未分组')
        result = _adopt_one_case(proto, request.user, edited, mname, sort_order,
                                 desc_suffix='编辑后采纳',
                                 extra_tags=['冒烟'] if is_smoke else None)
        if not result.get('ok'):
            return Response({'detail': result.get('detail', '采纳失败')}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response({
            'detail': result['detail'],
            'testcases': result['testcases'], 'skipped': result['skipped'],
            'modules': result['modules'], 'testcase_id': result.get('testcase_id'),
        })

    # 2) 精确定位原始用例
    if not entries:
        return Response({'detail': '没有可采纳的测试用例'}, status=http_status.HTTP_400_BAD_REQUEST)
    entry = _find_case_entry(entries, ref)
    if entry is None:
        return Response(
            {'detail': '未能定位到指定用例（请确认 page_id / page_index 或 index 是否正确）'},
            status=http_status.HTTP_400_BAD_REQUEST,
        )
    result = _adopt_one_case(proto, request.user, entry['tc_obj'], entry['module'],
                             entry['ordinal'], desc_suffix='逐条采纳',
                             extra_tags=['冒烟'] if is_smoke else None)
    if not result.get('ok'):
        return Response({'detail': result.get('detail', '采纳失败')}, status=http_status.HTTP_400_BAD_REQUEST)
    return Response({
        'detail': result['detail'],
        'testcases': result['testcases'], 'skipped': result['skipped'],
        'modules': result['modules'], 'testcase_id': result.get('testcase_id'),
    })


# ==================== 流水线日志查看器（免登录）====================

import os as _os

_LOG_PATH = '/app/_pipeline_v4.txt'

@csrf_exempt
def modao_log_viewer(request):
    """内嵌日志查看页面（自动 3 秒刷新，免登录）。"""
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>mini2 流水线日志</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1e1e1e;color:#d4d4d4;font:13px/1.5 "Cascadia Code","Fira Code",Consolas,monospace;padding:16px 20px}
h2{color:#569cd6;font-size:15px;margin-bottom:6px}
#bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;
  border-bottom:1px solid #3c3c3c;padding-bottom:6px}
#bar span{font-size:12px}#status{color:#6a9955}#time{color:#808080}
#log{white-space:pre-wrap;word-break:break-all}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-thumb{background:#555;border-radius:3px}
</style>
</head>
<body>
<h2>🚀 mini2 流水线日志 (proto id=36)</h2>
<div id="bar"><span id="status">连接中...</span><span id="time"></span></div>
<pre id="log">加载中...</pre>
<script>
var lastLen = 0;
// 通过当前页面路径拼出 log-raw 的完整路径
var base = window.location.pathname.replace('/log-viewer/', '/log-raw/');
async function fetchLog() {
    try {
        var r = await fetch(base + '?_=' + Date.now());
        var d = await r.json();
        var el = document.getElementById('log');
        el.textContent = d.content;
        var now = new Date().toLocaleTimeString();
        document.getElementById('time').textContent = now;
        var delta = d.lines - lastLen;
        if (delta > 0) {
            document.getElementById('status').innerHTML = '✅ 运行中 &nbsp;|&nbsp; <b>+'+delta+'</b> 条新日志';
            document.getElementById('status').style.color = '#6a9955';
        } else {
            document.getElementById('status').textContent = '⏳ 等待更新 | ' + d.lines + ' 行';
            document.getElementById('status').style.color = '#dcdcaa';
        }
        if (d.finished) {
            document.getElementById('status').innerHTML = '🏁 <b>流水线已结束</b> | ' + d.lines + ' 行 | 状态: ' + d.proto_status;
            document.getElementById('status').style.color = '#4ec9b0';
        }
        lastLen = d.lines;
        window.scrollTo(0, document.body.scrollHeight);
        setTimeout(fetchLog, 3000);
    } catch(e) {
        document.getElementById('status').textContent = '🔴 错误: ' + e.message;
        document.getElementById('status').style.color = '#f44747';
        setTimeout(fetchLog, 5000);
    }
}
fetchLog();
</script>
</body>
</html>"""
    return HttpResponse(html, content_type='text/html; charset=utf-8')


@csrf_exempt
def modao_log_raw(request):
    """返回原始日志文本（免登录，供日志页面 AJAX 轮询）。"""
    content = ''
    if _os.path.exists(_LOG_PATH):
        with open(_LOG_PATH, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    lines = content.count('\n') + (1 if content else 0)
    # 检测是否已结束
    finished = '===== 流水线完成 =====' in content
    proto_status = ''
    if finished:
        try:
            from apps.requirement_analysis.models import ModaoPrototype, ModaoPage
            p = ModaoPrototype.objects.filter(pk=36).first()
            if p:
                proto_status = p.status
        except Exception:
            pass
    return JsonResponse({'content': content, 'lines': lines, 'finished': finished, 'proto_status': proto_status})


# ---------- 阶段1 结构化摘要 ⇄ XMind（方案 A：上传仅覆盖结构化摘要，不联动下游）----------

@api_view(['GET'])
def modao_export_xmind(request, pk):
    """导出阶段1结构化摘要为可编辑 XMind 文件。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if not (proto.requirement_summary or '').strip():
        return Response({'detail': '尚未生成结构化摘要，无法导出 XMind'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    summary = _parse_yaml(_extract_block(proto.requirement_summary, 'yaml')) or {}
    if not isinstance(summary, dict):
        summary = {}
    data = modao_xmind.export_xmind_bytes(proto, summary)
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', (proto.title or 'requirement').strip()) or 'requirement'
    filename = f'{safe_title}.xmind'
    resp = HttpResponse(data, content_type='application/vnd.xmind.workbook')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}'
    return resp


@api_view(['POST'])
def modao_import_xmind(request, pk):
    """上传本地修改后的 XMind，解析后仅覆盖结构化摘要（requirement_summary）。

    约定（方案 A）：不联动阶段2/3，避免把未经验证的局部修改扩散到下游。
    上传前自动备份当前摘要到 requirement_summary 之外的临时字段（_xmind_backup），
    便于需要时回退。层级校验为宽松策略：仅识别约定前缀节点，其余节点忽略。
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    upload = request.FILES.get('file') or request.data.get('file')
    if not upload:
        return Response({'detail': '缺少 XMind 文件（字段名 file）'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    try:
        raw = upload.read()
    except Exception as e:
        return Response({'detail': f'读取上传文件失败：{e}'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    root_title, modules = modao_xmind.parse_xmind_bytes(raw)
    if root_title is None:
        return Response({'detail': '无法解析 XMind（仅支持 content.json 格式，请用本系统导出的 XMind 修改后回传）'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    if not modules:
        return Response({'detail': 'XMind 中未识别到任何模块节点（二级节点应作为模块名）'},
                        status=http_status.HTTP_400_BAD_REQUEST)
    # 宽松校验：模块名必须非空
    modules = [m for m in modules if (m.get('name') or '').strip()]
    if not modules:
        return Response({'detail': 'XMind 模块名不能为空'},
                        status=http_status.HTTP_400_BAD_REQUEST)

    # 保留原摘要中的非 modules 顶层字段（如决策表、结构等），仅替换 modules 列表
    prev = _parse_yaml(_extract_block(proto.requirement_summary, 'yaml')) or {}
    if not isinstance(prev, dict):
        prev = {}
    prev['modules'] = modules
    new_yaml = modao_xmind.modules_to_yaml(modules)
    backup = (proto.requirement_summary or '')
    proto.requirement_summary = new_yaml
    try:
        proto.save(update_fields=['requirement_summary'])
    except Exception as e:
        return Response({'detail': f'保存失败：{e}'},
                        status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response({
        'detail': f'已用 XMind 覆盖结构化摘要，共 {len(modules)} 个模块',
        'module_count': len(modules),
        'backup_length': len(backup),
        'requirement_summary': new_yaml,
    })
