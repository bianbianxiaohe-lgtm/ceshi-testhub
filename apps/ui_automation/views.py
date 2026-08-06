from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from django.utils import timezone
from apps.core.mixins import OwnerOrMemberMixin, filter_by_owner_or_member
import logging
import json
import re
import random
import time

from .smart_locator import smart_match_locator, parse_swipe_pattern, get_wheel_coords, dump_page_elements

from .models import (
    UiProject, LocatorStrategy, Element, TestScript, TestSuite,
    TestSuiteScript, TestExecution, Screenshot,
    ElementGroup, PageObject, PageObjectElement, ScriptStep, ScriptElementUsage,
    TestCase, TestCaseStep, TestCaseExecution, OperationRecord,
    TestCase, TestCaseStep, TestCaseExecution, OperationRecord,
    UiScheduledTask, UiNotificationLog, UiTaskNotificationSetting,
    AICase, AIExecutionRecord,
    AppDevice, AppConfig
)
from .serializers import (
    UiProjectSerializer, UiProjectCreateSerializer, UiProjectUpdateSerializer,
    LocatorStrategySerializer,
    ElementSerializer, ElementEnhancedSerializer,
    TestScriptSerializer, TestScriptCreateSerializer, TestScriptUpdateSerializer,
    TestSuiteSerializer, TestSuiteCreateSerializer, TestSuiteUpdateSerializer, TestSuiteWithScriptsSerializer,
    TestSuiteScriptSerializer, TestSuiteTestCaseSerializer,
    TestExecutionSerializer, TestExecutionCreateSerializer,
    ScreenshotSerializer,
    ElementGroupSerializer, ElementGroupCreateSerializer,
    PageObjectSerializer, PageObjectCreateSerializer, PageObjectElementSerializer,
    ScriptStepSerializer, ScriptElementUsageSerializer,
    ScriptAnalysisSerializer, ElementValidationSerializer, CodeGenerationSerializer,
    TestCaseSerializer, TestCaseStepSerializer, TestCaseExecutionSerializer, TestCaseRunSerializer,
    OperationRecordSerializer,
    UiScheduledTaskSerializer, UiNotificationLogSerializer, UiTaskNotificationSettingSerializer,
    AICaseSerializer, AIExecutionRecordSerializer,
    AppDeviceSerializer, AppConfigSerializer
)
from .operation_logger import log_operation

logger = logging.getLogger(__name__)
User = get_user_model()


def infer_appium_action_type(text):
    """根据步骤文字推断 Appium 操作类型（click/fill/assert/wait/screenshot）"""
    t = (text or '').lower()
    if any(k in t for k in ['输入', '填写', '录入', 'input']):
        return 'fill'
    if any(k in t for k in ['点击', '单击', '按下', '选择', 'click', 'tap', '点']):
        return 'click'
    if any(k in t for k in ['验证', '断言', '检查', '确认', '应该', '预期', 'assert', '校验']):
        return 'assert'
    if any(k in t for k in ['等待', 'wait', 'sleep']):
        return 'wait'
    if any(k in t for k in ['截图', 'screenshot']):
        return 'screenshot'
    return 'click'


def _infer_web_action_type(text):
    """根据步骤文字推断 Web/Playwright 操作类型（与 Appium 版基本一致，不含 launch_app/swipe 等）"""
    return infer_appium_action_type(text)


def extract_step_input_value(text):
    """从步骤文字中提取输入值（冒号/引号后的内容）"""
    if not text:
        return ''
    m = re.search(r'[：:]\s*["\']?(.+?)["\']?$', text.strip())
    if m:
        return m.group(1).strip()
    return ''


def extract_step_info(s, step_index):
    """提取步骤信息的辅助函数，确保返回可读的步骤描述"""
    step_info = {'step': step_index}

    # 尝试多种方式提取可读信息
    if hasattr(s, 'action'):
        # 如果有action属性
        action_data = s.action
        if isinstance(action_data, str):
            step_info['action'] = action_data
        elif hasattr(action_data, '__dict__'):
            # 如果是对象，提取关键属性
            attrs = {}
            for key in ['type', 'description', 'goal', 'coordinate', 'text', 'output', 'result']:
                if hasattr(action_data, key):
                    value = getattr(action_data, key)
                    if isinstance(value, str):
                        attrs[key] = value
                    elif callable(value):
                       attrs[key] = getattr(value, '__name__', str(value))
                    else:
                        attrs[key] = str(value)
            if attrs:
                step_info['action'] = attrs
        else:
            step_info['action'] = str(action_data)
    elif hasattr(s, 'model_output'):
        # 如果有model_output属性
        output_data = s.model_output
        if isinstance(output_data, str):
            step_info['action'] = output_data
        elif hasattr(output_data, '__dict__'):
            # 提取model_output的关键信息
            attrs = {'type': 'model_output'}
            for key in ['action', 'description', 'goal', 'coordinate', 'text']:
                if hasattr(output_data, key):
                    value = getattr(output_data, key)
                    attrs[key] = str(value) if value else None
            step_info['action'] = attrs
        else:
            step_info['action'] = str(output_data)
    elif hasattr(s, '__dict__'):
        # 通用的对象提取
        attrs = {}
        for key in dir(s):
            if not key.startswith('_'):
                try:
                    value = getattr(s, key)
                    if not callable(value):
                        attrs[key] = str(value)
                except:
                    pass
        if attrs:
            step_info['action'] = attrs
    else:
        # 最后回退，但检查是否是函数对象
        if callable(s):
            step_info['action'] = f"<Action: {getattr(s, '__name__', 'unknown action')}>"
        else:
            step_info['action'] = str(s)

    return step_info


from rest_framework.pagination import PageNumberPagination

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 1000


# AI 项目状态 → UI 项目状态 映射
_UI_AI_STATUS_MAP = {
    'active': 'IN_PROGRESS',
    'paused': 'NOT_STARTED',
    'completed': 'COMPLETED',
    'archived': 'COMPLETED',
}


