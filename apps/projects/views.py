from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from django.conf import settings
from .models import Project, ProjectMember, ProjectEnvironment, ProjectKnowledge
from .serializers import (
    ProjectSerializer, ProjectCreateSerializer,
    ProjectMemberSerializer, ProjectEnvironmentSerializer,
    ProjectKnowledgeSerializer
)
from apps.core.mixins import OwnerOrMemberMixin
import os
import re
import logging
from urllib.parse import unquote

logger = logging.getLogger(__name__)

class ProjectListCreateView(OwnerOrMemberMixin, generics.ListCreateAPIView):
    queryset = Project.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'owner']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at', 'name']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ProjectCreateSerializer
        return ProjectSerializer

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_all_projects(request):
    """获取所有项目列表，用于下拉选择等场景"""
    projects = Project.objects.all().values('id', 'name', 'description', 'status')
    return Response(list(projects))

class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_project_member(request, project_id):
    try:
        project = Project.objects.get(id=project_id)
        if project.owner != request.user and not (request.user.is_staff or request.user.is_superuser):
            return Response({'error': '无权限添加成员'}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = ProjectMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(project=project)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_project_members(request, project_id):
    """获取项目成员列表"""
    try:
        project = Project.objects.get(id=project_id)
        
        # 检查用户是否有权限查看项目成员
        if not (project.owner == request.user or 
                ProjectMember.objects.filter(project=project, user=request.user).exists() or
                (request.user.is_staff or request.user.is_superuser)):
            return Response({'error': '无权限查看项目成员'}, status=status.HTTP_403_FORBIDDEN)
        
        # 获取项目成员，包括项目所有者
        members = []
        
        # 添加项目所有者
        members.append({
            'id': project.owner.id,
            'username': project.owner.username,
            'email': project.owner.email,
            'first_name': project.owner.first_name,
            'last_name': project.owner.last_name,
            'role': 'owner'
        })
        
        # 添加项目成员
        project_members = ProjectMember.objects.filter(project=project).select_related('user')
        for member in project_members:
            members.append({
                'id': member.user.id,
                'username': member.user.username,
                'email': member.user.email,
                'first_name': member.user.first_name,
                'last_name': member.user.last_name,
                'role': member.role
            })
        
        return Response(members)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def remove_project_member(request, project_id, member_id):
    try:
        project = Project.objects.get(id=project_id)
        if project.owner != request.user and not (request.user.is_staff or request.user.is_superuser):
            return Response({'error': '无权限删除成员'}, status=status.HTTP_403_FORBIDDEN)
        
        member = ProjectMember.objects.get(id=member_id, project=project)
        member.delete()
        return Response({'message': '成员删除成功'})
    except (Project.DoesNotExist, ProjectMember.DoesNotExist):
        return Response({'error': '项目或成员不存在'}, status=status.HTTP_404_NOT_FOUND)

class ProjectEnvironmentListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectEnvironmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        project_id = self.kwargs['project_id']
        return ProjectEnvironment.objects.filter(project_id=project_id)
    
    def perform_create(self, serializer):
        project_id = self.kwargs['project_id']
        serializer.save(project_id=project_id)


# ============================================================
# 项目知识库 CRUD
# ============================================================

class ProjectKnowledgeListCreateView(generics.ListCreateAPIView):
    """列出 / 创建 某项目的知识库条目"""
    serializer_class = ProjectKnowledgeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        project_id = self.kwargs['project_id']
        queryset = ProjectKnowledge.objects.filter(project_id=project_id)
        # 支持按分类过滤
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        # 支持只看启用的
        active_only = self.request.query_params.get('active_only')
        if active_only and active_only.lower() == 'true':
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        project_id = self.kwargs['project_id']
        serializer.save(
            project_id=project_id,
            created_by=self.request.user
        )


class ProjectKnowledgeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """查看 / 修改 / 删除 单条知识库条目"""
    serializer_class = ProjectKnowledgeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        project_id = self.kwargs['project_id']
        return ProjectKnowledge.objects.filter(project_id=project_id)


# ============================================================
# 文件系统知识库（Markdown 文件驱动）
# ============================================================

def _resolve_knowledge_path(project: Project) -> str:
    """解析项目的知识库目录路径，若未配置或不存在返回空"""
    raw = (project.knowledge_base_path or '').strip()
    if not raw:
        return ''
    # 替换环境变量占位符
    path = raw
    for match in re.finditer(r'\$\{(\w+)\}', raw):
        env_var = match.group(1)
        path = path.replace(match.group(0), os.environ.get(env_var, ''))
    # 替换 ~ 为用户主目录
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return ''
    return os.path.abspath(path)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def knowledge_fs_tree(request, project_id):
    """
    扫描项目知识库目录，返回文件树结构。
    仅扫描 .md 文件，按文件名自然排序。
    返回格式：
    [
      {
        "path": "01-product-overview.md",
        "name": "01-product-overview.md",
        "title": "产品概述",
        "size": 1234,
        "modified": "2026-06-16T14:00:00"
      },
      ...
    ]
    """
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=404)

    kb_path = _resolve_knowledge_path(project)
    if not kb_path:
        return Response({'files': [], 'path': '', 'message': '未配置知识库目录或目录不存在'})

    def scan_dir(dir_path: str, rel_prefix: str = '') -> list:
        """递归扫描目录，返回文件/目录列表"""
        items = []
        def _natural_key(s):
            """自然排序：将数字部分转为整数比较，确保 1.9 < 1.10 < 1.11"""
            return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', s)]

        try:
            entries = sorted(os.scandir(dir_path), key=lambda e: _natural_key(e.name))
        except PermissionError:
            return items

        for entry in entries:
            if entry.name.startswith('.'):
                continue
            rel = f"{rel_prefix}{entry.name}" if rel_prefix else entry.name
            if entry.is_file():
                if entry.name.endswith('.md'):
                    stat = entry.stat()
                    # 从文件名提取显示标题（去掉编号前缀和 .md）
                    title = re.sub(r'^\d{1,3}[-_]', '', entry.name)
                    title = re.sub(r'\.md$', '', title)
                    items.append({
                        'type': 'file',
                        'path': rel,
                        'name': entry.name,
                        'title': title,
                        'size': stat.st_size,
                        'modified': entry.stat().st_mtime,
                    })
            elif entry.is_dir():
                children = scan_dir(entry.path, f"{rel}/")
                if children:
                    items.append({
                        'type': 'directory',
                        'path': rel,
                        'name': entry.name,
                        'children': children,
                    })
        return items

    files = scan_dir(kb_path)
    return Response({
        'files': files,
        'path': kb_path,
    })


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([permissions.IsAuthenticated])
def knowledge_fs_file(request, project_id, file_path):
    """
    GET    获取单个知识库 Markdown 文件的原始内容。
    PUT    保存（覆盖）单个知识库 Markdown 文件。请求体: { "content": "..." }
    PATCH  重命名文件。请求体: { "new_name": "新文件名.md" }
    DELETE 删除单个知识库 Markdown 文件。
    """
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=404)

    kb_path = _resolve_knowledge_path(project)
    if not kb_path:
        return Response({'error': '未配置知识库目录或目录不存在'}, status=404)

    # 对路径参数进行 URL 解码（前端 encodeURIComponent 编码的子目录路径需要还原）
    file_path = unquote(file_path)

    # 安全检查：防止路径穿越
    full_path = os.path.normpath(os.path.join(kb_path, file_path))
    if not full_path.startswith(os.path.abspath(kb_path)):
        return Response({'error': '非法的文件路径'}, status=403)

    if request.method == 'GET':
        if not os.path.isfile(full_path) or not full_path.endswith('.md'):
            return Response({'error': '文件不存在或非 Markdown 文件'}, status=404)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            stat = os.stat(full_path)
            return Response({
                'path': file_path,
                'name': os.path.basename(full_path),
                'content': content,
                'size': stat.st_size,
                'modified': stat.st_mtime,
            })
        except Exception as e:
            logger.error(f'读取知识库文件失败 {full_path}: {e}')
            return Response({'error': f'读取文件失败: {str(e)}'}, status=500)

    elif request.method == 'PUT':
        if not full_path.endswith('.md'):
            return Response({'error': '只允许编辑 .md 文件'}, status=403)
        if not os.path.isfile(full_path):
            return Response({'error': '文件不存在'}, status=404)
        content = request.data.get('content', '')
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            stat = os.stat(full_path)
            return Response({
                'path': file_path,
                'name': os.path.basename(full_path),
                'content': content,
                'size': stat.st_size,
                'modified': stat.st_mtime,
            })
        except Exception as e:
            logger.error(f'写入知识库文件失败 {full_path}: {e}')
            return Response({'error': f'写入文件失败: {str(e)}'}, status=500)

    elif request.method == 'PATCH':
        """重命名文件"""
        if not full_path.endswith('.md'):
            return Response({'error': '只允许重命名 .md 文件'}, status=403)
        if not os.path.isfile(full_path):
            return Response({'error': '文件不存在'}, status=404)

        new_name = request.data.get('new_name', '').strip()
        if not new_name:
            return Response({'error': '新文件名不能为空'}, status=400)
        if not new_name.endswith('.md'):
            new_name += '.md'
        # 安全检查：防止路径穿越
        if '/' in new_name or '\\' in new_name or '..' in new_name:
            return Response({'error': '文件名不能包含路径字符'}, status=400)

        new_full_path = os.path.join(os.path.dirname(full_path), new_name)
        if os.path.exists(new_full_path):
            return Response({'error': f'文件「{new_name}」已存在'}, status=409)

        try:
            os.rename(full_path, new_full_path)
            # 返回新的相对路径
            dir_rel = os.path.dirname(file_path)
            new_rel_path = f"{dir_rel}/{new_name}" if dir_rel else new_name
            stat = os.stat(new_full_path)
            return Response({
                'path': new_rel_path,
                'name': new_name,
                'message': '重命名成功',
                'size': stat.st_size,
                'modified': stat.st_mtime,
            })
        except Exception as e:
            logger.error(f'重命名知识库文件失败 {full_path} -> {new_name}: {e}')
            return Response({'error': f'重命名失败: {str(e)}'}, status=500)

    elif request.method == 'DELETE':
        if not os.path.isfile(full_path) or not full_path.endswith('.md'):
            return Response({'error': '文件不存在或非 Markdown 文件'}, status=404)
        try:
            os.remove(full_path)
            return Response({'message': '删除成功'})
        except Exception as e:
            logger.error(f'删除知识库文件失败 {full_path}: {e}')
            return Response({'error': f'删除文件失败: {str(e)}'}, status=500)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def knowledge_fs_file_create(request, project_id):
    """
    新建知识库 Markdown 文件。
    请求体: { "path": "relative/path/file.md", "content": "..." }
    """
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return Response({'error': '项目不存在'}, status=404)

    kb_path = _resolve_knowledge_path(project)
    if not kb_path:
        return Response({'error': '未配置知识库目录或目录不存在'}, status=404)

    rel_path = (request.data.get('path', '') or '').strip().lstrip('/')
    if not rel_path or not rel_path.endswith('.md'):
        return Response({'error': '文件名必须以 .md 结尾'}, status=400)

    # 安全检查：防止路径穿越
    full_path = os.path.normpath(os.path.join(kb_path, rel_path))
    if not full_path.startswith(os.path.abspath(kb_path)):
        return Response({'error': '非法的文件路径'}, status=403)

    if os.path.exists(full_path):
        return Response({'error': '文件已存在'}, status=400)

    content = request.data.get('content', '')
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        stat = os.stat(full_path)
        return Response({
            'path': rel_path,
            'name': os.path.basename(full_path),
            'content': content,
            'size': stat.st_size,
            'modified': stat.st_mtime,
        }, status=201)
    except Exception as e:
        logger.error(f'创建知识库文件失败 {full_path}: {e}')
        return Response({'error': f'创建文件失败: {str(e)}'}, status=500)