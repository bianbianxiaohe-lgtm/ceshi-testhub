"""
API Agent 工具函数

核心工具：
- parse_openapi: 自动识别并解析 OpenAPI / Swagger / YApi 文档，提取所有端点
- diff_specs: 对比两个文档版本，生成变更列表
- find_affected_cases: 根据变更找到受影响的 ApiRequest / TestSuite
- auto_match_endpoints: 自动匹配 spec 端点 → ApiRequest 用例
- generate_case_suggestion: AI 生成测试用例建议
- analyze_execution_result: AI 分析测试结果
"""

import copy
import json
import logging
from typing import Any
from django.db.models import Q

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  格式检测
# ─────────────────────────────────────────────

def detect_spec_format(spec_json: dict | list) -> str:
    """自动检测文档格式: openapi3, swagger2, yapi, postman"""
    if isinstance(spec_json, list):
        # YApi 导出格式： [{"title": "xx", "path": "/api/xx", "method": "POST", ...}, ...]
        if len(spec_json) > 0 and isinstance(spec_json[0], dict) and 'path' in spec_json[0] and 'method' in spec_json[0]:
            return 'yapi'
        # Postman 导出： [{"info": ..., "item": [...]}]
        if len(spec_json) > 0 and isinstance(spec_json[0], dict) and 'item' in spec_json[0]:
            return 'postman'
        return 'unknown'
    if isinstance(spec_json, dict):
        if 'swagger' in spec_json and str(spec_json.get('swagger', '')).startswith('2'):
            return 'swagger2'
        if 'openapi' in spec_json:
            return 'openapi3'
        # YApi 单项目导出也可能是 dict 带 paths/list
        if 'list' in spec_json or ('errcode' in spec_json and 'data' in spec_json):
            return 'yapi_wrapper'
        # Postman
        if 'info' in spec_json and 'item' in spec_json:
            return 'postman'
    return 'unknown'


# ─────────────────────────────────────────────
#  1. 统一解析入口
# ─────────────────────────────────────────────

def parse_openapi(spec_json: dict | list) -> dict:
    """
    自动识别格式并解析，支持 OpenAPI 3.x / Swagger 2.0 / YApi / Postman。
    返回: {endpoint_count, endpoints: [{path, method, summary, description, tags, parameters, request_body, responses}]}
    """
    fmt = detect_spec_format(spec_json)

    if fmt == 'yapi':
        return _parse_yapi(spec_json)
    if fmt == 'yapi_wrapper':
        return _parse_yapi_wrapper(spec_json)
    if fmt == 'postman':
        return _parse_postman(spec_json)

    endpoints = []
    spec_version = fmt

    if spec_version == 'swagger2':
        base_path = spec_json.get('basePath', '')
        paths = spec_json.get('paths', {})
        for path, methods in paths.items():
            full_path = _join_path(base_path, path)
            for method in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']:
                if method in methods:
                    endpoints.append(_extract_endpoint(full_path, method, methods[method], 'swagger2'))
    else:
        # OpenAPI 3.x
        servers = spec_json.get('servers', [{}])
        server_base = servers[0].get('url', '') if servers else ''
        if '://' in server_base:
            server_base = '/' + server_base.split('://', 1)[1].split('/', 1)[-1] if '/' in server_base.split('://', 1)[1] else ''

        paths = spec_json.get('paths', {})
        for path, methods in paths.items():
            for method in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']:
                if method in methods:
                    endpoints.append(_extract_endpoint(path, method, methods[method], 'openapi3'))

    return {
        'endpoint_count': len(endpoints),
        'endpoints': endpoints,
        'spec_version': spec_version,
        'spec_format': fmt,
    }


# ── YApi 解析 ──

