from rest_framework import serializers
from .models import FeatureModule, TestPoint
from apps.users.serializers import UserSerializer
from apps.projects.serializers import ProjectSimpleSerializer


class FeatureModuleSerializer(serializers.ModelSerializer):
    """功能模块序列化器"""
    created_by = UserSerializer(read_only=True)
    project = ProjectSimpleSerializer(read_only=True)
    project_id = serializers.IntegerField(write_only=True, required=False)
    version_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    versions = serializers.SerializerMethodField()
    testcases_count = serializers.SerializerMethodField()

    class Meta:
        model = FeatureModule
        fields = ['id', 'name', 'description', 'project', 'project_id', 'parent', 'created_by',
                  'created_at', 'testcases_count', 'version_ids', 'versions']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def create(self, validated_data):
        # version_ids 是 M2M 字段，不能传给 objects.create()，需提前取出
        validated_data.pop('version_ids', None)
        return super().create(validated_data)

    def get_testcases_count(self, obj):
        return obj.testcases.count()

    def get_versions(self, obj):
        return [{'id': v.id, 'name': v.name} for v in obj.versions.all()]


class FeatureModuleSimpleSerializer(serializers.ModelSerializer):
    """功能模块简单序列化器，用于在测试用例中显示"""
    class Meta:
        model = FeatureModule
        fields = ['id', 'name', 'project_id']


class TestPointSerializer(serializers.ModelSerializer):
    """测试点序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    feature_module_name = serializers.CharField(source='feature_module.name', read_only=True)
    feature_module_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = TestPoint
        fields = ['id', 'name', 'description', 'feature_module', 'feature_module_id',
                  'feature_module_name', 'created_by', 'created_by_name', 'created_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'feature_module', 'created_by']

    def create(self, validated_data):
        feature_module_id = validated_data.pop('feature_module_id', None)
        if feature_module_id:
            validated_data['feature_module_id'] = feature_module_id
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class TestPointSimpleSerializer(serializers.ModelSerializer):
    """测试点简单序列化器"""
    class Meta:
        model = TestPoint
        fields = ['id', 'name', 'feature_module_id']
