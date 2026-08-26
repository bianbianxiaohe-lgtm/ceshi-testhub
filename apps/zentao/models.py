from django.db import models
from django.utils import timezone

from apps.projects.models import Project
from apps.testcases.models import TestCase
from apps.versions.models import Version


class ZentaoConfig(models.Model):
    """禅道接入配置（一个 TestHub 版本对应一组禅道产品/执行）。"""

    name = models.CharField(max_length=100, default='禅道', verbose_name='配置名称')
    base_url = models.CharField(max_length=300, verbose_name='禅道地址')
    account = models.CharField(max_length=100, verbose_name='账号')
    password = models.CharField(max_length=200, verbose_name='密码')

    # 禅道侧映射：产品 / 执行 / 版本(build)
    # 新流程：配置只需填禅道地址+账号密码，登录后按「TestHub项目↔禅道产品名」映射
    # 自动定位产品，再拉该产品的版本(build)列表，选版本即可精确同步该版本 Bug。
    # 因此 product_id / build_id 由前端自动选中回填，用户无需手填。
    product_id = models.CharField(max_length=30, blank=True, default='', verbose_name='禅道产品ID')
    execution_id = models.CharField(max_length=30, blank=True, default='', verbose_name='禅道执行ID')
    build_id = models.CharField(max_length=30, blank=True, default='', verbose_name='禅道Build ID')
    build_name = models.CharField(max_length=100, blank=True, default='', verbose_name='禅道Build名称')
    opened_build_keyword = models.CharField(
        max_length=100, blank=True, default='', verbose_name='版本关键字(可选)',
        help_text='仅在不指定 Build 的旧模式下用于过滤：匹配 openedBuild 与标题。'
                  '新流程已按「产品+版本(Build)」精确拉取，无需填此关键字',
    )
    coverage_target = models.FloatField(default=90.0, verbose_name='覆盖率目标(%)')

    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='zentao_configs',
        verbose_name='TestHub项目',
    )
    version = models.ForeignKey(
        Version,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='zentao_configs',
        verbose_name='TestHub版本',
    )
    is_enabled = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'zentao_configs'
        verbose_name = '禅道配置'
        verbose_name_plural = '禅道配置'
        ordering = ['-created_at']

    def __str__(self):
        ver = self.version.name if self.version_id else '-'
        return f'{self.name}（{self.base_url} / 版本 {ver}）'


class ZentaoProductMapping(models.Model):
    """TestHub 项目 ↔ 禅道产品名称映射（用于自动匹配，如 轻卡日常 ↔ 卡鲁狸）。"""

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name='zentao_product_mapping',
        verbose_name='TestHub项目',
    )
    zentao_product_name = models.CharField(max_length=100, verbose_name='禅道产品名称')
    zentao_product_id = models.CharField(max_length=30, blank=True, default='', verbose_name='禅道产品ID')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'zentao_product_mappings'
        verbose_name = '禅道产品映射'
        verbose_name_plural = '禅道产品映射'

    def __str__(self):
        project_name = self.project.name if self.project_id else '-'
        return f'{project_name} ↔ {self.zentao_product_name}'


