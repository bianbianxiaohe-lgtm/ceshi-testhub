# -*- coding: utf-8 -*-
"""APP自动化项目管理视图"""
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import models
import logging

from .test_case_views import AppPagination
from ..models import AppProject
from ..serializers import (
    AppProjectSerializer,
    AppProjectCreateSerializer,
    AppProjectUpdateSerializer,
)

logger = logging.getLogger(__name__)

# AI 项目状态 → App 项目状态 映射
_AI_STATUS_MAP = {
    'active': 'IN_PROGRESS',
    'paused': 'NOT_STARTED',
    'completed': 'COMPLETED',
    'archived': 'COMPLETED',
}


class AppProjectViewSet(viewsets.ModelViewSet):
    """APP自动化项目 ViewSet"""
    queryset = AppProject.objects.all()
    permission_classes = [IsAuthenticated]
    pagination_class = AppPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'owner']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return AppProjectCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AppProjectUpdateSerializer
        return AppProjectSerializer

    def get_queryset(self):
        user = self.request.user
        return AppProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def list(self, request, *args, **kwargs):
        """
        列表：合并 App 自动化项目 + AI 用例生成项目（全局统一项目源）
        AI 项目标记 source='ai' 且 id 带 proj_ 前缀，前端据此禁用编辑/删除
        """
        # 1) 原生 App 项目（全部取出，后续与 AI 项目一起手动分页）
        queryset = self.filter_queryset(self.get_queryset())
        app_results = self.get_serializer(queryset, many=True).data

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
            logger.warning('加载 AI 项目失败: %s', e)
            ai_projects = []

        ai_results = []
        for p in ai_projects:
            mapped_status = _AI_STATUS_MAP.get(p.status, 'IN_PROGRESS')
            # 状态筛选：仅当未指定状态或匹配时加入
            if status and mapped_status != status:
                continue
            ai_results.append({
                'id': f'proj_{p.id}',
                'real_id': p.id,
                'name': p.name,
                'description': p.description or '',
                'status': mapped_status,
                'start_date': None,
                'end_date': None,
                'owner_name': p.owner.username if p.owner else None,
                'member_count': p.members.count(),
                'test_case_count': AiTestCase.objects.filter(project=p).count(),
                'test_suite_count': 0,
                'created_at': p.created_at.isoformat() if p.created_at else None,
                'updated_at': p.updated_at.isoformat() if p.updated_at else None,
                'source': 'ai',
            })

        # 3) 合并（App 项目在前，AI 项目在后）
        merged = list(app_results) + ai_results

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
