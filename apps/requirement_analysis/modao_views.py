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
from django.http import FileResponse

from apps.requirement_analysis.models import ModaoPrototype
from apps.requirement_analysis.serializers import ModaoPrototypeSerializer
from apps.requirement_analysis.modao_workflow import ModaoWorkflow, _parse_yaml, _extract_block
from apps.feature_modules.models import FeatureModule, TestPoint
from apps.testcases.models import TestCase


def _build_wf(proto, analyzer_id=None, writer_id=None, embedder_id=None):
    analyzer, writer, embedder = ModaoWorkflow.resolve_configs(analyzer_id, writer_id, embedder_id)
    # 视觉识别配置：用于纯图片/截图/表格型页面的 OCR 补充（writer_vision 角色）
    from apps.requirement_analysis.models import AIModelConfig
    vision_config = AIModelConfig.objects.filter(role='writer_vision', is_active=True).first()
    return ModaoWorkflow(proto, analyzer, writer, embedder, vision_config=vision_config)


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
        mname = m.get('name')
        if not mname:
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

    - 管理员（is_staff / is_superuser）：可查看所有人的生成历史；
    - 普通用户：仅查看自己创建的历史。
    """
    from apps.core.mixins import _is_superuser
    is_admin = _is_superuser(request.user)
    if is_admin:
        qs = ModaoPrototype.objects.all().order_by('-created_at')
    else:
        qs = ModaoPrototype.objects.filter(created_by=request.user).order_by('-created_at')
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

    # 安全网：URL 明显是 webshare/Axure 原型时，强制覆盖 source_type
    if source_type != 'webshare' and '/webshare/' in url_str:
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
    from apps.core.mixins import _is_superuser

    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if proto.created_by_id != request.user.id and not _is_superuser(request.user):
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
def modao_extract(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if proto.source_type == 'text':
        proto.current_stage = 1
        proto.status = 'extracted'
        proto.save(update_fields=['current_stage', 'status'])
        return Response({'detail': '文本来源无需读取，可直接进入结构化阶段'})

    cookies = proto.auth_cookie or request.data.get('cookies', '')
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

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id)
        wf.run_extract(urls=raw_urls, cookies=cookies, headless=headless,
                       source_type=proto.source_type,
                       dual_fusion=dual_fusion, fusion_config=fusion_config)

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '墨刀读取已启动，请轮询状态'})


@api_view(['POST'])
def modao_struct(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id)
        wf.run_struct()

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '需求结构化已启动'})


@api_view(['POST'])
def modao_clarify(request, pk):
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id)
        wf.run_clarify()

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '需求澄清已启动'})


@api_view(['POST'])
def modao_design(request, pk):
    """阶段3 第一段：模块拆分→测试点→风险→PCI→三路合并（到最终测试点为止，等待人工确认）。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    a_id, w_id, e_id = (request.data.get('analyzer_config_id'),
                        request.data.get('writer_config_id'),
                        request.data.get('embedder_config_id'))

    def job():
        wf = _build_wf(proto, a_id, w_id, e_id)
        wf.run_design_phase1()

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '测试点合并已启动（模块拆分→测试点→风险→PCI→三路合并）'})


