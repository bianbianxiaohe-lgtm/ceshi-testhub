# Generated migration - projects initial
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='项目名称')),
                ('description', models.TextField(blank=True, null=True, verbose_name='项目描述')),
                ('status', models.CharField(choices=[('active', '活跃'), ('archived', '已归档')], default='active', max_length=20, verbose_name='状态')),
                ('knowledge_base_path', models.CharField(blank=True, default='', max_length=500, verbose_name='知识库文件目录')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={'verbose_name': '项目', 'verbose_name_plural': '项目', 'db_table': 'projects', 'ordering': ['-created_at']},
        ),
    ]
