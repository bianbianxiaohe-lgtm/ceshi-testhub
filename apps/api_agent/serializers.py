from rest_framework import serializers
from .models import APISpec, APIEndpoint, APIChange, EndpointMapping


class APISpecSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()

    class Meta:
        model = APISpec
        fields = [
            'id', 'project', 'project_name', 'name', 'version', 'spec_format',
            'endpoint_count', 'file_name', 'notes', 'created_by', 'created_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'endpoint_count', 'created_at', 'updated_at']

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by else ''

    def get_project_name(self, obj):
        return obj.project.name


class APISpecCreateSerializer(serializers.ModelSerializer):
    """用于创建/导入 spec，接受 spec_json 文件内容"""
    spec_content = serializers.CharField(write_only=True, required=True, help_text='OpenAPI JSON 字符串')

    class Meta:
        model = APISpec
        fields = [
            'id', 'project', 'name', 'version', 'spec_format',
            'file_name', 'notes', 'spec_content',
        ]


class APIEndpointSerializer(serializers.ModelSerializer):
    mapping_status = serializers.SerializerMethodField()
    api_request_id = serializers.SerializerMethodField()
    api_request_name = serializers.SerializerMethodField()

    class Meta:
        model = APIEndpoint
        fields = [
            'id', 'spec', 'path', 'method', 'summary', 'description',
            'tags', 'parameters', 'request_body', 'responses',
            'mapping_status', 'api_request_id', 'api_request_name',
            'created_at',
        ]

    def get_mapping_status(self, obj):
        try:
            return obj.mapping.match_status
        except EndpointMapping.DoesNotExist:
            return 'unmapped'

    def get_api_request_id(self, obj):
        try:
            return str(obj.mapping.api_request_id) if obj.mapping.api_request_id else None
        except EndpointMapping.DoesNotExist:
            return None

    def get_api_request_name(self, obj):
        try:
            return obj.mapping.api_request.name if obj.mapping.api_request else ''
        except EndpointMapping.DoesNotExist:
            return ''


class APIChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = APIChange
        fields = [
            'id', 'old_spec', 'new_spec', 'endpoint_path', 'endpoint_method',
            'change_type', 'severity', 'detail', 'affected_endpoint',
            'created_at',
        ]


class EndpointMappingSerializer(serializers.ModelSerializer):
    endpoint_path = serializers.SerializerMethodField()
    endpoint_method = serializers.SerializerMethodField()

    class Meta:
        model = EndpointMapping
        fields = [
            'id', 'endpoint', 'endpoint_path', 'endpoint_method',
            'api_request', 'match_status', 'last_checked_at',
            'divergence_detail', 'created_at', 'updated_at',
        ]

    def get_endpoint_path(self, obj):
        return obj.endpoint.path

    def get_endpoint_method(self, obj):
        return obj.endpoint.method


# ── Agent 对话用序列化器 ──

class ChatMessageSerializer(serializers.Serializer):
    message = serializers.CharField(required=True)
    project_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    conversation_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class ToolExecuteSerializer(serializers.Serializer):
    tool_name = serializers.CharField(required=True)
    project_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    spec_json = serializers.JSONField(required=False)
    spec_name = serializers.CharField(required=False, allow_blank=True)
    spec_version = serializers.CharField(required=False, allow_blank=True)
    spec_format = serializers.CharField(required=False, allow_blank=True)
    file_name = serializers.CharField(required=False, allow_blank=True)
    old_spec_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    new_spec_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    endpoint_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    execution_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
