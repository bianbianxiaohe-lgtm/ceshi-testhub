# Generated migration for FeatureModule

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '__first__'),
        ('users', '__first__'),
    ]

    operations = [
        migrations.CreateModel(
            name='FeatureModule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='模块名称')),
                ('description', models.TextField(blank=True, verbose_name='模块描述')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='创建者')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feature_modules', to='projects.project', verbose_name='关联项目')),
            ],
            options={
                'verbose_name': '功能模块',
                'verbose_name_plural': '功能模块',
                'db_table': 'feature_modules',
                'ordering': ['project', 'name'],
                'unique_together': {('project', 'name')},
            },
        ),
    ]
