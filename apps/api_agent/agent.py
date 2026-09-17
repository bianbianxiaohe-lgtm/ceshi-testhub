"""
API Agent 调度器

负责：
1. 解析用户意图 → 选择工具
2. 调用 LLM 做对话理解
3. 执行工具函数
4. 组装返回结果
"""

import json
import logging
from typing import Any

from apps.requirement_analysis.models import AIModelService

from . import tools as agent_tools
from .models import APISpec, APIEndpoint, APIChange, EndpointMapping

logger = logging.getLogger(__name__)

# Agent 系统提示词
SYSTEM_PROMPT = """你是 TestHub 平台的 API 测试智能助手，负责帮助用户管理被测产品的接口自动化测试。

你的能力：
1. 导入并解析 OpenAPI 接口文档
2. 对比接口文档版本，发现变更
3. 分析接口变更对已有测试用例的影响
4. 自动生成测试用例建议
5. 分析测试执行结果并给出修复建议

回复规则：
- 用中文回答，简洁明了
- 涉及具体操作时，先告知用户你将要做什么
- 给出建议时，按优先级排列
- 不确定时，主动询问用户
"""

# 意图识别 prompt
INTENT_PROMPT = """根据用户消息判断意图，只输出 JSON，不要其他内容：

{
  "intent": "import_spec|diff_specs|analyze_impact|generate_cases|analyze_results|check_status|chat",
  "confidence": 0.0~1.0,
  "entities": {
    "project_id": "可选",
    "spec_version": "可选"
  }
}

用户消息: {user_message}
"""


