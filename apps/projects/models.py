from django.db import models
from django.utils import timezone
from apps.users.models import User


class ProjectRole(models.Model):
    """
    项目角色（组织级「组」）。

    2026-09-20 用户需求："用户管理加一个角色，以后再创建项目的时候默认这个角色下的人
    能够对这些项目有权限，每个角色对应各个项目。"

    与 ProjectMember.role 的区别（⚠️ 别混淆）：
      - ProjectMember.role 是**项目级角色**：每个项目单独把人加进来，人多了要逐个加。
      - ProjectRole 是**组织级角色（组）**：人属于组，项目挂在组下，
        新建项目时选一个角色 → 该角色全员**自动**获得该项目的编辑权限。
    一个项目最多挂 1 个角色（用户确认："1、一个角色"）。

    权限边界（用户确认）：
      - 角色成员 → 可查看、可编辑该项目（含项目下的用例/版本/模块等内容）
      - **不可删除项目**（删除仅限项目负责人 + 管理员）
    """

    name = models.CharField(max_length=100, unique=True, verbose_name='角色名称')
    description = models.TextField(blank=True, default='', verbose_name='角色描述')
    members = models.ManyToManyField(
        User, blank=True, related_name='project_roles', verbose_name='角色成员'
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'project_roles'
        verbose_name = '项目角色'
        verbose_name_plural = '项目角色'
        ordering = ['name']

    def __str__(self):
        return self.name


class Project(models.Model):
    """项目模型"""
    STATUS_CHOICES = [
        ('active', '进行中'),
        ('paused', '暂停'),
        ('completed', '已完成'),
        ('archived', '已归档'),
    ]
    
    name = models.CharField(max_length=200, verbose_name='项目名称')
    description = models.TextField(blank=True, verbose_name='项目描述')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name='状态')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_projects', verbose_name='负责人', null=True, blank=True)
    members = models.ManyToManyField(User, through='ProjectMember', related_name='joined_projects', verbose_name='成员')
    # 归属角色（组织级"组"）：该角色全员自动获得本项目的编辑权限。
    # 留空 = 不挂角色，只有 owner / members 能改（存量项目默认就是空，由管理员手动挂）。
    # on_delete=SET_NULL：删角色不应连带删项目，只解除关联。
    role = models.ForeignKey(
        'ProjectRole', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='projects', verbose_name='归属角色',
        help_text='该角色下的成员自动拥有此项目的编辑权限（不含删除）'
    )
    # 知识库文件目录（服务器上 markdown 文件所在的绝对路径）
    knowledge_base_path = models.CharField(
        max_length=500, blank=True, default='',
        verbose_name='知识库文件目录',
        help_text='服务器上知识库 markdown 文件的绝对路径，留空则不启用文件型知识库'
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    def __str__(self):
        return self.name
    
    class Meta:
        db_table = 'projects'
        verbose_name = '项目'
        verbose_name_plural = '项目'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner'], name='idx_project_owner'),
            models.Index(fields=['status'], name='idx_project_status'),
        ]

class ProjectMember(models.Model):
    """项目成员"""
    ROLE_CHOICES = [
        ('owner', '负责人'),
        ('admin', '管理员'),
        ('developer', '开发者'),
        ('tester', '测试者'),
        ('viewer', '观察者'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='tester', verbose_name='角色')
    joined_at = models.DateTimeField(default=timezone.now, verbose_name='加入时间')
    
    class Meta:
        db_table = 'project_members'
        unique_together = ['project', 'user']
        verbose_name = '项目成员'
        verbose_name_plural = '项目成员'

class ProjectEnvironment(models.Model):
    """项目环境"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='environments')
    name = models.CharField(max_length=100, verbose_name='环境名称')
    base_url = models.URLField(verbose_name='基础URL')
    description = models.TextField(blank=True, verbose_name='环境描述')
    variables = models.JSONField(default=dict, verbose_name='环境变量')
    is_default = models.BooleanField(default=False, verbose_name='是否默认')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        db_table = 'project_environments'
        verbose_name = '项目环境'
        verbose_name_plural = '项目环境'


class ProjectKnowledge(models.Model):
    """项目知识库 - 为AI生成测试用例提供业务背景和上下文"""
    CATEGORY_CHOICES = [
        ('background', '业务背景'),
        ('terminology', '关键术语'),
        ('test_focus', '测试重点'),
        ('constraints', '约束条件'),
        ('notes', '注意事项'),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='knowledge_base',
        verbose_name='所属项目'
    )
    title = models.CharField(max_length=200, verbose_name='知识条目标题')
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='background',
        verbose_name='分类'
    )
    content = models.TextField(verbose_name='内容')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    version = models.ForeignKey(
        'versions.Version',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='knowledge_entries',
        verbose_name='适用版本（空=全项目通用）',
    )
    source = models.CharField(max_length=30, default='manual', verbose_name='来源')
    needs_review = models.BooleanField(
        default=False,
        verbose_name='待复核',
        help_text='自动沉淀（来源=zentao_coverage）的条目默认待复核，'
                  '人工确认前不进入向量召回；手动创建默认为 False'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='创建者'
    )
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'project_knowledge'
        verbose_name = '项目知识库'
        verbose_name_plural = '项目知识库'
        ordering = ['category', 'sort_order', '-created_at']

    def __str__(self):
        return f'[{self.get_category_display()}] {self.title}'
