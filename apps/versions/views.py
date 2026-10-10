from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from .models import Version
from .serializers import VersionSerializer, VersionCreateSerializer
from apps.projects.models import Project
from apps.core.mixins import (
    get_accessible_projects_for_user, get_writable_projects_for_user,
)

# 版本管理视图
class VersionListCreateView(generics.ListCreateAPIView):
    """版本列表和创建视图"""
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_baseline']  # 移除projects，手动处理
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return VersionCreateSerializer
        return VersionSerializer
    
    def get_queryset(self):
        # 只显示用户有权限访问的项目的版本
        accessible_projects = get_accessible_projects_for_user(self.request.user)
        
        queryset = Version.objects.filter(projects__in=accessible_projects).distinct()
        
        # 手动处理项目筛选
        project_id = self.request.query_params.get('projects')
        if project_id and project_id.strip():  # 检查是否为空或空字符串
            try:
                project_id = int(project_id)
                queryset = queryset.filter(projects__id=project_id)
            except (ValueError, TypeError):
                # 如果无法转换为整数，忽略此筛选条件
                pass
        
        return queryset
    
    def perform_create(self, serializer):
        user = self.request.user
        project_ids = serializer.validated_data.get('project_ids')

        # 检查项目**写**权限。
        # ⚠️ 必须用 get_writable_projects_for_user：项目查看已对全员放开，
        # 若这里也用"可查看"集合，任何登录用户就能往别人的项目里建版本。
        accessible_projects = get_writable_projects_for_user(user)

        # 验证用户对所有指定项目都有权限
        accessible_project_ids = set(accessible_projects.values_list('id', flat=True))
        requested_project_ids = set(project_ids)
        
        if not requested_project_ids.issubset(accessible_project_ids):
            from rest_framework.exceptions import ValidationError
            raise ValidationError("没有权限访问部分项目")
        
        serializer.save(created_by=user)

class VersionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    版本详情 / 编辑 / 删除。

    2026-09-20：查看放开（全员可见），但**改/删**仍限"我负责或参与的项目"。
    """
    serializer_class = VersionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # 读取放开：登录用户可看到全部项目的版本
        return Version.objects.filter(
            projects__in=get_accessible_projects_for_user(self.request.user)
        ).distinct()

    def _ensure_writable(self, version):
        """改/删前校验：该版本关联的项目里，至少要有一个是我能写的。"""
        writable = get_writable_projects_for_user(self.request.user)
        writable_ids = set(writable.values_list('id', flat=True))
        ver_project_ids = set(version.projects.values_list('id', flat=True))
        if not (ver_project_ids & writable_ids):
            return Response(
                {'error': '只有版本所属项目的负责人、项目成员或管理员可以修改/删除该版本'},
                status=status.HTTP_403_FORBIDDEN
            )
        return None

    def update(self, request, *args, **kwargs):
        denied = self._ensure_writable(self.get_object())
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self._ensure_writable(self.get_object())
        if denied:
            return denied
        return super().destroy(request, *args, **kwargs)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_project_versions(request, project_id):
    """获取指定项目的版本列表"""
    # 检查项目权限
    accessible_projects = get_accessible_projects_for_user(request.user)
    
    if not accessible_projects.filter(id=project_id).exists():
        return Response({'error': '没有权限访问该项目'}, status=status.HTTP_403_FORBIDDEN)
    
    versions = Version.objects.filter(projects__id=project_id).order_by('-created_at')
    serializer = VersionSerializer(versions, many=True)
    return Response(serializer.data)