class APIAgent:
    """API 智能助手调度器"""

    def __init__(self, user=None, project_id=None):
        self.user = user
        self.project_id = project_id
        self._conversation_history = []

    def process_message(self, message: str) -> dict:
        """处理用户消息，返回结构化的响应"""
        self._conversation_history.append({'role': 'user', 'content': message})

        # 1. 意图识别
        intent_info = self._detect_intent(message)
        intent = intent_info.get('intent', 'chat')

        # 2. 根据意图调用对应处理器
        handlers = {
            'import_spec': self._handle_import_spec,
            'diff_specs': self._handle_diff_specs,
            'analyze_impact': self._handle_analyze_impact,
            'generate_cases': self._handle_generate_cases,
            'analyze_results': self._handle_analyze_results,
            'check_status': self._handle_check_status,
            'chat': self._handle_chat,
        }

        handler = handlers.get(intent, self._handle_chat)
        result = handler(message, intent_info)

        self._conversation_history.append({'role': 'assistant', 'content': result.get('reply', '')})

        return result

    # ── 意图识别 ──

    def _detect_intent(self, message: str) -> dict:
        """用 LLM 判断用户意图"""
        try:
            prompt = INTENT_PROMPT.format(user_message=message)
            config = self._get_ai_config('agent')
            if not config:
                return self._keyword_intent(message)

            response = AIModelService.call_openai_compatible_api(
                config,
                messages=[
                    {'role': 'system', 'content': '你是一个意图识别助手，只输出 JSON，不输出其他内容。'},
                    {'role': 'user', 'content': prompt},
                ],
                max_tokens=200,
            )
            if response:
                return json.loads(response)
        except Exception as e:
            logger.warning(f'意图识别 LLM 调用失败，回退到关键词: {e}')

        return self._keyword_intent(message)

    def _keyword_intent(self, message: str) -> dict:
        """关键词兜底意图识别"""
        msg = message.lower()
        result = {'intent': 'chat', 'confidence': 0.5, 'entities': {}}

        if any(kw in message for kw in ['导入', '上传', 'openapi', 'swagger', 'spec', '文档']):
            result['intent'] = 'import_spec'
        elif any(kw in msg for kw in ['对比', 'diff', '变更', '变动', '区别', '差异']):
            result['intent'] = 'diff_specs'
        elif any(kw in message for kw in ['影响', '关联', '哪些用例', '哪些测试']):
            result['intent'] = 'analyze_impact'
        elif any(kw in message for kw in ['生成用例', '写用例', '创建用例', '自动生成']):
            result['intent'] = 'generate_cases'
        elif any(kw in message for kw in ['失败原因', '分析结果', '测试报告', '为什么失败']):
            result['intent'] = 'analyze_results'
        elif any(kw in message for kw in ['状态', '概览', '总结', '情况']):
            result['intent'] = 'check_status'

        return result

    # ── 各意图处理器 ──

    def _handle_import_spec(self, message: str, intent: dict) -> dict:
        """处理导入 spec 的意图"""
        if not self.project_id:
            return self._ask_for_project()

        # 检查当前项目已导入的版本
        existing = APISpec.objects.filter(project_id=self.project_id).order_by('-created_at')
        versions = [{'id': str(s.id), 'name': s.name, 'version': s.version} for s in existing[:5]]

        return {
            'reply': (
                f'好的！你可以上传被测产品的 OpenAPI 文档（支持 JSON/YAML 格式）。\n\n'
                + (f'本项目已导入 {len(versions)} 个版本：\n'
                   + '\n'.join(f'  · {v["name"]} v{v["version"]}' for v in versions) + '\n\n'
                   if versions else '本项目还没有导入过接口文档。\n\n')
                + '请上传文件，或者在对话框中粘贴文档 URL。'
            ),
            'action': 'import_spec',
            'data': {'existing_versions': versions},
        }

    def _handle_diff_specs(self, message: str, intent: dict) -> dict:
        """处理文档对比的意图"""
        if not self.project_id:
            return self._ask_for_project()

        existing = APISpec.objects.filter(project_id=self.project_id).order_by('-created_at')[:2]
        if len(existing) < 2:
            return {
                'reply': f'当前项目只有 {len(existing)} 个文档版本，对比需要至少 2 个版本。请先上传新版本。',
                'action': 'import_spec',
            }

        return {
            'reply': f'项目中共有 {APISpec.objects.filter(project_id=self.project_id).count()} 个文档版本。\n\n最近两个版本：\n  · {existing[0].name} v{existing[0].version} ({existing[0].endpoint_count} 个接口)\n  · {existing[1].name} v{existing[1].version} ({existing[1].endpoint_count} 个接口)\n\n需要我对比这两个版本并生成变更报告吗？',
            'action': 'diff_confirm',
            'data': {
                'new_spec_id': str(existing[0].id),
                'old_spec_id': str(existing[1].id),
            },
        }

    def _handle_analyze_impact(self, message: str, intent: dict) -> dict:
        """处理影响分析的意图"""
        if not self.project_id:
            return self._ask_for_project()

        # 看有没有最近的变更记录
        latest_changes = APIChange.objects.filter(
            old_spec__project_id=self.project_id,
        ).order_by('-created_at')[:10]

        if not latest_changes:
            return {
                'reply': '当前项目还没有做过接口文档对比，无法进行影响分析。\n\n建议先上传被测产品的最新 OpenAPI 文档，然后对比两个版本。',
                'action': 'import_spec',
            }

        breaking = latest_changes.filter(severity='breaking').count()
        return {
            'reply': f'最近一次对比发现 {latest_changes.count()} 个变更，其中 {breaking} 个破坏性变更。\n\n你想了解哪次变更的具体影响？可以直接说接口名或路径。',
            'action': 'analyze_impact',
            'data': {'changes_count': latest_changes.count(), 'breaking_count': breaking},
        }

    def _handle_generate_cases(self, message: str, intent: dict) -> dict:
        """处理生成测试用例的意图"""
        if not self.project_id:
            return self._ask_for_project()

        # 查未映射的接口
        unmapped = EndpointMapping.objects.filter(
            endpoint__spec__project_id=self.project_id,
            match_status='unmapped',
        ).select_related('endpoint')[:10]

        unmapped_endpoints = [
            {'path': m.endpoint.path, 'method': m.endpoint.method, 'summary': m.endpoint.summary}
            for m in unmapped
        ]

        return {
            'reply': (
                f'我可以帮你自动生成测试用例！\n\n'
                + (f'当前有 {len(unmapped_endpoints)} 个接口还没有对应的测试用例：\n'
                   + '\n'.join(f'  · {e["method"]} {e["path"]} — {e.get("summary", "")}'
                               for e in unmapped_endpoints[:5])
                   + '\n\n你想给哪个接口生成用例？或者全部一起生成？'
                   if unmapped_endpoints
                   else '所有接口都已经有对应的测试用例了。如果你想重新生成某些用例，直接告诉我是哪个接口就好。')
            ),
            'action': 'generate_cases',
            'data': {'unmapped_count': len(unmapped_endpoints)},
        }

    def _handle_analyze_results(self, message: str, intent: dict) -> dict:
        """处理测试结果分析的意图"""
        if not self.project_id:
            return self._ask_for_project()

        from apps.api_testing.models import TestExecution

        latest = TestExecution.objects.filter(
            test_suite__project_id=self.project_id,
        ).order_by('-end_time').first()

        if not latest:
            return {
                'reply': '当前项目还没有执行过测试。你可以先选择一个测试套件执行，或者直接说"执行登录接口"之类的。',
                'action': 'execute',
            }

        total = latest.total_requests or 0
        passed = latest.passed_requests or 0
        failed = latest.failed_requests or 0
        pass_rate = (passed / total * 100) if total > 0 else 0

        return {
            'reply': (
                f'最近一次测试执行（{latest.test_suite.name}）：\n'
                f'  · 状态: {latest.status}\n'
                f'  · 总数: {total}\n'
                f'  · 通过: {passed}\n'
                f'  · 失败: {failed}\n'
                f'  · 通过率: {pass_rate:.1f}%\n\n'
                + ('需要我详细分析失败原因吗？' if failed > 0 else '全部通过 ✓')
            ),
            'action': 'analyze_results',
            'data': {
                'execution_id': str(latest.id),
                'total': total, 'passed': passed, 'failed': failed,
                'pass_rate': round(pass_rate, 1),
            },
        }

    def _handle_check_status(self, message: str, intent: dict) -> dict:
        """检查项目状态概览"""
        if not self.project_id:
            return self._ask_for_project()

        specs = APISpec.objects.filter(project_id=self.project_id)
        latest_spec = specs.order_by('-created_at').first()

        from apps.api_testing.models import ApiRequest, TestSuite, TestExecution

        api_requests_count = ApiRequest.objects.filter(collection__project_id=self.project_id).count()
        test_suites_count = TestSuite.objects.filter(project_id=self.project_id).count()
        latest_execution = TestExecution.objects.filter(
            test_suite__project_id=self.project_id,
        ).order_by('-end_time').first()

        return {
            'reply': (
                f'📊 项目当前状态：\n\n'
                f'接口文档: {specs.count()} 个版本'
                + (f'（最新: {latest_spec.name} v{latest_spec.version}, {latest_spec.endpoint_count} 个接口）' if latest_spec else '')
                + f'\n测试用例: {api_requests_count} 个'
                + f'\n测试套件: {test_suites_count} 个'
                + (f'\n最近执行: {latest_execution.status}' if latest_execution else '')
                + '\n\n你可以：\n  · 导入接口文档\n  · 自动生成测试用例\n  · 执行测试套件\n  · 查看测试报告'
                + '\n\n告诉我你想做什么。'
            ),
            'action': 'check_status',
            'data': {
                'specs_count': specs.count(),
                'api_requests_count': api_requests_count,
                'test_suites_count': test_suites_count,
            },
        }

    def _handle_chat(self, message: str, intent: dict) -> dict:
        """通用对话（调 LLM）"""
        # 构建上下文
        context = self._build_context()

        prompt = (
            f'当前 TestHub 项目上下文：\n{context}\n\n'
            f'用户说：{message}\n\n'
            f'请友好回复，如果用户想做具体操作但你没权力直接执行，'
            f'明确告诉用户需要通过什么方式操作（上传文件/点击按钮/输入命令）。'
        )

        try:
            config = self._get_ai_config('agent')
            if config:
                reply = AIModelService.call_openai_compatible_api(
                    config,
                    messages=[
                        {'role': 'system', 'content': SYSTEM_PROMPT},
                        {'role': 'user', 'content': prompt},
                    ],
                    max_tokens=800,
                )
                if reply:
                    return {'reply': reply, 'action': 'chat'}

        except Exception as e:
            logger.error(f'chat LLM 调用失败: {e}')

        return {
            'reply': (
                '你好！我是 TestHub 的 API 测试助手。我可以帮你：\n\n'
                '📥 导入 OpenAPI 文档\n'
                '🔄 对比接口变更\n'
                '🔍 分析变更影响\n'
                '📝 自动生成测试用例\n'
                '📊 分析测试结果\n\n'
                '需要我做什么？'
            ),
            'action': 'chat',
        }

    # ── 辅助方法 ──

    def _get_ai_config(self, role: str):
        """获取 AI 配置，优先 agent 角色，fallback 到 writer"""
        from apps.requirement_analysis.models import AIModelConfig

        config = None
        try:
            # 尝试获取 agent 角色配置
            config = AIModelConfig.get_active_config(model_type='deepseek', role='writer')
        except Exception:
            pass

        if not config:
            try:
                config = AIModelConfig.objects.filter(is_active=True).first()
            except Exception:
                pass

        return config

    def _build_context(self) -> str:
        """构建当前项目上下文"""
        if not self.project_id:
            return '未选择项目'

        from apps.api_testing.models import ApiProject, ApiRequest, TestSuite

        try:
            project = ApiProject.objects.get(id=self.project_id)
            specs = APISpec.objects.filter(project_id=self.project_id)
            latest = specs.order_by('-created_at').first()
            request_count = ApiRequest.objects.filter(collection__project_id=self.project_id).count()
            suite_count = TestSuite.objects.filter(project_id=self.project_id).count()

            lines = [
                f'项目: {project.name}',
                f'文档版本数: {specs.count()}',
                f'最新文档: {latest.name} v{latest.version} ({latest.endpoint_count} 个接口)' if latest else '暂无文档',
                f'测试用例: {request_count} 个',
                f'测试套件: {suite_count} 个',
            ]
            return '\n'.join(lines)
        except Exception as e:
            logger.error(f'构建上下文失败: {e}')
            return '项目信息获取失败'

    def _ask_for_project(self) -> dict:
        return {
            'reply': '请先在 TestHub 中选择一个项目，然后告诉我需要做什么。',
            'action': 'select_project',
        }

    @staticmethod
    def execute_tool(tool_name: str, **params) -> dict:
        """
        直接执行指定工具（供 View 层调用）。
        支持的工具: import_spec, diff_specs, generate_cases, analyze_results
        """
        from apps.api_testing.models import ApiProject, ApiRequest, TestSuite

        if tool_name == 'import_spec':
            return APIAgent._exec_import_spec(params)
        elif tool_name == 'diff_specs':
            return APIAgent._exec_diff_specs(params)
        elif tool_name == 'generate_cases':
            return APIAgent._exec_generate_cases(params)
        elif tool_name == 'analyze_results':
            return APIAgent._exec_analyze_results(params)
        else:
            return {'error': f'未知工具: {tool_name}'}

    @staticmethod
    def _exec_import_spec(params: dict) -> dict:
        from apps.api_testing.models import ApiProject, ApiRequest

        project_id = params.get('project_id')
        spec_json = params.get('spec_json')
        spec_name = params.get('name', '未命名文档')
        spec_version = params.get('version', '1.0')
        spec_format = params.get('format', 'openapi3')
        file_name = params.get('file_name', '')
        created_by = params.get('user')

        project = ApiProject.objects.get(id=project_id)

        # 解析 spec
        parsed = agent_tools.parse_openapi(spec_json)

        # 自动检测格式
        detected_format = parsed.get('spec_format', spec_format)

        # 创建 APISpec 记录
        spec = APISpec.objects.create(
            project=project,
            name=spec_name,
            version=spec_version,
            spec_format=detected_format,
            spec_json=spec_json,
            endpoint_count=parsed['endpoint_count'],
            file_name=file_name,
            created_by=created_by,
        )

        # 创建 APIEndpoint 记录
        endpoints = []
        for ep_data in parsed['endpoints']:
            ep = APIEndpoint.objects.create(
                spec=spec,
                path=ep_data['path'],
                method=ep_data['method'],
                summary=ep_data.get('summary', ''),
                description=ep_data.get('description', ''),
                tags=ep_data.get('tags', []),
                parameters=ep_data.get('parameters', []),
                request_body=ep_data.get('request_body'),
                responses=ep_data.get('responses', {}),
            )
            endpoints.append(ep)

        # 自动匹配已有用例
        match_result = agent_tools.auto_match_endpoints(spec, ApiRequest)

        # 为未匹配的接口自动创建 ApiRequest 测试用例
        created_count = 0
        unmapped = EndpointMapping.objects.filter(endpoint__spec=spec, match_status='unmapped')
        if unmapped.exists():
            # 获取或创建默认集合
            from apps.api_testing.models import ApiCollection
            default_collection, _ = ApiCollection.objects.get_or_create(
                project=project,
                name=f'{spec_name} 自动导入',
                defaults={'description': f'从 {spec_name} v{spec_version} 自动生成'},
            )
            for mapping in unmapped:
                ep = mapping.endpoint
                # 构建 body 模板
                body_data = _build_default_body(ep)
                api_request = ApiRequest.objects.create(
                    name=ep.summary or f'{ep.method} {ep.path}',
                    description=ep.description or '',
                    request_type=project.project_type or 'HTTP',
                    method=ep.method,
                    url=ep.path,
                    headers=[],
                    params=_build_default_params(ep),
                    body=body_data,
                    collection=default_collection,
                    created_by=created_by,
                )
                mapping.api_request = api_request
                mapping.match_status = 'matched'
                mapping.save()
                created_count += 1

        return {
            'success': True,
            'spec_id': str(spec.id),
            'endpoint_count': parsed['endpoint_count'],
            'matched': match_result.get('matched', 0),
            'unmapped': match_result.get('unmapped', 0) - created_count,
            'auto_created': created_count,
        }

    @staticmethod
    def _exec_diff_specs(params: dict) -> dict:
        old_spec_id = params.get('old_spec_id')
        new_spec_id = params.get('new_spec_id')

        old_spec = APISpec.objects.get(id=old_spec_id)
        new_spec = APISpec.objects.get(id=new_spec_id)

        old_parsed = agent_tools.parse_openapi(old_spec.spec_json)
        new_parsed = agent_tools.parse_openapi(new_spec.spec_json)

        diff_result = agent_tools.diff_specs(old_parsed, new_parsed)

        # 保存变更记录
        from apps.api_testing.models import ApiRequest, TestSuite

        api_request_model = ApiRequest
        for change in diff_result['changes']:
            api_change = APIChange.objects.create(
                old_spec=old_spec,
                new_spec=new_spec,
                endpoint_path=change['endpoint_path'],
                endpoint_method=change['endpoint_method'],
                change_type=change['change_type'],
                severity=change['severity'],
                detail=change['detail'],
            )

            # 查找受影响用例
            affected = agent_tools.find_affected_cases(
                change, new_spec.project_id,
                api_request_model, TestSuite,
            )

        return {
            'success': True,
            'total_changes': diff_result['total_changes'],
            'breaking_count': diff_result['breaking_count'],
            'warning_count': diff_result['warning_count'],
            'info_count': diff_result['info_count'],
            'changes': diff_result['changes'],
        }

    @staticmethod
    def _exec_generate_cases(params: dict) -> dict:
        project_id = params.get('project_id')
        endpoint_id = params.get('endpoint_id')  # 可选，指定某个 endpoint

        if endpoint_id:
            endpoints = [APIEndpoint.objects.get(id=endpoint_id)]
        else:
            endpoints = APIEndpoint.objects.filter(
                spec__project_id=project_id,
                mapping__match_status='unmapped',
            )[:10]

        suggestions = []
        for ep in endpoints:
            prompt = agent_tools.generate_case_suggestion({
                'path': ep.path,
                'method': ep.method,
                'summary': ep.summary,
                'parameters': ep.parameters,
                'request_body': ep.request_body,
            })
            suggestions.append({
                'endpoint_id': str(ep.id),
                'path': ep.path,
                'method': ep.method,
                'prompt': prompt,
            })

        return {
            'success': True,
            'suggestions': suggestions,
            'total': len(suggestions),
        }

    @staticmethod
    def _exec_analyze_results(params: dict) -> dict:
        execution_id = params.get('execution_id')
        from apps.api_testing.models import TestExecution

        execution = TestExecution.objects.select_related('test_suite').get(id=execution_id)
        results = execution.results or {}

        # 提取失败详情
        failed_details = []
        for idx, result in enumerate(results.get('results', [])):
            if not result.get('passed'):
                failed_details.append({
                    'index': idx,
                    'request_name': result.get('request_name', f'用例{idx + 1}'),
                    'status_code': result.get('status_code'),
                    'error_message': result.get('error_message', ''),
                    'assertion_results': result.get('assertions_results', []),
                })

        return {
            'success': True,
            'execution_id': execution_id,
            'suite_name': execution.test_suite.name,
            'status': execution.status,
            'total': execution.total_requests or 0,
            'passed': execution.passed_requests or 0,
            'failed': execution.failed_requests or 0,
            'failed_details': failed_details,
            'prompt': agent_tools.analyze_execution_log_prompt({
                'total_requests': execution.total_requests or 0,
                'passed_requests': execution.passed_requests or 0,
                'failed_requests': execution.failed_requests or 0,
                'failed_details': failed_details,
            }),
        }


# ── 辅助构建函数 ──

def _build_default_body(endpoint) -> dict:
    """根据 endpoint 的 request_body schema 构建默认请求体"""
    rb = endpoint.request_body
    if not rb or not rb.get('properties'):
        return {'type': 'json', 'data': {}}

    data = {}
    required_fields = rb.get('required', [])
    for name, prop in rb.get('properties', {}).items():
        if name in required_fields:
            # 必填字段给占位值
            prop_type = prop.get('type', 'string')
            if prop_type == 'integer' or prop_type == 'number':
                data[name] = 0
            elif prop_type == 'boolean':
                data[name] = False
            elif prop_type == 'array':
                data[name] = []
            else:
                data[name] = ''
        else:
            data[name] = None

    return {'type': 'json', 'data': data}


def _build_default_params(endpoint) -> list:
    """根据 endpoint 的 parameters 构建默认查询参数"""
    params = endpoint.parameters or []
    result = []
    for p in params:
        result.append({
            'name': p.get('name', ''),
            'value': '' if p.get('required') else None,
            'enabled': p.get('required', False),
            'description': p.get('description', ''),
        })
    return result
