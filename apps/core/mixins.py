"""
公共权限 Mixin —— 消除各 View 中重复的 Q(owner=user) | Q(members=user) 查询。

权限策略（2026-09-20 调整，用户明确要求）：
- superuser / staff：可查看和操作所有项目及资源
- **项目可见性：全体登录用户都能查看所有项目**（含项目下的用例/版本/模块等内容）
- **写操作（新增/修改/删除）：仅项目负责人(owner)、项目成员(members)、管理员**
- **删除项目：仅项目负责人(owner) 或管理员**

⚠️ 注意区分「查看」与「操作」：
   - 列表/详情这类**只读**接口 → 用 `ProjectReadableMixin`（全员可见）
   - create / update / destroy 这类**写**接口 → 用 `ProjectWritableMixin`（受限）
   - 只读放开是刻意的产品决策（"每个人都可以查看别人创建的项目"），
     不要把只读策略套到写接口上。

三种使用场景：
1. OwnerOrMemberMixin —— 模型本身有 owner/members 字段（如 ApiProject、Project）
2. ProjectScopedMixin  —— 模型通过 project 外键关联到 Project（如 TestCase、ApiCollection）
3. get_accessible_projects_for_user() —— 函数视图（FBV）中复用同一查询逻辑
"""

from django.db import models
from rest_framework import permissions
from apps.projects.models import Project


def _is_superuser(user):
    """判断用户是否为超级管理员"""
    if user is None or not user.is_authenticated:
        return False
    return user.is_staff or user.is_superuser


def get_accessible_projects_for_user(user):
    """
    获取用户有权限访问的项目 queryset。

    2026-09-20 起：**查看不再受限**，所有登录用户都能看到全部项目。
    （函数名保留，避免大规模改调用点；语义已从"可访问"变为"可查看"。）

    - 未登录：空
    - 其他：全部项目
    """
    if user is None or not user.is_authenticated:
        return Project.objects.none()
    return Project.objects.all()


def is_role_member(user, project) -> bool:
    """
    用户是否为项目**归属角色**的成员（2026-09-20 新增）。

    角色成员自动获得该项目的编辑权限（查看本来就已全员放开），
    但**不含删除**（删除仅限负责人 + 管理员，见 can_delete_project）。
    """
    if user is None or not user.is_authenticated:
        return False
    role_id = getattr(project, 'role_id', None)
    if not role_id:
        return False
    return project.role.members.filter(id=user.id).exists()


def get_writable_projects_for_user(user):
    """
    获取用户有**写权限**的项目 queryset（修改项目及项目下的资源）。

    2026-09-20 起 = 负责人(owner) ∪ 项目成员(members) ∪ **归属角色的成员**。

    - superuser / staff：全部项目
    - 普通用户：以上三者之一的项目
    ⚠️ 注意这里**不包含**"删除项目"的权限（删除另见 can_delete_project）。
    """
    if _is_superuser(user):
        return Project.objects.all()
    if user is None or not user.is_authenticated:
        return Project.objects.none()
    return Project.objects.filter(
        models.Q(owner=user)
        | models.Q(members=user)
        | models.Q(role__members=user)
    ).distinct()


def filter_by_owner_or_member(queryset, user):
    """
    【写操作用】对任意含 owner (FK) 和 members (M2M) 字段的 queryset 做写权限过滤。
    适用于 ApiProject、UiProject 等与 Project 同构的模型。
    - superuser：全部记录
    - 普通用户：owner 或 member

    ⚠️ 只用于**写**场景（改/删/以及"能被修改的资源列表"）。
       **纯查看列表请用 `filter_visible(queryset, user)`**，否则用户会看不到别人的项目。

    用法：
        qs = filter_by_owner_or_member(ApiProject.objects.all(), request.user)
    """
    if _is_superuser(user):
        return queryset.distinct()
    if user is None or not user.is_authenticated:
        return queryset.none()
    return queryset.filter(
        models.Q(owner=user) | models.Q(members=user)
    ).distinct()


def filter_visible(queryset, user):
    """
    【查看用】返回用户**可见**的记录 —— 登录用户可见全部。

    与 filter_by_owner_or_member 的区别就是"只读放开"：
       - 查看列表/详情 → filter_visible
       - 修改/删除    → filter_by_owner_or_member

    用法：
        qs = filter_visible(ApiProject.objects.all(), request.user)
    """
    if user is None or not user.is_authenticated:
        return queryset.none()
    return queryset.distinct()


