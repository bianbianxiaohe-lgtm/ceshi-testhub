from rest_framework import serializers
import json
from .models import (
    RequirementDocument, RequirementAnalysis, BusinessRequirement,
    GeneratedTestCase, AnalysisTask, AIModelConfig, PromptConfig, TestCaseGenerationTask,
    GenerationConfig, GeneratedRequirementDoc, RequirementAnalysisResult, ClarificationQuestion,
    ModaoPrototype, ModaoPage
)


class RequirementDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.username', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = RequirementDocument
        fields = ['id', 'title', 'file', 'file_url', 'document_type', 'document_type_display', 
                 'status', 'status_display', 'uploaded_by', 'uploaded_by_name', 'project', 
                 'project_name', 'created_at', 'updated_at', 'file_size', 'extracted_text']
        read_only_fields = ['uploaded_by', 'file_size', 'extracted_text']
    
    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None


class BusinessRequirementSerializer(serializers.ModelSerializer):
    requirement_type_display = serializers.CharField(source='get_requirement_type_display', read_only=True)
    requirement_level_display = serializers.CharField(source='get_requirement_level_display', read_only=True)
    parent_requirement_name = serializers.CharField(source='parent_requirement.requirement_name', read_only=True)
    
    class Meta:
        model = BusinessRequirement
        fields = ['id', 'requirement_id', 'requirement_name', 'requirement_type', 
                 'requirement_type_display', 'parent_requirement', 'parent_requirement_name',
                 'module', 'requirement_level', 'requirement_level_display', 'reviewer', 
                 'estimated_hours', 'description', 'acceptance_criteria', 'created_at', 'updated_at']


class RequirementAnalysisSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_id = serializers.IntegerField(source='document.id', read_only=True)
    requirements = BusinessRequirementSerializer(many=True, read_only=True)
    
    class Meta:
        model = RequirementAnalysis
        fields = ['id', 'document_id', 'document_title', 'analysis_report', 
                 'requirements_count', 'analysis_time', 'created_at', 'updated_at', 'requirements']


class GeneratedTestCaseSerializer(serializers.ModelSerializer):
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    requirement_name = serializers.CharField(source='requirement.requirement_name', read_only=True)
    requirement_id_display = serializers.CharField(source='requirement.requirement_id', read_only=True)
    
    class Meta:
        model = GeneratedTestCase
        fields = ['id', 'case_id', 'title', 'priority', 'priority_display', 'precondition',
                 'test_steps', 'expected_result', 'status', 'status_display', 'generated_by_ai',
                 'reviewed_by_ai', 'review_comments', 'requirement', 'requirement_name', 
                 'requirement_id_display', 'created_at', 'updated_at']


class AnalysisTaskSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True)
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = AnalysisTask
        fields = ['id', 'task_id', 'task_type', 'task_type_display', 'document', 'document_title',
                 'status', 'status_display', 'progress', 'result', 'error_message', 
                 'started_at', 'completed_at', 'created_at', 'duration']
        read_only_fields = ['task_id', 'result', 'error_message', 'started_at', 'completed_at']
    
    def get_duration(self, obj):
        if obj.started_at and obj.completed_at:
            return (obj.completed_at - obj.started_at).total_seconds()
        return None


class DocumentUploadSerializer(serializers.ModelSerializer):
    """文档上传专用序列化器"""
    class Meta:
        model = RequirementDocument
        fields = ['id', 'title', 'file', 'project']
    
    def create(self, validated_data):
        # 自动设置上传者
        user = self.context['request'].user
        validated_data['uploaded_by'] = user
        
        # 根据文件扩展名设置文档类型
        file = validated_data['file']
        if file.name.lower().endswith('.pdf'):
            validated_data['document_type'] = 'pdf'
        elif file.name.lower().endswith(('.doc', '.docx')):
            validated_data['document_type'] = 'docx'
        elif file.name.lower().endswith('.txt'):
            validated_data['document_type'] = 'txt'
        elif file.name.lower().endswith('.md'):
            validated_data['document_type'] = 'md'
        
        # 设置文件大小
        validated_data['file_size'] = file.size
        
        return super().create(validated_data)


class TestCaseGenerationRequestSerializer(serializers.Serializer):
    """测试用例生成请求序列化器"""
    requirement_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="需求ID列表"
    )
    test_level = serializers.ChoiceField(
        choices=[('unit', '单元测试'), ('integration', '集成测试'), ('system', '系统测试'), ('acceptance', '验收测试')],
        default='system',
        help_text="测试级别"
    )
    test_priority = serializers.ChoiceField(
        choices=[('P0', '最高优先级'), ('P1', '高优先级'), ('P2', '中优先级'), ('P3', '低优先级')],
        default='P1',
        help_text="测试优先级"
    )
    test_case_count = serializers.IntegerField(
        min_value=1,
        max_value=200,
        default=50,
        help_text="生成测试用例数量"
    )


