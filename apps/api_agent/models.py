import uuid
from django.db import models
from django.conf import settings


class APISpec(models.Model):
    """被测产品的 OpenAPI 文档版本"""
    SPEC_FORMAT_CHOICES = [
        ('openapi3', 'OpenAPI 3.x'),
        ('swagger2', 'Swagger 2.0'),
        ('yapi', 'YApi'),
        ('postman', 'Postman'),
        ('yaml', 'YAML'),
        ('json', 'JSON'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        'api_testing.ApiProject',
        on_delete=models.CASCADE,
        related_name='api_specs',
        verbose_name='所属项目',
    )
    name = models.CharField(max_length=200, verbose_name='文档名称')
    version = models.CharField(max_length=50, verbose_name='文档版本')
    spec_format = models.CharField(
        max_length=20, choices=SPEC_FORMAT_CHOICES, default='openapi3',
        verbose_name='文档格式',
    )
    spec_json = models.JSONField(verbose_name='完整 Spec 内容')
    endpoint_count = models.IntegerField(default=0, verbose_name='接口数量')
    file_name = models.CharField(max_length=500, blank=True, default='', verbose_name='原始文件名')
    notes = models.TextField(blank=True, default='', verbose_name='备注')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='imported_specs',
        verbose_name='导入者',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='导入时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'api_agent_specs'
        verbose_name = 'API 文档版本'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.project.name} - {self.name} v{self.version}'


class APIEndpoint(models.Model):
    """从 OpenAPI 文档解析出的单个接口定义"""
    METHOD_CHOICES = [
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('PATCH', 'PATCH'),
        ('DELETE', 'DELETE'),
        ('HEAD', 'HEAD'),
        ('OPTIONS', 'OPTIONS'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spec = models.ForeignKey(
        APISpec,
        on_delete=models.CASCADE,
        related_name='endpoints',
        verbose_name='所属文档',
    )
    path = models.CharField(max_length=500, verbose_name='接口路径')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, verbose_name='HTTP 方法')
    summary = models.CharField(max_length=500, blank=True, default='', verbose_name='接口简述')
    description = models.TextField(blank=True, default='', verbose_name='接口描述')
    tags = models.JSONField(default=list, verbose_name='标签')
    parameters = models.JSONField(default=list, verbose_name='请求参数')
    request_body = models.JSONField(null=True, blank=True, verbose_name='请求体 Schema')
    responses = models.JSONField(default=dict, verbose_name='响应 Schema')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'api_agent_endpoints'
        verbose_name = 'API 接口定义'
        verbose_name_plural = verbose_name
        ordering = ['path', 'method']
        unique_together = [['spec', 'path', 'method']]

    @property
    def full_identifier(self):
        return f'{self.method} {self.path}'

    def __str__(self):
        return f'{self.method} {self.path}'


class EndpointMapping(models.Model):
    """文档接口 与 TestHub 中 ApiRequest 测试用例的映射关系"""
    STATUS_CHOICES = [
        ('matched', '已匹配'),
        ('diverged', '已偏离'),
        ('unmapped', '未映射'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.OneToOneField(
        APIEndpoint,
        on_delete=models.CASCADE,
        related_name='mapping',
        verbose_name='文档接口',
    )
    api_request = models.ForeignKey(
        'api_testing.ApiRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='spec_mappings',
        verbose_name='映射的测试用例',
    )
    match_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='unmapped',
        verbose_name='匹配状态',
    )
    last_checked_at = models.DateTimeField(null=True, blank=True, verbose_name='上次检查时间')
    divergence_detail = models.JSONField(null=True, blank=True, verbose_name='偏离详情')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'api_agent_endpoint_mappings'
        verbose_name = '端点映射'
        verbose_name_plural = verbose_name

    def __str__(self):
        api_name = self.api_request.name if self.api_request else '(未映射)'
        return f'{self.endpoint.full_identifier} → {api_name}'


class APIChange(models.Model):
    """文档版本间的接口变更记录"""
    SEVERITY_CHOICES = [
        ('breaking', '破坏性变更'),
        ('warning', '警告'),
        ('info', '信息'),
    ]
    CHANGE_TYPE_CHOICES = [
        ('added', '新增接口'),
        ('removed', '删除接口'),
        ('method_changed', '方法变更'),
        ('path_changed', '路径变更'),
        ('param_added_required', '新增必填参数'),
        ('param_removed', '参数删除'),
        ('param_type_changed', '参数类型变更'),
        ('response_field_added', '响应新增字段'),
        ('response_field_removed', '响应字段删除'),
        ('response_type_changed', '响应类型变更'),
        ('deprecated', '标记废弃'),
        ('other', '其他'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    old_spec = models.ForeignKey(
        APISpec, on_delete=models.CASCADE, related_name='changes_as_old',
        verbose_name='旧版本',
    )
    new_spec = models.ForeignKey(
        APISpec, on_delete=models.CASCADE, related_name='changes_as_new',
        verbose_name='新版本',
    )
    endpoint_path = models.CharField(max_length=500, verbose_name='接口路径')
    endpoint_method = models.CharField(max_length=10, verbose_name='HTTP 方法')
    change_type = models.CharField(
        max_length=30, choices=CHANGE_TYPE_CHOICES, verbose_name='变更类型',
    )
    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default='info',
        verbose_name='严重程度',
    )
    detail = models.JSONField(verbose_name='变更详情')

    affected_endpoint = models.ForeignKey(
        APIEndpoint, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='changes', verbose_name='受影响的接口',
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'api_agent_changes'
        verbose_name = '接口变更记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.severity}] {self.change_type} - {self.endpoint_method} {self.endpoint_path}'