def _parse_yapi(data: list) -> dict:
    """解析 YApi 导出的 JSON 数组格式"""
    endpoints = []
    for item in data:
        path = item.get('path', '')
        method = item.get('method', 'GET').upper()
        if not path:
            continue

        # YApi 的 req_params 格式: [{name, desc, type, required, example}]
        params = []
        req_params = item.get('req_params') or item.get('req_query') or []
        if isinstance(req_params, dict):
            req_params = [{'name': k, **v} if isinstance(v, dict) else {'name': k} for k, v in req_params.items()]
        for p in req_params:
            params.append({
                'name': p.get('name', ''),
                'in': 'query',
                'required': p.get('required') == '1' or p.get('required') == True,
                'type': p.get('type', 'string'),
                'description': p.get('desc', p.get('description', '')),
            })

        # YApi 的 req_body_form / req_body_other
        body_data = item.get('req_body_other') or item.get('req_body_form') or None
        request_body = None
        if body_data:
            if isinstance(body_data, str):
                try:
                    body_data = json.loads(body_data)
                except json.JSONDecodeError:
                    body_data = {'raw': body_data}
            if isinstance(body_data, dict):
                props = body_data.get('properties', {})
                required = body_data.get('required', [])
                request_body = {'type': 'object', 'properties': props, 'required': required}

        # YApi 的 res_body
        resp_body = item.get('res_body') or '{}'
        if isinstance(resp_body, str):
            try:
                resp_body = json.loads(resp_body)
            except json.JSONDecodeError:
                resp_body = {'description': resp_body}
        elif isinstance(resp_body, dict):
            pass
        else:
            resp_body = {}

        endpoints.append({
            'path': path,
            'method': method,
            'summary': item.get('title', ''),
            'description': item.get('desc', ''),
            'tags': item.get('tag', []) if isinstance(item.get('tag'), list) else ([item['tag']] if item.get('tag') else []),
            'parameters': params,
            'request_body': request_body,
            'responses': {'200': resp_body},
            'deprecated': item.get('status') == 'done' or False,
        })

    return {
        'endpoint_count': len(endpoints),
        'endpoints': endpoints,
        'spec_version': 'yapi',
        'spec_format': 'yapi',
    }


def _parse_yapi_wrapper(data: dict) -> dict:
    """解析 YApi 单项目包装格式（带 errcode/data）"""
    inner = data.get('data', data.get('list', data))
    if isinstance(inner, list):
        return _parse_yapi(inner)
    if isinstance(inner, dict) and 'list' in inner:
        return _parse_yapi(inner['list'])
    return _parse_yapi([inner])


def _parse_postman(data: dict | list) -> dict:
    """解析 Postman 导出格式"""
    items_list = data if isinstance(data, list) else [data]
    endpoints = []
    for collection in items_list:
        for item in _flatten_postman_items(collection.get('item', []), ''):
            endpoints.append(item)

    return {
        'endpoint_count': len(endpoints),
        'endpoints': endpoints,
        'spec_version': 'postman',
        'spec_format': 'postman',
    }


def _flatten_postman_items(items: list, prefix: str) -> list:
    """递归展平 Postman 的文件夹结构"""
    result = []
    for item in items:
        if 'item' in item:
            # 子文件夹
            folder_name = item.get('name', '')
            result.extend(_flatten_postman_items(item['item'], prefix + folder_name + '/'))
        elif 'request' in item:
            req = item['request']
            method = req.get('method', 'GET').upper()
            url = req.get('url', {})
            if isinstance(url, dict):
                path = '/' + '/'.join(url.get('path', []))
            else:
                path = url

            # headers
            headers = []
            for h in req.get('header', []):
                headers.append({'name': h.get('key', ''), 'value': h.get('value', ''), 'enabled': True})

            result.append({
                'path': path,
                'method': method,
                'summary': item.get('name', ''),
                'description': req.get('description', ''),
                'tags': [prefix.strip('/')] if prefix else [],
                'parameters': [],
                'request_body': _parse_postman_body(req),
                'responses': {},
                'deprecated': False,
            })
    return result


def _parse_postman_body(req: dict) -> dict | None:
    """从 Postman request 中提取 body schema"""
    body = req.get('body', {})
    mode = body.get('mode', '')
    if mode == 'raw' and 'raw' in body:
        try:
            return json.loads(body['raw'])
        except json.JSONDecodeError:
            return {'raw': body['raw']}
    if mode == 'urlencoded' and 'urlencoded' in body:
        props = {}
        for item in body['urlencoded']:
            props[item['key']] = {'type': 'string', 'description': item.get('description', '')}
        return {'type': 'object', 'properties': props}
    return None


def _join_path(base: str, path: str) -> str:
    if not base:
        return path
    return (base.rstrip('/') + '/' + path.lstrip('/')).rstrip('/') or '/'


