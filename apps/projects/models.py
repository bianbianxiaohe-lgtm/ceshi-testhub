from django.db import models
from django.utils import timezone
from apps.users.models import User

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
