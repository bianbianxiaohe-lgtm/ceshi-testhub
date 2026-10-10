from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, UserProfile

class UserSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'avatar')

class UserSerializer(serializers.ModelSerializer):
    """
    用户序列化器（用户管理页列表/详情用）。

    2026-09-20 新增 `roles` / `role_names`：**只读**展示该用户所属的项目角色。
    角色的成员在「用户管理 → 角色」里维护，这里只负责"看得见"，不在这里改
    （用户明确要求："用户管理可以看到所属角色 只是不支持修改"）。
    依赖 ProjectRole.members 的 related_name='project_roles'。
    """
    roles = serializers.SerializerMethodField()
    role_names = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 
                 'avatar', 'phone', 'department', 'position', 'is_active',
                 'date_joined', 'created_at', 'updated_at',
                 'roles', 'role_names']
        read_only_fields = ['id', 'date_joined', 'created_at', 'updated_at']

    def get_roles(self, obj):
        return [{'id': r.id, 'name': r.name} for r in obj.project_roles.all()]

    def get_role_names(self, obj):
        return [r.name for r in obj.project_roles.all()]

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm',
                 'first_name', 'last_name', 'phone', 'department', 'position']
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("密码不一致")
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    
    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        
        if username and password:
            user = authenticate(username=username, password=password)
            if not user:
                raise serializers.ValidationError('用户名或密码错误')
            if not user.is_active:
                raise serializers.ValidationError('用户已被禁用')
        else:
            raise serializers.ValidationError('用户名和密码不能为空')
        
        attrs['user'] = user
        return attrs

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = '__all__'