class OwnerOrMemberMixin:
    """
    【写权限】适用于模型自身包含 owner (FK) 和 members (M2M) 字段的 ViewSet。
    - superuser：全部项目
    - 普通用户：owner 或 member

    ⚠️ 语义 = "我能改哪些"，不是"我能看哪些"。
       只读接口（list/retrieve）不要用这个 mixin，用 ProjectReadableMixin。

    用法：
        class ApiProjectViewSet(ProjectWritableMixin, viewsets.ModelViewSet):
            queryset = ApiProject.objects.all()
            ...
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if _is_superuser(self.request.user):
            return qs.distinct()
        user = self.request.user
        return qs.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()


class ProjectReadableMixin:
    """
    【读权限】项目及其内容对**全体登录用户**可见（2026-09-20 用户明确要求）。

    使用场景：项目列表、项目详情、以及"项目下的内容"列表/详情
    （用例、版本、功能模块、测试点、知识库……）。

    注意：这不等于放开写。写操作仍需在 View 上叠加
    `ProjectWritableMixin` 或对象级权限判断。
    """

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, 'user', None)
        if user is None or not user.is_authenticated:
            return qs.none()
        return qs.distinct()


def can_manage_project(user, project) -> bool:
    """
    是否有权**修改**项目（改名/改描述/改状态等）。

    2026-09-20 起 = 负责人(owner) ∪ 项目成员(members) ∪ **归属角色成员** ∪ 管理员。
    其他登录用户只读（查看已全员放开）。
    """
    if project is None:
        return False
    if _is_superuser(user):
        return True
    if user is None or not user.is_authenticated:
        return False
    if getattr(project, 'owner_id', None) == user.id:
        return True
    if project.members.filter(id=user.id).exists():
        return True
    return is_role_member(user, project)


def can_delete_project(user, project) -> bool:
    """
    是否有权**删除**项目 —— 仅项目负责人(owner) 或管理员。

    这是用户明确要求的核心约束："每个人都能查看别人创建的项目，只是不能删除"。
    ⚠️ 成员（members）也**不能**删；删项目是不可逆操作，从严控制。
    """
    if project is None:
        return False
    if _is_superuser(user):
        return True
    if user is None or not user.is_authenticated:
        return False
    return getattr(project, 'owner_id', None) == user.id


class IsProjectOwnerOrAdmin(permissions.BasePermission):
    """
    对象级权限：仅项目负责人(owner) 或管理员可操作。

    用于删除等高风险动作：
        class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
            permission_classes = [permissions.IsAuthenticated, IsProjectOwnerOrAdmin]
            def get_permissions(self):
                # 只有删除才要求 owner/admin，查看和编辑放开
                if self.request.method == 'DELETE':
                    return [permissions.IsAuthenticated(), IsProjectOwnerOrAdmin()]
                return [permissions.IsAuthenticated()]
    """

    message = '只有项目负责人或管理员可以删除项目'

    def has_object_permission(self, request, view, obj):
        return can_delete_project(request.user, obj)


class ProjectScopedMixin:
    """
    适用于通过 project 外键关联到 Project 的模型 View（如 TestCase、FeatureModule）。

    权限（2026-09-20 调整）：
      - **查看**（list/retrieve）：全部登录用户可见全部项目下的内容
      - **写**（create/update/destroy）：仅"我负责或参与的项目"下的内容

    提供两个方法：
      - get_accessible_projects()  —— 写场景用（我负责/参与的项目）
      - get_visible_projects()     —— 读场景用（全部项目）

    ⚠️ 本 mixin 的 get_queryset 只负责"看得到什么"（放开），
       写权限由各 View 在 perform_create/perform_update/destroy 里用
       get_accessible_projects() 判定 —— 不要退化回只用 get_queryset 限制。

    用法：
        class TestCaseListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
            queryset = TestCase.objects.all()
            # perform_create 里 project 必须取自 get_accessible_projects()
            # （即"我能写的项目"），不能取自 get_visible_projects()
    """

    def get_visible_projects(self):
        """当前用户**可查看**的项目（登录即可见全部）"""
        return get_accessible_projects_for_user(self.request.user)

    def get_accessible_projects(self):
        """
        当前用户**可写**的项目（仅自己负责/参与的）。

        ⚠️ 这个方法被 perform_create / perform_update 用来校验"能不能写进这个项目"，
           语义是写权限，**不要**改成返回全部项目。
        """
        return get_writable_projects_for_user(self.request.user)

    def get_queryset(self):
        # 查看放开：所有登录用户都能看到全部项目下的内容
        qs = super().get_queryset()
        return qs.filter(project__in=self.get_visible_projects())

