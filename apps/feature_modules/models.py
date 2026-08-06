from django.db import models
from django.utils import timezone
from apps.users.models import User
from apps.projects.models import Project
from apps.versions.models import Version


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
