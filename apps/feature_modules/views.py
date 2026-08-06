from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from .models import FeatureModule, TestPoint
from .serializers import FeatureModuleSerializer, TestPointSerializer
from apps.projects.models import Project
from apps.core.mixins import ProjectScopedMixin, get_accessible_projects_for_user


class FeatureModuleListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    """功能模块列表和创建视图"""
    queryset = FeatureModule.objects.all()
    serializer_class = FeatureModuleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['project']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']
    ordering = ['project', 'name']

    def get_queryset(self):
        qs = super().get_queryset()
        version_id = self.request.query_params.get('version_id')
        if version_id:
            qs = qs.filter(versions__id=version_id)
        return qs.distinct()

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError
        user = self.request.user
        project_id = self.request.data.get('project_id')
        name = self.request.data.get('name', '').strip()
        version_ids = self.request.data.get('version_ids', [])
        project = None
        if project_id:
            try:
                project = self.get_accessible_projects().get(id=project_id)
            except Project.DoesNotExist:
                raise ValidationError({'project_id': '没有权限访问该项目或项目不存在'})

        if not project:
            raise ValidationError({'project_id': '请选择所属项目'})

        # 防重：同一项目下同名功能模块直接返回已有的（幂等）
        if name:
            existing = FeatureModule.objects.filter(project=project, name=name).first()
            if existing:
                serializer.instance = existing
                if version_ids:
                    existing.versions.add(*version_ids)
                return

        instance = serializer.save(created_by=user, project=project)
        if version_ids:
            instance.versions.set(version_ids)


class FeatureModuleDetailView(ProjectScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """功能模块详情视图"""
    queryset = FeatureModule.objects.all()
    serializer_class = FeatureModuleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_update(self, serializer):
        instance = serializer.save()
        version_ids = self.request.data.get('version_ids')
        if version_ids is not None:
            instance.versions.set(version_ids)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_project_feature_modules(request, project_id):
    """获取指定项目的功能模块列表（支持 version_id 过滤只返回该版本关联的模块）"""
    accessible_projects = get_accessible_projects_for_user(request.user)

    if not accessible_projects.filter(id=project_id).exists():
        return Response({'error': '没有权限访问该项目'}, status=status.HTTP_403_FORBIDDEN)

    modules = FeatureModule.objects.filter(project_id=project_id)
    # 按版本过滤：返回已关联该版本 + 未关联任何版本的模块（避免游离模块丢失）
    version_id = request.query_params.get('version_id')
    if version_id:
        from django.db.models import Q
        modules = modules.filter(Q(versions__id=version_id) | Q(versions__isnull=True) | Q(versions=None)).distinct()
    modules = modules.order_by('name')
    from .serializers import FeatureModuleSerializer
    serializer = FeatureModuleSerializer(modules, many=True)
    return Response(serializer.data)


# ─── TestPoint Views ───

class TestPointListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    """测试点列表和创建视图"""
    serializer_class = TestPointSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['feature_module']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'name']
    ordering = ['feature_module', 'name']

    def get_queryset(self):
        accessible_projects = self.get_accessible_projects()
        accessible_modules = FeatureModule.objects.filter(project__in=accessible_projects)
        return TestPoint.objects.filter(feature_module__in=accessible_modules)

    def perform_create(self, serializer):
        user = self.request.user
        feature_module_id = self.request.data.get('feature_module_id')
        name = self.request.data.get('name', '').strip()
        feature_module = None
        if feature_module_id:
            try:
                accessible_modules = FeatureModule.objects.filter(
                    project__in=self.get_accessible_projects()
                )
                feature_module = accessible_modules.get(id=feature_module_id)
            except FeatureModule.DoesNotExist:
                pass

        # 防重：同一功能模块下同名测试点直接返回已有的（幂等）
        if name and feature_module:
            existing = TestPoint.objects.filter(feature_module=feature_module, name=name).first()
            if existing:
                serializer.instance = existing
                return

        serializer.save(created_by=user, feature_module=feature_module)


class TestPointDetailView(ProjectScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """测试点详情视图"""
    serializer_class = TestPointSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        accessible_projects = self.get_accessible_projects()
        accessible_modules = FeatureModule.objects.filter(project__in=accessible_projects)
        return TestPoint.objects.filter(feature_module__in=accessible_modules)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_module_test_points(request, module_id):
    """获取指定功能模块下的测试点列表"""
    accessible_projects = get_accessible_projects_for_user(request.user)
    accessible_modules = FeatureModule.objects.filter(project__in=accessible_projects)

    if not accessible_modules.filter(id=module_id).exists():
        return Response({'error': '没有权限访问该功能模块'}, status=status.HTTP_403_FORBIDDEN)

    test_points = TestPoint.objects.filter(feature_module_id=module_id).order_by('name')
    from .serializers import TestPointSerializer
    serializer = TestPointSerializer(test_points, many=True)
    return Response(serializer.data)
