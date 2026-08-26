from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0005_add_app_pipeline_run'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BusinessAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='动作名')),
                ('description', models.CharField(blank=True, max_length=200, verbose_name='描述')),
                ('action', models.CharField(
                    choices=[('aiAct', 'aiAct（自然语言执行）'), ('aiTap', 'aiTap（点击）'),
                             ('aiInput', 'aiInput（输入）'), ('aiQuery', 'aiQuery（提取）'),
                             ('assert', 'assert（断言）')],
                    default='aiAct', max_length=20, verbose_name='动作类型')),
                ('prompt', models.TextField(verbose_name='语义指令')),
                ('selector_hint', models.CharField(blank=True, max_length=300, verbose_name='定位提示')),
                ('value', models.CharField(blank=True, max_length=300, verbose_name='输入值')),
                ('wait_ms', models.IntegerField(default=0, verbose_name='等待毫秒')),
                ('extract', models.JSONField(blank=True, default=list, verbose_name='提取配置')),
                ('assert_config', models.JSONField(blank=True, default=dict, verbose_name='断言配置')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL, verbose_name='创建人')),
            ],
            options={
                'db_table': 'ui_business_actions',
                'verbose_name': '业务动作',
                'verbose_name_plural': '业务动作',
                'ordering': ['name'],
            },
        ),
    ]