@api_view(['POST'])
def modao_generate_cases(request, pk):
    """阶段3 第二段：基于（已确认/编辑的）最终测试点生成测试用例→冒烟→质量→Excel。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    if not (proto.final_testpoints_json or '').strip() or proto.final_testpoints_json.strip() in ('[]', '{}'):
        return Response({'detail': '请先运行测试点合并（第一段），生成最终测试点后再生成用例'},
                        status=http_status.HTTP_400_BAD_REQUEST)
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
        wf.run_design_phase2()

    threading.Thread(target=_run_in_thread(proto, job), daemon=True).start()
    return Response({'detail': '测试用例生成已启动（用例→冒烟→质量→Excel）'})


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
    setattr(proto, field, value)
    proto.save(update_fields=[field])
    return Response({'detail': f'已更新 {field}'})


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
    if request.method == 'DELETE':
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
        title = (tc_obj.get('title') if isinstance(tc_obj, dict) else None) or '未命名用例'
        # 幂等去重：同一项目下相同标题且已关联到该模块的用例不重复创建，返回已有对象供打标签
        existing = TestCase.objects.filter(project=proto.project, title=title, feature_modules=fm).first()
        if existing:
            existing._adopt_existing = True  # 标记：已存在，供调用方区分新建/跳过
            return existing
        steps = (tc_obj.get('steps', []) if isinstance(tc_obj, dict) else []) or []
        steps_txt = '\n'.join(f'{i+1}. {s}' for i, s in enumerate(steps)) if isinstance(steps, list) else str(steps or '')
        preconditions = expected = description = ''
        priority = 'P2'
        test_type = 'functional'
        if isinstance(tc_obj, dict):
            preconditions = tc_obj.get('precondition', '') or tc_obj.get('preconditions', '') or ''
            expected = tc_obj.get('expected', '') or tc_obj.get('pass_criteria', '') or ''
            priority = tc_obj.get('priority', 'P2')
            test_type = tc_obj.get('type', 'functional') or tc_obj.get('test_type', 'functional')
            description = tc_obj.get('notes', '') or tc_obj.get('requirement_ref', '') or ''
        tc = TestCase(
            project=proto.project, title=title, preconditions=preconditions,
            steps=steps_txt, expected_result=expected,
            priority=_PRIO_MAP.get(priority, 'medium'),
            test_type=_TYPE_MAP.get((test_type or '').lower(), 'functional'),
            description=description, status='draft', author=user,
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
        mname = _module_of(c)
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
            mname = _module_of(sc)
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
    """一键采纳：把阶段3生成的用例按项目/版本/功能模块自动建模块并入库（幂等）。"""
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    include_smoke = bool(request.data.get('include_smoke', False))
    result = _adopt_to_library(proto, request.user, include_smoke=include_smoke)
    if not result.get('ok'):
        return Response({'detail': result.get('detail', '采纳失败')}, status=http_status.HTTP_400_BAD_REQUEST)
    return Response({
        'detail': '已采纳到用例库',
        'modules': result['counts']['modules'],
        'testcases': result['counts']['testcases'],
        'skipped': result['counts']['skipped'],
        'smoke': result['counts']['smoke'],
        'project': result.get('project', ''),
    })


def _adopt_single_case(proto, user, case_index):
    """逐条采纳：按索引从 testcases_json 中取出一条用例，自动建功能模块并入库。幂等。
    
    Args:
        proto: ModaoPrototype 实例
        user: 当前用户
        case_index: testcases_json 中的用例索引（0-based）
    
    Returns:
        dict with ok/counts/detail
    """
    if not proto.project_id:
        return {'ok': False, 'detail': '请先在阶段0关联项目'}
    cases = _safe_json_list(proto.testcases_json)
    if not cases:
        return {'ok': False, 'detail': '没有可采纳的测试用例'}
    if case_index < 0 or case_index >= len(cases):
        return {'ok': False, 'detail': f'用例索引 {case_index} 超出范围（共 {len(cases)} 条）'}

    c = cases[case_index]
    parent = proto.feature_module

    # 解析 module
    def _module_of(c):
        if not isinstance(c, dict):
            return '未分组'
        if c.get('testcase'):
            t = c['testcase']
            return (c.get('module') or t.get('module') or t.get('feature_module') or '未分组')
        return (c.get('module') or c.get('feature_module') or '未分组')

    mname = _module_of(c)
    fm, created = FeatureModule.objects.get_or_create(
        project=proto.project, name=mname,
        defaults={
            'description': f'墨刀流程「{proto.title}」逐条采纳自动创建',
            'created_by': user,
            'parent': parent,
        },
    )
    if proto.version_id:
        fm.versions.add(proto.version)

    tc_obj = c.get('testcase', c) if isinstance(c, dict) else c
    title = (tc_obj.get('title') if isinstance(tc_obj, dict) else None) or f'用例#{case_index + 1}'

    # 幂等检查
    if TestCase.objects.filter(project=proto.project, title=title, feature_modules=fm).exists():
        return {'ok': True, 'counts': {'testcases': 0, 'skipped': 1, 'modules': int(created)}, 'detail': '该用例已存在（跳过）'}

    steps = (tc_obj.get('steps', []) if isinstance(tc_obj, dict) else []) or []
    steps_txt = '\n'.join(f'{i+1}. {s}' for i, s in enumerate(steps)) if isinstance(steps, list) else str(steps or '')
    preconditions = expected = description = ''
    priority = 'P2'
    test_type = 'functional'
    if isinstance(tc_obj, dict):
        preconditions = tc_obj.get('precondition', '') or tc_obj.get('preconditions', '') or ''
        expected = tc_obj.get('expected', '') or tc_obj.get('pass_criteria', '') or ''
        priority = tc_obj.get('priority', 'P2')
        test_type = tc_obj.get('type', 'functional') or tc_obj.get('test_type', 'functional')
        description = tc_obj.get('notes', '') or tc_obj.get('requirement_ref', '') or ''

    tc = TestCase(
        project=proto.project, title=title, preconditions=preconditions,
        steps=steps_txt, expected_result=expected,
        priority=_PRIO_MAP.get(priority, 'medium'),
        test_type=_TYPE_MAP.get((test_type or '').lower(), 'functional'),
        description=description, status='draft', author=user,
        sort_order=case_index + 1,
    )
    tc.save()
    if proto.version_id:
        tc.versions.add(proto.version)
    tc.feature_modules.add(fm)

    return {
        'ok': True,
        'counts': {'testcases': 1, 'skipped': 0, 'modules': int(created)},
        'detail': f'已采纳「{title}」',
    }


@api_view(['POST'])
def modao_adopt_single(request, pk):
    """逐条采纳：把阶段3生成的某一条用例采纳到用例库（幂等）。

    POST body: { "index": 0 }  （testcases_json 中的 0-based 索引）
    """
    proto = get_object_or_404(ModaoPrototype, pk=pk)
    try:
        case_index = int(request.data.get('index', -1))
    except (TypeError, ValueError):
        return Response({'detail': '缺少有效参数 index（整数）'}, status=http_status.HTTP_400_BAD_REQUEST)

    result = _adopt_single_case(proto, request.user, case_index)
    if not result.get('ok'):
        return Response({'detail': result.get('detail', '采纳失败')}, status=http_status.HTTP_400_BAD_REQUEST)
    return Response({
        'detail': result['detail'],
        **result['counts'],
    })
