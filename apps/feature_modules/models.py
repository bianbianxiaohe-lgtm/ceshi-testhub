import logging
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone
from apps.users.models import User
from apps.projects.models import Project
from apps.versions.models import Version

logger = logging.getLogger('django')


class FeatureModule(models.Model):
    """功能模块模型 - 表示项目下的功能点"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='feature_modules', verbose_name='关联项目')
    versions = models.ManyToManyField(Version, related_name='feature_modules', blank=True, verbose_name='关联版本')
    name = models.CharField(max_length=100, verbose_name='模块名称')
    description = models.TextField(blank=True, verbose_name='模块描述')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='children', verbose_name='父模块')

    def __str__(self):
        return f"{self.project.name} / {self.name}"

    class Meta:
        db_table = 'feature_modules'
        verbose_name = '功能模块'
        verbose_name_plural = '功能模块'
        ordering = ['project', 'name']
        unique_together = ['project', 'name']


class TestPoint(models.Model):
    """测试点模型 - 功能模块下的具体测试子项"""
    feature_module = models.ForeignKey(FeatureModule, on_delete=models.CASCADE, related_name='test_points', verbose_name='关联功能模块')
    name = models.CharField(max_length=200, verbose_name='测试点名称')
    description = models.TextField(blank=True, verbose_name='测试点描述')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    def __str__(self):
        return f"{self.feature_module.name} / {self.name}"

    class Meta:
        db_table = 'test_points'
        verbose_name = '测试点'
        verbose_name_plural = '测试点'
        ordering = ['feature_module', 'name']
        unique_together = ['feature_module', 'name']


@receiver(pre_delete, sender=FeatureModule)
def _feature_module_pre_delete(sender, instance, **kwargs):
    """功能模块删除前的审计日志。

    覆盖任何删除路径（DRF 接口 / Django admin / 后台任务 / parent 级联删子模块）。
    用于排查"删除几个冗余模块却连带删掉大量正常模块"的问题——
    这里能记录每次被删模块的完整上下文，以及它是否是被父模块级联删除的。
    """
    try:
        tp_count = instance.test_points.count()
        child_count = instance.children.count()
        version_ids = list(instance.versions.values_list('id', flat=True))
        # 是否被子模块级联删除（parent 为 NULL 的非父模块自身删除时这里无意义）
        parent_desc = None
        if instance.parent_id:
            try:
                parent_desc = f"name={instance.parent.name!r}(id={instance.parent_id})"
            except Exception:  # noqa: BLE001
                parent_desc = f"(id={instance.parent_id})"
        logger.info(
            '[FEATURE_MODULE_PRE_DELETE] id=%s name=%r project_id=%s '
            'test_points=%s children=%s versions=%s parent=%s created_by_id=%s',
            instance.id, instance.name, instance.project_id,
            tp_count, child_count, version_ids, parent_desc, instance.created_by_id,
        )
    except Exception as e:  # noqa: BLE001 日志失败不影响删除
        logger.warning('[FEATURE_MODULE_PRE_DELETE] 记录日志失败 id=%s err=%s',
                       getattr(instance, 'id', None), e)