class TestCaseReviewRequestSerializer(serializers.Serializer):
    """测试用例评审请求序列化器"""
    test_case_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="测试用例ID列表"
    )
    review_criteria = serializers.CharField(
        max_length=500,
        default="检查测试用例的完整性、准确性和可执行性",
        help_text="评审标准"
    )


class AIModelConfigSerializer(serializers.ModelSerializer):
    """AI模型配置序列化器"""
    model_type_display = serializers.CharField(source='get_model_type_display', read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    api_key_masked = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = AIModelConfig
        fields = ['id', 'name', 'model_type', 'model_type_display', 'role', 'role_display',
                 'api_key', 'api_key_masked', 'base_url', 'model_name', 'max_tokens', 'temperature', 'top_p', 
                 'is_active', 'created_by', 'created_by_name', 'created_at', 'updated_at']
        read_only_fields = ['created_by', 'created_by_name']
        extra_kwargs = {
            'api_key': {'write_only': True}  # API Key只用于写入，不在响应中返回
        }
    
    def get_api_key_masked(self, obj):
        """返回掩码版本的API Key"""
        if obj.api_key:
            # 显示前3个字符和后4个字符，中间用*替代
            if len(obj.api_key) > 7:
                return f"{obj.api_key[:3]}{'*' * (len(obj.api_key) - 7)}{obj.api_key[-4:]}"
            else:
                return '*' * len(obj.api_key)
        return ''
    
    def create(self, validated_data):
        # 自动设置创建者
        user = self.context['request'].user
        validated_data['created_by'] = user
        
        return super().create(validated_data)


class PromptConfigSerializer(serializers.ModelSerializer):
    """提示词配置序列化器"""
    prompt_type_display = serializers.CharField(source='get_prompt_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = PromptConfig
        fields = ['id', 'name', 'prompt_type', 'prompt_type_display', 'content', 'is_active',
                 'created_by', 'created_by_name', 'created_at', 'updated_at']
        read_only_fields = ['created_by', 'created_by_name']
    
    def create(self, validated_data):
        # 自动设置创建者
        user = self.context['request'].user
        validated_data['created_by'] = user
        
        return super().create(validated_data)


class TestCaseGenerationTaskSerializer(serializers.ModelSerializer):
    """测试用例生成任务序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    writer_model_name = serializers.CharField(source='writer_model_config.name', read_only=True)
    reviewer_model_name = serializers.CharField(source='reviewer_model_config.name', read_only=True)
    writer_prompt_name = serializers.CharField(source='writer_prompt_config.name', read_only=True)
    reviewer_prompt_name = serializers.CharField(source='reviewer_prompt_config.name', read_only=True)
    version_name = serializers.CharField(source='version.name', read_only=True)
    feature_module_name = serializers.CharField(source='feature_module.name', read_only=True)
    test_point_name = serializers.CharField(source='test_point.name', read_only=True)
    generation_mode_display = serializers.CharField(source='get_generation_mode_display', read_only=True)
    review_status = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = TestCaseGenerationTask
        fields = ['id', 'task_id', 'title', 'requirement_text', 'status', 'status_display',
                 'progress', 'project', 'project_name', 'version', 'version_name',
                 'feature_module', 'feature_module_name', 'test_point', 'test_point_name',
                 'generation_mode', 'generation_mode_display',
                 'writer_model_config', 'writer_model_name', 
                 'reviewer_model_config', 'reviewer_model_name', 'writer_prompt_config', 'writer_prompt_name',
                 'reviewer_prompt_config', 'reviewer_prompt_name', 'generated_test_cases',
                 'review_feedback', 'human_feedback', 'final_test_cases', 'kb_audit_result',
                 'confirmed_answers',
                 # 历史缺陷复盘注入（方案 A）
                 # defect_review_used = 本次实际注入的测试点审计快照（只读，由生成侧写入）
                 'defect_review', 'defect_review_detail_level', 'defect_review_used',
                 'review_count', 'review_updated_at', 'review_status',
                 'generation_log', 'error_message',
                 'created_by', 'created_by_name', 'created_at', 'updated_at', 'completed_at']
        read_only_fields = ['task_id', 'status', 'progress', 'generated_test_cases', 
                         'review_feedback', 'final_test_cases', 'generation_log', 
                         'error_message', 'created_by', 'completed_at',
                         'review_count', 'review_updated_at',
                         # 审计快照只能由生成侧写入，接口不可篡改
                         'defect_review_used']
    
    def get_review_status(self, obj):
        """
        计算评审结果状态：
        - not_reviewed: 未评审（无 review_feedback）
        - passed: 评审通过（已评审且 human_feedback 中无不确定项）
        - pending: 待确认（有未回复的不确定项，含 "(未填写)"）
        - confirmed: 已确认（所有不确定项均已回复）
        """
        if not obj.review_feedback:
            return 'not_reviewed'
        if not obj.human_feedback or '【确认项' not in obj.human_feedback:
            return 'passed'
        if '确认回复：(未填写)' in obj.human_feedback:
            return 'pending'
        return 'confirmed'
    
    def create(self, validated_data):
        # 自动设置创建者和任务ID
        import uuid
        user = self.context['request'].user
        validated_data['created_by'] = user
        
        validated_data['task_id'] = f"TASK_{uuid.uuid4().hex[:8].upper()}"
        
        return super().create(validated_data)


class TestCaseGenerationRequestSerializer(serializers.Serializer):
    """新的测试用例生成请求序列化器"""
    title = serializers.CharField(max_length=200, help_text="任务标题")
    requirement_text = serializers.CharField(help_text="需求描述")
    use_writer_model = serializers.BooleanField(default=True, help_text="是否使用编写模型")
    use_reviewer_model = serializers.BooleanField(default=True, help_text="是否使用评审模型")
    project = serializers.IntegerField(required=False, allow_null=True, help_text="关联项目ID")
    version = serializers.IntegerField(required=False, allow_null=True, help_text="关联版本ID")
    feature_module = serializers.IntegerField(required=False, allow_null=True, help_text="关联功能模块ID")
    test_point = serializers.IntegerField(required=False, allow_null=True, help_text="关联测试点ID")
    generation_mode = serializers.ChoiceField(
        choices=[('smart', '智能'), ('quick', '快速'), ('standard', '标准'), ('comprehensive', '全面')],
        default='smart',
        help_text="生成模式：智能(默认)/快速(10-20条)/标准(20-40条)/全面(不限)"
    )
    confirmed_answers = serializers.CharField(
        required=False, allow_blank=True,
        help_text='需求拆解阶段确认的问答对JSON: [{question,answer}]，将注入用例生成提示词'
    )
    # 历史缺陷复盘注入（2026-10-22，方案 A：任务级显式开关）
    # 不传/传 null = 不注入，与旧行为完全一致
    defect_review = serializers.IntegerField(
        required=False, allow_null=True,
        help_text='关联的历史缺陷复盘报告ID；传入后按需求二次筛选其测试点并注入生成'
    )
    defect_review_detail_level = serializers.ChoiceField(
        choices=[('', '自动'), ('brief', '精简'), ('standard', '标准'), ('full', '详细')],
        required=False, default='',
        help_text='测试点注入详略；留空按改动规模自动决定'
    )


class GenerationConfigSerializer(serializers.ModelSerializer):
    """生成行为配置序列化器"""
    default_output_mode_display = serializers.CharField(source='get_default_output_mode_display', read_only=True)

    class Meta:
        model = GenerationConfig
        fields = [
            'id', 'name', 'default_output_mode', 'default_output_mode_display',
            'enable_auto_review', 'review_timeout',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class GeneratedRequirementDocSerializer(serializers.ModelSerializer):
    """生成的需求文档序列化器"""
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    content_preview = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedRequirementDoc
        fields = [
            'id', 'title', 'markdown_content', 'source_type', 'source_type_display',
            'source_detail', 'project', 'project_name', 'created_by', 'created_by_name',
            'created_at', 'content_preview'
        ]
        read_only_fields = ['created_at']

    def get_content_preview(self, obj):
        """返回 markdown 前 200 字符作为预览"""
        if not obj.markdown_content:
            return ''
        return obj.markdown_content[:200]


class GeneratedRequirementDocListSerializer(serializers.ModelSerializer):
    """生成的需求文档列表序列化器（不含完整 markdown）"""
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    content_preview = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedRequirementDoc
        fields = [
            'id', 'title', 'source_type', 'source_type_display',
            'source_detail', 'project', 'project_name', 'created_by', 'created_by_name',
            'created_at', 'content_preview'
        ]

    def get_content_preview(self, obj):
        if not obj.markdown_content:
            return ''
        return obj.markdown_content[:200]


class RequirementAnalysisResultSerializer(serializers.ModelSerializer):
    """需求拆解结果详情序列化器（含完整内容）"""
    project_name = serializers.CharField(source='project.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    req_doc = serializers.IntegerField(source='req_doc_id', required=False, allow_null=True)

    class Meta:
        model = RequirementAnalysisResult
        fields = [
            'id', 'title', 'requirement_text', 'result_content',
            'project', 'project_name', 'req_doc', 'created_by', 'created_by_name', 'created_at'
        ]
        read_only_fields = ['created_at', 'created_by']


class RequirementAnalysisResultListSerializer(serializers.ModelSerializer):
    """需求拆解结果列表序列化器（不含完整内容）"""
    project_name = serializers.CharField(source='project.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    req_doc = serializers.IntegerField(source='req_doc_id', read_only=True)

    class Meta:
        model = RequirementAnalysisResult
        fields = [
            'id', 'title', 'content_preview', 'project', 'project_name', 'req_doc',
            'created_by', 'created_by_name', 'created_at'
        ]
        read_only_fields = ['created_at', 'created_by']


class ClarificationQuestionSerializer(serializers.ModelSerializer):
    """深度追问清单条目序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ClarificationQuestion
        fields = [
            'id', 'analysis_result', 'question', 'answer', 'category',
            'status', 'status_display', 'order', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ModaoPageSerializer(serializers.ModelSerializer):
    """墨刀单页提取结果序列化器（含 A2-c 画布级流水线产物）"""
    screenshot_segments = serializers.SerializerMethodField()

    def get_screenshot_segments(self, obj):
        raw = getattr(obj, 'screenshot_segments', '') or ''
        if isinstance(raw, str):
            try:
                val = json.loads(raw)
            except Exception:
                val = []
        else:
            val = raw or []
        return [s for s in val if isinstance(s, str) and s] if isinstance(val, list) else []

    class Meta:
        model = ModaoPage
        fields = [
            'id', 'page_no', 'page_name', 'text', 'annotations', 'screenshot',
            'screenshot_segments',
            'selected', 'recognition_note', 'parent_name',
            'folder',
            'current_stage', 'stage_status', 'work_log', 'error_message', 'rerun_stages',
            'page_summary', 'page_clarification', 'page_testpoints_json',
            'page_testcases_json', 'page_smoke_json', 'page_approved',
        ]


class ModaoPageLightSerializer(serializers.ModelSerializer):
    """画布看板首屏用的轻量单页序列化器（2026-10-23）。

    ⚠️ 背景：`modao/<id>/` 详情接口原来返回每页的**全部阶段产物**，
    实测单任务 89 = **2113 KB / 5 秒**，其中 pages 占 1152KB（54%），
    而「画布任务看板」首屏只渲染画布卡片（编号/名称/阶段/缩略图/识别摘要）。

    实测该任务 23 页的体积构成：
      首屏真正需要的轻量字段  51.8 KB
      抽屉「进入当前阶段」+「用例集合」tab 才用的重字段  1091.5 KB
        └ page_testcases_json 358KB / page_summary 346KB
          page_testpoints_json 248KB / page_smoke_json 95KB / page_clarification 45KB

    ⇒ 首屏用本序列化器，重字段由前端按需再拉一次全量详情。
    """

    screenshot_segments = serializers.SerializerMethodField()

    def get_screenshot_segments(self, obj):
        raw = getattr(obj, 'screenshot_segments', '') or ''
        if isinstance(raw, str):
            try:
                val = json.loads(raw)
            except Exception:
                val = []
        else:
            val = raw or []
        return [s for s in val if isinstance(s, str) and s] if isinstance(val, list) else []

    class Meta:
        model = ModaoPage
        fields = [
            'id', 'page_no', 'page_name', 'parent_name', 'folder',
            'selected', 'current_stage', 'stage_status',
            'screenshot', 'screenshot_segments', 'recognition_note',
            'work_log', 'error_message', 'text',
        ]


class ModaoPrototypeLightSerializer(serializers.ModelSerializer):
    """画布看板首屏用的轻量原型序列化器（2026-10-23）。

    配合 `GET /api/modao/<id>/?light=1` 使用，把 2113 KB 压到约 112 KB（-95%）。
    顶层重字段（testcases_json 355KB / final_testpoints_json 232KB /
    extracted_json 228KB / smoke_json 70KB）首屏一个都不渲染，全部剔除。
    """

    pages = ModaoPageLightSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    version_name = serializers.SerializerMethodField()
    feature_module_info = serializers.SerializerMethodField()

    class Meta:
        model = ModaoPrototype
        fields = [
            'id', 'uuid', 'title', 'url', 'source_type', 'status', 'current_stage',
            'error_message', 'work_log', 'excel_path', 'stage4_decision',
            'project', 'project_name', 'version', 'version_name',
            'created_by_name', 'created_at', 'updated_at',
            'pages', 'feature_module_info',
        ]

    def get_version_name(self, obj):
        return obj.version.name if obj.version_id else None

    def get_feature_module_info(self, obj):
        if obj.feature_module_id:
            return {'id': obj.feature_module_id, 'name': obj.feature_module.name}
        return None


class ModaoPrototypeSerializer(serializers.ModelSerializer):
    """墨刀技能 - 原型/需求来源序列化器（含逐页结果与各阶段产物）"""
    pages = ModaoPageSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    version_name = serializers.SerializerMethodField()
    confirmations = serializers.SerializerMethodField()
    feature_module_info = serializers.SerializerMethodField()
    generation_gate = serializers.SerializerMethodField()

    class Meta:
        model = ModaoPrototype
        fields = [
            'id', 'uuid', 'title', 'url', 'source_type', 'status', 'current_stage',
            'extracted_json', 'requirement_summary', 'clarification_log', 'module_split',
            'risks_json', 'pci_json', 'final_testpoints_json', 'testcases_json',
            'dedup_audit_json', 'smoke_json', 'quality_report_json', 'excel_path', 'stage4_decision',
            'error_message', 'work_log', 'qa_log', 'project', 'project_name', 'version', 'version_name',
            'created_by_name', 'created_at', 'updated_at',
            'pages', 'confirmations', 'feature_module_info', 'generation_gate',
            'merged_testcases_json', 'merged_smoke_json',
        ]
        read_only_fields = [
            'id', 'uuid', 'status', 'current_stage', 'extracted_json', 'requirement_summary',
            'clarification_log', 'module_split', 'risks_json', 'pci_json',
            'final_testpoints_json', 'dedup_audit_json', 'testcases_json', 'smoke_json', 'quality_report_json',
            'excel_path', 'stage4_decision', 'error_message', 'work_log', 'qa_log', 'created_by_name',
            'created_at', 'updated_at', 'pages', 'confirmations', 'generation_gate',
            'merged_testcases_json', 'merged_smoke_json',
        ]

    def get_version_name(self, obj):
        return obj.version.name if obj.version_id else None

    def get_confirmations(self, obj):
        return obj.get_confirmations()

    def get_feature_module_info(self, obj):
        if obj.feature_module_id:
            return {'id': obj.feature_module_id, 'name': obj.feature_module.name}
        return None

    def get_generation_gate(self, obj):
        return obj.case_generation_gate()


class ModaoPrototypeListSerializer(serializers.ModelSerializer):
    """任务列表专用轻量序列化器（2026-10-23 性能修复）。

    ⚠️ 背景：`modao_list` 原来直接复用 `ModaoPrototypeSerializer`，把每个原型的
    **全部阶段产物**都返回。实测 35 个原型 → 响应体 **26.9MB**、耗时 381ms，
    页面"标题先出来、表格数据要等很久"。

    体积实测（35 个原型合计）：
      extracted_json 5.44MB / testcases_json 3.02MB / final_testpoints_json 2.97MB
      requirement_summary 1.64MB / risks_json 1.29MB / dedup_audit 0.97MB
      pci_json 0.97MB / smoke_json 0.53MB / module_split 0.45MB / pages 逐页数据
    ⇒ 这些字段列表页**一个都不渲染**，纯属白传。

    列表页 `ModaoListView.vue` 实际只依赖：
      title / source_type / status / current_stage / created_by_name /
      updated_at / work_log / error_message (+ id 用于跳转与操作)
    其中 work_log / error_message 是行展开面板"工作日志/错误信息"要用的，**必须保留**。

    详细产物请走详情接口 `GET /api/modao/<id>/`（仍用完整序列化器）。
    """

    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    # work_log 是展开行的「工作日志」内容，体积占列表响应的 90%（54 条 = 176KB），
    # 而它**默认不展开**，完全没必要随列表传输。
    # 改为只返回"有没有日志"的布尔值；展开时由前端按需拉详情接口。
    has_work_log = serializers.SerializerMethodField()

    class Meta:
        model = ModaoPrototype
        fields = [
            'id', 'uuid', 'title', 'url', 'source_type', 'status', 'current_stage',
            'project', 'version', 'created_by_name',
            'created_at', 'updated_at', 'has_work_log', 'error_message',
        ]

    def get_has_work_log(self, obj):
        return bool((obj.work_log or '').strip())