class ZentaoBug(models.Model):
    """从禅道同步过来的 Bug（长期入库，幂等 upsert）。"""

    config = models.ForeignKey(
        ZentaoConfig,
        on_delete=models.CASCADE,
        related_name='bugs',
        verbose_name='禅道配置',
    )
    version = models.ForeignKey(
        Version,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='zentao_bugs',
        verbose_name='关联TestHub版本',
    )
    zentao_id = models.CharField(max_length=30, verbose_name='禅道Bug ID')
    title = models.CharField(max_length=500, verbose_name='标题')
    steps = models.TextField(blank=True, default='', verbose_name='复现步骤(纯文本)')
    severity = models.CharField(max_length=20, blank=True, default='', verbose_name='严重程度')
    pri = models.CharField(max_length=20, blank=True, default='', verbose_name='优先级')
    status = models.CharField(max_length=30, blank=True, default='', verbose_name='状态')
    bug_type = models.CharField(max_length=50, blank=True, default='', verbose_name='Bug类型')
    execution = models.CharField(max_length=30, blank=True, default='', verbose_name='禅道执行ID')
    product = models.CharField(max_length=30, blank=True, default='', verbose_name='禅道产品ID')
    opened_build = models.CharField(max_length=100, blank=True, default='', verbose_name='发现版本')
    opened_by = models.CharField(max_length=100, blank=True, default='', verbose_name='创建人')
    opened_date = models.DateTimeField(null=True, blank=True, verbose_name='创建时间')
    assigned_to = models.CharField(max_length=100, blank=True, default='', verbose_name='指派给')
    resolved_by = models.CharField(max_length=100, blank=True, default='', verbose_name='解决人')
    resolution = models.CharField(max_length=100, blank=True, default='', verbose_name='解决方案')
    resolved_date = models.DateTimeField(null=True, blank=True, verbose_name='解决时间')
    raw_data = models.JSONField(default=dict, verbose_name='原始数据')
    is_active = models.BooleanField(default=True, verbose_name='是否在禅道仍存在')
    first_seen_at = models.DateTimeField(default=timezone.now, verbose_name='首次入库时间')
    last_seen_at = models.DateTimeField(default=timezone.now, verbose_name='最近同步时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'zentao_bugs'
        verbose_name = '禅道Bug'
        verbose_name_plural = '禅道Bug'
        ordering = ['-opened_date', '-id']
        unique_together = [['config', 'zentao_id']]
        indexes = [
            models.Index(fields=['config', 'is_active']),
            models.Index(fields=['version']),
        ]

    def __str__(self):
        return f'#{self.zentao_id} {self.title[:50]}'


class ZentaoSyncLog(models.Model):
    """禅道同步执行记录。"""

    STATUS_CHOICES = [
        ('running', '同步中'),
        ('success', '成功'),
        ('failed', '失败'),
    ]

    config = models.ForeignKey(
        ZentaoConfig,
        on_delete=models.CASCADE,
        related_name='sync_logs',
        verbose_name='禅道配置',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running', verbose_name='状态')
    total_count = models.IntegerField(default=0, verbose_name='禅道Bug总数')
    new_count = models.IntegerField(default=0, verbose_name='新增')
    updated_count = models.IntegerField(default=0, verbose_name='更新')
    deactivated_count = models.IntegerField(default=0, verbose_name='失效(已删除)')
    message = models.TextField(blank=True, default='', verbose_name='说明')
    detail = models.JSONField(default=dict, verbose_name='明细')
    started_at = models.DateTimeField(default=timezone.now, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')

    class Meta:
        db_table = 'zentao_sync_logs'
        verbose_name = '禅道同步记录'
        verbose_name_plural = '禅道同步记录'
        ordering = ['-started_at']


class CoverageReport(models.Model):
    """AI 用例对禅道 Bug 的覆盖率分析报告。"""

    STATUS_CHOICES = [
        ('running', '分析中'),
        ('success', '完成'),
        ('failed', '失败'),
    ]

    config = models.ForeignKey(
        ZentaoConfig,
        on_delete=models.CASCADE,
        related_name='coverage_reports',
        verbose_name='禅道配置',
    )
    version = models.ForeignKey(
        Version,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='zentao_coverage_reports',
        verbose_name='TestHub版本',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running', verbose_name='状态')
    total_bugs = models.IntegerField(default=0, verbose_name='Bug总数')
    covered_bugs = models.IntegerField(default=0, verbose_name='已覆盖')
    uncovered_bugs = models.IntegerField(default=0, verbose_name='未覆盖')
    coverage_rate = models.FloatField(default=0.0, verbose_name='覆盖率')
    matched_by = models.CharField(max_length=100, blank=True, default='', verbose_name='匹配方式')
    case_count = models.IntegerField(default=0, verbose_name='参与比对的用例数')
    error_message = models.TextField(blank=True, default='', verbose_name='错误信息')
    detail = models.JSONField(default=dict, verbose_name='明细')
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='zentao_coverage_reports',
        verbose_name='触发人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')

    class Meta:
        db_table = 'zentao_coverage_reports'
        verbose_name = '禅道覆盖率报告'
        verbose_name_plural = '禅道覆盖率报告'
        ordering = ['-created_at']


class CoverageItem(models.Model):
    """报告中的单条 Bug 覆盖判定。"""

    report = models.ForeignKey(
        CoverageReport,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='覆盖率报告',
    )
    bug = models.ForeignKey(
        ZentaoBug,
        on_delete=models.CASCADE,
        related_name='coverage_items',
        verbose_name='禅道Bug',
    )
    covered = models.BooleanField(default=False, verbose_name='是否覆盖')
    matched_testcase = models.ForeignKey(
        TestCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='zentao_coverage_items',
        verbose_name='匹配用例',
    )
    matched_case_title = models.CharField(max_length=300, blank=True, default='', verbose_name='匹配用例标题')
    match_score = models.FloatField(null=True, blank=True, verbose_name='语义相似度')
    matched_score = models.FloatField(null=True, blank=True, verbose_name='匹配用例相似度')
    judge_confidence = models.FloatField(null=True, blank=True, verbose_name='判定置信度(0-1)')
    candidates = models.JSONField(default=list, verbose_name='候选用例')
    reason = models.TextField(blank=True, default='', verbose_name='判定理由')
    suggestion = models.TextField(blank=True, default='', verbose_name='覆盖建议')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'zentao_coverage_items'
        verbose_name = '覆盖判定明细'
        verbose_name_plural = '覆盖判定明细'
        ordering = ['id']