def _extract_endpoint(path: str, method: str, operation: dict, spec_type: str) -> dict:
    params = []
    if spec_type == 'swagger2':
        # Swagger 2.0 的 parameters 直接在 operation 下
        for p in operation.get('parameters', []):
            params.append({
                'name': p.get('name', ''),
                'in': p.get('in', 'query'),
                'required': p.get('required', False),
                'type': p.get('type', 'string'),
                'description': p.get('description', ''),
                'schema': p if p.get('schema') else None,
            })
        request_body = _parse_swagger2_body(operation)
    else:
        # OpenAPI 3.x
        for p in operation.get('parameters', []):
            schema = p.get('schema', {})
            params.append({
                'name': p.get('name', ''),
                'in': p.get('in', 'query'),
                'required': p.get('required', False),
                'type': schema.get('type', 'string'),
                'description': p.get('description', ''),
                'schema': schema,
            })
        request_body = _parse_openapi3_body(operation)

    return {
        'path': path,
        'method': method.upper(),
        'summary': operation.get('summary', ''),
        'description': operation.get('description', ''),
        'tags': operation.get('tags', []),
        'parameters': params,
        'request_body': request_body,
        'responses': operation.get('responses', {}),
        'deprecated': operation.get('deprecated', False),
    }


def _parse_swagger2_body(operation: dict) -> dict | None:
    for p in operation.get('parameters', []):
        if p.get('in') == 'body':
            return p.get('schema', {})
    return None


def _parse_openapi3_body(operation: dict) -> dict | None:
    rb = operation.get('requestBody')
    if not rb:
        return None
    content = rb.get('content', {})
    for content_type in ['application/json', '*/*']:
        if content_type in content:
            return content[content_type].get('schema', {})
    # 取第一个可用的 content type
    for ct, ct_val in content.items():
        return ct_val.get('schema', {})
    return None


# ─────────────────────────────────────────────
#  2. Spec 版本对比
# ─────────────────────────────────────────────

def diff_specs(old_data: dict, new_data: dict) -> dict:
    """
    对比两个解析后的 spec 数据，生成变更列表。
    old_data / new_data 为 parse_openapi 的返回值。
    """
    old_map = {f"{e['method']} {e['path']}": e for e in old_data.get('endpoints', [])}
    new_map = {f"{e['method']} {e['path']}": e for e in new_data.get('endpoints', [])}

    changes = []
    old_keys = set(old_map.keys())
    new_keys = set(new_map.keys())

    # 新增接口
    for key in new_keys - old_keys:
        e = new_map[key]
        changes.append({
            'endpoint_path': e['path'],
            'endpoint_method': e['method'],
            'change_type': 'added',
            'severity': 'info',
            'detail': {'summary': e.get('summary', '')},
            'summary': f"新增接口 {e['method']} {e['path']}",
        })

    # 删除接口
    for key in old_keys - new_keys:
        e = old_map[key]
        changes.append({
            'endpoint_path': e['path'],
            'endpoint_method': e['method'],
            'change_type': 'removed',
            'severity': 'breaking',
            'detail': {'summary': e.get('summary', '')},
            'summary': f"删除接口 {e['method']} {e['path']}",
        })

    # 修改的接口
    for key in old_keys & new_keys:
        old_ep = old_map[key]
        new_ep = new_map[key]
        ep_changes = _diff_endpoint(old_ep, new_ep)
        for c in ep_changes:
            changes.append(c)

    return {
        'total_changes': len(changes),
        'breaking_count': sum(1 for c in changes if c['severity'] == 'breaking'),
        'warning_count': sum(1 for c in changes if c['severity'] == 'warning'),
        'info_count': sum(1 for c in changes if c['severity'] == 'info'),
        'changes': changes,
    }


