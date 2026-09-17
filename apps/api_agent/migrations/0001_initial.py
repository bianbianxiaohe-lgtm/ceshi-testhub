import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api_testing', '0003_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='APISpec',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200, verbose_name='文档名称')),
                ('version', models.CharField(max_length=50, verbose_name='文档版本')),
                ('spec_format', models.CharField(choices=[('openapi3', 'OpenAPI 3.x'), ('swagger2', 'Swagger 2.0'), ('yaml', 'YAML'), ('json', 'JSON')], default='openapi3', max_length=20, verbose_name='文档格式')),
                ('spec_json', models.JSONField(verbose_name='完整 Spec 内容')),
                ('endpoint_count', models.IntegerField(default=0, verbose_name='接口数量')),
                ('file_name', models.CharField(blank=True, default='', max_length=500, verbose_name='原始文件名')),
                ('notes', models.TextField(blank=True, default='', verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='导入时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='imported_specs', to=settings.AUTH_USER_MODEL, verbose_name='导入者')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_specs', to='api_testing.ApiProject', verbose_name='所属项目')),
            ],
            options={
                'verbose_name': 'API 文档版本',
                'verbose_name_plural': 'API 文档版本',
                'db_table': 'api_agent_specs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='APIEndpoint',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('path', models.CharField(max_length=500, verbose_name='接口路径')),
                ('method', models.CharField(choices=[('GET', 'GET'), ('POST', 'POST'), ('PUT', 'PUT'), ('PATCH', 'PATCH'), ('DELETE', 'DELETE'), ('HEAD', 'HEAD'), ('OPTIONS', 'OPTIONS')], max_length=10, verbose_name='HTTP 方法')),
                ('summary', models.CharField(blank=True, default='', max_length=500, verbose_name='接口简述')),
                ('description', models.TextField(blank=True, default='', verbose_name='接口描述')),
                ('tags', models.JSONField(default=list, verbose_name='标签')),
                ('parameters', models.JSONField(default=list, verbose_name='请求参数')),
                ('request_body', models.JSONField(blank=True, null=True, verbose_name='请求体 Schema')),
                ('responses', models.JSONField(default=dict, verbose_name='响应 Schema')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('spec', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='endpoints', to='api_agent.APISpec', verbose_name='所属文档')),
            ],
            options={
                'verbose_name': 'API 接口定义',
                'verbose_name_plural': 'API 接口定义',
                'db_table': 'api_agent_endpoints',
                'ordering': ['path', 'method'],
                'unique_together': {('spec', 'path', 'method')},
            },
        ),
        migrations.CreateModel(
            name='APIChange',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('endpoint_path', models.CharField(max_length=500, verbose_name='接口路径')),
                ('endpoint_method', models.CharField(max_length=10, verbose_name='HTTP 方法')),
                ('change_type', models.CharField(choices=[('added', '新增接口'), ('removed', '删除接口'), ('method_changed', '方法变更'), ('path_changed', '路径变更'), ('param_added_required', '新增必填参数'), ('param_removed', '参数删除'), ('param_type_changed', '参数类型变更'), ('response_field_added', '响应新增字段'), ('response_field_removed', '响应字段删除'), ('response_type_changed', '响应类型变更'), ('deprecated', '标记废弃'), ('other', '其他')], max_length=30, verbose_name='变更类型')),
                ('severity', models.CharField(choices=[('breaking', '破坏性变更'), ('warning', '警告'), ('info', '信息')], default='info', max_length=20, verbose_name='严重程度')),
                ('detail', models.JSONField(verbose_name='变更详情')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('affected_endpoint', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='changes', to='api_agent.APIEndpoint', verbose_name='受影响的接口')),
                ('new_spec', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='changes_as_new', to='api_agent.APISpec', verbose_name='新版本')),
                ('old_spec', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='changes_as_old', to='api_agent.APISpec', verbose_name='旧版本')),
            ],
            options={
                'verbose_name': '接口变更记录',
                'verbose_name_plural': '接口变更记录',
                'db_table': 'api_agent_changes',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='EndpointMapping',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('match_status', models.CharField(choices=[('matched', '已匹配'), ('diverged', '已偏离'), ('unmapped', '未映射')], default='unmapped', max_length=20, verbose_name='匹配状态')),
                ('last_checked_at', models.DateTimeField(blank=True, null=True, verbose_name='上次检查时间')),
                ('divergence_detail', models.JSONField(blank=True, null=True, verbose_name='偏离详情')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('api_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='spec_mappings', to='api_testing.ApiRequest', verbose_name='映射的测试用例')),
                ('endpoint', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='mapping', to='api_agent.APIEndpoint', verbose_name='文档接口')),
            ],
            options={
                'verbose_name': '端点映射',
                'verbose_name_plural': '端点映射',
                'db_table': 'api_agent_endpoint_mappings',
            },
        ),
    ]
