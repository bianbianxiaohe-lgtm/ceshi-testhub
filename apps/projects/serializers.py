from rest_framework import serializers
from .models import (
    Project, ProjectMember, ProjectEnvironment, ProjectKnowledge, ProjectRole,
)
from apps.users.models import User
from apps.users.serializers import UserSerializer

class ProjectSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ('id', 'name')

class ProjectEnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectEnvironment
        fields = '__all__'

class ProjectMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = ProjectMember
        fields = ['id', 'user', 'user_id', 'role', 'joined_at']

class ProjectRoleSerializer(serializers.ModelSerializer):
    """
    项目角色（组织级组）。

    member_ids  只写；members 只读（用于展示成员名单）。
    projects    只读；project_ids 只写但**可选**（用于展示 / 批量调整归属）。

    ⚠️ 项目归属的唯一"设置入口"是项目管理页（`PATCH /projects/{id}/` 带 `role`），
      本序列化器的 `project_ids` 只作为**程序化批量调整**的补充通道，前端角色页不传它。
      语义（传了才生效，不传 = 完全不动）：
        - project_ids 传了：其中选中的项目 role 设为本角色（会从原角色"抢"过来），
          原本属于本角色但本次没选中的项目 role 清空（解除关联）——即"所见即所得"。
        - project_ids 不传：项目的归属保持原样，**不会被清空**。
      两个入口不要同时被前端使用，否则会互相覆盖。

    project_count 便于在用户管理页看到"这个角色挂了几个项目"，
    避免管理员误删还在用的角色。
    """
    members = UserSerializer(many=True, read_only=True)
    member_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False,
        queryset=User.objects.all(), source='members'
    )
    projects = ProjectSimpleSerializer(many=True, read_only=True)
    project_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, required=False,
        queryset=Project.objects.all()
    )
    project_count = serializers.SerializerMethodField()

    class Meta:
        model = ProjectRole
        fields = ['id', 'name', 'description',
                  'members', 'member_ids',
                  'projects', 'project_ids',
                  'project_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_project_count(self, obj):
        return obj.projects.count()

    def _sync_projects(self, role, project_ids):
        """双向同步：选中的挂到本角色，未选中的（原属本角色）解除关联。"""
        wanted = set(project_ids or [])
        # 挂上选中的
        if wanted:
            Project.objects.filter(id__in=wanted).update(role=role)
        # 解除本次没选中的（仅限原本属于本角色的）
        Project.objects.filter(role=role).exclude(id__in=wanted).update(role=None)

    def create(self, validated_data):
        project_ids = validated_data.pop('project_ids', None)
        role = super().create(validated_data)
        if project_ids is not None:
            self._sync_projects(role, project_ids)
        return role

    def update(self, instance, validated_data):
        # project_ids 没传 = 不调整项目归属（避免 PATCH 时把项目清空）
        project_ids = validated_data.pop('project_ids', None)
        role = super().update(instance, validated_data)
        if project_ids is not None:
            self._sync_projects(role, project_ids)
        return role


class ProjectSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    members = ProjectMemberSerializer(source='projectmember_set', many=True, read_only=True)
    environments = ProjectEnvironmentSerializer(many=True, read_only=True)
    # 只读展示（前端列表要显示"归属角色"）
    role_name = serializers.CharField(source='role.name', read_only=True, default='')
    # 当前用户对该项目的能力标记，前端据此决定是否显示「删除」「编辑」按钮。
    # ⚠️ 以前端隐藏为体验、以后端校验为准 —— 后端权限见 core/mixins.py。
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'status', 'owner', 'members',
                  'environments', 'knowledge_base_path', 'role', 'role_name',
                  'can_edit', 'can_delete', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_can_edit(self, obj):
        from apps.core.mixins import can_manage_project
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        return can_manage_project(user, obj)

    def get_can_delete(self, obj):
        from apps.core.mixins import can_delete_project
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        return can_delete_project(user, obj)


class ProjectCreateSerializer(serializers.ModelSerializer):
    # 创建时可选指定归属角色（该角色全员自动获得编辑权）
    role = serializers.PrimaryKeyRelatedField(
        queryset=ProjectRole.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Project
        fields = ['name', 'description', 'status', 'knowledge_base_path', 'role']

    def create(self, validated_data):
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)


class ProjectKnowledgeSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = ProjectKnowledge
        fields = [
            'id', 'project', 'title', 'category', 'category_display',
            'content', 'is_active', 'sort_order', 'source', 'needs_review',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']