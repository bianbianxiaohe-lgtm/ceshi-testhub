from rest_framework import serializers
from .models import TestCase, TestCaseStep, TestCaseAttachment, TestCaseComment, TestCaseExecution
from apps.users.serializers import UserSerializer
from apps.versions.serializers import VersionSimpleSerializer
from apps.feature_modules.serializers import FeatureModuleSimpleSerializer, TestPointSimpleSerializer

class TestCaseStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestCaseStep
        fields = '__all__'

class TestCaseAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = UserSerializer(read_only=True)
    
    class Meta:
        model = TestCaseAttachment
        fields = '__all__'

class TestCaseCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    
    class Meta:
        model = TestCaseComment
        fields = '__all__'


class TestCaseExecutionSerializer(serializers.ModelSerializer):
    """执行记录序列化器"""
    executed_by_name = serializers.CharField(source='executed_by.username', read_only=True)
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    
    class Meta:
        model = TestCaseExecution
        fields = ['id', 'testcase', 'executed_by', 'executed_by_name', 'result', 'result_display', 'notes', 'executed_at']
        read_only_fields = ['id', 'executed_at']


class TestCaseExecutionCreateSerializer(serializers.ModelSerializer):
    """创建执行记录序列化器"""
    class Meta:
        model = TestCaseExecution
        fields = ['testcase', 'result', 'notes']

class ProjectSimpleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

class TestCaseSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    assignee = UserSerializer(read_only=True)
    project = ProjectSimpleSerializer(read_only=True)
    versions = VersionSimpleSerializer(many=True, read_only=True)
    feature_modules = FeatureModuleSimpleSerializer(many=True, read_only=True)
    test_point = TestPointSimpleSerializer(read_only=True)
    step_details = TestCaseStepSerializer(many=True, read_only=True)
    attachments = TestCaseAttachmentSerializer(many=True, read_only=True)
    comments = TestCaseCommentSerializer(many=True, read_only=True)
    latest_execution_result = serializers.CharField(read_only=True)
    latest_execution_at = serializers.DateTimeField(source='executions.first.executed_at', read_only=True, allow_null=True)
    
    class Meta:
        model = TestCase
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'latest_execution_result', 'latest_execution_at']

class TestCaseCreateSerializer(serializers.ModelSerializer):
    project_id = serializers.IntegerField(required=False, allow_null=True, help_text="项目ID，可选")
    source = serializers.ChoiceField(
        choices=TestCase.SOURCE_CHOICES,
        default='manual',
        required=False,
        help_text="用例来源：manual=人工编写，ai=AI生成",
    )
    version_ids = serializers.ListField(
        child=serializers.IntegerField(), 
        required=False, 
        allow_empty=True,
        help_text="关联版本ID列表"
    )
    feature_module_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        help_text="关联功能模块ID列表"
    )
    test_point_id = serializers.IntegerField(required=False, allow_null=True, help_text="关联测试点ID")
    
    class Meta:
        model = TestCase
        fields = [
            'title', 'description', 'preconditions', 'steps', 'expected_result', 
            'priority', 'status', 'test_type', 'tags', 'project_id', 'version_ids',
            'feature_module_ids', 'test_point_id', 'source'
        ]
    
    def create(self, validated_data):
        version_ids = validated_data.pop('version_ids', [])
        feature_module_ids = validated_data.pop('feature_module_ids', [])
        test_point_id = validated_data.pop('test_point_id', None)
        # project_id会在视图的perform_create中处理
        validated_data.pop('project_id', None)
        
        testcase = super().create(validated_data)
        
        # 设置版本关联
        if version_ids:
            testcase.versions.set(version_ids)
        
        # 设置功能模块关联
        if feature_module_ids:
            testcase.feature_modules.set(feature_module_ids)
        
        # 设置测试点
        if test_point_id:
            testcase.test_point_id = test_point_id
            testcase.save(update_fields=['test_point'])
        
        return testcase

class TestCaseUpdateSerializer(serializers.ModelSerializer):
    project_id = serializers.IntegerField(required=False, allow_null=True, help_text="项目ID，可选")
    version_ids = serializers.ListField(
        child=serializers.IntegerField(), 
        required=False, 
        allow_empty=True,
        help_text="关联版本ID列表"
    )
    feature_module_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        help_text="关联功能模块ID列表"
    )
    test_point_id = serializers.IntegerField(required=False, allow_null=True, help_text="关联测试点ID")
    
    class Meta:
        model = TestCase
        fields = [
            'title', 'description', 'preconditions', 'steps', 'expected_result', 
            'priority', 'status', 'test_type', 'tags', 'project_id', 'version_ids',
            'feature_module_ids', 'test_point_id', 'source'
        ]
    
    def update(self, instance, validated_data):
        version_ids = validated_data.pop('version_ids', None)
        feature_module_ids = validated_data.pop('feature_module_ids', None)
        test_point_id = validated_data.pop('test_point_id', None)
        # project_id会在视图中处理
        validated_data.pop('project_id', None)
        
        instance = super().update(instance, validated_data)
        
        # 更新版本关联
        if version_ids is not None:
            instance.versions.set(version_ids)
        
        # 更新功能模块关联
        if feature_module_ids is not None:
            instance.feature_modules.set(feature_module_ids)
        
        # 更新测试点
        if test_point_id is not None:
            instance.test_point_id = test_point_id
            instance.save(update_fields=['test_point'])
        
        return instance