def _diff_endpoint(old: dict, new: dict) -> list[dict]:
    changes = []
    path = new['path']
    method = new['method']

    # 检查 parameters 变更
    old_params = {p['name']: p for p in old.get('parameters', [])}
    new_params = {p['name']: p for p in new.get('parameters', [])}

    for name, new_p in new_params.items():
        if name not in old_params:
            severity = 'breaking' if new_p.get('required') else 'info'
            changes.append({
                'endpoint_path': path, 'endpoint_method': method,
                'change_type': 'param_added_required' if new_p.get('required') else 'other',
                'severity': severity,
                'detail': {'param_name': name, 'required': new_p.get('required'), 'type': new_p.get('type')},
                'summary': f"新增{'必填' if new_p.get('required') else '可选'}参数 {name}",
            })
        else:
            old_p = old_params[name]
            if old_p.get('type') != new_p.get('type'):
                changes.append({
                    'endpoint_path': path, 'endpoint_method': method,
                    'change_type': 'param_type_changed',
                    'severity': 'breaking',
                    'detail': {'param_name': name, 'old_type': old_p.get('type'), 'new_type': new_p.get('type')},
                    'summary': f"参数 {name} 类型变更: {old_p.get('type')} → {new_p.get('type')}",
                })

    for name in old_params.keys() - new_params.keys():
        old_p = old_params[name]
        severity = 'breaking' if old_p.get('required') else 'warning'
        changes.append({
            'endpoint_path': path, 'endpoint_method': method,
            'change_type': 'param_removed',
            'severity': severity,
            'detail': {'param_name': name, 'required': old_p.get('required'), 'type': old_p.get('type')},
            'summary': f"删除{'必填' if old_p.get('required') else '可选'}参数 {name}",
        })

    # 检查 request body
    old_body = old.get('request_body')
    new_body = new.get('request_body')

    if old_body and not new_body:
        changes.append({
            'endpoint_path': path, 'endpoint_method': method,
            'change_type': 'other', 'severity': 'warning',
            'detail': {}, 'summary': '请求体被移除',
        })
    elif new_body and not old_body:
        severity = 'breaking' if new_body.get('required') else 'info'
        changes.append({
            'endpoint_path': path, 'endpoint_method': method,
            'change_type': 'other', 'severity': severity,
            'detail': {'properties': list(new_body.get('properties', {}).keys())},
            'summary': '新增请求体',
        })
    elif old_body and new_body:
        old_props = set(old_body.get('properties', {}).keys())
        new_props = set(new_body.get('properties', {}).keys())
        old_required = set(old_body.get('required', []))
        new_required = set(new_body.get('required', []))

        for field in new_props - old_props:
            severity = 'breaking' if field in new_required else 'info'
            changes.append({
                'endpoint_path': path, 'endpoint_method': method,
                'change_type': 'param_added_required' if field in new_required else 'other',
                'severity': severity,
                'detail': {
                    'field_name': field,
                    'required': field in new_required,
                    'type': new_body['properties'].get(field, {}).get('type'),
                },
                'summary': f"请求体新增{'必填' if field in new_required else '可选'}字段 {field}",
            })

        for field in old_props - new_props:
            severity = 'breaking' if field in old_required else 'warning'
            changes.append({
                'endpoint_path': path, 'endpoint_method': method,
                'change_type': 'response_field_removed',
                'severity': severity,
                'detail': {
                    'field_name': field,
                    'was_required': field in old_required,
                },
                'summary': f"请求体删除{'必填' if field in old_required else '可选'}字段 {field}",
            })

    return changes


# ─────────────────────────────────────────────
#  3. 影响分析
# ─────────────────────────────────────────────

def find_affected_cases(change: dict, project_id: Any, api_request_model, test_suite_model) -> dict:
    """
    根据一笔变更，找出 TestHub 中受影响的 ApiRequest 和 TestSuite。
    匹配规则：ApiRequest 的 url 包含 endpoint_path，且 method 一致。

    返回: {api_requests: [...], test_suites: [...], affected_count}
    """
    from apps.api_testing.models import TestSuiteRequest  # noqa

    path = change.get('endpoint_path', '')
    method = change.get('endpoint_method', '')

    # 查找匹配的 ApiRequest
    matching_requests = api_request_model.objects.filter(
        collection__project_id=project_id,
        url__icontains=_normalize_path_for_match(path),
    )

    if method:
        matching_requests = matching_requests.filter(method=method)

    affected_requests = [
        {'id': str(r.id), 'name': r.name, 'url': r.url, 'method': r.method}
        for r in matching_requests
    ]

    # 查找包含这些 ApiRequest 的 TestSuite
    affected_suites_qs = test_suite_model.objects.filter(
        project_id=project_id,
        id__in=TestSuiteRequest.objects.filter(
            request__in=matching_requests,
        ).values_list('test_suite_id', flat=True).distinct(),
    )

    affected_suites = [
        {'id': str(s.id), 'name': s.name}
        for s in affected_suites_qs
    ]

    return {
        'api_requests': affected_requests,
        'test_suites': affected_suites,
        'affected_count': len(affected_requests),
    }


def _normalize_path_for_match(path: str) -> str:
    """将路径参数 /users/{id} 转成 /users/ 用于模糊匹配"""
    result = []
    i = 0
    while i < len(path):
        if path[i] == '{':
            while i < len(path) and path[i] != '}':
                i += 1
            if i < len(path):
                i += 1  # skip }
            continue
        result.append(path[i])
        i += 1
    path_stripped = ''.join(result).rstrip('/') + '/'
    # 去掉连续斜杠
    while '//' in path_stripped:
        path_stripped = path_stripped.replace('//', '/')
    return path_stripped


