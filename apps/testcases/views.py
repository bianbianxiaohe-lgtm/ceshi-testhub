from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from django.shortcuts import get_object_or_404
from .models import TestCase, TestCaseStep, TestCaseAttachment, TestCaseComment, TestCaseExecution
from .serializers import (
    TestCaseSerializer, TestCaseCreateSerializer, TestCaseUpdateSerializer,
    TestCaseExecutionSerializer, TestCaseExecutionCreateSerializer
)
from apps.projects.models import Project
from apps.core.mixins import ProjectScopedMixin

class TestCaseListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    queryset = TestCase.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['priority', 'status', 'test_type', 'project']
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'updated_at', 'priority', 'sort_order']
    # sort_order 升序优先（业务顺序：墨刀采纳的用例按生成顺序 1,2,3... 排列），
    # 其次 created_at 升序（同 sort_order 时早创建的在前），保证用例库顺序与生成顺序一致。
    ordering = ['sort_order', 'created_at', 'id']
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TestCaseCreateSerializer
        return TestCaseSerializer
    
    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('executions')
        
        # 版本筛选
        version = self.request.query_params.get('version', None)
        if version:
            qs = qs.filter(versions__id=version)
        
        # 功能模块筛选
        feature_module = self.request.query_params.get('feature_module', None)
        if feature_module:
            qs = qs.filter(feature_modules__id=feature_module)
        
        # 测试点筛选
        test_point = self.request.query_params.get('test_point', None)
        if test_point:
            qs = qs.filter(test_point_id=test_point)
        
        # 按标签筛选（如 tags=冒烟）
        tag_filter = self.request.query_params.get('tags', None)
        if tag_filter:
            qs = qs.filter(tags__contains=[tag_filter])
        
        return qs.distinct()
    
    def perform_create(self, serializer):
        user = self.request.user
        project_id = self.request.data.get('project_id')
        
        # 获取用户有权限的项目
        accessible_projects = self.get_accessible_projects()
        
        if project_id:
            # 检查指定的项目是否存在且用户有权限
            try:
                project = accessible_projects.get(id=project_id)
            except Project.DoesNotExist:
                # 如果指定项目不存在或无权限，使用第一个可访问的项目
                project = accessible_projects.first()
                if not project:
                    # 如果用户没有任何项目，创建默认项目
                    project = Project.objects.create(
                        name="默认项目",
                        owner=user,
                        description='系统自动创建的默认项目'
                    )
        else:
            # 没有指定项目，使用第一个可访问的项目
            project = accessible_projects.first()
            if not project:
                # 如果用户没有任何项目，创建默认项目
                project = Project.objects.create(
                    name="默认项目",
                    owner=user,
                    description='系统自动创建的默认项目'
                )
        
        serializer.save(author=user, project=project)

class TestCaseDetailView(ProjectScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = TestCase.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return TestCaseUpdateSerializer
        return TestCaseSerializer
    
    def perform_update(self, serializer):
        user = self.request.user
        project_id = self.request.data.get('project_id')
        
        if project_id:
            # 检查指定的项目是否存在且用户有权限
            accessible_projects = self.get_accessible_projects()
            try:
                project = accessible_projects.get(id=project_id)
                serializer.save(project=project)
            except Project.DoesNotExist:
                # 如果指定项目不存在或无权限，保持原项目不变
                serializer.save()
        else:
            # 没有指定项目，保持原项目不变
            serializer.save()


class TestCaseExecuteView(generics.CreateAPIView):
    """执行测试用例（通过/失败）"""
    serializer_class = TestCaseExecutionCreateSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def perform_create(self, serializer):
        testcase_id = self.kwargs.get('pk')
        testcase = get_object_or_404(TestCase, pk=testcase_id)
        serializer.save(
            testcase=testcase,
            executed_by=self.request.user
        )


class TestCaseExecutionListView(generics.ListAPIView):
    """查看测试用例执行历史"""
    serializer_class = TestCaseExecutionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        testcase_id = self.kwargs.get('pk')
        return TestCaseExecution.objects.filter(
            testcase_id=testcase_id
        ).select_related('executed_by').order_by('-executed_at')
