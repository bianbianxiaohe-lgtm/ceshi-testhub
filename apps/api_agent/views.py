import json
import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import APISpec, APIEndpoint, APIChange, EndpointMapping
from .serializers import (
    APISpecSerializer, APISpecCreateSerializer,
    APIEndpointSerializer, APIChangeSerializer, EndpointMappingSerializer,
    ChatMessageSerializer, ToolExecuteSerializer,
)
from .agent import APIAgent
from . import tools as agent_tools

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  APISpec — 文档版本管理
# ─────────────────────────────────────────────

class APISpecViewSet(viewsets.ModelViewSet):
    queryset = APISpec.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return APISpecCreateSerializer
        return APISpecSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project_id')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def create(self, request, *args, **kwargs):
        """导入/创建接口文档"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        project_id = serializer.validated_data.get('project').id
        spec_content = serializer.validated_data.pop('spec_content')

        # 解析 spec_content（可能是字符串或已解析的 JSON）
        if isinstance(spec_content, str):
            try:
                spec_json = json.loads(spec_content)
            except json.JSONDecodeError:
                return Response(
                    {'error': '无法解析文档内容，请确认是有效的 JSON 格式'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            spec_json = spec_content

        # 调用 Agent 工具解析并入库
        result = APIAgent.execute_tool(
            'import_spec',
            project_id=project_id,
            spec_json=spec_json,
            name=serializer.validated_data.get('name', '未命名文档'),
            version=serializer.validated_data.get('version', '1.0'),
            format=serializer.validated_data.get('spec_format', 'openapi3'),
            file_name=serializer.validated_data.get('file_name', ''),
            user=request.user,
        )

        # 读取创建的 spec 实例
        spec = APISpec.objects.get(id=result['spec_id'])
        output = APISpecSerializer(spec).data
        output['endpoint_count'] = result['endpoint_count']
        output['matched_count'] = result.get('matched', 0)
        output['unmapped_count'] = result.get('unmapped', 0)

        return Response(output, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def diff(self, request, pk=None):
        """对比两个 spec 版本"""
        new_spec = self.get_object()
        old_spec_id = request.data.get('old_spec_id')
        if not old_spec_id:
            return Response(
                {'error': '请提供 old_spec_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_spec = APISpec.objects.get(id=old_spec_id)
        result = APIAgent.execute_tool(
            'diff_specs',
            old_spec_id=str(old_spec.id),
            new_spec_id=str(new_spec.id),
            project_id=new_spec.project_id,
        )

        return Response(result)

    @action(detail=True, methods=['get'])
    def endpoints(self, request, pk=None):
        """查看 spec 下的所有 endpoint"""
        spec = self.get_object()
        endpoints = APIEndpoint.objects.filter(spec=spec)

        status_filter = request.query_params.get('status')
        if status_filter == 'unmapped':
            endpoints = endpoints.filter(mapping__match_status='unmapped')
        elif status_filter == 'matched':
            endpoints = endpoints.filter(mapping__match_status='matched')
        elif status_filter == 'diverged':
            endpoints = endpoints.filter(mapping__match_status='diverged')

        serializer = APIEndpointSerializer(endpoints, many=True)
        return Response(serializer.data)


# ─────────────────────────────────────────────
#  APIEndpoint — 接口端点
# ─────────────────────────────────────────────

class APIEndpointViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = APIEndpoint.objects.all()
    serializer_class = APIEndpointSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        spec_id = self.request.query_params.get('spec_id')
        if spec_id:
            qs = qs.filter(spec_id=spec_id)
        method = self.request.query_params.get('method')
        if method:
            qs = qs.filter(method=method.upper())
        return qs


# ─────────────────────────────────────────────
#  APIChange — 变更记录
# ─────────────────────────────────────────────

class APIChangeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = APIChange.objects.all()
    serializer_class = APIChangeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        spec_id = self.request.query_params.get('spec_id')
        if spec_id:
            qs = qs.filter(new_spec_id=spec_id)
        severity = self.request.query_params.get('severity')
        if severity:
            qs = qs.filter(severity=severity)
        return qs

    @action(detail=True, methods=['get'])
    def affected(self, request, pk=None):
        """查询此变更影响的 ApiRequest 和 TestSuite"""
        change = self.get_object()
        from apps.api_testing.models import ApiRequest, TestSuite

        result = agent_tools.find_affected_cases(
            {
                'endpoint_path': change.endpoint_path,
                'endpoint_method': change.endpoint_method,
            },
            change.new_spec.project_id,
            ApiRequest,
            TestSuite,
        )
        return Response(result)


# ─────────────────────────────────────────────
#  EndpointMapping — 端点映射管理
# ─────────────────────────────────────────────

class EndpointMappingViewSet(viewsets.ModelViewSet):
    queryset = EndpointMapping.objects.all()
    serializer_class = EndpointMappingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        spec_id = self.request.query_params.get('spec_id')
        if spec_id:
            qs = qs.filter(endpoint__spec_id=spec_id)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(match_status=status_filter)
        return qs

    @action(detail=False, methods=['post'])
    def rematch(self, request):
        """重新匹配所有端点"""
        spec_id = request.data.get('spec_id')
        if not spec_id:
            return Response({'error': '请提供 spec_id'}, status=status.HTTP_400_BAD_REQUEST)

        spec = APISpec.objects.get(id=spec_id)
        from apps.api_testing.models import ApiRequest

        result = agent_tools.auto_match_endpoints(spec, ApiRequest)
        return Response(result)


# ─────────────────────────────────────────────
#  Agent 对话接口
# ─────────────────────────────────────────────

class AgentChatViewSet(viewsets.ViewSet):
    """AI 助手对话和工具调用"""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def send_message(self, request):
        """发送对话消息"""
        serializer = ChatMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = serializer.validated_data['message']
        project_id = serializer.validated_data.get('project_id') or request.query_params.get('project_id')

        agent = APIAgent(user=request.user, project_id=project_id)
        result = agent.process_message(message)

        return Response(result)

    @action(detail=False, methods=['post'])
    def execute_tool(self, request):
        """直接执行工具（供前端/AI 工作流调用）"""
        serializer = ToolExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tool_name = serializer.validated_data['tool_name']
        params = {
            k: v for k, v in serializer.validated_data.items()
            if v is not None and k != 'tool_name'
        }
        params['user'] = request.user

        result = APIAgent.execute_tool(tool_name, **params)
        return Response(result)

    @action(detail=False, methods=['post'])
    def generate_cases(self, request):
        """AI 生成测试用例"""
        project_id = request.data.get('project_id') or request.query_params.get('project_id')
        endpoint_id = request.data.get('endpoint_id')

        result = APIAgent.execute_tool(
            'generate_cases',
            project_id=project_id,
            endpoint_id=endpoint_id,
        )

        return Response(result)

    @action(detail=False, methods=['get'])
    def status(self, request):
        """获取项目概览"""
        project_id = request.query_params.get('project_id')
        agent = APIAgent(user=request.user, project_id=project_id)
        result = agent._handle_check_status('', {})
        return Response(result)