class UiProjectViewSet(OwnerOrMemberMixin, viewsets.ModelViewSet):
    queryset = UiProject.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'owner', 'members']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return UiProjectCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return UiProjectUpdateSerializer
        return UiProjectSerializer

    def list(self, request, *args, **kwargs):
        """
        列表：合并 UI 自动化项目 + AI 用例生成项目（全局统一项目源）
        AI 项目标记 source='ai' 且 id 带 proj_ 前缀，前端据此禁用编辑/删除
        """
        from rest_framework.response import Response

        # 1) 原生 UI 项目（全部取出，后续与 AI 项目一起手动分页）
        queryset = self.filter_queryset(self.get_queryset())
        ui_results = self.get_serializer(queryset, many=True).data

        # 2) AI 用例生成项目（apps.projects.Project）
        from apps.projects.models import Project as AiProject
        from apps.testcases.models import TestCase as AiTestCase
        search = request.query_params.get('search', '').strip()
        status = request.query_params.get('status', '').strip()
        try:
            ai_qs = AiProject.objects.all().prefetch_related('members', 'owner')
            if search:
                ai_qs = ai_qs.filter(name__icontains=search)
            ai_projects = ai_qs
        except Exception as e:
            logger.warning('UI项目管理加载AI项目失败: %s', e)
            ai_projects = []

        ai_results = []
        for p in ai_projects:
            mapped_status = _UI_AI_STATUS_MAP.get(p.status, 'IN_PROGRESS')
            if status and mapped_status != status:
                continue
            ai_results.append({
                'id': f'proj_{p.id}',
                'real_id': p.id,
                'name': p.name,
                'description': p.description or '',
                'status': mapped_status,
                'base_url': '',
                'start_date': None,
                'end_date': None,
                'owner_name': p.owner.username if p.owner else None,
                'member_count': p.members.count(),
                'test_case_count': AiTestCase.objects.filter(project=p).count(),
                'created_at': p.created_at.isoformat() if p.created_at else None,
                'updated_at': p.updated_at.isoformat() if p.updated_at else None,
                'source': 'ai',
            })

        # 3) 合并（UI 项目在前，AI 项目在后）
        merged = list(ui_results) + ai_results

        # 4) 手动分页（保持与前端分页参数兼容）
        try:
            page_size = int(request.query_params.get('page_size', 20))
            page = int(request.query_params.get('page', 1))
        except (TypeError, ValueError):
            page_size, page = 20, 1
        page_size = max(page_size, 1)
        page = max(page, 1)
        start = (page - 1) * page_size
        end = start + page_size
        page_data = merged[start:end]

        return Response({
            'count': len(merged),
            'next': None,
            'previous': None,
            'results': page_data,
        })

    def perform_create(self, serializer):
        # 创建项目时，当前用户自动成为负责人
        instance = serializer.save(owner=self.request.user)
        # 记录操作
        log_operation('create', 'project', instance.id, instance.name, self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()
        # 记录操作
        log_operation('edit', 'project', instance.id, instance.name, self.request.user)

    def perform_destroy(self, instance):
        # 记录操作（在删除前记录）
        log_operation('delete', 'project', instance.id, instance.name, self.request.user)
        instance.delete()


class LocatorStrategyViewSet(viewsets.ModelViewSet):
    queryset = LocatorStrategy.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = LocatorStrategySerializer
    ordering = ['id']


class ElementViewSet(viewsets.ModelViewSet):
    queryset = Element.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project', 'locator_strategy', 'element_type', 'validation_status', 'group']
    search_fields = ['name', 'description', 'page', 'component_name']

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return ElementEnhancedSerializer
        return ElementSerializer

    def get_queryset(self):
        # 只显示用户有权限访问的项目的元素
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return Element.objects.filter(project__in=accessible_projects).select_related(
            'project', 'group', 'locator_strategy', 'created_by', 'parent_element'
        ).prefetch_related('script_usages__script').order_by('page', 'name')

    def filter_queryset(self, queryset):
        # 先应用默认的过滤器
        queryset = super().filter_queryset(queryset)

        # 处理页面筛选（使用page_name参数避免与分页page冲突）
        page_name = self.request.query_params.get('page_name', None)
        if page_name:
            queryset = queryset.filter(page=page_name)

        return queryset

    def perform_create(self, serializer):
        # 创建元素时自动设置创建人
        instance = serializer.save(created_by=self.request.user)
        # 记录操作
        log_operation('create', 'element', instance.id, instance.name, self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()
        # 记录操作
        log_operation('edit', 'element', instance.id, instance.name, self.request.user)

    def perform_destroy(self, instance):
        # 记录操作（在删除前记录）
        log_operation('delete', 'element', instance.id, instance.name, self.request.user)
        instance.delete()

    @action(detail=True, methods=['post'])
    def validate_locator(self, request, pk=None):
        """验证元素定位器有效性"""
        element = self.get_object()

        # 这里可以集成实际的浏览器验证逻辑
        # 现在只是模拟验证
        validation_result = self._perform_element_validation(element)

        element.validation_status = 'VALID' if validation_result['is_valid'] else 'INVALID'
        element.validation_message = validation_result['validation_message']
        element.last_validated = timezone.now()
        element.save()

        serializer = ElementValidationSerializer(validation_result)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def usages(self, request, pk=None):
        """获取元素在脚本中的使用情况"""
        element = self.get_object()
        usages = ScriptElementUsage.objects.filter(element=element).select_related('script')
        serializer = ScriptElementUsageSerializer(usages, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """获取元素树形结构"""
        project_id = request.query_params.get('project')
        if not project_id:
            return Response({'error': '需要指定项目ID'}, status=status.HTTP_400_BAD_REQUEST)

        elements = self.get_queryset().filter(project_id=project_id)
        tree_data = self._build_element_tree(elements)
        return Response(tree_data)

    @action(detail=True, methods=['post'])
    def add_backup_locator(self, request, pk=None):
        """添加备用定位器"""
        element = self.get_object()
        strategy = request.data.get('strategy')
        value = request.data.get('value')

        if not strategy or not value:
            return Response({'error': '策略和值都是必需的'}, status=status.HTTP_400_BAD_REQUEST)

        backup_locators = element.backup_locators or []
        backup_locators.append({'strategy': strategy, 'value': value})
        element.backup_locators = backup_locators
        element.save()

        return Response({'message': '备用定位器添加成功'})

    @action(detail=True, methods=['post'])
    def generate_suggestions(self, request, pk=None):
        """生成元素使用建议"""
        element = self.get_object()
        suggestions = self._generate_element_suggestions(element)
        return Response({'suggestions': suggestions})

    def _perform_element_validation(self, element):
        """执行元素验证（模拟实现）"""
        try:
            # 这里可以集成实际的浏览器自动化工具进行验证
            # 现在只是简单的语法检查
            is_valid = True
            message = "定位器验证通过"
            suggestions = []

            # 简单的语法检查
            if element.locator_strategy.name == 'css':
                if not element.locator_value.strip():
                    is_valid = False
                    message = "CSS选择器不能为空"
            elif element.locator_strategy.name == 'xpath':
                if not element.locator_value.strip():
                    is_valid = False
                    message = "XPath表达式不能为空"

            return {
                'is_valid': is_valid,
                'validation_message': message,
                'suggestions': suggestions
            }
        except Exception as e:
            return {
                'is_valid': False,
                'validation_message': f'验证过程中出现错误: {str(e)}',
                'suggestions': []
            }

    def _build_element_tree(self, elements):
        """构建元素树形结构 - 返回元素列表而不是页面分组，因为前端会自己处理页面关联"""
        element_data_list = []
        for element in elements:
            element_data = {
                'id': element.id,
                'name': element.name,
                'type': 'element',
                'element_type': element.element_type,
                'locator_strategy': element.locator_strategy.name if element.locator_strategy else None,
                'locator_value': element.locator_value,
                'validation_status': element.validation_status,
                'usage_count': element.usage_count,
                'group_id': element.group_id,  # 用于前端关联到页面
                'page': element.page,  # 保留向后兼容
                'children': []
            }
            element_data_list.append(element_data)

        return element_data_list

    def _generate_element_suggestions(self, element):
        """生成元素使用建议"""
        suggestions = []

        # 基于元素类型生成建议
        if element.element_type == 'INPUT':
            suggestions.append("建议为输入框元素添加清空和输入验证操作")
        elif element.element_type == 'BUTTON':
            suggestions.append("建议验证按钮点击后的页面跳转或状态变化")
        elif element.element_type == 'DROPDOWN':
            suggestions.append("建议测试下拉框的所有选项")

        # 基于使用频率生成建议
        if element.usage_count == 0:
            suggestions.append("此元素尚未在任何脚本中使用，考虑是否需要删除")
        elif element.usage_count > 10:
            suggestions.append("此元素使用频率较高，建议添加到页面对象中以提高复用性")

        return suggestions


class ElementGroupViewSet(viewsets.ModelViewSet):
    queryset = ElementGroup.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project', 'parent_group']
    search_fields = ['name', 'description']

    def get_serializer_class(self):
        if self.action == 'create':
            return ElementGroupCreateSerializer
        return ElementGroupSerializer

    def get_queryset(self):
        # 只显示用户有权限访问的项目的元素分组
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return ElementGroup.objects.filter(project__in=accessible_projects).select_related('project', 'parent_group').order_by('order', 'name')

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """获取分组树形结构"""
        project_id = request.query_params.get('project')
        if not project_id:
            return Response({'error': '需要指定项目ID'}, status=status.HTTP_400_BAD_REQUEST)

        groups = self.get_queryset().filter(project_id=project_id, parent_group__isnull=True)
        serializer = ElementGroupSerializer(groups, many=True)
        return Response(serializer.data)


class PageObjectViewSet(viewsets.ModelViewSet):
    queryset = PageObject.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'class_name', 'description']

    def get_serializer_class(self):
        if self.action == 'create':
            return PageObjectCreateSerializer
        return PageObjectSerializer

    def get_queryset(self):
        # 只显示用户有权限访问的项目的页面对象
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return PageObject.objects.filter(project__in=accessible_projects).select_related(
            'project', 'created_by'
        ).prefetch_related('page_object_elements__element').order_by('-created_at')

    @action(detail=True, methods=['post'])
    def generate_code(self, request, pk=None):
        """生成页面对象代码"""
        page_object = self.get_object()
        serializer = CodeGenerationSerializer(data=request.data)

        if serializer.is_valid():
            language = serializer.validated_data['language']
            framework = serializer.validated_data['framework']
            include_comments = serializer.validated_data['include_comments']

            try:
                generated_code = page_object.generate_code(language)

                # 保存生成的代码模板
                page_object.template_code = generated_code
                page_object.save()

                return Response({
                    'code': generated_code,
                    'language': language,
                    'framework': framework
                })
            except Exception as e:
                return Response({
                    'error': f'代码生成失败: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def add_element(self, request, pk=None):
        """向页面对象添加元素"""
        page_object = self.get_object()
        serializer = PageObjectElementSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(page_object=page_object)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def elements(self, request, pk=None):
        """获取页面对象的所有元素"""
        page_object = self.get_object()
        po_elements = page_object.page_object_elements.select_related('element').all()
        serializer = PageObjectElementSerializer(po_elements, many=True)
        return Response(serializer.data)


class PageObjectElementViewSet(viewsets.ModelViewSet):
    queryset = PageObjectElement.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = PageObjectElementSerializer

    def get_queryset(self):
        # 只显示用户有权限访问的页面对象元素
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return PageObjectElement.objects.filter(
            page_object__project__in=accessible_projects
        ).select_related('page_object', 'element').order_by('id')


class ScriptStepViewSet(viewsets.ModelViewSet):
    queryset = ScriptStep.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = ScriptStepSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['script', 'action_type', 'target_element', 'page_object']

    def get_queryset(self):
        # 只显示用户有权限访问的脚本步骤
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return ScriptStep.objects.filter(
            script__project__in=accessible_projects
        ).select_related('script', 'target_element', 'page_object').order_by('step_order')

    @action(detail=False, methods=['post'])
    def batch_create(self, request):
        """批量创建脚本步骤"""
        steps_data = request.data.get('steps', [])
        created_steps = []

        for step_data in steps_data:
            serializer = ScriptStepSerializer(data=step_data)
            if serializer.is_valid():
                step = serializer.save()
                created_steps.append(step)
            else:
                return Response({
                    'error': f'步骤创建失败: {serializer.errors}'
                }, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = ScriptStepSerializer(created_steps, many=True)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class ScriptElementUsageViewSet(viewsets.ModelViewSet):
    queryset = ScriptElementUsage.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = ScriptElementUsageSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['script', 'element', 'usage_type']

    def get_queryset(self):
        # 只显示用户有权限访问的脚本元素使用记录
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return ScriptElementUsage.objects.filter(
            script__project__in=accessible_projects
        ).select_related('script', 'element').order_by('script', 'line_number')

    @action(detail=False, methods=['post'])
    def analyze_script(self, request):
        """分析脚本中的元素使用情况"""
        script_id = request.data.get('script_id')
        if not script_id:
            return Response({'error': '需要指定脚本ID'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            script = TestScript.objects.get(id=script_id)
            analysis_result = self._analyze_script_elements(script)

            serializer = ScriptAnalysisSerializer(analysis_result)
            return Response(serializer.data)
        except TestScript.DoesNotExist:
            return Response({'error': '脚本不存在'}, status=status.HTTP_404_NOT_FOUND)

    def _analyze_script_elements(self, script):
        """分析脚本中的元素使用"""
        # 解析脚本内容，查找元素使用情况
        content = script.content
        usages = []
        missing_elements = []
        recommendations = []

        # 简单的元素使用分析（实际实现会更复杂）
        if script.script_type == 'CODE':
            # 分析代码中的定位器使用
            locator_patterns = [
                r'locator\(["\']([^"\']+)["\']\)',
                r'findElement\(["\']([^"\']+)["\']\)',
                r'css\(["\']([^"\']+)["\']\)',
                r'xpath\(["\']([^"\']+)["\']\)'
            ]

            for pattern in locator_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    # 查找对应的元素
                    try:
                        element = Element.objects.get(
                            project=script.project,
                            locator_value=match
                        )
                        usage, created = ScriptElementUsage.objects.get_or_create(
                            script=script,
                            element=element,
                            defaults={
                                'usage_type': 'CLICK',  # 默认类型
                                'line_number': 1,  # 需要实际解析
                                'frequency': 1
                            }
                        )
                        if not created:
                            usage.frequency += 1
                            usage.save()

                        element.increment_usage_count()
                        usages.append(usage)
                    except Element.DoesNotExist:
                        missing_elements.append(match)

        # 生成建议
        if missing_elements:
            recommendations.append(f"发现 {len(missing_elements)} 个未定义的元素定位器")

        if len(usages) > 20:
            recommendations.append("脚本复杂度较高，建议拆分为多个小脚本")

        complexity_score = min(100, len(usages) * 5)

        return {
            'element_usages': usages,
            'missing_elements': missing_elements,
            'recommendations': recommendations,
            'complexity_score': complexity_score
        }


class TestScriptViewSet(viewsets.ModelViewSet):
    queryset = TestScript.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project', 'script_type']
    search_fields = ['name', 'description']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return TestScriptCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TestScriptUpdateSerializer
        return TestScriptSerializer

    def get_queryset(self):
        # 只显示用户有权限访问的项目的测试脚本
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return TestScript.objects.filter(project__in=accessible_projects)


class TestSuiteViewSet(viewsets.ModelViewSet):
    queryset = TestSuite.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'description']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return TestSuiteCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TestSuiteUpdateSerializer
        elif self.action == 'retrieve':
            return TestSuiteWithScriptsSerializer
        return TestSuiteSerializer

    def get_queryset(self):
        # 只显示用户有权限访问的项目的测试套件
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return TestSuite.objects.filter(project__in=accessible_projects)

    def perform_create(self, serializer):
        instance = serializer.save()
        # 记录操作
        log_operation('create', 'suite', instance.id, instance.name, self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()
        # 记录操作
        log_operation('edit', 'suite', instance.id, instance.name, self.request.user)

    def perform_destroy(self, instance):
        # 记录操作（在删除前记录）
        log_operation('delete', 'suite', instance.id, instance.name, self.request.user)
        instance.delete()

    @action(detail=True, methods=['get'])
    def scripts(self, request, pk=None):
        """获取测试套件中的所有脚本"""
        test_suite = self.get_object()
        scripts = test_suite.suite_scripts.all()
        serializer = TestSuiteScriptSerializer(scripts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_script(self, request, pk=None):
        """向测试套件添加脚本"""
        test_suite = self.get_object()
        data = request.data
        data['test_suite'] = pk
        serializer = TestSuiteScriptSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'])
    def remove_script(self, request, pk=None, script_id=None):
        """从测试套件移除脚本"""
        test_suite = self.get_object()
        try:
            suite_script = TestSuiteScript.objects.get(test_suite=test_suite, id=script_id)
            suite_script.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TestSuiteScript.DoesNotExist:
            return Response({'error': '脚本不存在于该测试套件中'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['get'])
    def test_cases(self, request, pk=None):
        """获取测试套件中的所有测试用例"""
        test_suite = self.get_object()
        test_cases = test_suite.suite_test_cases.all()
        serializer = TestSuiteTestCaseSerializer(test_cases, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_test_case(self, request, pk=None):
        """向测试套件添加测试用例"""
        test_suite = self.get_object()
        test_case_id = request.data.get('test_case_id')
        order = request.data.get('order', 0)

        try:
            from .models import TestSuiteTestCase
            suite_test_case = TestSuiteTestCase.objects.create(
                test_suite=test_suite,
                test_case_id=test_case_id,
                order=order
            )
            serializer = TestSuiteTestCaseSerializer(suite_test_case)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'])
    def remove_test_case(self, request, pk=None):
        """从测试套件移除测试用例"""
        test_suite = self.get_object()
        test_case_id = request.data.get('test_case_id')

        try:
            from .models import TestSuiteTestCase
            suite_test_case = TestSuiteTestCase.objects.get(
                test_suite=test_suite,
                test_case_id=test_case_id
            )
            suite_test_case.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TestSuiteTestCase.DoesNotExist:
            return Response({'error': '测试用例不存在于该测试套件中'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def update_test_case_order(self, request, pk=None):
        """更新测试套件中测试用例的顺序"""
        test_suite = self.get_object()
        test_case_orders = request.data.get('test_case_orders', [])

        try:
            from .models import TestSuiteTestCase
            for item in test_case_orders:
                TestSuiteTestCase.objects.filter(
                    test_suite=test_suite,
                    test_case_id=item['test_case_id']
                ).update(order=item['order'])

            return Response({'message': '顺序更新成功'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def run_suite(self, request, pk=None):
        """执行测试套件"""
        test_suite = self.get_object()

        # 传统模式执行（Playwright/Selenium）
        # 检查是否包含测试用例
        test_case_count = test_suite.suite_test_cases.count()
        if test_case_count == 0:
            return Response({
                'error': '该测试套件未包含任何测试用例，无法执行'
            }, status=status.HTTP_400_BAD_REQUEST)

        engine = request.data.get('engine', 'playwright')
        browser = request.data.get('browser', 'chrome')
        headless = request.data.get('headless', False)
        device_id = request.data.get('device_id', None)
        app_config_id = request.data.get('app_config_id', None)

        # Appium 引擎必须指定设备和应用
        if engine == 'appium' and (not device_id or not app_config_id):
            return Response({
                'error': '使用 Appium 引擎时必须选择设备和应用配置'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 更新套件执行状态为运行中
        test_suite.execution_status = 'running'
        test_suite.save()

        try:
            # 在后台线程中执行测试
            import threading
            from .test_executor import TestExecutor

            def run_test():
                executor = TestExecutor(
                    test_suite=test_suite,
                    engine=engine,
                    browser=browser,
                    headless=headless,
                    executed_by=request.user,
                    device_id=device_id,
                    app_config_id=app_config_id
                )
                executor.run()

            # 启动后台线程执行测试
            thread = threading.Thread(target=run_test)
            thread.daemon = True
            thread.start()

            # 记录运行操作
            log_operation('run', 'suite', test_suite.id, test_suite.name, request.user)

            response_data = {
                'message': '测试套件开始执行',
                'suite_id': test_suite.id,
                'test_case_count': test_case_count,
                'engine': engine,
                'browser': browser,
                'headless': headless
            }
            if device_id:
                response_data['device_id'] = device_id
            if app_config_id:
                response_data['app_config_id'] = app_config_id
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            test_suite.execution_status = 'failed'
            test_suite.save()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TestExecutionViewSet(viewsets.ModelViewSet):
    queryset = TestExecution.objects.all()
    permission_classes = [IsAuthenticated]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['project', 'test_suite', 'test_script', 'status', 'environment', 'executed_by']
    search_fields = ['error_message']
    ordering = ['-created_at']
    ordering = ['-created_at']
    pagination_class = StandardPagination

    def get_queryset(self):
        # 只显示用户有权限访问的项目的测试执行记录
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return TestExecution.objects.filter(
            project__in=accessible_projects
        ).select_related('project', 'test_suite', 'test_script', 'executed_by')

    def get_serializer_class(self):
        if self.action == 'create':
            return TestExecutionCreateSerializer
        return TestExecutionSerializer



    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        """运行测试执行"""
        execution = self.get_object()
        execution.status = 'RUNNING'
        execution.started_at = timezone.now()
        execution.save()
        
        # 这里应该有实际的测试运行逻辑，这里只是模拟
        # 在实际实现中，这里可能会启动一个异步任务来执行测试
        
        # 模拟测试运行结果
        import time
        time.sleep(2)  # 模拟测试执行时间
        
        execution.status = 'SUCCESS'  # 假设测试成功
        execution.finished_at = timezone.now()
        execution.result_data = {
            'steps': [
                {'name': 'Step 1', 'status': 'PASS', 'duration': 1.2},
                {'name': 'Step 2', 'status': 'PASS', 'duration': 0.8},
                {'name': 'Step 3', 'status': 'PASS', 'duration': 1.5},
            ],
            'total_steps': 3,
            'passed_steps': 3,
            'failed_steps': 0,
            'duration': 3.5
        }
        execution.save()
        
        serializer = TestExecutionSerializer(execution)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def abort(self, request, pk=None):
        """中止测试执行"""
        execution = self.get_object()
        if execution.status == 'RUNNING':
            execution.status = 'ABORTED'
            execution.finished_at = timezone.now()
            execution.save()
            return Response(TestExecutionSerializer(execution).data)
        return Response({'error': '测试执行未在运行中'}, status=status.HTTP_400_BAD_REQUEST)

    def perform_destroy(self, instance):
        # 记录操作（删除测试报告）
        suite_name = instance.test_suite.name if instance.test_suite else f"执行记录#{instance.id}"
        log_operation('delete', 'report', instance.id, suite_name, self.request.user)
        instance.delete()


class ScreenshotViewSet(viewsets.ModelViewSet):
    queryset = Screenshot.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = ScreenshotSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['execution']

    def get_queryset(self):
        # 只显示用户有权限访问的项目的截图
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        executions = TestExecution.objects.filter(project__in=accessible_projects)
        return Screenshot.objects.filter(execution__in=executions)


class TestCaseViewSet(viewsets.ModelViewSet):
    """测试用例视图集"""
    queryset = TestCase.objects.all()
    serializer_class = TestCaseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at', 'name', 'priority', 'status']
    ordering = ['-created_at']
    filterset_fields = ['project', 'status', 'priority', 'created_by']

    def get_queryset(self):
        # 只显示用户有权限访问的项目的测试用例
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        qs = TestCase.objects.filter(project__in=accessible_projects).select_related('project', 'created_by')
        # 按 tags 筛选（如 tags=冒烟）
        tag_filter = self.request.query_params.get('tags')
        if tag_filter:
            qs = qs.filter(tags__contains=[tag_filter])
        return qs

    def perform_create(self, serializer):
        # 创建测试用例
        instance = serializer.save(created_by=self.request.user)

        # 记录操作
        log_operation('create', 'test_case', instance.id, instance.name, self.request.user)

        # 处理步骤数据
        steps_data = self.request.data.get('steps', [])
        logger.info(f"创建测试用例 {instance.id} 的步骤数据: {len(steps_data)} 个步骤")

        if steps_data:
            # 创建新步骤
            created_count = 0
            for i, step_data in enumerate(steps_data):
                # 确保步骤数据结构正确
                step_data = dict(step_data)  # 创建副本避免修改原数据
                step_data['test_case'] = instance.id  # 使用测试用例ID
                step_data['step_number'] = i + 1  # 确保步骤序号正确

                # 处理元素ID
                if 'element_id' in step_data:
                    step_data['element'] = step_data.pop('element_id')

                # 移除只读字段
                step_data.pop('id', None)
                step_data.pop('element_name', None)
                step_data.pop('element_locator', None)
                step_data.pop('created_at', None)
                step_data.pop('expanded', None)  # 前端UI状态字段

                # 使用模型直接创建，避免序列化器的复杂性
                try:
                    TestCaseStep.objects.create(
                        test_case=instance,
                        step_number=step_data.get('step_number', i + 1),
                        action_type=step_data.get('action_type', 'click'),
                        element_id=step_data.get('element') if step_data.get('element') else None,
                        input_value=step_data.get('input_value', ''),
                        wait_time=step_data.get('wait_time', 1000),
                        assert_type=step_data.get('assert_type', ''),
                        assert_value=step_data.get('assert_value', ''),
                        description=step_data.get('description', '')
                    )
                    created_count += 1
                except Exception as e:
                    logger.error(f"创建步骤 {i+1} 失败: {str(e)}")
                    logger.error(f"步骤数据: {step_data}")

            logger.info(f"成功创建了 {created_count} 个新步骤")

    @action(detail=True, methods=['post'])
    def copy_case(self, request, pk=None):
        """复制测试用例"""
        test_case = self.get_object()
        
        try:
            # 1. 复制测试用例基本信息
            new_case = TestCase.objects.create(
                project=test_case.project,
                name=f"{test_case.name}_copy",
                description=test_case.description,
                priority=test_case.priority,
                status=test_case.status,
                created_by=request.user
            )
            
            # 2. 复制测试步骤
            steps = test_case.steps.all().order_by('step_number')
            new_steps = []
            for step in steps:
                new_steps.append(TestCaseStep(
                    test_case=new_case,
                    step_number=step.step_number,
                    action_type=step.action_type,
                    element=step.element,
                    input_value=step.input_value,
                    wait_time=step.wait_time,
                    assert_type=step.assert_type,
                    assert_value=step.assert_value,
                    description=step.description
                ))
            
            if new_steps:
                TestCaseStep.objects.bulk_create(new_steps)
            
            # 记录操作
            log_operation('create', 'test_case', new_case.id, new_case.name, request.user)
            
            serializer = self.get_serializer(new_case)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"复制测试用例失败: {str(e)}")
            return Response({'error': f"复制失败: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_update(self, serializer):
        # 更新测试用例步骤
        instance = serializer.save()

        # 记录操作
        log_operation('edit', 'test_case', instance.id, instance.name, self.request.user)

        # 处理步骤数据
        steps_data = self.request.data.get('steps', [])
        logger.info(f"更新测试用例 {instance.id} 的步骤数据: {len(steps_data)} 个步骤")

        if steps_data:
            # 删除现有步骤
            existing_steps_count = instance.steps.count()
            instance.steps.all().delete()
            logger.info(f"删除了 {existing_steps_count} 个现有步骤")

            # 创建新步骤
            created_count = 0
            for i, step_data in enumerate(steps_data):
                # 确保步骤数据结构正确
                step_data = dict(step_data)  # 创建副本避免修改原数据
                step_data['test_case'] = instance.id  # 使用测试用例ID
                step_data['step_number'] = i + 1  # 确保步骤序号正确

                # 处理元素ID
                if 'element_id' in step_data:
                    step_data['element'] = step_data.pop('element_id')

                # 移除只读字段
                step_data.pop('id', None)
                step_data.pop('element_name', None)
                step_data.pop('element_locator', None)
                step_data.pop('created_at', None)
                step_data.pop('expanded', None)  # 前端UI状态字段

                # 使用模型直接创建，避免序列化器的复杂性
                try:
                    TestCaseStep.objects.create(
                        test_case=instance,
                        step_number=step_data.get('step_number', i + 1),
                        action_type=step_data.get('action_type', 'click'),
                        element_id=step_data.get('element') if step_data.get('element') else None,
                        input_value=step_data.get('input_value', ''),
                        wait_time=step_data.get('wait_time', 1000),
                        assert_type=step_data.get('assert_type', ''),
                        assert_value=step_data.get('assert_value', ''),
                        description=step_data.get('description', '')
                    )
                    created_count += 1
                except Exception as e:
                    logger.error(f"创建步骤 {i+1} 失败: {str(e)}")
                    logger.error(f"步骤数据: {step_data}")

            logger.info(f"成功创建了 {created_count} 个新步骤")

    def _generate_step_log(self, step, step_result='success'):
        """根据测试步骤生成执行日志"""
        import time

        # 模拟执行时间（0.1秒到2秒之间）
        execution_time = round(random.uniform(0.1, 2.0), 2)

        # 构建基础日志
        log_parts = []

        # 步骤信息
        if step.element:
            element_name = step.element.name
            locator_info = f"{step.element.locator_strategy.name}={step.element.locator_value}"
        else:
            element_name = "页面"
            locator_info = "无"

        # 根据操作类型生成具体日志
        if step.action_type == 'click':
            log_parts.append(f"点击元素 '{element_name}'")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                log_parts.append(f"- 元素点击成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 元素点击失败 - 元素未找到或不可点击")

        elif step.action_type == 'fill':
            log_parts.append(f"在元素 '{element_name}' 中输入文本")
            log_parts.append(f"- 使用定位器: {locator_info}")
            log_parts.append(f"- 输入值: '{step.input_value}'")
            if step_result == 'success':
                log_parts.append(f"- 文本输入成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 文本输入失败 - 元素未找到或不可编辑")

        elif step.action_type == 'getText':
            log_parts.append(f"获取元素 '{element_name}' 的文本内容")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                # 模拟获取到的文本
                mock_text = f"示例文本内容_{step.id}" if step.id else "示例文本内容"
                log_parts.append(f"- 获取到文本: '{mock_text}' - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 获取文本失败 - 元素未找到")

        elif step.action_type == 'waitFor':
            log_parts.append(f"等待元素 '{element_name}' 出现")
            log_parts.append(f"- 使用定位器: {locator_info}")
            log_parts.append(f"- 超时时间: {step.wait_time/1000}秒")
            if step_result == 'success':
                log_parts.append(f"- 元素在 {execution_time}s 后出现")
            else:
                log_parts.append(f"- 等待超时 - 元素未在指定时间内出现")

        elif step.action_type == 'hover':
            log_parts.append(f"在元素 '{element_name}' 上悬停")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                log_parts.append(f"- 悬停操作成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 悬停操作失败 - 元素未找到")

        elif step.action_type == 'scroll':
            log_parts.append(f"滚动到元素 '{element_name}'")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                log_parts.append(f"- 滚动操作成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 滚动操作失败 - 元素未找到")

        elif step.action_type == 'screenshot':
            log_parts.append(f"执行截图操作")
            if step.element:
                log_parts.append(f"- 截图范围: 元素 '{element_name}'")
            else:
                log_parts.append(f"- 截图范围: 整个页面")
            if step_result == 'success':
                screenshot_name = f"screenshot_{int(time.time())}.png"
                log_parts.append(f"- 截图保存成功: {screenshot_name} - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 截图保存失败")

        elif step.action_type == 'assert':
            log_parts.append(f"执行断言验证")
            log_parts.append(f"- 断言类型: {step.assert_type}")
            if step.assert_value:
                log_parts.append(f"- 期望值: '{step.assert_value}'")
            if step_result == 'success':
                log_parts.append(f"- 断言通过 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 断言失败 - 实际值与期望值不匹配")

        elif step.action_type == 'wait':
            log_parts.append(f"固定等待")
            log_parts.append(f"- 等待时间: {step.wait_time/1000}秒")
            log_parts.append(f"- 等待完成")

        else:
            # 默认处理其他操作类型
            log_parts.append(f"执行操作: {step.action_type}")
            if step.element:
                log_parts.append(f"- 目标元素: {element_name}")
            if step.input_value:
                log_parts.append(f"- 输入值: {step.input_value}")
            log_parts.append(f"- 操作{'成功' if step_result == 'success' else '失败'} - 耗时 {execution_time}s")

        # 如果步骤有描述，添加到日志中
        if step.description:
            log_parts.insert(0, f"说明: {step.description}")

        return '\n'.join(log_parts)

    def _generate_failure_screenshot(self, step_number, step_description):
        """生成失败截图的模拟数据（base64格式）"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io
            import base64

            # 创建一个模拟的失败截图
            # 实际应用中，这里应该是通过Playwright/Selenium捕获真实的页面截图
            width, height = 1280, 720
            img = Image.new('RGB', (width, height), color=(240, 240, 245))
            draw = ImageDraw.Draw(img)

            # 绘制标题区域
            draw.rectangle([0, 0, width, 80], fill=(220, 53, 69))

            # 添加文本信息（使用默认字体）
            try:
                # 尝试使用系统字体
                font_title = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 40)
                font_text = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 24)
            except:
                # 如果系统字体不可用，使用默认字体
                font_title = ImageFont.load_default()
                font_text = ImageFont.load_default()

            # 标题
            draw.text((40, 20), "测试步骤执行失败", fill=(255, 255, 255), font=font_title)

            # 失败信息
            info_y = 120
            draw.text((40, info_y), f"失败步骤: 步骤 {step_number}", fill=(50, 50, 50), font=font_text)
            draw.text((40, info_y + 40), f"步骤说明: {step_description}", fill=(50, 50, 50), font=font_text)
            draw.text((40, info_y + 80), f"失败时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     fill=(50, 50, 50), font=font_text)

            # 绘制一个模拟的浏览器窗口
            browser_y = info_y + 140
            draw.rectangle([40, browser_y, width-40, height-40], outline=(200, 200, 200), width=2)
            draw.rectangle([40, browser_y, width-40, browser_y + 40], fill=(200, 200, 200))
            draw.text((60, browser_y + 10), "模拟浏览器页面 - 失败截图", fill=(80, 80, 80), font=font_text)

            # 在浏览器窗口中绘制错误提示
            error_y = browser_y + 80
            draw.text((60, error_y), "× 元素定位失败或操作执行异常", fill=(220, 53, 69), font=font_text)
            draw.text((60, error_y + 40), "× 请检查元素定位器是否正确", fill=(220, 53, 69), font=font_text)
            draw.text((60, error_y + 80), "× 或页面加载是否完成", fill=(220, 53, 69), font=font_text)

            # 转换为base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()

            return f"data:image/png;base64,{img_base64}"

        except Exception as e:
            logger.error(f"生成失败截图时出错: {str(e)}")
            # 返回一个简单的错误占位符
            return None

    @action(detail=False, methods=['post'], url_path='convert-from-testcases')
    def convert_from_testcases(self, request):
        """将用例库用例转换为 UI 自动化结构化用例。
        mode='web'(默认): 生成 Web/Playwright 用例（通用 click/fill/assert）
        mode='appium':     生成 Appium App 用例（含 launch_app、swipe 等）
        """
        from apps.testcases.models import TestCase as LibTestCase

        case_ids = request.data.get('case_ids', [])
        ui_project_id = request.data.get('ui_project_id')
        mode = request.data.get('mode', 'web')  # 'web' | 'appium'

        if not case_ids:
            return Response({'success': False, 'message': '请选择要转换的用例'}, status=status.HTTP_400_BAD_REQUEST)
        if not ui_project_id:
            return Response({'success': False, 'message': '请选择目标 UI 自动化项目'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ui_project = UiProject.objects.get(id=ui_project_id)
        except UiProject.DoesNotExist:
            return Response({'success': False, 'message': '目标 UI 自动化项目不存在'}, status=status.HTTP_400_BAD_REQUEST)

        default_strategy = LocatorStrategy.objects.filter(name='xpath').first() or LocatorStrategy.objects.first()
        if not default_strategy:
            return Response(
                {'success': False, 'message': '定位策略未初始化，请先在「UI自动化测试→元素管理」初始化定位策略'},
                status=status.HTTP_400_BAD_REQUEST
            )

        priority_map = {'critical': 'high', 'high': 'high', 'medium': 'medium', 'low': 'low'}

        created = []
        for cid in case_ids:
            try:
                src = LibTestCase.objects.get(id=cid)
            except LibTestCase.DoesNotExist:
                continue

            # 同项目同名用例自动加序号后缀，避免被跳过
            base_name = src.title
            name_suffix = ''
            existing_names = set(TestCase.objects.filter(project=ui_project).values_list('name', flat=True))
            if base_name in existing_names:
                for i in range(1, 100):
                    candidate = f"{base_name}({i})"
                    if candidate not in existing_names:
                        name_suffix = f"({i})"
                        break

            desc_parts = []
            if src.preconditions:
                desc_parts.append(f"前置条件：{src.preconditions}")
            if src.expected_result:
                desc_parts.append(f"预期结果：{src.expected_result}")
            if src.description:
                desc_parts.append(src.description)

            ui_case = TestCase.objects.create(
                name=base_name + name_suffix,
                description="\n".join(desc_parts),
                project=ui_project,
                priority=priority_map.get(src.priority, 'medium'),
                status='draft',
                created_by=request.user
            )

            # 收集步骤：优先用结构化 step_details，否则解析 steps 文本
            step_objs = list(src.step_details.all().order_by('step_number'))
            if not step_objs and src.steps:
                step_objs = [
                    type('S', (), {'action': line.strip(), 'expected': '', 'step_number': i + 1})()
                    for i, line in enumerate(l for l in src.steps.splitlines() if l.strip())
                ]

            step_num = 1

            # === Appium 模式：插入启动 App 步骤 ===
            if mode == 'appium':
                TestCaseStep.objects.create(
                    test_case=ui_case, step_number=step_num,
                    action_type='launch_app',
                    description='启动应用',
                    wait_time=2000,
                )
                step_num += 1

            # 预创建高频元素（仅 appium 模式）
            def get_sure_btn():
                return Element.objects.get_or_create(
                    project=ui_project,
                    name='确认按钮',
                    defaults={
                        'locator_strategy': default_strategy,
                        'locator_value': 'com.youloft.calendar:id/dc_sureBtn',
                        'element_type': 'BUTTON',
                    }
                )[0]

            for s in step_objs:
                action_text = getattr(s, 'action', '') or ''
                expected_text = getattr(s, 'expected', '') or ''

                # === Appium 模式：滑动模式解析 ===
                if mode == 'appium':
                    swipe_pattern = parse_swipe_pattern(action_text)
                    if swipe_pattern:
                        wheel_type, times = swipe_pattern
                        coords = get_wheel_coords().get(wheel_type, (585, 2228, 585, 2078))
                        swipe_input = f"{coords[0]},{coords[1]},{coords[2]},{coords[3]}"
                        wheel_label = {"month":"月","year":"年","day":"日"}.get(wheel_type, "月")
                        for i in range(times):
                            TestCaseStep.objects.create(
                                test_case=ui_case, step_number=step_num,
                                action_type='swipe',
                                description=f'在{wheel_label}滚轮上滑动1个{wheel_label}({i+1}/{times})',
                                input_value=swipe_input,
                                wait_time=500,
                            )
                            step_num += 1
                        sure_btn = get_sure_btn()
                        TestCaseStep.objects.create(
                            test_case=ui_case, step_number=step_num,
                            action_type='click', element=sure_btn,
                            description='点击确认按钮，关闭选择器',
                        )
                        step_num += 1
                        continue

                # 通用步骤生成（Web 和 Appium 共用）
                atype = infer_appium_action_type(action_text) if mode == 'appium' else _infer_web_action_type(action_text)

                matched_strategy, matched_value = smart_match_locator(action_text)
                elem = Element.objects.create(
                    project=ui_project,
                    name=(action_text[:50] or f'步骤{step_num}')[:50],
                    locator_strategy=LocatorStrategy.objects.filter(name=matched_strategy.upper()).first() if matched_strategy else default_strategy,
                    locator_value=matched_value if matched_value else ('TODO_待补充元素定位器' if mode == 'web' else 'TODO_待补充控件定位器'),
                    element_type=('INPUT' if atype in ('fill', 'input') else 'TEXT' if atype == 'assert' else 'BUTTON'),
                    description=action_text
                )
                TestCaseStep.objects.create(
                    test_case=ui_case,
                    step_number=step_num,
                    action_type=atype,
                    element=elem,
                    input_value=extract_step_input_value(action_text),
                    wait_time=1000,
                    assert_type='exists' if atype == 'assert' else '',
                    assert_value=expected_text if atype == 'assert' else '',
                    description=action_text
                )
                step_num += 1

            # 用例级预期结果追加为断言步骤
            if src.expected_result:
                matched_strategy2, matched_value2 = smart_match_locator(src.expected_result or src.title)
                elem = Element.objects.create(
                    project=ui_project,
                    name=f'断言_{src.title[:30]}'[:50],
                    locator_strategy=LocatorStrategy.objects.filter(name=matched_strategy2.upper()).first() if matched_strategy2 else default_strategy,
                    locator_value=matched_value2 if matched_value2 else ('TODO_待补充元素定位器' if mode == 'web' else 'TODO_待补充控件定位器'),
                    element_type='TEXT',
                    description='用例预期结果断言'
                )
                TestCaseStep.objects.create(
                    test_case=ui_case,
                    step_number=step_num,
                    action_type='assert',
                    element=elem,
                    assert_type='textContains',
                    assert_value=src.expected_result[:200],
                    description=f'断言预期结果：{src.expected_result[:100]}'
                )

            log_operation('create', 'test_case', ui_case.id, ui_case.name, request.user)
            created.append({'id': ui_case.id, 'name': ui_case.name})

        return Response({
            'success': True,
            'count': len(created),
            'created': created,
            'message': f'成功转换 {len(created)} 条用例到项目「{ui_project.name}」。请到「UI自动化测试→用例管理」为占位元素回填控件定位器，再选 Appium 引擎执行。'
        })

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        """运行单个测试用例 - 支持选择Playwright或Selenium执行引擎"""
        test_case = self.get_object()

        try:
            # 获取执行引擎选择，默认使用playwright
            engine_type = request.data.get('engine', 'playwright')

            # 创建执行记录
            execution = TestCaseExecution.objects.create(
                test_case=test_case,
                project=test_case.project,
                execution_source='manual',
                status='running',
                engine=engine_type,
                browser=request.data.get('browser', 'chrome'),
                headless=request.data.get('headless', False),
                created_by=request.user,
                started_at=timezone.now()
            )

            # ========== 所有引擎共用的步骤数据（提前构建，避免各分支重复） ==========
            test_steps = list(test_case.steps.all().order_by('step_number'))
            steps_data = []
            for step in test_steps:
                step_data = {
                    'step': step,
                    'action_type': step.action_type,
                    'description': step.description,
                    'input_value': step.input_value,
                    'wait_time': step.wait_time,
                    'assert_type': step.assert_type,
                    'assert_value': step.assert_value,
                    'center_x': step.center_x,
                    'center_y': step.center_y,
                }
                if step.element:
                    step_data['element_data'] = {
                        'locator_strategy': step.element.locator_strategy.name if step.element.locator_strategy else ('css' if engine_type != 'appium' else 'xpath'),
                        'locator_value': step.element.locator_value,
                        'name': step.element.name,
                        'element_id': step.element.id,
                        'wait_timeout': getattr(step.element, 'wait_timeout', None),
                        'force_action': getattr(step.element, 'force_action', False),
                    }
                else:
                    step_data['element_data'] = None
                steps_data.append(step_data)

            # 共享结果容器（Appium / Playwright / Selenium 各分支共用）
            step_results = []
            execution_logs = []
            screenshots = []
            detailed_errors = []
            execution_result = {'status': 'passed', 'error_message': None}

            # 根据引擎类型导入对应的执行引擎
            if engine_type == 'selenium':
                from .selenium_engine import SeleniumTestEngine

                # Selenium 引擎需要预先检查浏览器是否可用
                browser_type = request.data.get('browser', 'chrome')
                is_available, error_msg = SeleniumTestEngine.check_browser_available(browser_type)
                if not is_available:
                    # 浏览器不可用，立即返回错误
                    logger.error(f"Selenium 浏览器检查失败: {error_msg}")
                    execution.status = 'failed'
                    execution.error_message = error_msg
                    execution.execution_logs = f"浏览器检查失败\n\n{error_msg}\n\n建议：\n1. 请确认已安装 {browser_type.capitalize()} 浏览器\n2. 或者尝试使用其他浏览器（Chrome、Firefox、Edge）\n3. 或者使用 Playwright 引擎（支持自动下载浏览器）"
                    execution.finished_at = timezone.now()
                    execution.save()

                    return Response({
                        'success': False,
                        'logs': execution.execution_logs,
                        'screenshots': [],
                        'execution_time': 0,
                        'errors': [{
                            'message': f'{browser_type.capitalize()} 浏览器不可用',
                            'details': error_msg,
                            'step_number': None,
                            'action_type': '浏览器检查',
                            'element': '',
                            'description': '执行前浏览器环境检查'
                        }]
                    }, status=status.HTTP_400_BAD_REQUEST)
            elif engine_type == 'appium':
                # Appium 引擎：使用 Appium 执行 App 自动化测试
                from .appium_engine import AppiumTestEngine
                import threading as thread_mod

                device_id = request.data.get('device_id')
                app_config_id = request.data.get('app_config_id')

                if not device_id or not app_config_id:
                    execution.status = 'failed'
                    execution.error_message = '使用 Appium 引擎时必须选择设备和应用配置'
                    execution.execution_logs = '使用 Appium 引擎时必须选择设备和应用配置'
                    execution.finished_at = timezone.now()
                    execution.save()
                    return Response({
                        'success': False,
                        'logs': execution.execution_logs,
                        'screenshots': [],
                        'execution_time': 0,
                        'errors': [{
                            'message': '缺少必要参数',
                            'details': '使用 Appium 引擎时必须选择设备和应用配置',
                            'step_number': None,
                            'action_type': '参数检查',
                            'element': '',
                            'description': '执行前参数检查'
                        }]
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 加载设备和应用配置（统一使用 app_automation 设备表）
                try:
                    from apps.app_automation.models import AppDevice as AutoAppDevice
                    _raw_device = AutoAppDevice.objects.get(device_id=device_id)
                    app_config = AppConfig.objects.get(id=app_config_id)
                    # 字段映射：app_automation.AppDevice → 执行引擎期望的接口
                    class _DeviceAdapter:
                        def __init__(self, d):
                            self._d = d
                        @property
                        def udid(self): return self._d.device_id
                        @property
                        def platform(self): return 'android'
                        @property
                        def appium_server_url(self): return ''
                        @property
                        def capabilities(self): return {}
                        def __getattr__(self, name): return getattr(self._d, name)
                    device = _DeviceAdapter(_raw_device)
                except Exception:
                    execution.status = 'failed'
                    execution.error_message = f'设备不存在 (device_id: {device_id})'
                    execution.finished_at = timezone.now()
                    execution.save()
                    return Response({'success': False, 'logs': execution.error_message}, status=status.HTTP_400_BAD_REQUEST)
                except AppConfig.DoesNotExist:
                    execution.status = 'failed'
                    execution.error_message = f'应用配置不存在 (ID: {app_config_id})'
                    execution.finished_at = timezone.now()
                    execution.save()
                    return Response({'success': False, 'logs': execution.error_message}, status=status.HTTP_400_BAD_REQUEST)

                # 异步执行 Appium 测试
                def run_appium_test():
                    try:
                        engine_config = {
                            'appium_server_url': device.appium_server_url,
                            'platform': device.platform,
                            'device_udid': device.udid,
                            'app_package': app_config.package_name,
                            'app_activity': app_config.app_activity,
                            'bundle_id': app_config.package_name if device.platform == 'ios' else None,
                            'app_path': app_config.app_path or None,
                        }
                        if device.capabilities:
                            engine_config.update(device.capabilities)

                        app_engine = AppiumTestEngine(**engine_config)
                        # 连接前清理设备端残留的 UiAutomator2 进程
                        if device.udid:
                            import subprocess as _sp
                            try:
                                _sp.run(
                                    ['adb', '-s', device.udid, 'shell', 'am', 'force-stop',
                                     'io.appium.uiautomator2.server'],
                                    capture_output=True, timeout=5,
                                )
                                logger.info(f"执行前已清理设备 {device.udid} 上的残留 UiAutomator2 进程")
                            except Exception:
                                pass
                        app_engine.connect()

                        execution_logs.append(f"========== Appium 引擎初始化 ==========")
                        execution_logs.append(f"✓ Appium 连接成功: {device.platform} 设备 {device.name}")
                        execution_logs.append(f"  应用: {app_config.name}")
                        execution_logs.append(f"  Server: {device.appium_server_url}")
                        execution_logs.append("")

                        if steps_data:
                            execution_logs.append("========== 执行测试步骤 ==========")
                            execution_logs.append(f"共有 {len(steps_data)} 个步骤需要执行")
                            execution_logs.append("")

                            for i, step_info in enumerate(steps_data, 1):
                                execution_logs.append(f"--- 步骤 {i}/{len(steps_data)} ---")
                                execution_logs.append(f"操作: {step_info['action_type']} - {step_info['description']}")

                                # element 字段兼容：录制存储可能是 'element' 或 'element_data'
                                el = step_info.get('element_data') or step_info.get('element')
                                # 自动捕获步骤的坐标可能在顶层
                                if el is None or (not el.get('center_x') and not el.get('center_y')):
                                    cx = step_info.get('center_x')
                                    cy = step_info.get('center_y')
                                    if cx is not None and cy is not None:
                                        el = {'center_x': cx, 'center_y': cy,
                                              'locator_strategy': 'coordinate',
                                              'value': f'{cx},{cy}',
                                              'name': f'坐标({cx},{cy})'}
                                    elif el is None:
                                        el = {}

                                step_data = {
                                    'step_number': i,
                                    'action_type': step_info['action_type'],
                                    'description': step_info['description'],
                                    'input_value': step_info.get('input_value', ''),
                                    'wait_time': step_info.get('wait_time', 0),
                                    'assert_type': step_info.get('assert_type', ''),
                                    'assert_value': step_info.get('assert_value', ''),
                                    'element': el
                                }

                                result = app_engine.execute_step(step_data)
                                step_result_entry = {
                                    'step_number': i,
                                    'action_type': step_info['action_type'],
                                    'description': step_info['description'],
                                    'success': result.get('success', False),
                                    'error': result.get('error', ''),
                                    'screenshot': result.get('screenshot', None)
                                }
                                step_results.append(step_result_entry)

                                if result.get('success'):
                                    execution_logs.append(f"  ✓ 步骤 {i} 执行成功")
                                else:
                                    execution_logs.append(f"  ✗ 步骤 {i} 执行失败: {result.get('error', '')}")
                                    if result.get('screenshot'):
                                        screenshots.append(result['screenshot'])
                                    execution_result['status'] = 'failed'
                                    detailed_errors.append({
                                        'step_number': i,
                                        'action_type': step_info['action_type'],
                                        'element': step_info['element_data']['name'] if step_info.get('element_data') else '',
                                        'message': f'步骤 {i} 执行失败',
                                        'details': result.get('error', ''),
                                        'description': step_info['description']
                                    })
                                    break

                                execution_logs.append("")

                        app_engine.disconnect()
                        execution_logs.append("========== 测试执行完成 ==========")

                        # 更新执行记录
                        execution.execution_logs = '\n'.join(execution_logs)
                        execution.screenshots = screenshots
                        execution.step_results = step_results
                        execution.status = execution_result['status']
                        execution.error_message = execution_result.get('error_message', '')
                        execution.finished_at = timezone.now()
                        execution.save()

                    except Exception as e:
                        error_msg = f"Appium 执行异常: {str(e)}"
                        execution_logs.append(f"✗ {error_msg}")
                        execution.execution_logs = '\n'.join(execution_logs)
                        execution.status = 'failed'
                        execution.error_message = error_msg
                        execution.finished_at = timezone.now()
                        execution.save()

                # 启动后台线程
                thread = thread_mod.Thread(target=run_appium_test)
                thread.daemon = True
                thread.start()

                return Response({
                    'success': True,
                    'message': 'App 自动化测试已启动',
                    'execution_id': execution.id,
                    'engine': 'appium',
                    'device': device.name,
                    'app_config': app_config.name
                })
            elif engine_type == 'airtest':
                # Airtest 引擎：使用 Airtest 直接连接设备执行 App 自动化测试
                from .airtest_engine import AirtestRecordingEngine
                import threading as _thread_mod

                device_id = request.data.get('device_id')
                app_config_id = request.data.get('app_config_id')

                if not device_id or not app_config_id:
                    execution.status = 'failed'
                    execution.error_message = '使用 Airtest 引擎时必须选择设备和应用配置'
                    execution.execution_logs = '使用 Airtest 引擎时必须选择设备和应用配置'
                    execution.finished_at = timezone.now()
                    execution.save()
                    return Response({
                        'success': False,
                        'logs': execution.execution_logs,
                        'screenshots': [],
                        'execution_time': 0,
                        'errors': [{
                            'message': '缺少必要参数',
                            'details': '使用 Airtest 引擎时必须选择设备和应用配置',
                            'step_number': None,
                            'action_type': '参数检查',
                            'element': '',
                            'description': '执行前参数检查'
                        }]
                    }, status=status.HTTP_400_BAD_REQUEST)

                try:
                    from apps.app_automation.models import AppDevice as AutoAppDevice
                    _raw_device = AutoAppDevice.objects.get(device_id=device_id)
                    app_config = AppConfig.objects.get(id=app_config_id)
                    # 字段映射：app_automation.AppDevice → 执行引擎期望的接口
                    class _DeviceAdapter:
                        def __init__(self, d):
                            self._d = d
                        @property
                        def udid(self): return self._d.device_id
                        @property
                        def platform(self): return 'android'
                        @property
                        def appium_server_url(self): return ''
                        @property
                        def capabilities(self): return {}
                        def __getattr__(self, name): return getattr(self._d, name)
                    device = _DeviceAdapter(_raw_device)
                except Exception:
                    execution.status = 'failed'
                    execution.error_message = f'设备不存在 (device_id: {device_id})'
                    execution.finished_at = timezone.now()
                    execution.save()
                    return Response({'success': False, 'logs': execution.error_message}, status=status.HTTP_400_BAD_REQUEST)
                except AppConfig.DoesNotExist:
                    execution.status = 'failed'
                    execution.error_message = f'应用配置不存在 (ID: {app_config_id})'
                    execution.finished_at = timezone.now()
                    execution.save()
                    return Response({'success': False, 'logs': execution.error_message}, status=status.HTTP_400_BAD_REQUEST)

                def run_airtest_test():
                    try:
                        _adb_host = getattr(device, 'adb_host', None) or None
                        at_engine = AirtestRecordingEngine(
                            serial=device.udid,
                            platform=device.platform,
                            app_package=app_config.package_name,
                            wda_url=device.appium_server_url,
                            adb_host=_adb_host,
                        )
                        at_engine.connect()

                        # 启动被测应用
                        try:
                            at_engine.activate_app(app_config.package_name)
                        except Exception:
                            pass
                        time.sleep(1)

                        execution_logs.append("========== Airtest 引擎初始化 ==========")
                        execution_logs.append(f"✓ Airtest 连接成功: {device.platform} 设备 {device.name}")
                        execution_logs.append(f"  应用: {app_config.name}")
                        execution_logs.append(f"  设备UDID: {device.udid}")
                        execution_logs.append("")

                        if steps_data:
                            execution_logs.append("========== 执行测试步骤 ==========")
                            execution_logs.append(f"共有 {len(steps_data)} 个步骤需要执行")
                            execution_logs.append("")

                            for i, step_info in enumerate(steps_data, 1):
                                execution_logs.append(f"--- 步骤 {i}/{len(steps_data)} ---")
                                execution_logs.append(f"操作: {step_info['action_type']} - {step_info['description']}")

                                # element 字段兼容：录制存储可能是 'element' 或 'element_data'
                                el = step_info.get('element_data') or step_info.get('element')
                                # 自动捕获步骤的坐标可能在顶层
                                if el is None or (not el.get('center_x') and not el.get('center_y')):
                                    cx = step_info.get('center_x')
                                    cy = step_info.get('center_y')
                                    if cx is not None and cy is not None:
                                        el = {'center_x': cx, 'center_y': cy,
                                              'locator_strategy': 'coordinate',
                                              'value': f'{cx},{cy}',
                                              'name': f'坐标({cx},{cy})'}
                                    elif el is None:
                                        el = {}

                                step_data = {
                                    'step_number': i,
                                    'action_type': step_info['action_type'],
                                    'description': step_info['description'],
                                    'input_value': step_info.get('input_value', ''),
                                    'wait_time': step_info.get('wait_time', 0),
                                    'assert_type': step_info.get('assert_type', ''),
                                    'assert_value': step_info.get('assert_value', ''),
                                    'element': el
                                }

                                result = at_engine.execute_step(step_data)
                                step_result_entry = {
                                    'step_number': i,
                                    'action_type': step_info['action_type'],
                                    'description': step_info['description'],
                                    'success': result.get('success', False),
                                    'error': result.get('error', ''),
                                    'screenshot': result.get('screenshot', None)
                                }
                                step_results.append(step_result_entry)

                                if result.get('success'):
                                    execution_logs.append(f"  ✓ 步骤 {i} 执行成功")
                                else:
                                    execution_logs.append(f"  ✗ 步骤 {i} 执行失败: {result.get('error', '')}")
                                    if result.get('screenshot'):
                                        screenshots.append(result['screenshot'])
                                    execution_result['status'] = 'failed'
                                    detailed_errors.append({
                                        'step_number': i,
                                        'action_type': step_info['action_type'],
                                        'element': step_info.get('element_data', {}).get('name', '') if step_info.get('element_data') else '',
                                        'message': f'步骤 {i} 执行失败',
                                        'details': result.get('error', ''),
                                        'description': step_info['description']
                                    })
                                    break

                                execution_logs.append("")

                        at_engine.disconnect()
                        execution_logs.append("========== 测试执行完成 ==========")

                        # 更新执行记录
                        execution.execution_logs = '\n'.join(execution_logs)
                        execution.screenshots = screenshots
                        execution.step_results = step_results
                        execution.status = execution_result['status']
                        execution.error_message = execution_result.get('error_message', '')
                        execution.finished_at = timezone.now()
                        execution.save()

                    except Exception as e:
                        error_msg = f"Airtest 执行异常: {str(e)}"
                        execution_logs.append(f"✗ {error_msg}")
                        execution.execution_logs = '\n'.join(execution_logs)
                        execution.status = 'failed'
                        execution.error_message = error_msg
                        execution.finished_at = timezone.now()
                        execution.save()

                _thread_mod.Thread(target=run_airtest_test, daemon=True).start()

                return Response({
                    'success': True,
                    'message': 'Airtest 自动化测试已启动',
                    'execution_id': execution.id,
                    'engine': 'airtest',
                    'device': device.name,
                    'app_config': app_config.name
                })
            else:
                import asyncio
                import threading
                from .playwright_engine import PlaywrightTestEngine

            start_time = time.time()

            # 执行日志头部（Playwright/Selenium 专用，Appium 在闭包内自己写）
            if engine_type != 'appium':
                execution_logs.append(f"测试用例 '{test_case.name}' 开始执行")
                execution_logs.append(f"执行时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
                execution_logs.append(f"执行引擎: {engine_type.upper()}")
                execution_logs.append(f"浏览器: {request.data.get('browser', 'chrome').capitalize()}")
                headless_mode = request.data.get('headless', False)
                mode_text = "无头模式" if headless_mode else "有头模式"
                execution_logs.append(f"执行模式: {mode_text}")
                execution_logs.append(f"执行用户: {request.user.username}")
                execution_logs.append(f"项目基础URL: {test_case.project.base_url}")
                execution_logs.append("")

            # 根据引擎类型选择执行方式
            if engine_type == 'selenium':
                # Selenium同步执行
                def run_test_selenium():
                    """使用Selenium执行测试"""
                    browser_type = request.data.get('browser', 'chrome')
                    headless = request.data.get('headless', False)

                    # 创建Selenium引擎实例
                    engine = SeleniumTestEngine(browser_type=browser_type, headless=headless)

                    try:
                        # 启动浏览器
                        execution_logs.append("========== 初始化浏览器 ==========")
                        try:
                            engine.start()
                            mode_text = "无头模式" if headless else "有头模式"
                            execution_logs.append(f"✓ {browser_type.capitalize()} 浏览器启动成功 (Selenium, {mode_text})")
                            execution_logs.append("")
                        except Exception as browser_error:
                            # 浏览器启动失败
                            execution_logs.append(f"✗ {browser_type.capitalize()} 浏览器启动失败")
                            execution_logs.append(f"  错误: {str(browser_error)}")
                            execution_logs.append("")
                            execution_result['status'] = 'failed'
                            execution_result['error_message'] = f"{browser_type.capitalize()} 浏览器启动失败: {str(browser_error)}"

                            # 添加详细错误信息
                            detailed_errors.append({
                                'step_number': None,
                                'action_type': '浏览器启动',
                                'element': '',
                                'message': f"{browser_type.capitalize()} 浏览器启动失败",
                                'details': str(browser_error),
                                'description': '执行前浏览器启动检查'
                            })

                            return False

                        # 导航到项目基础URL
                        if test_case.project.base_url:
                            execution_logs.append("========== 导航到测试页面 ==========")
                            success, nav_log = engine.navigate(test_case.project.base_url)
                            execution_logs.append(nav_log)
                            execution_logs.append("")

                            if not success:
                                execution_result['status'] = 'failed'
                                execution_result['error_message'] = "导航到测试页面失败"
                                return False

                        if steps_data:
                            execution_logs.append("========== 执行测试步骤 ==========")
                            step_count = len(steps_data)
                            execution_logs.append(f"共有 {step_count} 个步骤需要执行")
                            execution_logs.append("")

                            for i, step_info in enumerate(steps_data, 1):
                                execution_logs.append(f"========== 开始执行步骤 {i}/{step_count} ==========")
                                execution_logs.append(f"步骤 {i}/{step_count}:")

                                step = step_info['step']
                                action_type = step_info['action_type']
                                description = step_info['description']
                                element_data = step_info['element_data']

                                action_type_text = {
                                    'click': '点击',
                                    'tap': '轻触',
                                    'double_tap': '双击',
                                    'long_press': '长按',
                                    'fill': '输入文本',
                                    'input': '输入',
                                    'clear': '清空',
                                    'getText': '获取文本',
                                    'waitFor': '等待元素',
                                    'hover': '悬停',
                                    'scroll': '滚动',
                                    'swipe': '滑动',
                                    'screenshot': '截图',
                                    'assert': '断言',
                                    'wait': '等待',
                                    'switchTab': '切换标签页',
                                    'launch_app': '启动应用',
                                    'close_app': '关闭应用',
                                    'back': '返回',
                                    'home': '主页'
                                }.get(action_type, action_type)
                                execution_logs.append(f"  操作: {action_type_text}")

                                if description:
                                    execution_logs.append(f"  说明: {description}")

                                if element_data:
                                    execution_logs.append(f"  元素: {element_data['name']}")
                                    execution_logs.append(f"  定位器: {element_data['locator_strategy']}={element_data['locator_value']}")
                                else:
                                    execution_logs.append(f"  (此步骤不需要元素)")

                                try:
                                    success, step_log, screenshot_base64 = engine.execute_step(step, element_data or {})
                                    execution_logs.append(f"  {step_log}")
                                    execution_logs.append("")

                                    # 记录步骤执行结果（用于JSON格式）
                                    step_results.append({
                                        'step_number': i,
                                        'action_type': action_type,
                                        'description': description or '',
                                        'success': success,
                                        'error': None if success else step_log,
                                        'screenshot': f'data:image/png;base64,{screenshot_base64}' if screenshot_base64 else None
                                    })

                                    if not success:
                                        logger.info(f"[调试-Selenium] 步骤 {i} 执行失败，设置状态为 failed")
                                        execution_result['status'] = 'failed'
                                        element_info = element_data['name'] if element_data else "未知元素"
                                        execution_result['error_message'] = step_log  # 使用step_log作为错误信息
                                        logger.info(f"[调试-Selenium] execution_result = {execution_result}")

                                        detailed_errors.append({
                                            'step_number': i,
                                            'action_type': action_type_text,
                                            'element': element_info,
                                            'message': f"步骤 {i}/{step_count} 执行失败",
                                            'details': step_log,
                                            'description': description or ''
                                        })

                                        if not screenshot_base64:
                                            screenshot_base64 = engine.capture_screenshot()

                                        if screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i} 失败截图: {description or action_type_text}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                                # 移除 loaded 和 error 字段，让前端自行处理
                                            })
                                            execution_logs.append(f"  📸 失败截图已捕获")

                                        return False

                                    if action_type == 'screenshot' and screenshot_base64:
                                        screenshots.append({
                                            'url': screenshot_base64,
                                            'description': f'步骤 {i}: {description or "手动截图"}',
                                            'step_number': i,
                                            'timestamp': timezone.now().isoformat()
                                            # 移除 loaded 和 error 字段，让前端自行处理
                                        })

                                except Exception as e:
                                    execution_logs.append(f"  ✗ 步骤执行异常: {str(e)}")
                                    import traceback
                                    tb_str = traceback.format_exc()
                                    execution_logs.append(f"  [调试] 异常堆栈:\n{tb_str}")

                                    # 记录步骤执行结果（异常情况）
                                    step_results.append({
                                        'step_number': i,
                                        'action_type': action_type,
                                        'description': description or '',
                                        'success': False,
                                        'error': str(e)
                                    })

                                    execution_result['status'] = 'failed'
                                    execution_result['error_message'] = f"步骤 {i} 执行异常: {str(e)}"

                                    element_info = element_data['name'] if element_data else "未知元素"
                                    detailed_errors.append({
                                        'step_number': i,
                                        'action_type': action_type_text,
                                        'element': element_info,
                                        'message': f"步骤 {i}/{step_count} 执行异常",
                                        'details': f"异常: {str(e)}\n\n堆栈跟踪:\n{tb_str}",
                                        'description': description or ''
                                    })

                                    try:
                                        screenshot_base64 = engine.capture_screenshot()
                                        if screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i} 异常截图: {str(e)}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                                # 移除 loaded 和 error 字段，让前端自行处理
                                            })
                                    except:
                                        pass

                                    return False

                            execution_logs.append(f"========== 执行完成 ({step_count} 个步骤全部通过) ==========")
                            return True
                        else:
                            execution_logs.append("警告: 测试用例没有定义任何步骤")
                            execution_result['status'] = 'failed'
                            execution_result['error_message'] = "测试用例没有定义任何步骤，无法执行"
                            return False

                    finally:
                        execution_logs.append("")
                        execution_logs.append("========== 清理资源 ==========")
                        engine.stop()
                        execution_logs.append("✓ 浏览器已关闭")

                # 在独立线程中运行Selenium测试
                import threading
                test_thread = threading.Thread(target=run_test_selenium)
                test_thread.start()
                test_thread.join()

            else:
                # Playwright异步执行
                def run_test_in_thread():
                    """在独立线程中运行异步测试"""
                    async def run_test():
                        """异步执行测试"""
                        # 根据浏览器类型选择
                        browser_map = {
                            'chrome': 'chromium',
                            'firefox': 'firefox',
                            'safari': 'webkit'
                        }
                        browser_type = browser_map.get(request.data.get('browser', 'chrome'), 'chromium')
                        headless = request.data.get('headless', False)

                        # 创建Playwright引擎实例
                        engine = PlaywrightTestEngine(browser_type=browser_type, headless=headless)

                        try:
                            # 启动浏览器
                            execution_logs.append("========== 初始化浏览器 ==========")
                            await engine.start()
                            mode_text = "无头模式" if headless else "有头模式"
                            execution_logs.append(f"✓ {browser_type.capitalize()} 浏览器启动成功 (Playwright, {mode_text})")
                            execution_logs.append("")

                            # 导航到项目基础URL
                            if test_case.project.base_url:
                                execution_logs.append("========== 导航到测试页面 ==========")
                                success, nav_log = await engine.navigate(test_case.project.base_url)
                                execution_logs.append(nav_log)
                                execution_logs.append("")

                                if not success:
                                    execution_result['status'] = 'failed'
                                    execution_result['error_message'] = "导航到测试页面失败"
                                    return False

                            if steps_data:
                                execution_logs.append("========== 执行测试步骤 ==========")
                                step_count = len(steps_data)
                                execution_logs.append(f"共有 {step_count} 个步骤需要执行")
                                execution_logs.append("")

                                for i, step_info in enumerate(steps_data, 1):
                                    execution_logs.append(f"========== 开始执行步骤 {i}/{step_count} ==========")
                                    execution_logs.append(f"步骤 {i}/{step_count}:")

                                    # 从预先获取的数据中获取信息
                                    step = step_info['step']
                                    action_type = step_info['action_type']
                                    description = step_info['description']
                                    element_data = step_info['element_data']

                                    # 获取操作类型的中文显示
                                    action_choices_dict = dict(TestCaseStep.ACTION_TYPE_CHOICES)
                                    action_type_text = action_choices_dict.get(action_type, action_type)
                                    execution_logs.append(f"  操作: {action_type_text}")

                                    if description:
                                        execution_logs.append(f"  说明: {description}")

                                    if element_data:
                                        execution_logs.append(f"  元素: {element_data['name']}")
                                        execution_logs.append(f"  定位器: {element_data['locator_strategy']}={element_data['locator_value']}")
                                    else:
                                        execution_logs.append(f"  (此步骤不需要元素)")

                                    # 执行步骤
                                    try:
                                        execution_logs.append(f"  [调试] 准备执行步骤...")
                                        success, step_log, screenshot_base64 = await engine.execute_step(step, element_data or {})
                                        execution_logs.append(f"  [调试] 步骤执行完成, success={success}")

                                        execution_logs.append(f"  {step_log}")
                                        execution_logs.append("")

                                        # 记录步骤执行结果（用于JSON格式）
                                        step_results.append({
                                            'step_number': i,
                                            'action_type': action_type,
                                            'description': description or '',
                                            'success': success,
                                            'error': None if success else step_log,
                                            'screenshot': f'data:image/png;base64,{screenshot_base64}' if screenshot_base64 else None
                                        })

                                        # 如果步骤失败,保存截图
                                        if not success:
                                            execution_logs.append(f"  [调试] 检测到步骤失败,准备处理...")
                                            execution_result['status'] = 'failed'

                                            # 获取失败的元素信息
                                            element_info = element_data['name'] if element_data else "未知元素"

                                            execution_result['error_message'] = step_log  # 使用step_log作为错误信息

                                            # 添加详细错误信息
                                            detailed_errors.append({
                                                'step_number': i,
                                                'action_type': action_type_text,
                                                'element': element_info,
                                                'message': f"步骤 {i}/{step_count} 执行失败",
                                                'details': step_log,  # 包含详细的错误日志
                                                'description': description or ''
                                            })

                                            # 如果没有截图,捕获一张
                                            if not screenshot_base64:
                                                screenshot_base64 = await engine.capture_screenshot()

                                        if screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i} 失败截图: {description or action_type_text}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                                # 移除 loaded 和 error 字段，让前端自行处理
                                            })
                                            execution_logs.append(f"  📸 失败截图已捕获")

                                            execution_logs.append(f"  [调试] 步骤失败,准备退出执行...")
                                            return False

                                        # 如果是截图步骤且成功,也保存截图
                                        if action_type == 'screenshot' and screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i}: {description or "手动截图"}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                                # 移除 loaded 和 error 字段，让前端自行处理
                                            })

                                        execution_logs.append(f"  [调试] 步骤 {i} 成功完成,准备执行下一步...")

                                    except Exception as e:
                                        execution_logs.append(f"  ✗ 步骤执行异常: {str(e)}")
                                        execution_logs.append(f"  [调试] 异常详情: {repr(e)}")
                                        import traceback
                                        tb_str = traceback.format_exc()
                                        execution_logs.append(f"  [调试] 异常堆栈:\n{tb_str}")

                                        # 记录步骤执行结果（异常情况）
                                        step_results.append({
                                            'step_number': i,
                                            'action_type': action_type,
                                            'description': description or '',
                                            'success': False,
                                            'error': str(e)
                                        })

                                        execution_result['status'] = 'failed'
                                        execution_result['error_message'] = f"步骤 {i} 执行异常: {str(e)}"

                                        # 添加详细错误信息
                                        element_info = element_data['name'] if element_data else "未知元素"
                                        detailed_errors.append({
                                            'step_number': i,
                                            'action_type': action_type_text,
                                            'element': element_info,
                                            'message': f"步骤 {i}/{step_count} 执行异常",
                                            'details': f"异常: {str(e)}\n\n堆栈跟踪:\n{tb_str}",
                                            'description': description or ''
                                        })

                                        # 捕获异常截图
                                        try:
                                            screenshot_base64 = await engine.capture_screenshot()
                                            if screenshot_base64:
                                                screenshots.append({
                                                    'url': screenshot_base64,
                                                    'description': f'步骤 {i} 异常截图: {str(e)}',
                                                    'step_number': i,
                                                    'timestamp': timezone.now().isoformat()
                                                    # 移除 loaded 和 error 字段，让前端自行处理
                                                })
                                        except:
                                            pass

                                        execution_logs.append(f"  [调试] 发生异常,准备退出执行...")
                                        return False

                                # 所有步骤都成功
                                execution_logs.append(f"========== 执行完成 ({step_count} 个步骤全部通过) ==========")
                                return True

                            else:
                                execution_logs.append("警告: 测试用例没有定义任何步骤")
                                execution_result['status'] = 'failed'
                                execution_result['error_message'] = "测试用例没有定义任何步骤，无法执行"
                                return False

                        finally:
                            # 关闭浏览器
                            execution_logs.append("")
                            execution_logs.append("========== 清理资源 ==========")
                            await engine.stop()
                            execution_logs.append("✓ 浏览器已关闭")

                    # 在新的事件循环中运行测试
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(run_test())
                    finally:
                        loop.close()

                # 在独立线程中运行Playwright测试
                import threading
                test_thread = threading.Thread(target=run_test_in_thread)
                test_thread.start()
                test_thread.join()  # 等待测试完成

            # 计算总执行时间
            total_time = round(time.time() - start_time, 2)
            execution_logs.append("")
            execution_logs.append("执行环境信息:")
            execution_logs.append(f"- 执行引擎: {engine_type.upper()}")
            execution_logs.append(f"- 浏览器: {request.data.get('browser', 'chrome').capitalize()}")
            execution_logs.append(f"- 屏幕分辨率: 1920x1080")
            execution_logs.append(f"- 总执行时间: {total_time}秒")

            if screenshots:
                execution_logs.append(f"- 截图数量: {len(screenshots)} 张")

            # 保存执行日志和截图
            logger.info(f"[调试] 准备保存执行结果: execution_result['status'] = {execution_result['status']}")
            execution.status = execution_result['status']

            # 保存error_message（step_log已经是简洁的错误信息）
            execution.error_message = execution_result['error_message'] or ''

            # 保存步骤执行结果为JSON格式
            execution.execution_logs = json.dumps(step_results, ensure_ascii=False)
            execution.step_results = step_results
            execution.execution_time = total_time
            execution.finished_at = timezone.now()
            execution.screenshots = screenshots
            execution.save()
            logger.info(f"[调试] 执行结果已保存: execution.status = {execution.status}")

            serializer = TestCaseExecutionSerializer(execution)
            # 格式化错误信息为统一的对象格式
            errors = []
            if detailed_errors:
                # 使用详细的错误信息
                for error in detailed_errors:
                    errors.append({
                        'message': error['message'],
                        'details': error['details'],
                        'step_number': error['step_number'],
                        'action_type': error['action_type'],
                        'element': error['element'],
                        'description': error['description']
                    })
            elif execution.error_message:
                # 如果没有详细错误信息，使用简单格式
                errors.append({
                    'message': execution.error_message,
                    'details': ''
                })

            # 记录运行操作
            log_operation('run', 'test_case', test_case.id, test_case.name, request.user)

            return Response({
                'success': execution.status == 'passed',
                'logs': execution.execution_logs,
                'screenshots': screenshots,
                'execution_time': execution.execution_time,
                'errors': errors
            })

        except Exception as e:
            logger.error(f"执行测试用例失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'logs': f"执行失败: {str(e)}\n\n{traceback.format_exc()}",
                'screenshots': [],
                'execution_time': 0,
                'errors': [{'message': str(e), 'stack': traceback.format_exc()}]
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def batch_run(self, request):
        """批量运行测试用例"""
        test_case_ids = request.data.get('test_case_ids', [])
        project_id = request.data.get('project_id')

        if not test_case_ids:
            return Response({'error': '请选择要运行的测试用例'}, status=status.HTTP_400_BAD_REQUEST)

        results = []
        for test_case_id in test_case_ids:
            try:
                test_case = TestCase.objects.get(id=test_case_id)
                # 这里调用单个运行逻辑
                # 简化处理，实际应该异步执行
                results.append({
                    'test_case_id': test_case_id,
                    'test_case_name': test_case.name,
                    'status': 'passed'
                })
            except TestCase.DoesNotExist:
                results.append({
                    'test_case_id': test_case_id,
                    'test_case_name': '未知',
                    'status': 'error',
                    'error': '测试用例不存在'
                })

        return Response({'results': results})

    def perform_destroy(self, instance):
        # 记录操作（在删除前记录）
        log_operation('delete', 'test_case', instance.id, instance.name, self.request.user)
        instance.delete()


class TestCaseStepViewSet(viewsets.ModelViewSet):
    """测试用例步骤视图集"""
    queryset = TestCaseStep.objects.all()
    serializer_class = TestCaseStepSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['step_number']
    ordering = ['step_number']
    filterset_fields = ['test_case', 'action_type']

    def get_queryset(self):
        # 只显示用户有权限访问的测试用例的步骤
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        accessible_test_cases = TestCase.objects.filter(project__in=accessible_projects)
        return TestCaseStep.objects.filter(test_case__in=accessible_projects)


class TestCaseExecutionViewSet(viewsets.ModelViewSet):
    """测试用例执行记录视图集"""
    queryset = TestCaseExecution.objects.all().select_related(
        'test_case', 'project', 'test_suite', 'executed_by'
    )
    serializer_class = TestCaseExecutionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['test_case__name', 'error_message']
    ordering_fields = ['created_at', 'started_at', 'finished_at', 'status']
    ordering = ['-created_at']
    filterset_fields = ['project', 'test_suite', 'test_case', 'status', 'execution_source']
    pagination_class = StandardPagination

    def get_queryset(self):
        # 只显示用户有权限访问的项目的执行记录
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return TestCaseExecution.objects.filter(
            project__in=accessible_projects
        ).select_related(
            'test_case', 'project', 'test_suite', 'created_by'
        )

    def perform_destroy(self, instance):
        # 记录操作
        name = instance.test_case.name if instance.test_case else f"执行记录#{instance.id}"
        log_operation('delete', 'report', instance.id, name, self.request.user)
        instance.delete()

    @action(detail=False, methods=['post'], url_path='batch-delete')
    def batch_delete(self, request):
        """批量删除执行记录"""
        ids = request.data.get('ids', [])
        if not ids:
            return Response({'error': '未提供要删除的记录ID'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 确保只能删除有权限的记录
        queryset = self.get_queryset()
        deleted_count, _ = queryset.filter(id__in=ids).delete()
        
        return Response({'message': f'成功删除 {deleted_count} 条记录'})




class OperationRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """操作记录视图集（只读）"""
    queryset = OperationRecord.objects.all()
    serializer_class = OperationRecordSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['operation_type', 'resource_type', 'user']

    def get_queryset(self):
        # 返回最近的操作记录，按创建时间倒序
        # 过滤掉AI智能模式相关的操作记录
        queryset = OperationRecord.objects.exclude(
            resource_type__in=['ai_case', 'ai_execution']
        ).order_by('-created_at')

        # 支持通过查询参数限制返回数量
        limit = self.request.query_params.get('limit', None)
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass

        return queryset


# ==================== 定时任务和通知相关视图 ====================

class UiScheduledTaskViewSet(viewsets.ModelViewSet):
    """UI定时任务视图集"""
    queryset = UiScheduledTask.objects.all()
    serializer_class = UiScheduledTaskSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['task_type', 'status', 'trigger_type', 'project']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'next_run_time', 'last_run_time']
    ordering = ['-created_at']

    def get_queryset(self):
        """只显示用户有权限访问的项目的定时任务"""
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        return UiScheduledTask.objects.filter(project__in=accessible_projects)

    def perform_create(self, serializer):
        """创建定时任务"""
        instance = serializer.save(created_by=self.request.user)
        log_operation('create', 'scheduled_task', instance.id, instance.name, self.request.user)

    def perform_update(self, serializer):
        """更新定时任务"""
        instance = serializer.save()
        log_operation('edit', 'scheduled_task', instance.id, instance.name, self.request.user)

    def perform_destroy(self, instance):
        """删除定时任务"""
        log_operation('delete', 'scheduled_task', instance.id, instance.name, self.request.user)
        instance.delete()

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """暂停定时任务"""
        task = self.get_object()
        task.status = 'PAUSED'
        task.save()
        return Response({'message': '任务已暂停', 'status': task.status})

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """恢复定时任务"""
        task = self.get_object()
        task.status = 'ACTIVE'
        task.next_run_time = task.calculate_next_run()
        task.save()
        return Response({'message': '任务已恢复', 'status': task.status})

    @action(detail=True, methods=['post'])
    def run_now(self, request, pk=None):
        """立即运行任务"""
        task = self.get_object()

        try:
            # 更新任务执行时间和次数
            task.last_run_time = timezone.now()
            task.total_runs += 1
            # 重新计算下次运行时间
            task.next_run_time = task.calculate_next_run()
            task.save()

            # 根据任务类型执行不同的逻辑
            if task.task_type == 'TEST_SUITE':
                # 执行测试套件
                if not task.test_suite:
                    return Response({
                        'error': '该任务未配置测试套件'
                    }, status=status.HTTP_400_BAD_REQUEST)

                test_suite = task.test_suite
                test_case_count = test_suite.suite_test_cases.count()

                if test_case_count == 0:
                    return Response({
                        'error': '该测试套件未包含任何测试用例，无法执行'
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 更新套件执行状态
                test_suite.execution_status = 'running'
                test_suite.save()

                # 在后台线程中执行测试
                import threading
                from .test_executor import TestExecutor

                def run_test():
                    try:
                        executor = TestExecutor(
                            test_suite=test_suite,
                            engine=task.engine,
                            browser=task.browser,
                            headless=task.headless,
                            executed_by=task.created_by
                        )
                        executor.run()

                        # 更新任务执行结果
                        task.successful_runs += 1
                        task.last_result = {'status': 'success', 'message': '测试套件执行成功'}
                        task.error_message = ''
                        task.save()

                        # 发送成功通知
                        self._send_task_notification(task, success=True)

                    except Exception as e:
                        task.failed_runs += 1
                        task.last_result = {'status': 'failed', 'message': str(e)}
                        task.error_message = str(e)
                        test_suite.execution_status = 'failed'
                        test_suite.save()
                        task.save()

                        # 发送失败通知
                        self._send_task_notification(task, success=False)

                # 启动后台线程执行测试
                thread = threading.Thread(target=run_test)
                thread.daemon = True
                thread.start()

                log_operation('run', 'scheduled_task', task.id, task.name, request.user)

                return Response({
                    'message': '测试套件开始执行',
                    'task_id': task.id,
                    'task_name': task.name,
                    'test_suite': test_suite.name,
                    'test_case_count': test_case_count,
                    'engine': task.engine,
                    'browser': task.browser,
                    'headless': task.headless
                }, status=status.HTTP_200_OK)

            elif task.task_type == 'TEST_CASE':
                # 执行测试用例
                if not task.test_cases or len(task.test_cases) == 0:
                    return Response({
                        'error': '该任务未配置测试用例'
                    }, status=status.HTTP_400_BAD_REQUEST)

                test_case_ids = task.test_cases
                test_cases = TestCase.objects.filter(id__in=test_case_ids)
                test_case_count = test_cases.count()

                if test_case_count == 0:
                    return Response({
                        'error': '找不到配置的测试用例'
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 在后台线程中执行测试用例
                import threading

                def run_test_cases():
                    """在后台线程中执行测试用例"""
                    success_count = 0
                    failed_count = 0

                    try:
                        for test_case in test_cases:
                            # 创建执行记录
                            execution = TestCaseExecution.objects.create(
                                test_case=test_case,
                                project=task.project,
                                execution_source='scheduled',
                                status='running',
                                engine=task.engine,
                                browser=task.browser,
                                headless=task.headless,
                                created_by=task.created_by,
                                started_at=timezone.now()
                            )

                            # 实际执行测试用例
                            try:
                                logger.info(f"开始执行定时任务的测试用例: {test_case.name} (ID: {test_case.id})")

                                start_time = time.time()

                                # 获取测试用例的所有步骤
                                test_steps = list(test_case.steps.all().order_by('step_number'))

                                # 预先获取所有步骤的数据
                                steps_data = []
                                for step in test_steps:
                                    step_data = {
                                        'step': step,
                                        'action_type': step.action_type,
                                        'description': step.description,
                                        'input_value': step.input_value,
                                        'wait_time': step.wait_time,
                                        'assert_type': step.assert_type,
                                        'assert_value': step.assert_value,
                                    }

                                    if step.element:
                                        step_data['element_data'] = {
                                            'locator_strategy': step.element.locator_strategy.name if step.element.locator_strategy else 'css',
                                            'locator_value': step.element.locator_value,
                                            'name': step.element.name,
                                            'wait_timeout': step.element.wait_timeout,
                                            'force_action': step.element.force_action
                                        }
                                    else:
                                        step_data['element_data'] = None

                                    steps_data.append(step_data)

                                # 存储步骤执行结果和截图
                                step_results = []
                                screenshots = []
                                execution_logs = []
                                execution_result = {'status': 'passed', 'error_message': None}

                                # 根据引擎类型执行
                                if task.engine == 'selenium':
                                    from .selenium_engine import SeleniumTestEngine

                                    # 检查浏览器是否可用
                                    is_available, error_msg = SeleniumTestEngine.check_browser_available(task.browser)
                                    if not is_available:
                                        execution.status = 'failed'
                                        execution.error_message = error_msg
                                        execution.execution_logs = json.dumps([{
                                            'step_number': 0,
                                            'action_type': '浏览器检查',
                                            'description': '执行前浏览器环境检查',
                                            'success': False,
                                            'error': error_msg
                                        }], ensure_ascii=False)
                                        execution.finished_at = timezone.now()
                                        execution.save()
                                        failed_count += 1
                                        continue

                                    # 创建Selenium引擎实例并执行
                                    engine = SeleniumTestEngine(browser_type=task.browser, headless=task.headless)

                                    try:
                                        # 启动浏览器
                                        engine.start()
                                        execution_logs.append("✓ 浏览器启动成功")

                                        # 导航到项目基础URL
                                        if test_case.project.base_url:
                                            success, nav_log = engine.navigate(test_case.project.base_url)
                                            execution_logs.append(nav_log)
                                            if not success:
                                                execution_result['status'] = 'failed'
                                                execution_result['error_message'] = "导航到测试页面失败"
                                                raise Exception("导航到测试页面失败")

                                        # 执行测试步骤
                                        for i, step_info in enumerate(steps_data, 1):
                                            step = step_info['step']
                                            action_type = step_info['action_type']
                                            element_data = step_info['element_data']

                                            success, step_log, screenshot_base64 = engine.execute_step(step, element_data or {})

                                            step_results.append({
                                                'step_number': i,
                                                'action_type': action_type,
                                                'description': step_info['description'] or '',
                                                'success': success,
                                                'error': None if success else step_log,
                                                'screenshot': f'data:image/png;base64,{screenshot_base64}' if screenshot_base64 else None
                                            })

                                            if not success:
                                                execution_result['status'] = 'failed'
                                                execution_result['error_message'] = step_log

                                                if not screenshot_base64:
                                                    screenshot_base64 = engine.capture_screenshot()

                                                if screenshot_base64:
                                                    screenshots.append({
                                                        'url': screenshot_base64,
                                                        'description': f'步骤 {i} 失败截图',
                                                        'step_number': i,
                                                        'timestamp': timezone.now().isoformat()
                                                    })

                                                break

                                            if action_type == 'screenshot' and screenshot_base64:
                                                screenshots.append({
                                                    'url': screenshot_base64,
                                                    'description': f'步骤 {i}: {step_info["description"] or "手动截图"}',
                                                    'step_number': i,
                                                    'timestamp': timezone.now().isoformat()
                                                })

                                    finally:
                                        engine.stop()

                                else:  # Playwright
                                    import asyncio
                                    from asgiref.sync import sync_to_async
                                    from .playwright_engine import PlaywrightTestEngine

                                    async def run_playwright_test():
                                        browser_map = {
                                            'chrome': 'chromium',
                                            'firefox': 'firefox',
                                            'safari': 'webkit'
                                        }
                                        browser_type = browser_map.get(task.browser, 'chromium')

                                        engine = PlaywrightTestEngine(browser_type=browser_type, headless=task.headless)

                                        try:
                                            # 启动浏览器
                                            await engine.start()
                                            execution_logs.append("✓ 浏览器启动成功")

                                            # 获取项目基础URL（同步操作）
                                            base_url = await sync_to_async(lambda: test_case.project.base_url)()

                                            # 导航到项目基础URL
                                            if base_url:
                                                success, nav_log = await engine.navigate(base_url)
                                                execution_logs.append(nav_log)
                                                if not success:
                                                    execution_result['status'] = 'failed'
                                                    execution_result['error_message'] = "导航到测试页面失败"
                                                    return False

                                            # 执行测试步骤
                                            for i, step_info in enumerate(steps_data, 1):
                                                step = step_info['step']
                                                action_type = step_info['action_type']
                                                element_data = step_info['element_data']

                                                success, step_log, screenshot_base64 = await engine.execute_step(step, element_data or {})

                                                step_results.append({
                                                    'step_number': i,
                                                    'action_type': action_type,
                                                    'description': step_info['description'] or '',
                                                    'success': success,
                                                    'error': None if success else step_log,
                                                    'screenshot': f'data:image/png;base64,{screenshot_base64}' if screenshot_base64 else None
                                                })

                                                if not success:
                                                    execution_result['status'] = 'failed'
                                                    execution_result['error_message'] = step_log

                                                    if not screenshot_base64:
                                                        screenshot_base64 = await engine.capture_screenshot()

                                                    if screenshot_base64:
                                                        screenshots.append({
                                                            'url': screenshot_base64,
                                                            'description': f'步骤 {i} 失败截图',
                                                            'step_number': i,
                                                            'timestamp': timezone.now().isoformat()
                                                        })

                                                    return False

                                                if action_type == 'screenshot' and screenshot_base64:
                                                    screenshots.append({
                                                        'url': screenshot_base64,
                                                        'description': f'步骤 {i}: {step_info["description"] or "手动截图"}',
                                                        'step_number': i,
                                                        'timestamp': timezone.now().isoformat()
                                                    })

                                            return True

                                        finally:
                                            await engine.stop()

                                    # 在新的事件循环中运行Playwright测试
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    try:
                                        loop.run_until_complete(run_playwright_test())
                                    finally:
                                        loop.close()

                                # 计算执行时间
                                total_time = round(time.time() - start_time, 2)

                                # 保存执行结果
                                execution.status = execution_result['status']
                                execution.error_message = execution_result['error_message'] or ''
                                execution.execution_logs = json.dumps(step_results, ensure_ascii=False)
                                execution.step_results = step_results
                                execution.execution_time = total_time
                                execution.screenshots = screenshots
                                execution.finished_at = timezone.now()
                                execution.save()

                                if execution.status == 'passed':
                                    success_count += 1
                                    logger.info(f"测试用例 {test_case.name} 执行成功")
                                else:
                                    failed_count += 1
                                    logger.warning(f"测试用例 {test_case.name} 执行失败: {execution.error_message}")

                            except Exception as e:
                                logger.error(f"执行测试用例 {test_case.name} 时发生异常: {str(e)}")
                                execution.status = 'failed'
                                execution.error_message = str(e)
                                execution.finished_at = timezone.now()
                                execution.save()
                                failed_count += 1

                        # 更新任务执行结果
                        if failed_count == 0:
                            task.successful_runs += 1
                            task.last_result = {
                                'status': 'success',
                                'message': f'执行完成: {success_count}个成功',
                                'success_count': success_count,
                                'failed_count': failed_count
                            }
                            task.error_message = ''
                            task.save()

                            # 发送成功通知
                            self._send_task_notification(task, success=True)
                        else:
                            task.failed_runs += 1
                            task.last_result = {
                                'status': 'partial',
                                'message': f'执行完成: {success_count}个成功, {failed_count}个失败',
                                'success_count': success_count,
                                'failed_count': failed_count
                            }
                            task.error_message = f'{failed_count}个测试用例执行失败'
                            task.save()

                            # 发送失败通知
                            self._send_task_notification(task, success=False)

                    except Exception as e:
                        logger.error(f"执行定时任务测试用例时发生异常: {str(e)}")
                        task.failed_runs += 1
                        task.last_result = {'status': 'failed', 'message': str(e)}
                        task.error_message = str(e)
                        task.save()

                        # 发送失败通知
                        self._send_task_notification(task, success=False)

                # 启动后台线程执行测试
                thread = threading.Thread(target=run_test_cases)
                thread.daemon = True
                thread.start()

                log_operation('run', 'scheduled_task', task.id, task.name, request.user)

                return Response({
                    'message': '测试用例开始执行',
                    'task_id': task.id,
                    'task_name': task.name,
                    'test_case_count': test_case_count,
                    'engine': task.engine,
                    'browser': task.browser,
                    'headless': task.headless
                }, status=status.HTTP_200_OK)

            else:
                return Response({
                    'error': '不支持的任务类型'
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f'执行定时任务失败: {str(e)}')
            return Response({
                'error': f'执行失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _send_task_notification(self, task, success):
        """发送任务执行通知"""
        try:
            logger.info(f"准备发送任务 {task.id} 的通知，执行结果: {'成功' if success else '失败'}")

            # 检查是否需要发送通知
            if success and not task.notify_on_success:
                logger.info("任务执行成功但未启用成功通知")
                return

            if not success and not task.notify_on_failure:
                logger.info("任务执行失败但未启用失败通知")
                return

            # 检查通知类型
            if not task.notification_type:
                logger.info("未设置通知类型")
                return

            logger.info(f"通知类型: {task.notification_type}")

            # 根据通知类型发送不同的通知
            if task.notification_type in ['webhook', 'both']:
                logger.info("发送Webhook通知")
                self._send_webhook_notification(task, success)

            if task.notification_type in ['email', 'both']:
                logger.info("发送邮件通知")
                self._send_email_notification(task, success)

        except Exception as e:
            logger.error(f"发送通知失败: {str(e)}", exc_info=True)

    def _send_webhook_notification(self, task, success):
        """发送Webhook通知"""
        try:
            import requests
            import json

            logger.info("=== 开始发送Webhook通知 ===")

            # 使用统一的通知配置
            try:
                from apps.core.models import UnifiedNotificationConfig
                all_webhook_configs = UnifiedNotificationConfig.objects.filter(
                    config_type__in=['webhook_wechat', 'webhook_feishu', 'webhook_dingtalk'],
                    is_active=True
                )
                logger.info("使用统一通知配置 (UnifiedNotificationConfig)")
            except ImportError as e:
                # 如果 core 模块不可用，记录错误并返回
                logger.error(f"无法导入统一通知配置: {e}")
                logger.warning("通知发送失败：无法找到通知配置模块")
                return
            except Exception as e:
                logger.error(f"获取通知配置时出错: {e}")
                return

            all_webhook_bots = []
            for config in all_webhook_configs:
                bots = config.get_webhook_bots()
                if bots:
                    for bot in bots:
                        # 只添加启用了"UI自动化测试"的机器人
                        if bot.get('enabled', True) and bot.get('enable_ui_automation', True):
                            all_webhook_bots.append(bot)
                            logger.info(f"添加机器人: {bot.get('name')} (UI自动化测试已启用)")
                        elif bot.get('enabled', True):
                            logger.info(f"配置中心机器人 {bot.get('name')} 未启用UI自动化测试，跳过")

            if not all_webhook_bots:
                logger.warning("没有找到任何启用的webhook机器人配置")
                return

            logger.info(f"找到 {len(all_webhook_bots)} 个启用的webhook机器人配置")

            # 准备通知内容
            status_text = '成功' if success else '失败'
            task_type_text = '测试套件执行' if task.task_type == 'TEST_SUITE' else '测试用例执行'

            # 获取最后执行结果的详细信息
            last_result = task.last_result or {}
            result_message = last_result.get('message', '')
            success_count = last_result.get('success_count', 0)
            failed_count = last_result.get('failed_count', 0)

            # 为不同的机器人平台准备消息格式
            for bot in all_webhook_bots:
                if not bot.get('enabled', True) or not bot.get('webhook_url'):
                    logger.info(f"跳过未启用或无URL的机器人: {bot.get('name', 'Unknown')}")
                    continue

                bot_type = bot.get('type', 'unknown')
                webhook_url = bot['webhook_url']
                logger.info(f"发送通知到 {bot_type} 机器人: {bot.get('name', 'Unknown')}")

                # 构造详细内容
                # 转换执行时间到本地时区
                local_run_time = timezone.localtime(task.last_run_time).strftime('%Y-%m-%d %H:%M:%S') if task.last_run_time else '未知'
                detail_content = f"""任务名称: {task.name}

执行状态: {status_text}

执行时间: {local_run_time}

任务类型: {task_type_text}

执行引擎: {task.engine.upper()}

浏览器: {task.browser.capitalize()}"""

                if result_message:
                    detail_content += f"\n\n执行结果: {result_message}"

                if success_count > 0 or failed_count > 0:
                    detail_content += f"\n\n成功: {success_count} 个，失败: {failed_count} 个"

                # 根据机器人类型构造消息格式
                if bot_type == 'wechat':  # 企业微信
                    message_data = {
                        "msgtype": "markdown",
                        "markdown": {
                            "content": f"""**UI自动化定时任务执行{status_text}**

{detail_content}"""
                        }
                    }
                elif bot_type == 'feishu':  # 飞书
                    message_data = {
                        "msg_type": "interactive",
                        "card": {
                            "elements": [{
                                "tag": "div",
                                "text": {
                                    "content": f"**UI自动化定时任务执行{status_text}**\n\n{detail_content}",
                                    "tag": "lark_md"
                                }
                            }],
                            "header": {
                                "title": {
                                    "content": f"UI自动化定时任务执行{status_text}",
                                    "tag": "plain_text"
                                },
                                "template": "green" if success else "red"
                            }
                        }
                    }
                elif bot_type == 'dingtalk':  # 钉钉
                    message_data = {
                        "msgtype": "markdown",
                        "markdown": {
                            "title": f"UI自动化定时任务执行{status_text}",
                            "text": f"""**UI自动化定时任务执行{status_text}**

{detail_content}"""
                        }
                    }

                    # 钉钉机器人签名验证
                    secret = bot.get('secret')
                    if secret:
                        import time
                        import hmac
                        import hashlib
                        import base64
                        import urllib.parse

                        timestamp = str(round(time.time() * 1000))
                        string_to_sign = f'{timestamp}\n{secret}'
                        string_to_sign_enc = string_to_sign.encode('utf-8')
                        secret_enc = secret.encode('utf-8')
                        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
                        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))

                        # 在URL中添加签名参数
                        if '?' in webhook_url:
                            webhook_url += f'&timestamp={timestamp}&sign={sign}'
                        else:
                            webhook_url += f'?timestamp={timestamp}&sign={sign}'
                else:
                    logger.warning(f"未知的机器人类型: {bot_type}")
                    continue

                # 发送webhook请求
                try:
                    logger.info(f"发送请求到: {webhook_url}")
                    logger.info(f"消息数据: {json.dumps(message_data, ensure_ascii=False, indent=2)}")

                    response = requests.post(
                        webhook_url,
                        json=message_data,
                        headers={'Content-Type': 'application/json'},
                        timeout=10
                    )

                    logger.info(f"响应状态码: {response.status_code}")
                    logger.info(f"响应内容: {response.text}")

                    if response.status_code == 200:
                        logger.info(f"成功发送通知到 {bot.get('name', 'Unknown')}")

                        # 记录通知日志
                        UiNotificationLog.objects.create(
                            task=task,
                            task_name=task.name,
                            task_type=task.task_type,
                            notification_type='task_execution',
                            sender_name='系统Webhook通知',
                            sender_email='system@notification.com',
                            recipient_info=[{'name': bot.get('name', 'Unknown'), 'webhook_url': webhook_url}],
                            webhook_bot_info=bot,
                            notification_content=json.dumps(message_data, ensure_ascii=False),
                            status='success',
                            response_info={'status_code': response.status_code, 'response': response.text},
                            sent_at=timezone.now()
                        )
                    else:
                        logger.error(f"发送通知失败，状态码: {response.status_code}, 响应: {response.text}")

                        # 记录失败日志
                        UiNotificationLog.objects.create(
                            task=task,
                            task_name=task.name,
                            task_type=task.task_type,
                            notification_type='task_execution',
                            sender_name='系统Webhook通知',
                            sender_email='system@notification.com',
                            recipient_info=[{'name': bot.get('name', 'Unknown'), 'webhook_url': webhook_url}],
                            webhook_bot_info=bot,
                            notification_content=json.dumps(message_data, ensure_ascii=False),
                            status='failed',
                            error_message=f'HTTP {response.status_code}: {response.text}',
                            response_info={'status_code': response.status_code, 'response': response.text}
                        )

                except requests.exceptions.RequestException as e:
                    logger.error(f"发送webhook请求失败: {str(e)}")

                    # 记录失败日志
                    UiNotificationLog.objects.create(
                        task=task,
                        task_name=task.name,
                        task_type=task.task_type,
                        notification_type='task_execution',
                        sender_name='系统Webhook通知',
                        sender_email='system@notification.com',
                        recipient_info=[{'name': bot.get('name', 'Unknown'), 'webhook_url': webhook_url}],
                        webhook_bot_info=bot,
                        notification_content=json.dumps(message_data, ensure_ascii=False),
                        status='failed',
                        error_message=str(e)
                    )

        except Exception as e:
            logger.error(f"发送Webhook通知失败: {str(e)}", exc_info=True)

    def _send_email_notification(self, task, success):
        """发送邮件通知"""
        try:
            from django.core.mail import send_mail
            from django.conf import settings

            logger.info("=== 开始发送邮件通知 ===")

            # 获取收件人列表
            recipients = []
            if task.notify_emails:
                if isinstance(task.notify_emails, list):
                    recipients = task.notify_emails
                else:
                    recipients = [task.notify_emails]

            if not recipients:
                logger.warning("没有找到任何邮件收件人")
                return

            # 准备邮件内容
            status_text = '成功' if success else '失败'
            task_type_text = '测试套件执行' if task.task_type == 'TEST_SUITE' else '测试用例执行'

            subject = f"UI自动化定时任务执行{status_text}: {task.name}"

            last_result = task.last_result or {}
            result_message = last_result.get('message', '')

            # 转换执行时间到本地时区
            local_run_time = timezone.localtime(task.last_run_time).strftime('%Y-%m-%d %H:%M:%S') if task.last_run_time else '未知'

            message = f"""
任务名称: {task.name}
执行状态: {status_text}
执行时间: {local_run_time}
任务类型: {task_type_text}
执行引擎: {task.engine.upper()}
浏览器: {task.browser.capitalize()}

执行结果:
{result_message if result_message else '无详细信息'}

错误信息:
{task.error_message if task.error_message else '无错误信息'}
            """

            # 发送邮件
            from_email = settings.DEFAULT_FROM_EMAIL
            logger.info(f"准备发送邮件，发件人: {from_email}, 收件人: {recipients}")

            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=recipients,
                fail_silently=False,
            )
            logger.info("邮件发送成功")

            # 记录通知日志
            UiNotificationLog.objects.create(
                task=task,
                task_name=task.name,
                task_type=task.task_type,
                notification_type='task_execution',
                sender_name='系统邮件通知',
                sender_email=from_email,
                recipient_info=[{'email': email} for email in recipients],
                notification_content=message,
                status='success',
                sent_at=timezone.now()
            )

        except Exception as e:
            logger.error(f"发送邮件通知失败: {str(e)}", exc_info=True)

            # 记录失败日志
            try:
                UiNotificationLog.objects.create(
                    task=task,
                    task_name=task.name,
                    task_type=task.task_type,
                    notification_type='task_execution',
                    sender_name='系统邮件通知',
                    sender_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_info=[{'email': email} for email in recipients] if recipients else [],
                    notification_content=f"发送邮件通知失败: {str(e)}",
                    status='failed',
                    error_message=str(e)
                )
            except:
                pass


class UiNotificationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """UI通知日志视图集（只读）"""
    queryset = UiNotificationLog.objects.all()
    serializer_class = UiNotificationLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'notification_type']
    search_fields = ['task_name', 'notification_content']
    ordering_fields = ['created_at', 'sent_at']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """重试发送通知"""
        log = self.get_object()
        if log.status == 'failed':
            # 这里应该触发实际的重试逻辑
            log.retry_count += 1
            log.is_retried = True
            log.save()
            return Response({'message': '通知已加入重试队列'})
        return Response({'error': '只能重试失败的通知'}, status=status.HTTP_400_BAD_REQUEST)


class UiTaskNotificationSettingViewSet(viewsets.ModelViewSet):
    """UI任务通知设置视图集"""
    queryset = UiTaskNotificationSetting.objects.all()
    serializer_class = UiTaskNotificationSettingSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['task', 'is_enabled', 'notification_type']


class AICaseViewSet(viewsets.ModelViewSet):
    queryset = AICase.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = AICaseSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'description', 'task_description']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        # 返回用户有权限的项目下的AI用例，以及没有关联项目的AI用例
        return AICase.objects.filter(
            models.Q(project__in=accessible_projects) | models.Q(project__isnull=True)
        ).distinct()

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()

    @action(detail=False, methods=['post'], url_path='import-from-generated')
    def import_from_generated(self, request):
        """将AI生成的测试用例（需求分析模块的 TestCaseGenerationTask）批量转换为UI自动化AI用例(AICase)，转换后可直接执行"""
        from apps.requirement_analysis.models import TestCaseGenerationTask

        task_id = request.data.get('task_id')
        if not task_id:
            return Response({'error': '缺少 task_id 参数'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            task = TestCaseGenerationTask.objects.get(task_id=task_id)
        except TestCaseGenerationTask.DoesNotExist:
            return Response({'error': '未找到对应的生成任务'}, status=status.HTTP_404_NOT_FOUND)

        if not task.final_test_cases:
            return Response({'error': '该任务没有最终生成的测试用例'}, status=status.HTTP_404_NOT_FOUND)

        # 支持只转换前端勾选的指定用例；未指定 cases 时转换全部
        selected_cases = request.data.get('cases')
        if selected_cases is not None:
            if not isinstance(selected_cases, list) or len(selected_cases) == 0:
                return Response({'error': 'cases 为空，请至少选择一条用例'}, status=status.HTTP_400_BAD_REQUEST)
            test_cases = selected_cases
        else:
            test_cases = self._parse_generation_task_cases(task.final_test_cases)
            if not test_cases:
                # 解析失败时，将整个内容作为一个 AICase 导入
                ai_case = AICase.objects.create(
                    name=task.title or f'AI生成用例-{task.task_id}',
                    description=f'由AI生成任务导入（{task.task_id}），原始文本模式',
                    task_description=f"任务标题：{task.title or '未命名'}\n\n{task.final_test_cases}",
                    created_by=request.user
                )
                return Response({
                    'message': '已将全部测试用例内容导入为1条UI自动化AI用例（因无法自动拆分，整段文本作为任务描述）',
                    'created_ids': [ai_case.id],
                    'count': 1,
                    'mode': 'raw'
                }, status=status.HTTP_201_CREATED)

        created_ids = []
        for idx, case in enumerate(test_cases):
            scenario = case.get('scenario', case.get('title', f'用例{idx+1}'))
            precondition = case.get('precondition', '')
            steps = case.get('steps', case.get('test_steps', ''))
            expected = case.get('expected', case.get('expected_result', ''))
            priority = case.get('priority', '')

            task_description = (
                f"任务目标：{scenario}\n"
                f"前置条件：{precondition or '无'}\n"
                f"测试步骤：\n{steps or '无'}\n"
                f"预期结果：{expected or '无'}"
            )
            case_id = case.get('caseId', str(idx + 1))
            description = f'由AI生成任务导入（{task.task_id}/{case_id}）'
            if priority:
                description += f'，优先级 {priority}'

            ai_case = AICase.objects.create(
                name=scenario,
                description=description,
                task_description=task_description,
                created_by=request.user
            )
            created_ids.append(ai_case.id)

        return Response({
            'message': f'成功导入 {len(created_ids)} 条AI生成用例为UI自动化AI用例',
            'created_ids': created_ids,
            'count': len(created_ids)
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def _parse_generation_task_cases(content):
        """解析 TestCaseGenerationTask.final_test_cases 文本，返回用例列表"""
        import re
        if not content or not content.strip():
            return []

        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)
        cases = []

        # 表格格式
        if '|' in clean:
            lines = [l.strip() for l in clean.split('\n') if l.strip() and '|' in l]
            rows = []
            for line in lines:
                cells = [c.strip() for c in line.split('|')]
                while cells and cells[0] == '':
                    cells = cells[1:]
                while cells and cells[-1] == '':
                    cells.pop()
                if len(cells) > 1:
                    rows.append(cells)
            if len(rows) >= 2:
                headers = [h.lower() for h in rows[0]]
                for row in rows[1:]:
                    tc = {}
                    for i, h in enumerate(headers):
                        v = row[i] if i < len(row) else ''
                        if any(k in h for k in ['编号','id','序号']):
                            tc['caseId'] = v
                        elif any(k in h for k in ['场景','标题','名称','title','目标']):
                            tc['scenario'] = v
                        elif any(k in h for k in ['前置','前提','precondition']):
                            tc['precondition'] = v
                        elif any(k in h for k in ['步骤','step']):
                            tc['steps'] = v
                        elif any(k in h for k in ['预期','结果','expected','result']):
                            tc['expected'] = v
                        elif 'priority' in h or '优先级' in h:
                            tc['priority'] = v
                    if tc.get('scenario') or tc.get('steps'):
                        cases.append(tc)
                return cases

        # 文本格式
        lines = clean.split('\n')
        current = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            is_start = (
                '测试用例' in line or 'Test Case' in line
                or bool(re.match(r'^\d+[\.\)、]', line))
                or line.startswith(('一、','二、','三、','四、','五、'))
            )
            if is_start:
                if current:
                    cases.append(current)
                title = re.sub(r'^\d+[\.\)、]\s*', '', line.replace('测试用例','').replace('Test Case','').replace(':','').replace('：','').strip())
                current = {'scenario': title}
            elif current:
                for keywords, key in [(['前置条件','前提条件','前置','前提'],'precondition'),
                                      (['测试步骤','操作步骤','执行步骤','步骤'],'steps'),
                                      (['预期结果','期望结果','预期'],'expected'),
                                      (['优先级'],'priority')]:
                    if any(kw in line for kw in keywords):
                        for sep in [':','：','】']:
                            if sep in line:
                                current[key] = line.split(sep, 1)[-1].strip()
                                break
                        else:
                            for pfx in keywords:
                                if line.startswith(pfx):
                                    current[key] = line[len(pfx):].strip()
                                    break
        if current:
            cases.append(current)
        return cases

    @action(detail=False, methods=['post'], url_path='import-from-testcases')
    def import_from_testcases(self, request):
        """将用例库（apps.testcases.TestCase）中的用例批量转为UI自动化AI用例(AICase)，转换后可直接执行"""
        from apps.testcases.models import TestCase

        case_ids = request.data.get('case_ids')
        if not case_ids or not isinstance(case_ids, list) or len(case_ids) == 0:
            return Response({'error': '请提供 case_ids 列表'}, status=status.HTTP_400_BAD_REQUEST)

        testcases_qs = TestCase.objects.filter(id__in=case_ids)
        if not testcases_qs.exists():
            return Response({'error': '未找到对应的用例库用例'}, status=status.HTTP_404_NOT_FOUND)

        created_ids = []
        for case in testcases_qs:
            # 拼接步骤：优先用步骤明细，其次用 steps 文本
            steps_text = (case.steps or '').strip()
            if case.step_details.exists():
                detail_lines = []
                for s in case.step_details.all().order_by('step_number'):
                    line = f"{s.step_number}. {s.action or ''}"
                    if s.expected:
                        line += f" → 预期：{s.expected}"
                    detail_lines.append(line)
                if detail_lines:
                    steps_text = '\n'.join(detail_lines)
            if not steps_text:
                steps_text = '参考测试目标执行相应操作'

            task_description = (
                f"任务目标：{case.title}\n"
                f"前置条件：{case.preconditions or '无'}\n"
                f"测试步骤：\n{steps_text}\n"
                f"预期结果：{case.expected_result or '无'}"
            )
            priority_text = dict(TestCase.PRIORITY_CHOICES).get(case.priority, case.priority)
            description = f"由用例库导入（用例ID {case.id}）"
            if priority_text:
                description += f"，优先级 {priority_text}"
            if case.test_type:
                type_map = dict(TestCase.TYPE_CHOICES)
                description += f"，测试类型 {type_map.get(case.test_type, case.test_type)}"

            ai_case = AICase.objects.create(
                name=case.title,
                description=description,
                task_description=task_description,
                created_by=request.user
            )
            created_ids.append(ai_case.id)

        return Response({
            'message': f'成功导入 {len(created_ids)} 条用例库用例为UI自动化AI用例',
            'created_ids': created_ids,
            'count': len(created_ids)
        }, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        instance.delete()

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        """执行 AI 用例"""
        ai_case = self.get_object()

        # 创建执行记录
        execution_record = AIExecutionRecord.objects.create(
            project=ai_case.project,
            ai_case=ai_case,
            case_name=ai_case.name,
            task_description=ai_case.task_description,
            status='running',
            executed_by=request.user,
            logs="正在分析任务...\n"
        )
        
        # 异步执行
        import threading
        from asgiref.sync import sync_to_async
        from .ai_agent import run_full_process_sync
        
        def run_task():
            # 注册停止信号
            STOP_SIGNALS[execution_record.id] = False

            try:
                def should_stop():
                    return STOP_SIGNALS.get(execution_record.id, False)

                async def on_analysis_complete(planned_tasks):
                    execution_record.planned_tasks = planned_tasks
                    execution_record.logs += "任务分析完成，开始执行...\n"
                    await sync_to_async(execution_record.save)()
                    
                async def on_step_update(step_info):
                    try:
                        # 处理日志
                        if step_info.get('type') == 'log':
                            content = step_info.get('content')
                            if content:
                                execution_record.logs += content
                                await sync_to_async(execution_record.save)()
                            return

                        # 处理任务状态
                        task_id = step_info.get('task_id')
                        status = step_info.get('status')
                        if task_id and status:
                            updated = False
                            for task in execution_record.planned_tasks:
                                if task['id'] == task_id:
                                    task['status'] = status
                                    updated = True
                                    break
                            if updated:
                                await sync_to_async(execution_record.save)()
                    except Exception as e:
                        print(f"更新步骤状态失败: {e}")

                history = run_full_process_sync(
                    ai_case.task_description, 
                    analysis_callback=on_analysis_complete, 
                    step_callback=on_step_update,
                    should_stop=should_stop
                )
                
                # 检查是否是手动停止
                if should_stop():
                    execution_record.status = 'stopped'
                    execution_record.logs += "\n[System] 任务已由用户停止。"
                else:
                    # 更新成功状态
                    execution_record.status = 'passed'
                    execution_record.logs += "\n执行完成。"

                    # 记录任务完成统计信息
                    if execution_record.planned_tasks:
                        total_tasks = len(execution_record.planned_tasks)
                        completed_tasks = len([t for t in execution_record.planned_tasks if t.get('status') == 'completed'])
                        pending_tasks = len([t for t in execution_record.planned_tasks if t.get('status') == 'pending'])
                        logger.info(f"🏁 Task completion summary: {completed_tasks}/{total_tasks} tasks completed, {pending_tasks} pending")
                
                execution_record.end_time = timezone.now()
                execution_record.duration = (execution_record.end_time - execution_record.start_time).total_seconds()
                
                # 格式化 history 为日志 (如果不是停止状态)
                steps = []
                if history:
                    if hasattr(history, 'steps'):
                        steps = [extract_step_info(s, i) for i, s in enumerate(history.steps)]

                execution_record.steps_completed = steps

                # 自动标记已完成的任务
                if execution_record.planned_tasks:
                    self._auto_mark_completed_tasks(execution_record)

                # 处理GIF录制文件
                self._process_gif_recording(execution_record, history)

                execution_record.save()

            except Exception as e:
                execution_record.status = 'failed'
                execution_record.end_time = timezone.now()
                execution_record.duration = (execution_record.end_time - execution_record.start_time).total_seconds()
                execution_record.logs += f"\n执行出错: {str(e)}"
                execution_record.save()
            finally:
                # 清理停止信号
                if execution_record.id in STOP_SIGNALS:
                    del STOP_SIGNALS[execution_record.id]

        thread = threading.Thread(target=run_task)
        thread.daemon = True
        thread.start()
        
        return Response({
            'message': 'AI 用例开始执行',
            'execution_id': execution_record.id
        })

    def _process_gif_recording(self, execution_record, history):
        """
        处理GIF录制文件
        在执行完成后查找生成的GIF文件并保存路径到数据库
        """
        try:
            import os
            from django.conf import settings
            from datetime import datetime

            # browser-use 默认生成的GIF文件名（固定为agent_history.gif）
            default_gif_path = os.path.join(os.getcwd(), 'agent_history.gif')

            # 如果找到GIF文件，移动到media/ai_recording目录并重命名
            if os.path.exists(default_gif_path):
                import shutil

                # 创建录制文件目录
                gif_dir = os.path.join(settings.MEDIA_ROOT, 'ai_recording')
                os.makedirs(gif_dir, exist_ok=True)

                # 生成新的文件名：用例名称+年月日时分秒
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                # 清理用例名称中的非法字符
                safe_case_name = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in execution_record.case_name])
                new_gif_filename = f"{safe_case_name}_{timestamp}.gif"
                new_gif_path = os.path.join(gif_dir, new_gif_filename)

                # 移动并重命名文件
                shutil.move(default_gif_path, new_gif_path)

                # 保存相对路径到数据库
                relative_path = os.path.join('media', 'ai_recording', new_gif_filename)
                execution_record.gif_path = relative_path

                logger.info(f"✅ GIF recording saved to: {relative_path}")
            else:
                logger.warning(f"⚠️ GIF file not found at: {default_gif_path}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to process GIF recording: {e}")

    def _auto_mark_completed_tasks(self, execution_record):
        """
        自动标记已完成的任务
        通过分析执行历史和当前任务状态，自动标记那些已经执行但未被标记完成的任务
        """
        try:
            # 记录初始状态
            initial_completed = 0
            initial_pending = 0
            if execution_record.planned_tasks:
                initial_completed = len([t for t in execution_record.planned_tasks if t.get('status') == 'completed'])
                initial_pending = len([t for t in execution_record.planned_tasks if t.get('status') == 'pending'])
                logger.info(f"📊 Before auto-mark: {initial_completed} completed, {initial_pending} pending tasks")

            # 如果执行成功，标记所有任务为完成
            if execution_record.status == 'passed' and execution_record.planned_tasks:
                auto_marked_count = 0
                for task in execution_record.planned_tasks:
                    # 只对标记为pending的任务进行处理
                    if task.get('status') == 'pending':
                        task['status'] = 'completed'
                        auto_marked_count += 1
                        logger.info(f"🔒 Auto-marked task {task['id']} as completed")

                if auto_marked_count > 0:
                    logger.info(f"✨ Auto-marked {auto_marked_count} tasks as completed")
                else:
                    logger.info("📋 No pending tasks needed auto-marking")

            # TODO: 可以添加更智能的分析逻辑来识别部分完成的任务

        except Exception as e:
            logger.warning(f"⚠️ Failed to auto-mark completed tasks: {e}")


# 全局停止信号字典 {execution_id: bool}
STOP_SIGNALS = {}

class AIExecutionRecordViewSet(viewsets.ModelViewSet):
    """AI执行记录视图集"""
    queryset = AIExecutionRecord.objects.all()
    serializer_class = AIExecutionRecordSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['project', 'ai_case', 'status']
    ordering = ['-start_time']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        # 返回用户有权限的项目下的执行记录，以及没有关联项目的执行记录
        return AIExecutionRecord.objects.filter(
            models.Q(project__in=accessible_projects) | models.Q(project__isnull=True)
        ).distinct()

    def perform_destroy(self, instance):
        instance.delete()

    @action(detail=False, methods=['post'])
    def batch_delete(self, request):
        """批量删除AI执行记录"""
        ids = request.data.get('ids', [])
        if not ids:
            return Response({'error': '请选择要删除的记录'}, status=status.HTTP_400_BAD_REQUEST)

        # 确保只能删除有权限的记录，重新构建查询以避免 distinct() 限制
        user = self.request.user
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        deleted_count, _ = AIExecutionRecord.objects.filter(
            id__in=ids
        ).filter(
            models.Q(project__in=accessible_projects) | models.Q(project__isnull=True)
        ).delete()

        return Response({'message': f'成功删除 {deleted_count} 条记录'})

    @action(detail=False, methods=['post'], url_path='run_adhoc')
    def run_adhoc(self, request):
        """执行临时 AI 任务"""
        project_id = request.data.get('project_id')
        task_description = request.data.get('task_description')
        execution_mode = request.data.get('execution_mode', 'text')  # 默认文本模式
        enable_gif = request.data.get('enable_gif', True)  # GIF录制开关，默认开启

        if not task_description:
            return Response({'error': '缺少任务描述参数'}, status=status.HTTP_400_BAD_REQUEST)

        # 获取项目对象（如果提供了project_id）
        project = None
        if project_id:
            try:
                project = UiProject.objects.get(id=project_id)
            except UiProject.DoesNotExist:
                return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

        # 创建执行记录
        execution_record = AIExecutionRecord.objects.create(
            project=project,
            case_name="Adhoc Task",
            task_description=task_description,
            execution_mode=execution_mode,
            status='running',
            executed_by=request.user,
            logs="正在分析任务...\n"
        )

        # 异步执行
        import threading
        from asgiref.sync import sync_to_async
        from .ai_agent import run_full_process_sync

        def run_task():
            # 注册停止信号
            STOP_SIGNALS[execution_record.id] = False

            try:
                # 定义异步安全的 should_stop
                async def should_stop_async():
                    # 优先检查内存信号
                    if STOP_SIGNALS.get(execution_record.id, False):
                        return True
                    # 兜底检查数据库状态 (使用 sync_to_async 避免异步上下文错误)
                    await sync_to_async(execution_record.refresh_from_db)()
                    return execution_record.status == 'stopped'

                # 定义同步版本的 should_stop 用于最后检查
                def should_stop_sync():
                    if STOP_SIGNALS.get(execution_record.id, False):
                        return True
                    execution_record.refresh_from_db()
                    return execution_record.status == 'stopped'

                async def on_analysis_complete(planned_tasks):
                    execution_record.planned_tasks = planned_tasks
                    execution_record.logs += "任务分析完成，开始执行...\n"
                    await sync_to_async(execution_record.save)()
                    
                async def on_step_update(step_info):
                    try:
                        # 处理日志
                        if step_info.get('type') == 'log':
                            content = step_info.get('content')
                            if content:
                                execution_record.logs += content
                                # 立即保存到数据库，确保前端轮询能看到最新日志
                                await sync_to_async(execution_record.save)(update_fields=['logs'])
                            return

                        # 处理任务状态
                        task_id = step_info.get('task_id')
                        status = step_info.get('status')
                        logger.info(f"DEBUG: on_step_update received: task_id={task_id}, status={status}")
                        
                        if task_id and status:
                            updated = False
                            if execution_record.planned_tasks:
                                for task in execution_record.planned_tasks:
                                    # 确保类型一致进行比较
                                    if str(task['id']) == str(task_id):
                                        old_status = task.get('status', 'pending')
                                        task['status'] = status
                                        updated = True
                                        logger.info(f"DEBUG: Updated task {task_id} from {old_status} to {status}")
                                        break
                            if updated:
                                # 立即保存到数据库，确保前端轮询能看到最新状态
                                await sync_to_async(execution_record.save)(update_fields=['planned_tasks'])
                            else:
                                logger.warning(f"DEBUG: Task ID {task_id} not found in planned_tasks: {execution_record.planned_tasks}")
                    except Exception as e:
                        logger.error(f"更新步骤状态失败: {e}", exc_info=True)

                history = run_full_process_sync(
                    task_description,
                    analysis_callback=on_analysis_complete,
                    step_callback=on_step_update,
                    should_stop=should_stop_async, # 传递异步版本
                    execution_mode=execution_mode,
                    enable_gif=enable_gif,  # 传递GIF录制开关
                    case_name=task_description[:50] if task_description else "Adhoc Task"  # 传递用例名称用于GIF文件命名
                )

                # 检查是否是手动停止 (使用同步版本)
                if should_stop_sync():
                    execution_record.status = 'stopped'
                    execution_record.logs += "\n[System] 任务已由用户停止。"
                else:
                    # 更新成功状态
                    execution_record.status = 'passed'
                    execution_record.logs += "\n执行完成。"

                    # 记录任务完成统计信息
                    if execution_record.planned_tasks:
                        total_tasks = len(execution_record.planned_tasks)
                        completed_tasks = len([t for t in execution_record.planned_tasks if t.get('status') == 'completed'])
                        pending_tasks = len([t for t in execution_record.planned_tasks if t.get('status') == 'pending'])
                        logger.info(f"🏁 Task completion summary: {completed_tasks}/{total_tasks} tasks completed, {pending_tasks} pending")
                
                execution_record.end_time = timezone.now()
                execution_record.duration = (execution_record.end_time - execution_record.start_time).total_seconds()
                
                # 格式化 history 为日志 (如果不是停止状态)
                steps = []
                if history:
                    if hasattr(history, 'steps'):
                        steps = [extract_step_info(s, i) for i, s in enumerate(history.steps)]

                execution_record.steps_completed = steps

                # 自动标记已完成的任务
                if execution_record.planned_tasks:
                    self._auto_mark_completed_tasks(execution_record)

                # 处理GIF录制文件
                self._process_gif_recording(execution_record, history)

                execution_record.save()

            except Exception as e:
                execution_record.status = 'failed'
                execution_record.end_time = timezone.now()
                execution_record.duration = (execution_record.end_time - execution_record.start_time).total_seconds()
                execution_record.logs += f"\n执行出错: {str(e)}"
                execution_record.save()
            finally:
                # 清理停止信号
                if execution_record.id in STOP_SIGNALS:
                    del STOP_SIGNALS[execution_record.id]

        thread = threading.Thread(target=run_task)
        thread.daemon = True
        thread.start()
        
        return Response({
            'message': 'AI 任务开始执行',
            'execution_id': execution_record.id
        })


    @action(detail=True, methods=['post'], url_path='stop')
    def stop_task(self, request, pk=None):
        """停止正在执行的任务"""
        try:
            execution_id = int(pk)
            if execution_id in STOP_SIGNALS:
                STOP_SIGNALS[execution_id] = True
                return Response({'message': '已发送停止信号'})
            else:
                # 如果不在内存中，可能已经结束，或者重启过服务
                # 尝试直接更新数据库状态
                record = self.get_object()
                if record.status == 'running':
                    record.status = 'stopped'
                    record.end_time = timezone.now()
                    record.logs += "\n[System] 任务被强制标记为停止（未在运行队列中找到）。"
                    record.save()
                    return Response({'message': '任务已标记为停止'})
                return Response({'message': '任务不在运行中'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _process_gif_recording(self, execution_record, history):
        """
        处理GIF录制文件
        在执行完成后查找生成的GIF文件并保存路径到数据库
        """
        try:
            import os
            from django.conf import settings
            from datetime import datetime

            # browser-use 默认生成的GIF文件名（固定为agent_history.gif）
            default_gif_path = os.path.join(os.getcwd(), 'agent_history.gif')

            # 如果找到GIF文件，移动到media/ai_recording目录并重命名
            if os.path.exists(default_gif_path):
                import shutil

                # 创建录制文件目录
                gif_dir = os.path.join(settings.MEDIA_ROOT, 'ai_recording')
                os.makedirs(gif_dir, exist_ok=True)

                # 生成新的文件名：用例名称+年月日时分秒
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                # 清理用例名称中的非法字符
                safe_case_name = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in execution_record.case_name])
                new_gif_filename = f"{safe_case_name}_{timestamp}.gif"
                new_gif_path = os.path.join(gif_dir, new_gif_filename)

                # 移动并重命名文件
                shutil.move(default_gif_path, new_gif_path)

                # 保存相对路径到数据库
                relative_path = os.path.join('media', 'ai_recording', new_gif_filename)
                execution_record.gif_path = relative_path

                logger.info(f"✅ GIF recording saved to: {relative_path}")
            else:
                logger.warning(f"⚠️ GIF file not found at: {default_gif_path}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to process GIF recording: {e}")

    def _auto_mark_completed_tasks(self, execution_record):
        """
        自动标记已完成的任务
        通过分析执行历史和当前任务状态，自动标记那些已经执行但未被标记完成的任务
        """
        try:
            # 记录初始状态
            initial_completed = 0
            initial_pending = 0
            if execution_record.planned_tasks:
                initial_completed = len([t for t in execution_record.planned_tasks if t.get('status') == 'completed'])
                initial_pending = len([t for t in execution_record.planned_tasks if t.get('status') == 'pending'])
                logger.info(f"📊 Before auto-mark: {initial_completed} completed, {initial_pending} pending tasks")

            # 如果执行成功，标记所有任务为完成
            if execution_record.status == 'passed' and execution_record.planned_tasks:
                auto_marked_count = 0
                for task in execution_record.planned_tasks:
                    # 只对标记为pending的任务进行处理
                    if task.get('status') == 'pending':
                        task['status'] = 'completed'
                        auto_marked_count += 1
                        logger.info(f"🔒 Auto-marked task {task['id']} as completed")

                if auto_marked_count > 0:
                    logger.info(f"✨ Auto-marked {auto_marked_count} tasks as completed")
                else:
                    logger.info("📋 No pending tasks needed auto-marking")

            # TODO: 可以添加更智能的分析逻辑来识别部分完成的任务

        except Exception as e:
            logger.warning(f"⚠️ Failed to auto-mark completed tasks: {e}")

    @action(detail=True, methods=['get'], url_path='report')
    def generate_report(self, request, pk=None):
        """
        生成AI执行报告

        Query Parameters:
            report_type: 报告类型 (summary/detailed/performance)，默认为 summary

        Returns:
            执行报告数据
        """
        try:
            record = self.get_object()
            report_type = request.query_params.get('report_type', 'summary')

            # 导入报告生成器
            from .reports import AIExecutionReportGenerator

            # 生成报告
            generator = AIExecutionReportGenerator(record)

            if report_type == 'detailed':
                report = generator.generate_detailed_report()
            elif report_type == 'performance':
                report = generator.generate_performance_report()
            else:  # summary
                report = generator.generate_summary_report()

            return Response({
                'success': True,
                'data': report,
                'report_type': report_type
            })

        except Exception as e:
            logger.error(f"生成AI执行报告失败: {e}", exc_info=True)
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='export-pdf')
    def export_pdf(self, request, pk=None):
        """
        导出AI执行报告为PDF

        Query Parameters:
            report_type: 报告类型 (summary/detailed/performance)，默认为 summary

        Returns:
            PDF文件下载
        """
        try:
            record = self.get_object()
            report_type = request.query_params.get('report_type', 'summary')

            # 导入报告生成器
            from .reports import AIExecutionReportGenerator
            from .pdf_generator import AIReportPDFGenerator

            # 生成报告数据
            generator = AIExecutionReportGenerator(record)

            if report_type == 'detailed':
                report_data = generator.generate_detailed_report()
            elif report_type == 'performance':
                report_data = generator.generate_performance_report()
            else:  # summary
                report_data = generator.generate_summary_report()

            # 生成PDF
            pdf_generator = AIReportPDFGenerator(report_data, report_type)
            pdf_buffer = pdf_generator.generate()

            # 生成文件名
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            safe_case_name = "".join([c if c.isalnum() or c in (' ', '_', '-') else '_' for c in record.case_name])
            filename = f"AI_Report_{safe_case_name}_{timestamp}.pdf"

            # 返回PDF文件
            response = HttpResponse(
                pdf_buffer.getvalue(),
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = len(pdf_buffer.getvalue())

            return response

        except ImportError as e:
            logger.error(f"PDF生成库未安装: {e}")
            return Response({
                'success': False,
                'error': 'PDF生成功能需要安装 reportlab 库，请运行: pip install reportlab'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"导出PDF失败: {e}", exc_info=True)
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UiDashboardViewSet(viewsets.ViewSet):
    """UI自动化仪表盘视图集"""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """获取仪表盘统计数据"""
        user = request.user
        
        # 获取用户可访问的项目ID列表
        accessible_projects = filter_by_owner_or_member(UiProject.objects.all(), user)
        project_ids = accessible_projects.values_list('id', flat=True)

        # 统计数据
        project_count = accessible_projects.count()
        
        # 测试用例数量
        test_case_count = TestCase.objects.filter(project_id__in=project_ids).count()
        
        # 测试套件数量（包含用例总数）
        suite_count = TestSuite.objects.filter(project_id__in=project_ids).count()
        
        from .models import TestSuiteTestCase
        suite_test_case_count = TestSuiteTestCase.objects.filter(
            test_suite__project_id__in=project_ids
        ).count()

        # 测试执行数量（传统+新版）
        execution_count = TestExecution.objects.filter(project_id__in=project_ids).count()
        test_case_execution_count = TestCaseExecution.objects.filter(project_id__in=project_ids).count()
        total_execution_count = execution_count + test_case_execution_count

        return Response({
            'project_count': project_count,
            'test_case_count': test_case_count,
            'suite_count': suite_test_case_count,
            'execution_count': total_execution_count
        })


# ==================== App 自动化 ViewSet ====================

class AppDeviceViewSet(viewsets.ModelViewSet):
    """移动设备管理"""
    queryset = AppDevice.objects.all()
    serializer_class = AppDeviceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['platform', 'device_type', 'status']
    search_fields = ['name', 'udid']
    ordering = ['platform', 'name']

    @action(detail=True, methods=['post'])
    def heartbeat(self, request, pk=None):
        """设备心跳上报"""
        device = self.get_object()
        device.last_heartbeat = timezone.now()
        if device.status == 'offline':
            device.status = 'online'
        device.save()
        return Response({'status': 'ok', 'last_heartbeat': device.last_heartbeat})

    @action(detail=True, methods=['post'])
    def set_status(self, request, pk=None):
        """手动设置设备状态"""
        device = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(AppDevice.STATUS_CHOICES):
            return Response({'error': '无效的状态值'}, status=status.HTTP_400_BAD_REQUEST)
        device.status = new_status
        device.save()
        return Response(AppDeviceSerializer(device).data)


class AppConfigViewSet(viewsets.ModelViewSet):
    """应用配置管理"""
    queryset = AppConfig.objects.all()
    serializer_class = AppConfigSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['platform', 'project', 'ai_project']
    search_fields = ['name', 'package_name']
    ordering = ['platform', 'name']

    def get_queryset(self):
        """支持按 project 参数筛选（同时匹配 project 和 ai_project）"""
        qs = super().get_queryset()
        project_param = self.request.query_params.get('project')
        if project_param:
            # project 参数可能是 "ui_xxx" 或 "proj_xxx" 格式
            if project_param.startswith('ui_'):
                qs = qs.filter(project_id=project_param[3:])
            elif project_param.startswith('proj_'):
                qs = qs.filter(ai_project_id=project_param[6:])
            else:
                # 兼容纯数字（旧的 UiProject id）
                qs = qs.filter(project_id=project_param)
        return qs


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_all_projects_unified(request):
    """
    获取合并后的项目列表（UI自动化项目 + AI用例模块项目）
    用于 UI 自动化模块中所有项目下拉选择框
    返回格式：[{id: "ui_1", name: "xxx", source: "ui"}, {id: "proj_1", name: "yyy", source: "proj"}]
    """
    from apps.projects.models import Project

    result = []

    # 加载 UI自动化项目
    ui_projects = UiProject.objects.all().values('id', 'name')
    for p in ui_projects:
        result.append({
            'id': f'ui_{p["id"]}',
            'name': p['name'],
            'source': 'ui',
            'real_id': p['id']
        })

    # 加载 AI用例模块项目
    ai_projects = Project.objects.all().values('id', 'name')
    for p in ai_projects:
        result.append({
            'id': f'proj_{p["id"]}',
            'name': p['name'],
            'source': 'proj',
            'real_id': p['id']
        })

    return Response(result)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ensure_ui_project(request):
    """
    确保 AI项目有对应的 UiProject
    传入 {ai_project_id: xxx}，返回对应的 UiProject ID
    如果不存在则自动创建
    """
    from apps.projects.models import Project

    ai_project_id = request.data.get('ai_project_id')
    if not ai_project_id:
        return Response({'error': 'ai_project_id is required'}, status=400)

    try:
        ai_project = Project.objects.get(id=ai_project_id)
    except Project.DoesNotExist:
        return Response({'error': 'AI project not found'}, status=404)

    # 查找是否已有同名 UiProject
    ui_project = UiProject.objects.filter(name=ai_project.name).first()
    if not ui_project:
        ui_project = UiProject.objects.create(
            name=ai_project.name,
            description=ai_project.description or '',
            status='IN_PROGRESS',
            base_url='',
            owner=request.user
        )
        # 同步成员
        if hasattr(ai_project, 'members'):
            for member in ai_project.members.all():
                ui_project.members.add(member)

    return Response({
        'id': ui_project.id,
        'name': ui_project.name,
        'created': True
    })



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def learn_elements(request):
    """连接 Appium dump 当前页面控件，返回元素列表供前端选择"""
    from .smart_locator import dump_page_elements

    device_id = request.data.get('device_id')
    app_config_id = request.data.get('app_config_id')
    app_name = request.data.get('app_name', '万年历')

    if not device_id or not app_config_id:
        return Response({'success': False, 'message': '缺少 device_id 或 app_config_id'}, status=400)

    try:
        device = _resolve_recording_device(device_id)
        app_config = get_object_or_404(AppConfig, id=app_config_id)

        from .appium_engine import AppiumTestEngine
        engine = AppiumTestEngine(
            appium_server_url=device.appium_server_url,
            platform=device.platform,
            device_udid=device.udid,
            app_package=app_config.package_name,
            app_activity=app_config.app_activity,
            no_reset=True,
            new_command_timeout=60,
        )
        engine.connect()
        try:
            engine.driver.activate_app(app_config.package_name)
        except Exception:
            pass
        import time
        time.sleep(1)

        elements = dump_page_elements(engine)

        if engine.driver:
            engine.driver.quit()

        return Response({
            'success': True,
            'count': len(elements),
            'elements': elements,
            'message': f'发现 {len(elements)} 个控件'
        })
    except Exception as e:
        err_msg = str(e).lower()
        hint = ''
        if 'instrumentation' in err_msg or 'not running' in err_msg or 'crashed' in err_msg:
            hint = ' 设备连接可能已断开，建议重新开始录制。'
        return Response({'success': False, 'message': f'获取页面控件失败: {e}{hint}'}, status=500)



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_knowledge(request):
    """保存控件到 JSON 知识库"""
    from .smart_locator import add_knowledge

    app_name = request.data.get('app_name', '万年历')
    items = request.data.get('items', [])  # [{chinese_name, value}]

    saved = 0
    for item in items:
        add_knowledge(app_name, item.get('chinese_name', ''), item.get('value', ''))
        saved += 1

    return Response({
        'success': True,
        'saved': saved,
        'message': f'已保存 {saved} 个控件到 "{app_name}" 知识库'
    })


# ==================== 操作录制（自动生成可运行用例） ====================
# 录制会话：每个用户同时只能有一个进行中的录制会话。
# key = request.user.id, value 见下方 dict 结构。
RECORDING_SESSIONS = {}


def _recording_session_key(request):
    return request.user.id


def _resolve_recording_device(device_id):
    """兼容新旧两套设备表解析设备（录制/探测共用）。
    优先查新表 app_automation.AppDevice(device_id)，回退旧表 ui_automation.AppDevice(udid)。
    返回统一对象（含 udid/platform/appium_server_url/adb_host/name）。找不到抛 DoesNotExist。
    """
    import types as _types
    from apps.app_automation.models import AppDevice as NewAppDevice

    # 优先新表（主表，新版设备都在这里）
    try:
        nd = NewAppDevice.objects.get(device_id=device_id)
        return _types.SimpleNamespace(
            udid=nd.device_id,
            platform='android',
            appium_server_url='http://localhost:4723',
            adb_host=getattr(nd, 'adb_host', '') or '',
            name=nd.name or nd.device_id,
            _source='new',
        )
    except NewAppDevice.DoesNotExist:
        pass

    # 回退旧表（ui_automation.AppDevice，用 udid 查询）
    od = AppDevice.objects.get(udid=device_id)  # 找不到抛 DoesNotExist
    return _types.SimpleNamespace(
        udid=od.udid,
        platform=od.platform or 'android',
        appium_server_url=od.appium_server_url or 'http://localhost:4723',
        adb_host=getattr(od, 'adb_host', '') or '',
        name=od.name,
        _source='old',
    )


def _close_recording_session(key):
    """关闭录制会话并断开连接（含自动触摸监听）"""
    sess = RECORDING_SESSIONS.pop(key, None)
    if sess and sess.get('engine'):
        engine = sess['engine']
        # 停止自动触摸捕获
        if hasattr(engine, 'stop_auto_capture'):
            try: engine.stop_auto_capture()
            except Exception: pass
        try:
            engine.disconnect()
        except Exception:
            pass
    return sess


def _get_screenshot_base64(engine):
    """获取设备截图 base64（失败返回空串，不影响主流程）"""
    try:
        return engine.driver.get_screenshot_base64() if engine and engine.driver else ''
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning('获取设备截图失败: %s', e)
        return ''


def _airtest_script_for_session(sess, steps):
    """把当前录制会话的步骤实时编译为可直接 `airtest run` 的脚本文本（仅 airtest 引擎）"""
    if not sess or sess.get('engine_type') != 'airtest':
        return ''
    try:
        from django.conf import settings
        from .airtest_engine import build_airtest_script
        return build_airtest_script(
            steps,
            app_package=sess['app_config'].package_name,
            serial=sess['device'].udid,
            adb_host=getattr(settings, 'AIRTEST_ADB_HOST', 'host.docker.internal'),
            adb_port=int(getattr(settings, 'AIRTEST_ADB_PORT', 5037)),
            platform=sess['device'].platform,
            wda_url=sess['device'].appium_server_url,
            display_size=sess.get('display'),
        )
    except Exception:
        return ''


def _default_desc(action_type, element_data, input_value, assert_value):
    """为录制步骤生成默认描述"""
    name = element_data.get('name') if element_data else ''
    if action_type in ('click', 'tap'):
        return f"点击{name or '元素'}"
    if action_type == 'double_tap':
        return f"双击{name or '元素'}"
    if action_type == 'long_press':
        return f"长按{name or '元素'}"
    if action_type in ('fill', 'input'):
        return f"在{name or '输入框'}输入「{input_value}」"
    if action_type == 'clear':
        return f"清空{name or '输入框'}"
    if action_type == 'swipe':
        return f"滑动{input_value or '屏幕'}"
    if action_type == 'scroll':
        return f"滚动{name or '页面'}"
    if action_type == 'screenshot':
        return "截图"
    if action_type == 'wait':
        return f"等待{input_value or '1'}秒"
    if action_type == 'assert':
        return f"断言{name or '元素'}{assert_value or ''}"
    if action_type == 'getText':
        return f"获取{name or '元素'}文本"
    if action_type == 'back':
        return "返回上一页"
    if action_type == 'home':
        return "回到主页"
    if action_type == 'launch_app':
        return "启动应用"
    if action_type == 'close_app':
        return "关闭应用"
    return action_type


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_recording(request):
    """开始录制：建立并保持 Appium 会话，后续人工操作将被记录为步骤"""
    device_id = request.data.get('device_id')
    app_config_id = request.data.get('app_config_id')
    project_id = request.data.get('project_id')
    case_name = (request.data.get('case_name') or '').strip()
    engine_type = (request.data.get('engine') or 'appium').lower()
    logger.info(f"[start_recording] 收到请求: device_id={device_id}, engine={engine_type}, raw_engine={request.data.get('engine')!r}")
    continue_case_id = request.data.get('continue_case_id')  # 继续录制：已有用例 ID

    if not device_id or not app_config_id or not project_id:
        return Response({'success': False, 'message': '缺少 device_id / app_config_id / project_id'}, status=400)

    try:
        device = _resolve_recording_device(device_id)
        app_config = get_object_or_404(AppConfig, id=app_config_id)
        project = get_object_or_404(UiProject, id=project_id)
    except Exception as e:
        return Response({'success': False, 'message': f'参数无效: {e}'}, status=400)

    # 若已有会话，先关闭旧会话
    key = _recording_session_key(request)
    _close_recording_session(key)

    # 继续录制：预加载已有用例的步骤
    existing_steps = []
    existing_case = None
    if continue_case_id:
        try:
            existing_case = get_object_or_404(TestCase, id=continue_case_id)
            case_name = case_name or existing_case.name
            project = existing_case.project  # 强制用用例所属项目
            # 将 DB 步骤转为录制步骤同构格式（与 _gesture_to_step / _build_test_case_from_steps 兼容）
            for s in existing_case.steps.all().order_by('step_number'):
                el_data = None
                if s.element:
                    el_data = {
                        'locator_strategy': s.element.locator_strategy.name if s.element.locator_strategy else 'coordinate',
                        'locator_value': s.element.locator_value or '',
                        'name': s.element.name,
                    }
                    if s.center_x is not None and s.center_y is not None:
                        el_data['center_x'] = s.center_x
                        el_data['center_y'] = s.center_y
                step_dict = {
                    'step_number': s.step_number,
                    'action_type': s.action_type,
                    'description': s.description or '',
                    'input_value': s.input_value or '',
                    'wait_time': s.wait_time or 0,
                    'assert_type': s.assert_type or '',
                    'assert_value': s.assert_value or '',
                    'element': el_data,
                    'center_x': s.center_x,
                    'center_y': s.center_y,
                }
                existing_steps.append(step_dict)
        except Exception as e:
            return Response({'success': False, 'message': f'加载已有用例失败: {e}'}, status=400)

    # Appium 模式：连接前清理设备端残留的 UiAutomator2 进程，
    # 避免 "UiAutomation not connected" 导致新建 Session 失败
    if engine_type != 'airtest' and device.udid:
        import subprocess
        try:
            subprocess.run(
                ['adb', '-s', device.udid, 'shell', 'am', 'force-stop',
                 'io.appium.uiautomator2.server'],
                capture_output=True, timeout=5,
            )
            logger.info(f"已清理设备 {device.udid} 上的残留 UiAutomator2 进程")
        except Exception:
            pass  # 清理失败不阻塞后续连接

    try:
        if engine_type == 'airtest':
            from .airtest_engine import AirtestRecordingEngine
            # iOS 通过 Airtest 连接时不依赖 Appium，复用 appium_server_url 字段存放
            # WDA(WebDriverAgent) 的 HTTP 代理地址（如 http://host.docker.internal:8100）。
            # adb_host：手机USB所在电脑的IP，后端通过该电脑的ADB服务控制设备
            _adb_host = getattr(device, 'adb_host', None) or None  # None 则用默认 host.docker.internal
            engine = AirtestRecordingEngine(
                serial=device.udid,
                platform=device.platform,
                app_package=app_config.package_name,
                wda_url=device.appium_server_url,
                adb_host=_adb_host,
            )
            engine.connect()
            try:
                engine.activate_app(app_config.package_name)
            except Exception:
                pass
            time.sleep(1)
            elements = dump_page_elements(engine)
            screenshot = _get_screenshot_base64(engine)
            display = engine.display_size
        else:
            from .appium_engine import AppiumTestEngine
            engine = AppiumTestEngine(
                appium_server_url=device.appium_server_url,
                platform=device.platform,
                device_udid=device.udid,
                app_package=app_config.package_name,
                app_activity=app_config.app_activity,
                bundle_id=app_config.package_name if device.platform == 'ios' else None,
                app_path=app_config.app_path or None,
                no_reset=True,
                new_command_timeout=600,
            )
            engine.connect()
            try:
                engine.driver.activate_app(app_config.package_name)
            except Exception:
                pass
            time.sleep(1)
            elements = dump_page_elements(engine)
            screenshot = _get_screenshot_base64(engine)
            display = None
    except Exception as e:
        err_msg = str(e).lower()
        hint = ''
        if 'instrumentation' in err_msg or 'not running' in err_msg or 'crashed' in err_msg:
            hint = (
                ' 设备端 instrumentation 进程异常，建议：1) 重启 Appium Server；'
                '2) 在设备上重新打开被测 App 后重试；3) 若仍失败，尝试 adb 重启设备。'
            )
        return Response({'success': False, 'message': f'建立录制会话失败: {e}{hint}'}, status=500)

    RECORDING_SESSIONS[key] = {
        'engine': engine,
        'engine_type': engine_type,
        'display': display,
        'device': device,
        'app_config': app_config,
        'project': project,
        'case_name': case_name or f'录制用例_{timezone.now():%Y%m%d_%H%M%S}',
        'steps': existing_steps,  # 继续录制时预加载已有步骤，否则为空列表
        'started_at': timezone.now(),
        'continue_case_id': continue_case_id,  # 非空表示继续录制模式
    }

    # 纯 Airtest 模式：启动自动触摸捕获（真机上操作自动记录步骤）
    auto_capture_ok = False
    if engine_type == 'airtest' and hasattr(engine, 'start_auto_capture'):
        sess_ref = RECORDING_SESSIONS[key]  # 闭包引用

        def _auto_step_callback(step_dict):
            """自动捕获回调：把手势转成的 step 追加到会话 steps"""
            steps = sess_ref.get('steps', [])
            step_dict['step_number'] = len(steps) + 1
            steps.append(step_dict)
            # 同时更新实时代码（下次 refreshRecordPage 会带上）

        try:
            auto_capture_ok = engine.start_auto_capture(_auto_step_callback)
        except Exception:
            auto_capture_ok = False

    msg = '录制已开始，自动捕获已启用 — 直接在真机上操作即可自动记录每一步' \
        if auto_capture_ok else '录制已开始，请在真机上操作，并通过面板记录每一步'

    return Response({
        'success': True,
        'message': msg,
        'auto_capture': auto_capture_ok,
        'elements': elements,
        'count': len(elements),
        'screenshot': screenshot,
        'case_name': RECORDING_SESSIONS[key]['case_name'],
        'steps': existing_steps,  # 继续录制时返回预加载的步骤
        'airtest_script': _airtest_script_for_session(RECORDING_SESSIONS[key], existing_steps),
        'continue_case_id': continue_case_id or None,  # 前端据此判断模式
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recording_page(request):
    """获取当前录制会话的实时页面控件（重新 dump）"""
    key = _recording_session_key(request)
    sess = RECORDING_SESSIONS.get(key)
    if not sess or not sess.get('engine'):
        return Response({'success': False, 'message': '没有进行中的录制会话，请先开始录制'}, status=400)
    try:
        time.sleep(0.3)
        elements = dump_page_elements(sess['engine'])
        screenshot = _get_screenshot_base64(sess['engine'])
        return Response({
            'success': True,
            'count': len(elements),
            'elements': elements,
            'screenshot': screenshot,
            'steps': sess['steps'],
            'case_name': sess.get('case_name'),
            'airtest_script': _airtest_script_for_session(sess, sess['steps']),
        })
    except Exception as e:
        err_msg = str(e).lower()
        hint = ''
        if 'instrumentation' in err_msg or 'not running' in err_msg or 'crashed' in err_msg:
            hint = ' 设备连接可能已断开，建议重新开始录制。'
        return Response({'success': False, 'message': f'获取页面控件失败: {e}{hint}'}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_action(request):
    """记录一个操作：先在真机上真实执行，成功后保存为步骤"""
    key = _recording_session_key(request)
    sess = RECORDING_SESSIONS.get(key)
    if not sess or not sess.get('engine'):
        return Response({'success': False, 'message': '没有进行中的录制会话，请先开始录制'}, status=400)

    engine = sess['engine']
    action_type = (request.data.get('action_type') or '').lower()
    element = request.data.get('element') or {}
    input_value = request.data.get('input_value', '') or ''
    assert_type = request.data.get('assert_type', '') or ''
    assert_value = request.data.get('assert_value', '') or ''
    wait_time = int(request.data.get('wait_time', 0) or 0)

    valid_actions = {
        'click', 'tap', 'double_tap', 'long_press', 'fill', 'input', 'clear',
        'swipe', 'scroll', 'screenshot', 'wait', 'assert', 'getText',
        'launch_app', 'close_app', 'back', 'home'
    }
    if action_type not in valid_actions:
        return Response({'success': False, 'message': f'不支持的操作类型: {action_type}'}, status=400)

    # 需要目标元素的操作
    element_data = None
    need_element = action_type in (
        'click', 'tap', 'double_tap', 'long_press', 'fill', 'input',
        'clear', 'assert', 'getText'
    )
    # 滑动/滚动不需要元素定位，但需保留坐标信息（Airtest 引擎按坐标滑动依赖 center_x/center_y）
    need_coords = action_type in ('swipe', 'scroll')
    if need_element:
        if not (element and element.get('value')):
            return Response({'success': False, 'message': '该操作需要提供目标元素'}, status=400)
        element_data = {
            'locator_strategy': element.get('strategy', 'xpath'),
            'locator_value': element.get('value'),
            'name': element.get('name') or element.get('chinese_name') or element.get('text') or '未命名元素',
            # 保留坐标信息，用于坐标点击（比 el.click() 更可靠）
            'center_x': element.get('center_x'),
            'center_y': element.get('center_y'),
        }
    elif need_coords:
        element_data = {
            'locator_strategy': element.get('strategy') or element.get('locator_strategy'),
            'locator_value': element.get('value') or element.get('locator_value'),
            'name': element.get('name') or element.get('chinese_name') or element.get('text'),
            'center_x': element.get('center_x'),
            'center_y': element.get('center_y'),
        }

    step_data = {
        'step_number': len(sess['steps']) + 1,
        'action_type': action_type,
        'description': request.data.get('description', '') or _default_desc(
            action_type, element_data, input_value, assert_value
        ),
        'input_value': input_value,
        'wait_time': wait_time * 1000,
        'assert_type': assert_type,
        'assert_value': assert_value,
        'element': element_data,
    }

    # 在真机上真实执行
    try:
        result = engine.execute_step(step_data)
    except Exception as e:
        return Response({'success': False, 'message': f'执行操作失败: {e}'}, status=500)

    if not result.get('success'):
        return Response({
            'success': False,
            'message': f"操作未在真机上成功执行，已跳过记录: {result.get('error')}",
            'error': result.get('error'),
        }, status=400)

    recorded = {
        'step_number': step_data['step_number'],
        'action_type': action_type,
        'description': step_data['description'],
        'input_value': input_value,
        'wait_time': wait_time * 1000,
        'assert_type': assert_type,
        'assert_value': assert_value,
        'element': element_data,
    }
    sess['steps'].append(recorded)

    # 刷新页面，便于记录下一步
    try:
        time.sleep(0.3)
        elements = dump_page_elements(engine)
    except Exception:
        elements = []
    # 记录操作后页面可能已变化，重新截图便于在变化后的页面继续点选元素
    try:
        screenshot = _get_screenshot_base64(engine)
    except Exception:
        screenshot = ''

    return Response({
        'success': True,
        'message': f"已记录步骤 {recorded['step_number']}: {recorded['description']}",
        'recorded': recorded,
        'elements': elements,
        'count': len(elements),
        'screenshot': screenshot,
        'steps': sess['steps'],
        'airtest_script': _airtest_script_for_session(sess, sess['steps']),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stop_recording(request):
    """停止录制（放弃生成用例）"""
    key = _recording_session_key(request)
    sess = _close_recording_session(key)
    # 会话已关闭也视为成功（可能已被 generate 自动关闭）
    return Response({'success': True, 'message': '录制已停止'})


def _build_test_case_from_steps(user, project, case_name, steps, app_package=""):
    """把归一化步骤落库为 TestCase（含自动建元素、前插启动应用步骤）。

    归一化步骤格式与 generate_recording_case 录制的步骤完全一致：
    {'action_type','element':{locator_strategy,value,name,center_x,center_y}|None,
     'input_value','wait_time','assert_type','assert_value','description','center_x','center_y'}
    录制的步骤与 Airtest 导入的步骤共用此逻辑。
    """
    test_case = TestCase.objects.create(
        name=case_name,
        description=f"由自动化工具于 {timezone.now():%Y-%m-%d %H:%M:%S} 自动生成"
                    f"（{'Appium 真机录制' if app_package else '脚本导入'}）",
        project=project,
        status='ready',
        priority='medium',
        created_by=user,
    )

    created_elements = 0
    # 自动在最前面加一步「启动应用」，保证回放从干净的起点开始
    all_steps = [{'action_type': 'launch_app', 'element': None, 'input_value': '',
                  'wait_time': 1000, 'assert_type': '', 'assert_value': '',
                  'description': f'启动应用 {app_package}' if app_package else '启动应用',
                  'center_x': None, 'center_y': None}] + list(steps)
    for idx, st in enumerate(all_steps, 1):
        ed = st.get('element')
        element_obj = None
        # 兼容两种归一化格式：record_action 存 locator_value/value，
        # airtest_importer 可能直接存 value
        if ed and (ed.get('value') or ed.get('locator_value')):
            strategy_name = ed.get('locator_strategy', ed.get('strategy', 'xpath'))
            locator_val = ed.get('value') or ed.get('locator_value')
            locator_strategy, _ = LocatorStrategy.objects.get_or_create(name=strategy_name)
            element_obj, el_created = Element.objects.get_or_create(
                project=project,
                locator_strategy=locator_strategy,
                locator_value=locator_val,
                defaults={
                    'name': ed.get('name') or ed.get('chinese_name') or '未命名元素',
                    'element_type': 'INPUT' if st['action_type'] in ('fill', 'input', 'clear') else 'BUTTON',
                    'created_by': user,
                }
            )
            if el_created:
                created_elements += 1

        TestCaseStep.objects.create(
            test_case=test_case,
            step_number=idx,
            action_type=st['action_type'],
            element=element_obj,
            input_value=st.get('input_value', ''),
            wait_time=st.get('wait_time', 1000) or 1000,
            assert_type=st.get('assert_type', ''),
            assert_value=st.get('assert_value', ''),
            description=st.get('description', ''),
            center_x=ed.get('center_x') if ed else None,
            center_y=ed.get('center_y') if ed else None,
        )

    return test_case, created_elements, len(all_steps)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_recording_case(request):
    """结束录制并生成/更新测试用例（继续录制时追加步骤到已有用例）"""
    key = _recording_session_key(request)
    sess = RECORDING_SESSIONS.get(key)
    if not sess:
        return Response({'success': False, 'message': '没有进行中的录制会话'}, status=400)

    project = sess['project']
    case_name = (request.data.get('case_name') or '').strip() or sess['case_name']
    steps = sess['steps']
    continue_case_id = sess.get('continue_case_id')

    if not steps:
        _close_recording_session(key)
        return Response({'success': False, 'message': '尚未记录任何操作步骤，无法生成用例'}, status=400)

    try:
        # ---- 继续录制模式：删除旧步骤后重建全部步骤（旧+新） ----
        if continue_case_id:
            test_case = get_object_or_404(TestCase, id=continue_case_id)
            test_case.name = case_name
            test_case.save()
            # 删除旧步骤（元素保留，因为可能被其他用例引用）
            test_case.steps.all().delete()
            # 直接在原用例上重建全部步骤（旧+新）；不要调用
            # _build_test_case_from_steps（它会另建一个多余的 TestCase）
            created_elements = 0
            for idx, st in enumerate(steps, 1):
                ed = st.get('element')
                element_obj = None
                if ed and (ed.get('value') or ed.get('locator_value')):
                    strategy_name = ed.get('locator_strategy', ed.get('strategy', 'xpath'))
                    locator_val = ed.get('value') or ed.get('locator_value')
                    ls, _ = LocatorStrategy.objects.get_or_create(name=strategy_name)
                    element_obj, el_created = Element.objects.get_or_create(
                        project=project,
                        locator_strategy=ls,
                        locator_value=locator_val,
                        defaults={
                            'name': ed.get('name') or ed.get('chinese_name') or '未命名元素',
                            'element_type': 'INPUT' if st['action_type'] in ('fill', 'input', 'clear') else 'BUTTON',
                        }
                    )
                    if el_created:
                        created_elements += 1
                TestCaseStep.objects.update_or_create(
                    test_case=test_case,
                    step_number=idx,
                    defaults={
                        'action_type': st['action_type'],
                        'description': st.get('description', ''),
                        'input_value': st.get('input_value', ''),
                        'wait_time': st.get('wait_time', 1000) or 1000,
                        'assert_type': st.get('assert_type', ''),
                        'assert_value': st.get('assert_value', ''),
                        'element': element_obj,
                        'center_x': ed.get('center_x') if ed else None,
                        'center_y': ed.get('center_y') if ed else None,
                    }
                )
            step_count = len(steps)
            msg = f'已更新用例「{test_case.name}」，共 {step_count} 个步骤'
        else:
            test_case, created_elements, step_count = _build_test_case_from_steps(
                request.user, project, case_name, steps, sess['app_config'].package_name)
            msg = f'已生成用例「{test_case.name}」，包含 {step_count} 个步骤（含启动应用）'
    except Exception as e:
        _close_recording_session(key)
        return Response({'success': False, 'message': f'生成用例失败: {e}'}, status=500)
    finally:
        _close_recording_session(key)

    # 纯 Airtest 录制模式：额外导出可直接 `airtest run` 的脚本
    airtest_script = _airtest_script_for_session(sess, steps)

    return Response({
        'success': True,
        'message': msg,
        'case_id': test_case.id,
        'case_name': test_case.name,
        'step_count': step_count,
        'created_elements': created_elements,
        'engine_type': sess.get('engine_type', 'appium'),
        'airtest_script': airtest_script,
        'is_update': bool(continue_case_id),  # 告知前端是追加还是新建
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_airtest_script(request):
    """导入 Airtest / Poco 录制脚本（.air / .py），解析为统一步骤并生成 TestCase

    入参：
      - script: Airtest 脚本文本（与 script_file 二选一）
      - script_file: 上传的 .air 脚本文件
      - project_id: 目标 UI 项目 ID（必填）
      - case_name: 用例名称（可选，默认自动命名）
      - app_package: 被测应用包名（可选，用于「启动应用」步骤描述）
    返回生成的 case_id 与解析出的步骤列表。
    """
    script = request.data.get('script') or ''
    if not script and request.FILES.get('script_file'):
        try:
            script = request.FILES['script_file'].read().decode('utf-8', 'ignore')
        except Exception:
            script = ''
    if not script.strip():
        return Response({'success': False, 'message': '请提供 script 文本或上传 script_file（.air/.py）'}, status=400)

    project_id = request.data.get('project_id')
    if not project_id:
        return Response({'success': False, 'message': '缺少 project_id'}, status=400)
    try:
        project = get_object_or_404(UiProject, id=project_id)
    except Exception as e:
        return Response({'success': False, 'message': f'project_id 无效: {e}'}, status=400)

    case_name = (request.data.get('case_name') or '').strip() or f'Airtest导入_{timezone.now():%Y%m%d_%H%M%S}'

    try:
        from .airtest_importer import parse_airtest_script
        steps = parse_airtest_script(script)
    except Exception as e:
        return Response({'success': False, 'message': f'脚本解析失败: {e}'}, status=400)

    if not steps:
        return Response({'success': False, 'message': '未能从脚本中解析出任何操作步骤'}, status=400)

    try:
        test_case, created_elements, step_count = _build_test_case_from_steps(
            request.user, project, case_name, steps, request.data.get('app_package', ''))
    except Exception as e:
        return Response({'success': False, 'message': f'生成用例失败: {e}'}, status=500)

    return Response({
        'success': True,
        'message': f'已生成用例「{test_case.name}」，包含 {step_count} 个步骤（含启动应用）',
        'case_id': test_case.id,
        'case_name': test_case.name,
        'step_count': step_count,
        'created_elements': created_elements,
        'parsed_steps': steps,
    })








