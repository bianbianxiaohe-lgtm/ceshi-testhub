from django.urls import path
from rest_framework.routers import DefaultRouter
from . import views, project_list_views

# 项目角色（组织级组）：仅管理员可增删改，所有人可读（项目表单要选角色）
_role_router = DefaultRouter()
_role_router.register(r'roles', views.ProjectRoleViewSet, basename='project-role')

urlpatterns = [
    path('', views.ProjectListCreateView.as_view(), name='project-list'),
    path('all/', views.get_all_projects, name='all-projects'),
    path('<int:pk>/', views.ProjectDetailView.as_view(), name='project-detail'),
    path('<int:project_id>/members/', views.get_project_members, name='get-project-members'),
    path('<int:project_id>/members/add/', views.add_project_member, name='add-member'),
    path('<int:project_id>/members/<int:member_id>/', views.remove_project_member, name='remove-member'),
    path('<int:project_id>/environments/', views.ProjectEnvironmentListCreateView.as_view(), name='environment-list'),
    path('list/', project_list_views.user_projects_list, name='user-projects-list'),
    # 知识库（数据库模式，保留兼容）
    path('<int:project_id>/knowledge/', views.ProjectKnowledgeListCreateView.as_view(), name='knowledge-list'),
    path('<int:project_id>/knowledge/<int:pk>/', views.ProjectKnowledgeDetailView.as_view(), name='knowledge-detail'),
    # 知识条目确认前的语义去重预检
    path('<int:project_id>/knowledge/check-duplicate/', views.check_kb_duplicate, name='knowledge-check-duplicate'),
    # 知识库（文件系统模式 - Markdown 文件驱动）
    path('<int:project_id>/knowledge/fs/tree/', views.knowledge_fs_tree, name='knowledge-fs-tree'),
    path('<int:project_id>/knowledge/fs/create/', views.knowledge_fs_file_create, name='knowledge-fs-file-create'),
    path('<int:project_id>/knowledge/fs/file/', views.knowledge_fs_file, name='knowledge-fs-file-root'),
    path('<int:project_id>/knowledge/fs/file/<path:file_path>/', views.knowledge_fs_file, name='knowledge-fs-file'),
] + _role_router.urls