# ─────────────────────────────────────────────
#  4. 自动匹配端点 → 用例
# ─────────────────────────────────────────────

def auto_match_endpoints(spec, api_request_model):
    """
    将 spec 解析出的 endpoint 列表自动匹配到已有 ApiRequest。
    返回每个 endpoint 的匹配状态。
    """
    from .models import APIEndpoint, EndpointMapping  # noqa

    endpoints = APIEndpoint.objects.filter(spec=spec)

    for ep in endpoints:
        normalized = _normalize_path_for_match(ep.path)

        # 先精确匹配 method + url
        matching = api_request_model.objects.filter(
            collection__project=spec.project,
            method=ep.method,
        )

        best_match = None
        for req in matching:
            if _normalize_path_for_match(req.url) == normalized:
                best_match = req
                break

        if not best_match:
            # 模糊匹配：至少 path 中包含相同关键词
            for req in matching:
                if _paths_are_similar(ep.path, req.url):
                    best_match = req
                    break

        mapping, _ = EndpointMapping.objects.get_or_create(endpoint=ep)
        if best_match:
            mapping.api_request = best_match
            mapping.match_status = 'matched'
        else:
            mapping.api_request = None
            mapping.match_status = 'unmapped'
        mapping.save()

    return {
        'matched': EndpointMapping.objects.filter(endpoint__spec=spec, match_status='matched').count(),
        'unmapped': EndpointMapping.objects.filter(endpoint__spec=spec, match_status='unmapped').count(),
    }


def _paths_are_similar(path1: str, path2: str) -> bool:
    """判断两个路径是否相似（忽略变量部分）"""
    segments1 = _normalize_path_for_match(path1).strip('/').split('/')
    segments2 = _normalize_path_for_match(path2).strip('/').split('/')
    if len(segments1) != len(segments2) or len(segments1) == 0:
        return False
    match_count = sum(1 for a, b in zip(segments1, segments2) if a == b)
    return match_count >= len(segments1) - 1


# ─────────────────────────────────────────────
#  5. AI 工具
# ─────────────────────────────────────────────

def generate_case_suggestion(endpoint_data: dict) -> str:
    """
    根据接口定义，生成提示词给 AI 用来生成测试用例建议。
    返回 prompt 字符串，由调用方送入 LLM。
    """
    path = endpoint_data.get('path', '')
    method = endpoint_data.get('method', 'GET')
    summary = endpoint_data.get('summary', '')
    params = endpoint_data.get('parameters', [])
    body = endpoint_data.get('request_body', {})

    # 构建接口说明
    lines = [
        f'请为以下 API 接口生成 5~10 条接口测试用例（含断言），直接输出用例文本，不需要代码：',
        f'',
        f'接口: {method} {path}',
        f'描述: {summary}',
    ]

    if params:
        lines.append('请求参数:')
        for p in params:
            req_mark = '必填' if p.get('required') else '可选'
            lines.append(f'  - {p["name"]} ({p.get("in", "query")}, {p.get("type", "string")}, {req_mark}): {p.get("description", "")}')

    if body and body.get('properties'):
        lines.append('请求体字段:')
        required_fields = body.get('required', [])
        for name, prop in body['properties'].items():
            req_mark = '必填' if name in required_fields else '可选'
            lines.append(f'  - {name} ({prop.get("type", "string")}, {req_mark}): {prop.get("description", "")}')

    lines.extend([
        '',
        '要求:',
        '1. 覆盖成功场景 + 失败场景（参数缺失 / 类型错误 / 边界值）',
        '2. 每条用例包含：名称、测试步骤、预期结果（状态码 + 断言）',
        '3. 重点关注必填字段的校验',
    ])

    return '\n'.join(lines)


def analyze_execution_log_prompt(execution_log: dict) -> str:
    """根据测试执行日志，生成分析提示词"""
    from apps.api_testing.models import TestExecution  # noqa

    return '\n'.join([
        '以下是接口测试执行结果，请分析：',
        '',
        f'测试总数: {execution_log.get("total_requests", 0)}',
        f'通过: {execution_log.get("passed_requests", 0)}',
        f'失败: {execution_log.get("failed_requests", 0)}',
        '',
        '失败详情:',
        json.dumps(execution_log.get('failed_details', []), ensure_ascii=False, indent=2),
        '',
        '请给出：',
        '1. 失败原因分类（业务逻辑/数据问题/环境问题/断言不合理）',
        '2. 每类建议如何修复',
        '3. 建议优先重跑哪些用例',
    ])
