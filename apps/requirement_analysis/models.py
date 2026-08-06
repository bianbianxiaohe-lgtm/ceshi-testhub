from django.db import models
from django.utils import timezone
from apps.users.models import User
from apps.projects.models import Project, ProjectKnowledge
import json
import httpx
import asyncio
from typing import Dict, Any, List, AsyncIterator
import logging
import os
import re
import traceback
import hashlib

logger = logging.getLogger(__name__)


class RequirementDocument(models.Model):
    """需求文档模型"""
    DOCUMENT_TYPE_CHOICES = [
        ('pdf', 'PDF文档'),
        ('docx', 'Word文档'),
        ('txt', '文本文档'),
        ('md', 'Markdown文档'),
    ]
    
    STATUS_CHOICES = [
        ('uploaded', '已上传'),
        ('analyzing', '分析中'),
        ('analyzed', '分析完成'),
        ('failed', '分析失败'),
    ]
    
    title = models.CharField(max_length=200, verbose_name='文档标题')
    file = models.FileField(upload_to='requirement_docs/%Y/%m/', verbose_name='文档文件')
    document_type = models.CharField(max_length=10, choices=DOCUMENT_TYPE_CHOICES, verbose_name='文档类型')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded', verbose_name='状态')
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_documents', verbose_name='上传者')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='requirement_documents', verbose_name='关联项目', null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    file_size = models.PositiveIntegerField(verbose_name='文件大小(bytes)', null=True, blank=True)
    extracted_text = models.TextField(verbose_name='提取的文本内容', blank=True)
    
    class Meta:
        db_table = 'requirement_documents'
        verbose_name = '需求文档'
        verbose_name_plural = '需求文档'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"


class RequirementAnalysis(models.Model):
    """需求分析记录"""
    document = models.OneToOneField(RequirementDocument, on_delete=models.CASCADE, related_name='analysis', verbose_name='关联文档')
    analysis_report = models.TextField(verbose_name='分析报告', blank=True)
    requirements_count = models.PositiveIntegerField(verbose_name='需求数量', default=0)
    analysis_time = models.FloatField(verbose_name='分析耗时(秒)', null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'requirement_analyses'
        verbose_name = '需求分析'
        verbose_name_plural = '需求分析'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.document.title} - 分析报告"


class BusinessRequirement(models.Model):
    """业务需求模型"""
    REQUIREMENT_TYPE_CHOICES = [
        ('functional', '功能需求'),
        ('performance', '性能需求'),
        ('security', '安全需求'),
        ('usability', '可用性需求'),
        ('interface', '接口需求'),
        ('other', '其他需求'),
    ]
    
    REQUIREMENT_LEVEL_CHOICES = [
        ('high', '高'),
        ('medium', '中'),
        ('low', '低'),
    ]
    
    analysis = models.ForeignKey(RequirementAnalysis, on_delete=models.CASCADE, related_name='requirements', verbose_name='关联分析')
    requirement_id = models.CharField(max_length=50, verbose_name='需求编号')
    requirement_name = models.CharField(max_length=200, verbose_name='需求名称')
    requirement_type = models.CharField(max_length=20, choices=REQUIREMENT_TYPE_CHOICES, verbose_name='需求类型')
    parent_requirement = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, verbose_name='父级需求')
    module = models.CharField(max_length=100, verbose_name='所属模块')
    requirement_level = models.CharField(max_length=10, choices=REQUIREMENT_LEVEL_CHOICES, verbose_name='需求级别')
    reviewer = models.CharField(max_length=50, verbose_name='评审人', default='admin')
    estimated_hours = models.PositiveIntegerField(verbose_name='预计工时', default=8)
    description = models.TextField(verbose_name='需求描述')
    acceptance_criteria = models.TextField(verbose_name='验收标准')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'business_requirements'
        verbose_name = '业务需求'
        verbose_name_plural = '业务需求'
        ordering = ['-created_at']
        unique_together = ['analysis', 'requirement_id']
    
    def __str__(self):
        return f"{self.requirement_id} - {self.requirement_name}"


class GeneratedTestCase(models.Model):
    """生成的测试用例模型"""
    PRIORITY_CHOICES = [
        ('P0', '最高优先级'),
        ('P1', '高优先级'),
        ('P2', '中优先级'),
        ('P3', '低优先级'),
    ]
    
    STATUS_CHOICES = [
        ('generated', '已生成'),
        ('reviewing', '评审中'),
        ('reviewed', '已评审'),
        ('approved', '已批准'),
        ('rejected', '已拒绝'),
        ('adopted', '已采纳'),
        ('discarded', '已弃用'),
    ]
    
    requirement = models.ForeignKey(BusinessRequirement, on_delete=models.CASCADE, related_name='test_cases', verbose_name='关联需求')
    case_id = models.CharField(max_length=50, verbose_name='用例编号')
    title = models.CharField(max_length=300, verbose_name='用例标题')
    priority = models.CharField(max_length=5, choices=PRIORITY_CHOICES, verbose_name='优先级')
    precondition = models.TextField(verbose_name='前置条件')
    test_steps = models.TextField(verbose_name='测试步骤')
    expected_result = models.TextField(verbose_name='预期结果')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='generated', verbose_name='状态')
    generated_by_ai = models.CharField(max_length=50, verbose_name='生成AI模型', default='AI-A')
    reviewed_by_ai = models.CharField(max_length=50, verbose_name='评审AI模型', null=True, blank=True)
    review_comments = models.TextField(verbose_name='评审意见', blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'generated_test_cases'
        verbose_name = '生成的测试用例'
        verbose_name_plural = '生成的测试用例'
        ordering = ['-created_at']
        unique_together = ['requirement', 'case_id']
    
    def __str__(self):
        return f"{self.case_id} - {self.title[:50]}"


class AnalysisTask(models.Model):
    """分析任务模型"""
    TASK_TYPE_CHOICES = [
        ('requirement_analysis', '需求分析'),
        ('testcase_generation', '测试用例生成'),
        ('testcase_review', '测试用例评审'),
    ]
    
    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('running', '运行中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    
    task_id = models.CharField(max_length=100, unique=True, verbose_name='任务ID')
    task_type = models.CharField(max_length=30, choices=TASK_TYPE_CHOICES, verbose_name='任务类型')
    document = models.ForeignKey(RequirementDocument, on_delete=models.CASCADE, related_name='tasks', verbose_name='关联文档')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    progress = models.PositiveIntegerField(default=0, verbose_name='进度百分比')
    result = models.JSONField(verbose_name='任务结果', null=True, blank=True)
    error_message = models.TextField(verbose_name='错误信息', blank=True)
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    
    class Meta:
        db_table = 'analysis_tasks'
        verbose_name = '分析任务'
        verbose_name_plural = '分析任务'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.task_id} - {self.get_task_type_display()}"


class AIModelConfig(models.Model):
    """AI模型配置模型"""
    MODEL_CHOICES = [
        ('deepseek', 'DeepSeek'),
        ('qwen', '通义千问'),
        ('siliconflow', '硅基流动'),
        ('other', '其他'),
    ]

    ROLE_CHOICES = [
        ('writer', '测试用例编写专家'),
        ('writer_vision', '视觉分析专家（截图/图片/PDF）'),
        ('reviewer', '测试评审专家'),
        ('analyzer', '需求拆解专家'),
        ('browser_use_text', 'Browser Use - 文本模式'),
        ('writer_vision_ocr', '视觉分析专家（OCR专用，可配更快模型）'),
        ('embedder', '向量化模型（Embedding）'),
    ]

    name = models.CharField(max_length=100, verbose_name='配置名称')
    model_type = models.CharField(max_length=20, choices=MODEL_CHOICES, verbose_name='模型类型')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, verbose_name='角色')
    api_key = models.CharField(max_length=200, verbose_name='API Key', blank=True, null=True)
    base_url = models.URLField(verbose_name='API Base URL')
    model_name = models.CharField(max_length=100, verbose_name='模型名称')
    max_tokens = models.IntegerField(default=4096, verbose_name='最大Token数')
    temperature = models.FloatField(default=0.7, verbose_name='温度参数')
    top_p = models.FloatField(default=0.9, verbose_name='Top P参数')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'ai_model_config'
        verbose_name = 'AI模型配置'
        verbose_name_plural = 'AI模型配置'
        # 移除 unique_together 约束，允许同一个 role 有多个配置
        # 在应用层面通过代码控制：每个 role 只能有一个 is_active=True 的配置

    def __str__(self):
        return f"{self.get_model_type_display()} - {self.get_role_display()}"

    @classmethod
    def get_active_config(cls, model_type: str, role: str):
        """获取活跃的配置"""
        return cls.objects.filter(
            model_type=model_type,
            role=role,
            is_active=True
        ).first()

    @classmethod
    def get_active_embedder(cls):
        """获取任意一个启用的向量化（embedding）配置"""
        return cls.objects.filter(role='embedder', is_active=True).first()


class PromptConfig(models.Model):
    """提示词配置模型"""
    PROMPT_CHOICES = [
        ('writer', '用例编写提示词'),
        ('reviewer', '用例评审提示词'),
        ('analyzer', '需求分析提示词'),
    ]
    
    name = models.CharField(max_length=100, verbose_name='配置名称')
    prompt_type = models.CharField(max_length=20, choices=PROMPT_CHOICES, verbose_name='提示词类型')
    content = models.TextField(verbose_name='提示词内容')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        db_table = 'prompt_config'
        verbose_name = '提示词配置'
        verbose_name_plural = '提示词配置'
    
    def __str__(self):
        return f"{self.get_prompt_type_display()} - {self.name}"
    
    @classmethod
    def get_active_config(cls, prompt_type: str):
        """获取活跃的提示词配置"""
        return cls.objects.filter(
            prompt_type=prompt_type,
            is_active=True
        ).first()


class GenerationConfig(models.Model):
    """生成行为配置模型"""
    OUTPUT_MODE_CHOICES = [
        ('stream', '实时流式输出'),
        ('complete', '完整输出'),
    ]

    name = models.CharField(max_length=100, verbose_name='配置名称', default='默认生成配置')
    default_output_mode = models.CharField(
        max_length=10,
        choices=OUTPUT_MODE_CHOICES,
        default='stream',
        verbose_name='默认输出模式',
        help_text='测试用例生成的默认输出方式'
    )

    # 扩展配置字段
    enable_auto_review = models.BooleanField(
        default=True,
        verbose_name='启用AI评审和改进',
        help_text='生成完成后自动进行AI评审，并根据评审意见改进测试用例'
    )
    review_timeout = models.IntegerField(
        default=120,
        verbose_name='评审和改进超时时间（秒）',
        help_text='AI评审和改进的最大等待时间（总时长）'
    )

    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'generation_config'
        verbose_name = '生成行为配置'
        verbose_name_plural = '生成行为配置'

    def __str__(self):
        return self.name

    @classmethod
    def get_active_config(cls):
        """获取活跃的生成配置"""
        return cls.objects.filter(is_active=True).first()


class TestCaseGenerationTask(models.Model):
    """测试用例生成任务模型"""
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('generating', '生成中'),
        ('reviewing', '评审中'),
        ('revising', '改进中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('cancelled', '已取消'),
    ]

    OUTPUT_MODE_CHOICES = [
        ('stream', '实时流式输出'),
        ('complete', '完整输出'),
    ]

    GENERATION_MODE_CHOICES = [
        ('smart', '智能模式'),
        ('quick', '快速模式'),
        ('standard', '标准模式'),
        ('comprehensive', '全面模式'),
    ]

    task_id = models.CharField(max_length=50, unique=True, verbose_name='任务ID')
    title = models.CharField(max_length=200, verbose_name='任务标题')
    requirement_text = models.TextField(verbose_name='需求描述')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    progress = models.IntegerField(default=0, verbose_name='进度百分比')

    # 流式输出配置
    output_mode = models.CharField(
        max_length=10,
        choices=OUTPUT_MODE_CHOICES,
        default='stream',
        verbose_name='输出模式'
    )

    generation_mode = models.CharField(
        max_length=20,
        choices=GENERATION_MODE_CHOICES,
        default='smart',
        verbose_name='生成模式'
    )

    # 流式缓冲区和状态跟踪
    stream_buffer = models.TextField(blank=True, verbose_name='流式输出缓冲区')
    stream_position = models.IntegerField(default=0, verbose_name='流式输出位置')
    last_stream_update = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='最后流式更新时间'
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generation_tasks',
        verbose_name='关联项目'
    )
    version = models.ForeignKey(
        'versions.Version',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generation_tasks',
        verbose_name='关联版本'
    )
    feature_module = models.ForeignKey(
        'feature_modules.FeatureModule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generation_tasks',
        verbose_name='关联功能模块'
    )
    test_point = models.ForeignKey(
        'feature_modules.TestPoint',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generation_tasks',
        verbose_name='关联测试点'
    )
    
    # 配置参数
    writer_model_config = models.ForeignKey(
        AIModelConfig, on_delete=models.SET_NULL, null=True, 
        related_name='writer_tasks', verbose_name='编写模型配置'
    )
    reviewer_model_config = models.ForeignKey(
        AIModelConfig, on_delete=models.SET_NULL, null=True,
        related_name='reviewer_tasks', verbose_name='评审模型配置'
    )
    writer_prompt_config = models.ForeignKey(
        PromptConfig, on_delete=models.SET_NULL, null=True,
        related_name='writer_tasks', verbose_name='编写提示词配置'
    )
    reviewer_prompt_config = models.ForeignKey(
        PromptConfig, on_delete=models.SET_NULL, null=True,
        related_name='reviewer_tasks', verbose_name='评审提示词配置'
    )
    
    # 生成结果
    generated_test_cases = models.TextField(blank=True, verbose_name='生成的测试用例')
    review_feedback = models.TextField(blank=True, verbose_name='评审反馈')
    human_feedback = models.TextField(blank=True, verbose_name='人工确认回复')  # 评审后人工对不确定需求的回复/确认
    final_test_cases = models.TextField(blank=True, verbose_name='最终测试用例')
    kb_audit_result = models.TextField(blank=True, verbose_name='知识库审计结果')
    confirmed_answers = models.TextField(
        blank=True, verbose_name='需求拆解阶段确认的问答对',
        help_text='JSON数组: [{question, answer}]，来自精炼时用户确认的不确定项回答，用于生成用例时的上下文注入'
    )
    review_count = models.IntegerField(default=0, verbose_name='评审次数')  # 0=未评审, 1=首次, 2+=重新评审
    review_updated_at = models.DateTimeField(null=True, blank=True, verbose_name='最后评审时间')

    # 元数据
    generation_log = models.TextField(blank=True, verbose_name='生成日志')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    is_saved_to_records = models.BooleanField(default=False, verbose_name='是否已保存到记录')
    saved_at = models.DateTimeField(null=True, blank=True, verbose_name='保存到记录时间')
    
    class Meta:
        db_table = 'testcase_generation_task'
        verbose_name = '测试用例生成任务'
        verbose_name_plural = '测试用例生成任务'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"


class GeneratedRequirementDoc(models.Model):
    """AI 生成的需求文档记录（历史记录）"""
    SOURCE_CHOICES = [
        ('text', '粘贴文字'),
        ('file', '上传文件'),
        ('template', '空白模板'),
    ]

    title = models.CharField(max_length=300, verbose_name='文档标题')
    markdown_content = models.TextField(verbose_name='Markdown 内容')
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, verbose_name='来源类型')
    source_detail = models.TextField(blank=True, verbose_name='来源详情', help_text='文件名列表或粘贴文字摘要')
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_req_docs', verbose_name='关联项目'
    )
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'generated_requirement_docs'
        verbose_name = '生成的需求文档'
        verbose_name_plural = '生成的需求文档'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class RequirementAnalysisResult(models.Model):
    """需求拆解结果历史记录"""
    title = models.CharField(max_length=300, verbose_name='结果标题')
    requirement_text = models.TextField(verbose_name='拆解的需求文本', blank=True)
    result_content = models.TextField(verbose_name='拆解结果（Markdown）')
    content_preview = models.TextField(verbose_name='内容预览', blank=True)
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requirement_analysis_results', verbose_name='关联项目'
    )
    req_doc = models.ForeignKey(
        'GeneratedRequirementDoc', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='analysis_results', verbose_name='关联需求文档'
    )
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'requirement_analysis_results'
        verbose_name = '需求拆解结果'
        verbose_name_plural = '需求拆解结果'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ClarificationQuestion(models.Model):
    """需求拆解「深度追问清单」条目（关联一条拆解结果历史记录）"""
    STATUS_CHOICES = [
        ('pending', '待回复'),
        ('answered', '已回复'),
        ('confirmed', '已确认'),
    ]

    analysis_result = models.ForeignKey(
        RequirementAnalysisResult, on_delete=models.CASCADE,
        related_name='clarifications', verbose_name='关联拆解结果'
    )
    question = models.TextField(verbose_name='追问问题')
    answer = models.TextField(verbose_name='人工回复', blank=True)
    category = models.CharField(max_length=50, verbose_name='分类', default='其他')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态'
    )
    order = models.IntegerField(default=0, verbose_name='排序', db_column='order_idx')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'clarification_questions'
        verbose_name = '深度追问'
        verbose_name_plural = '深度追问'
        ordering = ['order', 'id']

    def __str__(self):
        return f"追问#{self.order}: {self.question[:30]}"


class AIModelService:
    """AI模型服务类"""

    @staticmethod
    def build_knowledge_context(task, query_text=None) -> str:
        """
        构造项目知识库上下文文本，注入到 AI 生成用例的提示词中。
        优先级：文件系统 Markdown 知识库 > 数据库知识库条目

        方案 C：生成用例/审计时，若配置了 embedder，会按「需求语义」检索 top-K 知识
        条目（替代全量灌入），避免同名不同义功能被错误召回。无 embedder 时降级全量。

        如果 task 上已有 _pre_fetched_knowledge_context（由上层同步代码预计算），
        则直接返回缓存值，避免在 async 上下文中触发同步 ORM 操作。
        """
        if hasattr(task, '_pre_fetched_knowledge_context'):
            return task._pre_fetched_knowledge_context

        if not task.project_id:
            return ''
        try:
            project = Project.objects.get(id=task.project_id)
        except Project.DoesNotExist:
            return ''

        # 方案 C：默认以需求文本为查询锚点做语义检索（调用方可显式覆盖 query_text）
        q = query_text if query_text else (getattr(task, 'requirement_text', '') or '')
        if q:
            rag_ctx = AIModelService._rag_retrieve_kb(project, q, top_k=8)
            if rag_ctx:
                fs_ctx = ''
                kb_path = AIModelService._resolve_knowledge_path(project)
                if kb_path:
                    fs_ctx = AIModelService._read_knowledge_files(kb_path) or ''
                parts = []
                if fs_ctx:
                    parts.append(fs_ctx)
                parts.append(rag_ctx)
                return '\n\n'.join(parts)

        # 以下为降级/展示用全量逻辑（原行为）

        # 第一优先：文件系统 Markdown 知识库
        kb_path = AIModelService._resolve_knowledge_path(project)
        if kb_path:
            context = AIModelService._read_knowledge_files(kb_path)
            if context:
                return context

        # 回退：数据库知识库条目
        try:
            entries = ProjectKnowledge.objects.filter(
                project_id=task.project_id,
                is_active=True
            ).order_by('category', 'sort_order', '-created_at')

            if not entries.exists():
                return ''

            category_map = {}
            for entry in entries:
                cat_label = entry.get_category_display()
                if cat_label not in category_map:
                    category_map[cat_label] = []
                category_map[cat_label].append(f'- **{entry.title}**：{entry.content}')

            lines = ['【项目业务知识库】', '（以下是本项目的业务背景与测试约束，请在生成测试用例时严格参考）', '']
            for cat_label, items in category_map.items():
                lines.append(f'### {cat_label}')
                lines.extend(items)
                lines.append('')

            return '\n'.join(lines)
        except Exception as e:
            logger.warning(f'获取数据库知识库失败: {e}')
            return ''

    @staticmethod
    def build_knowledge_context_from_project(project, query_text=None, max_chunks=None) -> str:
        """基于项目对象构造知识库上下文（不依赖 task），用于知识库生成前的参考。

        合并两个来源：
          ① 文件系统 Markdown 知识库（项目知识库目录下的 .md）
          ② 数据库 ProjectKnowledge 条目（墨刀流程阶段3确认后自适应沉淀）

        方案 C：若传入 query_text 且已配置 embedder，则对来源②改用「语义检索 top-K」
        替代「全量灌入」，避免同名不同义功能（如不同版本的「引导」）被错误召回。
        无 embedder / 检索失败时自动降级为全量（原行为）。
        max_chunks: 限制检索 top-K 数量，默认 8。较小值（如 3）可减少 prompt 大小。
        """
        top_k = max_chunks if max_chunks else 8
        # 方案 C：语义检索 DB 知识条目（文件系统 .md 仍全量保留）
        if query_text:
            rag_ctx = AIModelService._rag_retrieve_kb(project, query_text, top_k=top_k)
            if rag_ctx:
                parts = []
                kb_path = AIModelService._resolve_knowledge_path(project)
                if kb_path:
                    fs_ctx = AIModelService._read_knowledge_files(kb_path, query_text=query_text, max_files=5)
                    if fs_ctx:
                        parts.append(fs_ctx)
                parts.append(rag_ctx)
                return '\n\n'.join(parts)

        parts = []

        # 来源①：文件系统 Markdown 知识库（query_text 非空时按相关性取 top 5）
        kb_path = AIModelService._resolve_knowledge_path(project)
        if kb_path:
            fs_ctx = AIModelService._read_knowledge_files(kb_path, query_text=query_text or '', max_files=5 if query_text else 0)
            if fs_ctx:
                parts.append(fs_ctx)

        # 来源②：数据库知识库条目（自适应回填的新知识落在这里）
        try:
            entries = ProjectKnowledge.objects.filter(
                project_id=project.id,
                is_active=True
            ).order_by('category', 'sort_order', '-created_at')
            if entries.exists():
                category_map = {}
                for entry in entries:
                    cat_label = entry.get_category_display()
                    if cat_label not in category_map:
                        category_map[cat_label] = []
                    category_map[cat_label].append(f'- **{entry.title}**：{entry.content}')
                lines = ['【项目知识库条目（含流程自适应沉淀的新知识）】', '']
                for cat_label, items in category_map.items():
                    lines.append(f'### {cat_label}')
                    lines.extend(items)
                    lines.append('')
                parts.append('\n'.join(lines))
        except Exception as e:
            logger.warning(f'获取数据库知识库失败: {e}')

        if not parts:
            return ''
        return '\n\n'.join(parts)

    # ------------------------------------------------------------------
    # 知识库 RAG 检索（方案 C）：按语义相似度召回 top-K 知识条目，
    # 替代「全量灌入 prompt」，解决同名不同义功能（如不同版本的「引导」）
    # 被错误召回的问题。向量只存 Chroma，不落业务库，无需数据库迁移。
    # ------------------------------------------------------------------

    @staticmethod
    def embed_texts_sync(texts, embedder_config=None):
        """同步包装 embed_texts，供非 async 上下文（生成线程 / workflow）调用。
        返回向量列表；无 embedder / 失败 / 处于运行中事件循环则返回 None。"""
        if not texts:
            return []
        if embedder_config is None:
            embedder_config = AIModelConfig.get_active_embedder()
        if not embedder_config:
            return None
        try:
            asyncio.get_running_loop()
            logger.warning('RAG embed 处于运行中的事件循环，降级跳过')
            return None
        except RuntimeError:
            pass
        try:
            return asyncio.run(asyncio.wait_for(
                AIModelService.embed_texts(embedder_config, texts), timeout=300))
        except Exception as e:
            logger.warning(f'RAG embed 失败（降级）: {e}')
            return None

    @staticmethod
    def _ensure_kb_indexed(project, embedder_config):
        """冷启动：把项目全部 active 知识条目批量向量化进 Chroma。"""
        from apps.projects.models import ProjectKnowledge
        from .vector_store import get_project_kb_collection, upsert_kb_item
        entries = list(ProjectKnowledge.objects.filter(
            project_id=project.id, is_active=True))
        if not entries:
            return
        texts = [f'{e.title}\n{e.content}' for e in entries]
        vecs = AIModelService.embed_texts_sync(texts, embedder_config)
        if not vecs:
            return
        collection = get_project_kb_collection(project.id)
        for e, vec in zip(entries, vecs):
            upsert_kb_item(
                collection, f'pk_{e.id}', vec,
                f'【{e.get_category_display()}】{e.title}：{e.content}',
                {'source': 'db', 'entry_id': e.id, 'category': e.category},
            )

    @staticmethod
    def _rag_retrieve_kb(project, query_text, top_k=8):
        """RAG 检索 DB 知识条目 top-K，返回拼接文本；失败/无结果返回 ''。"""
        from .vector_store import get_project_kb_collection, query_kb
        embedder = AIModelConfig.get_active_embedder()
        if not embedder or not query_text or not query_text.strip():
            return ''
        try:
            vec = AIModelService.embed_texts_sync([query_text], embedder)
            if not vec:
                return ''
            vec = vec[0]
            collection = get_project_kb_collection(project.id)
            if collection.count() == 0:
                AIModelService._ensure_kb_indexed(project, embedder)
            if collection.count() == 0:
                return ''
            hits = query_kb(collection, vec, top_k)
            if not hits:
                return ''
            lines = [f'【项目知识库参考（按当前需求语义检索 top-{len(hits)}）】', '']
            for h in hits:
                lines.append(f'- {h["text"]}')
            return '\n'.join(lines)
        except Exception as e:
            logger.warning(f'RAG 检索失败（降级全量）: {e}')
            return ''

    @staticmethod
    def sync_kb_entry_to_vector(entry, action='upsert'):
        """知识条目增删改后同步 Chroma 向量（写入点钩子调用）。"""
        from .vector_store import get_project_kb_collection, upsert_kb_item, delete_kb_item
        try:
            embedder = AIModelConfig.get_active_embedder()
            if not embedder:
                return
            collection = get_project_kb_collection(entry.project_id)
            if action == 'delete' or not entry.is_active:
                delete_kb_item(collection, f'pk_{entry.id}')
                return
            vec = AIModelService.embed_texts_sync([f'{entry.title}\n{entry.content}'], embedder)
            if not vec:
                return
            upsert_kb_item(
                collection, f'pk_{entry.id}', vec[0],
                f'【{entry.get_category_display()}】{entry.title}：{entry.content}',
                {'source': 'db', 'entry_id': entry.id, 'category': entry.category},
            )
        except Exception as e:
            logger.warning(f'同步知识库向量失败（可忽略）: {e}')

    @staticmethod
    def auto_fill_knowledge_from_modao_products(proto, model_config=None, user_id=None,
                                             version_tag='', module_tag='') -> dict:
        """
        从墨刀流程产物中提炼新知识，自适应回填项目知识库（ProjectKnowledge）。

        在阶段3确认时调用：把本次流程发现的风险处置 / PCI 处置 / 质量缺口 / 澄清结论等，
        沉淀为可复用的项目知识，供后续同类需求生成时参考（与 build_knowledge_context_from_project
        的数据库来源合并，形成「生成→沉淀→再生成」的自适应闭环）。

        Returns:
            dict: {'created_count': N, 'skipped_count': M, 'entries': [...]}
        """
        project_id = getattr(proto, 'project_id', None)
        if not project_id:
            return {'created_count': 0, 'skipped_count': 0, 'entries': [], 'reason': 'no_project'}

        from apps.projects.models import ProjectKnowledge

        # 解析功能/版本范围（用于知识条目标注，增强同名功能的语义区分度）
        if not version_tag and getattr(proto, 'version', None):
            version_tag = getattr(proto.version, 'name', '') or ''
        if not module_tag and getattr(proto, 'feature_module', None):
            module_tag = getattr(proto.feature_module, 'name', '') or ''
        scope_tag = ' / '.join([t for t in [module_tag, version_tag] if t]).strip()

        # 1. 汇总候选知识文本（来自各阶段产物）
        candidates = []
        if getattr(proto, 'clarification_log', ''):
            candidates.append('【需求澄清发现的模糊/缺失/边界点】\n' + proto.clarification_log)
        if getattr(proto, 'risks_json', ''):
            candidates.append('【风险点及处置建议】\n' + proto.risks_json)
        if getattr(proto, 'pci_json', ''):
            candidates.append('【PCI（兼容性/性能/集成）场景及处置】\n' + proto.pci_json)
        if getattr(proto, 'quality_report_json', ''):
            candidates.append('【质量自检发现的测试缺口】\n' + proto.quality_report_json)
        if not candidates:
            return {'created_count': 0, 'skipped_count': 0, 'entries': []}
        candidate_text = '\n\n'.join(candidates)

        # 2. 现有知识库（去重参考）
        existing = list(ProjectKnowledge.objects.filter(
            project_id=project_id, is_active=True
        ).values_list('title', 'content'))
        existing_summary = ''
        if existing:
            lines = ['【项目现有知识库条目】']
            for title, content in existing:
                lines.append(f'- {title}: {content[:100]}')
            existing_summary = '\n'.join(lines) + '\n'

        # 3. 调用 AI 提炼新知识条目；无模型则简单规则兜底
        import json as _json
        new_items = []
        if model_config:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    scope_instruction = ''
                    if scope_tag:
                        scope_instruction = (
                            f"\n重要：本条知识归属【{scope_tag}】。请在输出每条的 title 开头用"
                            f"【{scope_tag}】标注，并在 content 开头先点明适用的功能/版本范围，"
                            "便于后续按需求语义精确召回，避免与其他同名功能混淆。\n"
                        )
                    system_msg = (
                        "你是一个知识管理专家。请从墨刀需求分析流程的产物中，"
                        "筛选出值得沉淀到项目知识库的「新业务知识 / 测试约束 / 风险处置经验」。\n\n"
                        "判断标准：\n"
                        "- 只筛选**业务规则 / 约束 / 约定 / 风险处置经验 / 测试重点**类内容\n"
                        "- 排除纯过程性描述、与测试无关的闲聊\n"
                        "- 与已有知识高度相似的不要重复收录\n"
                        + scope_instruction +
                        "输出格式（严格JSON数组）：\n"
                        '[{"title":"简短标题(20字内，含【功能/版本】前缀)","category":"constraints|test_focus|notes|terminology|background", "content":"完整内容（开头点明适用功能/版本）"}]'
                    )
                    user_msg = (
                        f"{existing_summary}\n"
                        f"【待提炼的墨刀流程产物】\n{candidate_text}\n\n"
                        "请只输出JSON数组，不要其他文字。"
                    )
                    result = loop.run_until_complete(
                        AIModelService.call_openai_compatible_api(model_config, [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg}
                        ], max_tokens=2048)
                    )
                    text = result['choices'][0]['message']['content'].strip()
                    if text.startswith('```'):
                        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                    new_items = _json.loads(text)
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f'[KB自适应回填] AI提炼失败，使用简单规则兜底: {e}')

        # 兜底：无 AI 或 AI 失败，从风险/PCI 的处置字段直接抽取
        if not new_items:
            try:
                prefix = f'【{scope_tag}】' if scope_tag else ''
                risks = _json.loads(proto.risks_json or '[]')
                for r in risks:
                    if not isinstance(r, dict):
                        continue
                    data = r.get('data') or {}
                    for rp in data.get('risk_points', []):
                        mit = (rp.get('mitigation') or '').strip()
                        if mit:
                            new_items.append({
                                'title': f"{prefix}{(rp.get('risk') or rp.get('title') or '风险')[:16]}",
                                'category': 'notes',
                                'content': f"{prefix}风险：{rp.get('risk', rp.get('title', ''))}\n处置：{mit}",
                            })
                pci = _json.loads(proto.pci_json or '[]')
                for p in pci:
                    if not isinstance(p, dict):
                        continue
                    data = p.get('data') or {}
                    for item in data.get('pci_list', []):
                        rc = (item.get('resolution_condition') or item.get('answer') or '').strip()
                        if rc:
                            new_items.append({
                                'title': f"{prefix}{(item.get('scenario') or item.get('pci') or 'PCI')[:16]}",
                                'category': 'constraints',
                                'content': f"{prefix}场景：{item.get('scenario', item.get('pci', ''))}\n处置条件：{rc}",
                            })
            except Exception as e:
                logger.warning(f'[KB自适应回填] 兜底抽取失败: {e}')

        # 4. 创建条目（去重：同项目 + 同标题不重复）
        created_entries = []
        skipped = 0
        for item in new_items:
            if not isinstance(item, dict):
                continue
            title = (item.get('title') or '').strip()[:200]
            category = item.get('category', 'notes')
            content = (item.get('content') or '').strip()
            if not title or not content:
                continue
            if ProjectKnowledge.objects.filter(project_id=project_id, title=title).exists():
                skipped += 1
                continue
            try:
                entry = ProjectKnowledge.objects.create(
                    project_id=project_id,
                    title=title,
                    category=category,
                    content=content,
                    is_active=True,
                    sort_order=0,
                    created_by_id=user_id,
                )
                created_entries.append({'id': entry.id, 'title': title, 'category': category})
                AIModelService.sync_kb_entry_to_vector(entry, 'upsert')
            except Exception as e:
                logger.warning(f'[KB自适应回填] 创建条目失败({title}): {e}')
                skipped += 1

        result = {
            'created_count': len(created_entries),
            'skipped_count': skipped,
            'entries': created_entries,
        }
        logger.info(
            f'[KB自适应回填] 项目{project_id}: 新增{len(created_entries)}条, '
            f'跳过已存在{skipped}条'
        )
        return result

    @staticmethod
    def _resolve_knowledge_path(project: Project) -> str:
        """解析项目知识库目录的绝对路径"""
        raw = (project.knowledge_base_path or '').strip()
        if not raw:
            return ''
        path = raw
        for match in re.finditer(r'\$\{(\w+)\}', raw):
            env_var = match.group(1)
            path = path.replace(match.group(0), os.environ.get(env_var, ''))
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return ''
        return os.path.abspath(path)

    @staticmethod
    def _read_knowledge_files(kb_path: str, query_text: str = '', max_files: int = 0) -> str:
        """递归读取知识库目录下 .md 文件，拼接为上下文。
        query_text 非空时按相关性排序只取 top max_files 个文件；
        max_files=0 表示全量读取（旧行为）。
        """
        if not kb_path or not os.path.isdir(kb_path):
            return ''
        lines = [
            '【项目业务知识库】',
            '（以下内容来自项目知识库 Markdown 文档，请在生成测试用例时严格参考）',
            '',
        ]
        try:
            all_files = []
            def collect(dir_path: str, depth: int = 0):
                items = sorted(os.scandir(dir_path), key=lambda e: e.name)
                for entry in items:
                    if entry.name.startswith('.'):
                        continue
                    if entry.is_file() and entry.name.endswith('.md'):
                        try:
                            with open(entry.path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            title = re.sub(r'^\d{1,3}[-_]', '', entry.name)
                            title = re.sub(r'\.md$', '', title)
                            all_files.append({'path': entry.path, 'title': title, 'content': content, 'depth': depth})
                        except Exception as e:
                            logger.warning(f'读取知识库文件失败 {entry.path}: {e}')
                    elif entry.is_dir() and depth < 2:
                        collect(entry.path, depth + 1)

            collect(kb_path)

            # 如果指定了 max_files 且 query_text 非空，按标题/内容与 query 的相关性排序
            selected = all_files
            if max_files > 0 and query_text and len(all_files) > max_files:
                query_words = set(re.findall(r'[\u4e00-\u9fff\w]+', query_text.lower()))
                def score(f):
                    text = (f['title'] + ' ' + f['content'][:500]).lower()
                    return sum(1 for w in query_words if w in text)
                selected = sorted(all_files, key=score, reverse=True)[:max_files]
                selected.sort(key=lambda f: (f['depth'], f['title']))  # 保持目录结构

            for f in selected:
                lines.append(f'## {f["title"]}')
                body = f['content'].strip()
                if body.startswith('# '):
                    body = body.split('\n', 1)[1].strip() if '\n' in body else ''
                lines.append(body)
                lines.append('')

            return '\n'.join(lines) if len(lines) > 3 else ''
        except Exception as e:
            logger.warning(f'遍历知识库目录失败 {kb_path}: {e}')
            return ''


    @staticmethod
    async def call_openai_compatible_api(
        config: AIModelConfig,
        messages: List[Dict[str, Any]],
        max_tokens: int = None,
        temperature: float = None,
    ) -> Dict[str, Any]:
        """
        调用OpenAI兼容格式的API

        Args:
            config: AI模型配置
            messages: 消息列表
            max_tokens: 可选的最大token数，如果不指定则使用config.max_tokens
            temperature: 可选的温度参数，如果不指定则使用config.temperature

        Returns:
            API响应字典
        """
        headers = {
            'Authorization': f'Bearer {config.api_key}',
            'Content-Type': 'application/json'
        }

        # 使用传入的max_tokens或默认使用config.max_tokens
        actual_max_tokens = max_tokens if max_tokens is not None else config.max_tokens
        actual_temperature = temperature if temperature is not None else config.temperature

        data = {
            'model': config.model_name,
            'messages': messages,
            'max_tokens': actual_max_tokens,
            'temperature': actual_temperature,
            'top_p': config.top_p,
            'stream': False
        }
        
        # 确保base_url不以/结尾
        base_url = config.base_url.rstrip('/')
        # 如果用户没有输入完整的v1/chat/completions路径，尝试智能补全
        if not base_url.endswith('/chat/completions'):
            if base_url.endswith('/v1'):
                url = f"{base_url}/chat/completions"
            else:
                # 默认假设是根路径，尝试添加 v1/chat/completions
                # 但对于某些API（如DeepSeek），base_url可能已经是 https://api.deepseek.com
                url = f"{base_url}/v1/chat/completions"
        else:
            url = base_url

        logger.info(f"=== API调用详情 ===")
        logger.info(f"原始base_url: {config.base_url}")
        logger.info(f"最终请求URL: {url}")
        logger.info(f"模型名称: {config.model_name}")
        logger.info(f"请求参数: max_tokens={actual_max_tokens}, temperature={config.temperature}, top_p={config.top_p}")

        try:
            # 增加HTTP超时时间到900秒（15分钟），支持大文档生成
            # 禁用HTTP/2，使用HTTP/1.1以提高兼容性
            # 显式设置所有超时参数，避免默认的连接超时导致请求失败
            timeout_config = httpx.Timeout(
                connect=60.0,      # 连接超时：60秒
                read=900.0,        # 读取超时：900秒（15分钟）
                write=60.0,        # 写入超时：60秒
                pool=60.0          # 连接池超时：60秒
            )
            async with httpx.AsyncClient(timeout=timeout_config, http2=False) as client:
                logger.info(f"发送POST请求到: {url}")
                response = await client.post(
                    url,
                    headers=headers,
                    json=data
                )

                logger.info(f"收到响应: status_code={response.status_code}")

                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(f"API调用返回错误: Status={response.status_code}, Body={error_detail}")

                response.raise_for_status()
                result = response.json()
                logger.info(f"API调用成功，响应内容: {str(result)[:200]}...")
                return result
        except httpx.HTTPStatusError as e:
            provider_name = config.get_model_type_display()
            error_msg = f"{provider_name} API返回错误 {e.response.status_code}: {e.response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        except httpx.TimeoutException as e:
            provider_name = config.get_model_type_display()
            logger.error(f"{provider_name} API请求超时: {repr(e)}")
            raise Exception(f"{provider_name} API请求超时，请稍后再试或检查网络连接")
        except Exception as e:
            provider_name = config.get_model_type_display()
            # Use repr(e) to capture the full exception type and message, especially if str(e) is empty
            logger.error(f"{provider_name} API调用失败: {repr(e)}")
            raise Exception(f"{provider_name} API调用失败: {str(e) or repr(e)}")
    
    @staticmethod
    async def embed_texts(config: AIModelConfig, texts: List[str]) -> List[List[float]]:
        """
        调用 OpenAI 兼容的 embeddings 接口，返回每条文本的向量。
        用于墨刀技能的三路合并语义去重（方案 A：Chroma + bge-m3）。

        Args:
            config: 向量化模型配置（role='embedder'）
            texts: 待向量化的文本列表
        Returns:
            与 texts 等长的向量列表；空输入返回空列表
        """
        if not texts:
            return []
        headers = {
            'Authorization': f'Bearer {config.api_key}',
            'Content-Type': 'application/json'
        }
        base_url = config.base_url.rstrip('/')
        if base_url.endswith('/embeddings'):
            url = base_url
        elif base_url.endswith('/v1'):
            url = f"{base_url}/embeddings"
        else:
            url = f"{base_url}/v1/embeddings"

        # 分批调用：部分服务商（如 dashscope 兼容模式）单次请求最多约 10 条输入，
        # 超出会返回 400；按 BATCH_SIZE 切片后逐批请求，再按顺序拼接结果。
        BATCH_SIZE = 10
        timeout_config = httpx.Timeout(
            connect=60.0,
            read=120.0,
            write=60.0,
            pool=60.0
        )
        all_embeddings: List[List[float]] = []
        try:
            async with httpx.AsyncClient(timeout=timeout_config, http2=False) as client:
                for start in range(0, len(texts), BATCH_SIZE):
                    batch = texts[start:start + BATCH_SIZE]
                    data = {
                        'model': config.model_name,
                        'input': batch,
                    }
                    response = await client.post(url, headers=headers, json=data)
                    response.raise_for_status()
                    result = response.json()
                    # OpenAI 兼容返回：data[i].embedding（顺序与输入一致）
                    all_embeddings.extend(item['embedding'] for item in result['data'])
            return all_embeddings
        except Exception as e:
            provider_name = config.get_model_type_display()
            logger.error(f"{provider_name} Embedding 调用失败: {repr(e)}")
            raise Exception(f"{provider_name} Embedding 调用失败: {str(e) or repr(e)}")

    @staticmethod
    async def call_deepseek_api(config: AIModelConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """调用DeepSeek API (兼容OpenAI格式)"""
        return await AIModelService.call_openai_compatible_api(config, messages)
    
    @staticmethod
    async def call_qwen_api(config: AIModelConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """调用千问API (兼容OpenAI格式)"""
        return await AIModelService.call_openai_compatible_api(config, messages)

    @staticmethod
    async def call_openai_compatible_api_stream(
        config: AIModelConfig,
        messages: List[Dict[str, str]],
        callback=None,
        max_tokens: int = None,
        temperature: float = None,
    ) -> AsyncIterator[str]:
        """
        流式调用OpenAI兼容格式的API，支持自动续写
        """
        headers = {
            'Authorization': f'Bearer {config.api_key}',
            'Content-Type': 'application/json'
        }

        # 使用传入的max_tokens或默认使用config.max_tokens
        actual_max_tokens = max_tokens if max_tokens is not None else config.max_tokens
        actual_temperature = temperature if temperature is not None else config.temperature

        # 确保base_url不以/结尾
        base_url = config.base_url.rstrip('/')
        if not base_url.endswith('/chat/completions'):
            if base_url.endswith('/v1'):
                url = f"{base_url}/chat/completions"
            else:
                url = f"{base_url}/v1/chat/completions"
        else:
            url = base_url

        # 续写控制
        current_messages = list(messages)  # 浅拷贝
        continuation_count = 0
        MAX_CONTINUATIONS = 5  # 最大续写次数，防止死循环
        
        while continuation_count <= MAX_CONTINUATIONS:
            data = {
                'model': config.model_name,
                'messages': current_messages,
                'max_tokens': actual_max_tokens,
                'temperature': actual_temperature,
                'top_p': config.top_p,
                'stream': True
            }

            logger.info(f"发起流式请求 (第{continuation_count+1}次), messages数量: {len(current_messages)}")

            chunk_content_buffer = ""  # 本次请求生成的完整内容缓存
            finish_reason = None
            
            try:
                # 显式设置所有超时参数
                timeout_config = httpx.Timeout(
                    connect=60.0,      # 连接超时：60秒
                    read=900.0,        # 读取超时：900秒（15分钟）
                    write=60.0,        # 写入超时：60秒
                    pool=60.0          # 连接池超时：60秒
                )
                async with httpx.AsyncClient(timeout=timeout_config, http2=False) as client:
                    async with client.stream('POST', url, headers=headers, json=data) as response:
                        if response.status_code != 200:
                            error_detail = await response.aread()
                            error_msg = error_detail.decode('utf-8')
                            logger.error(f"流式API调用返回错误: Status={response.status_code}, Body={error_msg}")
                            response.raise_for_status()

                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue

                            if line.startswith('data: '):
                                data_str = line[6:]
                                if data_str.strip() == '[DONE]':
                                    break

                                try:
                                    chunk_data = json.loads(data_str)
                                    if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                        choice = chunk_data['choices'][0]
                                        delta = choice.get('delta', {})
                                        finish_reason = choice.get('finish_reason', None)
                                        content = delta.get('content', '')

                                        if content:
                                            chunk_content_buffer += content
                                            if callback:
                                                await callback(content)
                                            yield content
                                            
                                        # 如果在中途就收到了finish_reason（有些流式实现会在最后一条数据带上finish_reason）
                                        if finish_reason:
                                            pass 

                                except json.JSONDecodeError:
                                    continue
            
                # 本次请求结束
                # 检查 finish_reason
                if finish_reason == 'length':
                    logger.warning(f"检测到生成被截断 (finish_reason='length')，准备自动续写。当前已续写 {continuation_count} 次。")
                    continuation_count += 1
                    
                    # 将本次生成的内容作为 assistant 回复加入历史
                    # 注意：如果之前已经有assistant消息，需要追加内容而不是新增消息
                    if current_messages[-1]['role'] == 'assistant':
                        current_messages[-1]['content'] += chunk_content_buffer
                    else:
                        current_messages.append({"role": "assistant", "content": chunk_content_buffer})
                    
                    # 只有当上一条不是user的续写指令时，才添加新的user指令
                    # 防止多次续写时堆叠重复的 user 指令
                    if current_messages[-1]['role'] != 'user':
                        current_messages.append({"role": "user", "content": "请继续输出剩余的内容，不要重复已输出的部分，紧接着上文继续。"})
                    
                    # 发送换行符以分隔续写内容（可选，视模型而定，通常不需要，但为了保险）
                    # yield "\n" 
                    continue
                else:
                    logger.info(f"流式生成正常结束 (finish_reason={finish_reason})")
                    break

            except Exception as e:
                logger.error(f"流式请求异常: {e}")
                # 如果是超时或其他网络错误，可能需要重试机制，这里暂时直接抛出
                raise e
    
    @staticmethod
    def _build_generation_instructions(task: TestCaseGenerationTask):
        """根据生成模式构建不同的生成指令"""
        mode = task.generation_mode or 'smart'
        
        instructions = {
            'smart': (
                "【生成指令 - 智能模式】\n"
                "请你先快速评估需求文档的功能复杂度（简单/中等/复杂），然后自行决定生成策略：\n\n"
                "**复杂度判断标准**：\n"
                "- 简单：1-2个页面/弹窗，功能单一（如修改昵称、意见反馈）-> 目标 10~20 条\n"
                "- 中等：3-5个页面/交互环节，有状态流转或多种输入组合 -> 目标 20~35 条\n"
                "- 复杂：5个以上页面/模块，涉及多角色/权限/外部依赖/复杂状态机 -> 目标 35+ 条\n\n"
                "**生成要求**：\n"
                "1. 请在用例列表开头用一行注释标明你评估的复杂度等级和推理依据\n"
                "2. 简单功能：聚焦核心 Happy Path，每个功能点 1-2 条用例，允许合并相近场景\n"
                "3. 中等功能：每个功能点正常+异常各 1-2 条，适度拆分\n"
                "4. 复杂功能：全面覆盖，深度遍历，不设上限\n"
            ),
            'quick': (
                f"【生成指令 - 快速模式】\n"
                f"1. **数量目标**：总共生成 10-20 条用例，聚焦核心功能和最关键的风险点。\n"
                f"2. **覆盖策略**：\n"
                f"   - 仅覆盖核心功能流程（Happy Path）+ 最关键的 2-3 个异常场景。\n"
                f"   - 每个功能点只保留 1-2 条最重要的用例。\n"
                f"   - 跳过次要边界值和低优先级异常。\n"
                f"3. **合并原则**：可以将密切相关的正常场景合并为一条用例（如\"新增+查询\"可合并）。\n"
                f"4. **优先级**：80% 的用例应标记为 P1 或更高。\n"
            ),
            'standard': (
                f"【生成指令 - 标准模式】\n"
                f"1. **数量目标**：总共生成 20-40 条用例，覆盖主要功能流程和常见异常。\n"
                f"2. **覆盖策略**：\n"
                f"   - 每个功能点设计：1-2 个正常场景 + 1-2 个关键异常/边界场景。\n"
                f"   - 按需求文档结构逐章分析，不要遗漏主要功能点。\n"
                f"3. **合并原则**：同一功能的多个正常分支可以适当合并，但关键异常场景需独立。\n"
                f"4. **优先级**：核心流程 P1，边界/异常 P2。\n"
            ),
            'comprehensive': (
                f"【生成指令 - 全面模式】\n"
                f"1. **数量原则**：请根据需求内容的实际复杂度，自动决定生成用例的数量。务必覆盖所有功能点、异常场景和边界条件，不设数量上限，应写尽写。\n"
                f"2. **深度遍历策略**：\n"
                f"   - 请按文档结构逐章节分析，不要遗漏末尾的功能点。\n"
                f"   - 对每个功能点，必须设计：1个正常场景 + 2-3个异常/边界场景。\n"
                f"3. **拒绝合并**：严禁将多个验证点合并在一条用例中。例如'验证输入框'应拆分为'输入为空'、'输入超长'、'输入特殊字符'等独立用例。\n"
                f"4. **场景扩展库**：\n"
                f"   - 数据完整性（必填项、默认值、数据类型）\n"
                f"   - 业务逻辑约束（状态流转、权限控制、重复操作）\n"
                f"   - 外部接口异常（超时、断网、返回错误）\n"
                f"   - UI交互体验（提示文案、跳转逻辑、防误触）\n"
            ),
        }
        
        return instructions.get(mode, instructions['smart'])

    @staticmethod
    def _build_confirmed_answers_context(task: 'TestCaseGenerationTask') -> str:
        """
        从 task.confirmed_answers（JSON字符串）构建「需求拆解确认结论」上下文段，
        注入到用例生成提示词中，让 AI 基于已确认的业务决策生成更精准的用例。
        """
        raw = (task.confirmed_answers or '').strip()
        if not raw:
            return ''
        try:
            import json
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return ''
        if not isinstance(items, list) or not items:
            return ''
        lines = [
            '【需求拆解阶段确认结论】',
            '（以下为用户在需求拆解/精炼环节对不确定项的确认回答，生成测试用例时必须严格遵循）',
            '',
        ]
        for i, item in enumerate(items, 1):
            q = item.get('question', '').strip()
            a = item.get('answer', '').strip()
            if q:
                lines.append(f'{i}. **问题**：{q}')
                lines.append(f'   **确认**：{a or "（采纳AI推测）"}')
                lines.append('')
        return '\n'.join(lines)

    @staticmethod
    async def generate_test_cases(task: TestCaseGenerationTask) -> str:
        """生成测试用例"""
        writer_prompt = task.writer_prompt_config.content

        # 注入项目知识库上下文
        knowledge_context = AIModelService.build_knowledge_context(task)
        knowledge_section = f"{knowledge_context}\n" if knowledge_context else ""

        # 注入需求拆解确认结论上下文
        confirmed_section = AIModelService._build_confirmed_answers_context(task)
        confirmed_block = f"{confirmed_section}\n" if confirmed_section else ""

        # 根据生成模式构建不同的指令
        mode_instructions = AIModelService._build_generation_instructions(task)

        # 构建用户提示
        user_message = (
            f"请深入分析以下需求文档，并设计测试用例。\n\n"
            f"{knowledge_section}"
            f"{confirmed_block}"
            f"{mode_instructions}\n"
            f"5. **⚠️ 输出顺序要求（必须严格执行）**：\n"
            f"   - **必须按用例编号从小到大的顺序输出**（如：001, 002, 003...或LOGIN_001, LOGIN_002, LOGIN_003...）\n"
            f"   - **绝对不能跳号、重复或乱序输出**\n"
            f"   - **编号必须连续，中间不能有遗漏**\n"
            f"   - **所有用例必须一次性完整输出，不能中断**\n\n"
            f"【需求文档内容】\n{task.requirement_text}"
        )

        messages = [
            {"role": "system", "content": writer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 所有支持的模型都使用兼容OpenAI的接口
        # 使用配置的max_tokens，不硬编码限制
        response = await AIModelService.call_openai_compatible_api(
            task.writer_model_config,
            messages
            # 不再硬编码max_tokens，使用配置文件中的值（如32000）
        )

        return response['choices'][0]['message']['content']
    
    @staticmethod
    async def review_test_cases(task: TestCaseGenerationTask, test_cases: str) -> str:
        """评审测试用例"""
        try:
            reviewer_prompt = task.reviewer_prompt_config.content

            # 增强的评审指令
            user_message = (
                f"请对以下生成的测试用例进行严格的专家级评审。\n\n"
                f"【评审重点】\n"
                f"1. **覆盖率漏洞**：请仔细比对用例集是否覆盖了常见的异常场景（如断网、超时、数据冲突）和边界条件。\n"
                f"2. **逻辑严密性**：检查预期结果是否具体、可验证（例如'提示错误'是不够的，需说明具体错误码或文案）。\n"
                f"3. **冗余检查**：指出是否有重复或无效的用例。\n"
                f"4. **不确定项识别（⚠️重要）**：评审过程中，如果遇到需求文档未明确说明、或你无法根据现有信息做出确定判断的问题，\n"
                f"   必须在报告中用以下格式标记为不确定项，交由人工确认：\n"
                f"   - ⚠️ 待确认：[无法确定的具体问题，用问句形式简洁描述]\n"
                f"   例如：⚠️ 待确认：截屏保存到相册是否需要用户授权弹窗？需求中未提及\n"
                f"   例如：⚠️ 待确认：用户评论的字数上限是500还是1000？原有用例与需求描述不一致\n\n"
                f"【待评审用例】\n{test_cases}\n\n"
                f"【输出格式要求】\n"
                f"1. 先输出完整的评审报告（含评分、问题列表、改进建议），\n"
                f"   报告中的不确定项已在对应位置用 ⚠️ 标记。\n"
                f"2. 在报告末尾，用以下格式汇总所有不确定项（不要遗漏！）：\n\n"
                f"## ⚠️ 待人工确认项清单\n"
                f"- ⚠️ 待确认：[问题1简述]\n"
                f"- ⚠️ 待确认：[问题2简述]\n"
                f"...\n\n"
                f"**如果没有不确定项，请输出：## ⚠️ 待人工确认项清单\n无（所有评审点均可确定）**\n"
                f"**重要**：输出格式要求紧凑，不要在段落之间添加多余的空行，每个问题点之间用单空行分隔即可，用例展示仍为markdown形式。"
            )

            messages = [
                {"role": "system", "content": reviewer_prompt},
                {"role": "user", "content": user_message}
            ]

            # 所有支持的模型都使用兼容OpenAI的接口
            response = await AIModelService.call_openai_compatible_api(task.reviewer_model_config, messages)

            return response['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"评审测试用例时出错: {e}")
            # 返回一个默认的评审结果
            return f"评审过程中出现错误: {str(e)}\n\n建议：测试用例结构完整，可以使用。"

    @staticmethod
    async def generate_test_cases_stream(
        task: TestCaseGenerationTask,
        callback=None
    ) -> str:
        """
        流式生成测试用例

        Args:
            task: 生成任务对象
            callback: 可选的回调函数，每收到一个chunk就调用，用于实时保存到数据库

        Returns:
            str: 完整的测试用例内容
        """
        writer_prompt = task.writer_prompt_config.content

        # 注入项目知识库上下文
        knowledge_context = AIModelService.build_knowledge_context(task)
        knowledge_section = f"{knowledge_context}\n" if knowledge_context else ""

        # 注入需求拆解确认结论上下文
        confirmed_section = AIModelService._build_confirmed_answers_context(task)
        confirmed_block = f"{confirmed_section}\n" if confirmed_section else ""

        # 根据生成模式构建不同的指令
        mode_instructions = AIModelService._build_generation_instructions(task)

        # 构建用户提示
        user_message = (
            f"请深入分析以下需求文档，并设计测试用例。\n\n"
            f"{knowledge_section}"
            f"{confirmed_block}"
            f"{mode_instructions}\n"
            f"5. **⚠️ 输出顺序要求（必须严格执行）**：\n"
            f"   - **必须按用例编号从小到大的顺序输出**（如：001, 002, 003...或LOGIN_001, LOGIN_002, LOGIN_003...）\n"
            f"   - **绝对不能跳号、重复或乱序输出**\n"
            f"   - **编号必须连续，中间不能有遗漏**\n"
            f"   - **所有用例必须一次性完整输出，不能中断**\n\n"
            f"【需求文档内容】\n{task.requirement_text}"
        )

        messages = [
            {"role": "system", "content": writer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 流式调用API，确保正确关闭生成器
        # 使用配置的max_tokens，不硬编码限制
        generator = AIModelService.call_openai_compatible_api_stream(
            task.writer_model_config,
            messages,
            callback=callback
            # 不再硬编码max_tokens，使用配置文件中的值（如32000）
        )

        full_content = ""
        chunk_count = 0
        try:
            async for chunk in generator:
                full_content += chunk
                chunk_count += 1
        except Exception as e:
            logger.error(f"流式生成测试用例时出错: {e}")
            raise
        finally:
            # 确保生成器被正确关闭
            try:
                await generator.aclose()
            except Exception as close_error:
                logger.warning(f"关闭generator时出错: {close_error}")

        logger.info(f"流式生成完成: 总chunk数={chunk_count}, 总字符数={len(full_content)}")

        # 统计生成的用例数量
        case_count = full_content.count('TC-') + full_content.count('TEST-') + full_content.count('测试用例')
        logger.info(f"生成用例统计: 约检测到{case_count}个用例编号标记")

        return full_content

    @staticmethod
    async def review_test_cases_stream(
        task: TestCaseGenerationTask,
        test_cases: str,
        callback=None
    ) -> str:
        """
        流式评审测试用例

        Args:
            task: 生成任务对象
            test_cases: 待评审的测试用例
            callback: 可选的回调函数，每收到一个chunk就调用

        Returns:
            str: 完整的评审反馈
        """
        reviewer_prompt = task.reviewer_prompt_config.content

        # 增强的评审指令
        user_message = (
            f"请对以下生成的测试用例进行严格的专家级评审。\n\n"
            f"【评审重点】\n"
            f"1. **覆盖率漏洞**：请仔细比对用例集是否覆盖了常见的异常场景（如断网、超时、数据冲突）和边界条件。\n"
            f"2. **逻辑严密性**：检查预期结果是否具体、可验证（例如'提示错误'是不够的，需说明具体错误码或文案）。\n"
            f"3. **冗余检查**：指出是否有重复或无效的用例。\n"
            f"4. **不确定项识别（⚠️重要）**：评审过程中，如果遇到需求文档未明确说明、或你无法根据现有信息做出确定判断的问题，\n"
            f"   必须在报告中用以下格式标记为不确定项，交由人工确认：\n"
            f"   - ⚠️ 待确认：[无法确定的具体问题，用问句形式简洁描述]\n"
            f"   例如：⚠️ 待确认：截屏保存到相册是否需要用户授权弹窗？需求中未提及\n"
            f"   例如：⚠️ 待确认：用户评论的字数上限是500还是1000？原有用例与需求描述不一致\n\n"
            f"【待评审用例】\n{test_cases}\n\n"
            f"【输出格式要求】\n"
            f"1. 先输出完整的评审报告（含评分、问题列表、改进建议），\n"
            f"   报告中的不确定项已在对应位置用 ⚠️ 标记。\n"
            f"2. 在报告末尾，用以下格式汇总所有不确定项（不要遗漏！）：\n\n"
            f"## ⚠️ 待人工确认项清单\n"
            f"- ⚠️ 待确认：[问题1简述]\n"
            f"- ⚠️ 待确认：[问题2简述]\n"
            f"...\n\n"
            f"**如果没有不确定项，请输出：## ⚠️ 待人工确认项清单\n无（所有评审点均可确定）**\n"
            f"**重要**：输出格式要求紧凑，不要在段落之间添加多余的空行，每个问题点之间用单空行分隔即可，用例展示仍为markdown形式。"
        )

        messages = [
            {"role": "system", "content": reviewer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 流式调用API，确保正确关闭生成器
        generator = AIModelService.call_openai_compatible_api_stream(
            task.reviewer_model_config,
            messages,
            callback=callback
        )

        full_content = ""
        chunk_count = 0
        try:
            async for chunk in generator:
                full_content += chunk
                chunk_count += 1
        except Exception as e:
            logger.error(f"流式评审测试用例时出错: {e}")
            return f"评审过程中出现错误: {str(e)}\n\n建议：测试用例结构完整，可以使用。"
        finally:
            # 确保生成器被正确关闭
            try:
                await generator.aclose()
            except Exception as close_error:
                logger.warning(f"关闭generator时出错: {close_error}")

        logger.info(f"流式评审完成: 总chunk数={chunk_count}, 总字符数={len(full_content)}")
        return full_content

    @staticmethod
    async def revise_test_cases_based_on_review(
        task: TestCaseGenerationTask,
        original_test_cases: str,
        review_feedback: str,
        callback=None,
        human_feedback: str = None
    ) -> str:
        """
        根据评审意见改进测试用例

        Args:
            task: 生成任务对象
            original_test_cases: 原始生成的测试用例
            review_feedback: AI评审意见
            callback: 可选的回调函数，每收到一个chunk就调用
            human_feedback: 人工对评审中不确定需求的回复/确认

        Returns:
            str: 改进后的测试用例
        """
        writer_prompt = task.writer_prompt_config.content

        # 构建改进指令
        human_feedback_block = ""
        if human_feedback and human_feedback.strip():
            human_feedback_block = (
                f"【人工确认回复】\n{human_feedback.strip()}\n\n"
                f"⚠️ 以上是人工对评审中不确定需求的确认/补充说明。请务必据此调整测试用例的预期结果和场景设计，"
                f"人工确认的信息优先级最高。\n\n"
            )

        user_message = (
            f"请根据以下专家评审意见，改进和完善测试用例。\n\n"
            f"【原始测试用例】\n{original_test_cases}\n\n"
            f"【评审意见】\n{review_feedback}\n\n"
            f"{human_feedback_block}"
            f"【改进要求】\n"
            f"1. 严格根据评审意见指出的问题进行修改\n"
            f"2. 补充缺失的测试场景\n"
            f"3. 修正不合理的预期结果\n"
            f"4. 删除冗余的测试用例\n"
            f"5. 保持测试用例的格式规范\n"
            f"6. **加粗标记规则（必须严格执行）**：\n"
            f"   **6.1 新增测试用例**：对整个新增的测试用例进行加粗\n"
            f"   - 示例：**TC-004 测试用例标题**\\n**测试步骤：**\\n**1. 步骤内容**\\n**预期结果：**\\n**2. 预期内容**\n"
            f"   - 注意：新增用例的编号、标题、步骤、预期结果等所有内容都要加粗\n"
            f"   **6.2 修改现有用例**：只对被修改的具体部分进行加粗\n"
            f"   - 修改标题：**TC-001 修改后的新标题**（其他内容保持原样）\n"
            f"   - 修改步骤：1. 原步骤\\n2. **修改后的步骤内容**（只有步骤2加粗）\n"
            f"   - 修改预期结果：预期结果：**修改后的预期内容**（只有预期内容加粗）\n"
            f"   - 新增步骤：1. 原步骤\\n**2. 新增的步骤内容**（新增的步骤整体加粗）\n"
            f"   **6.3 注意事项**：\n"
            f"   - 未修改的部分不要加粗\n"
            f"   - 原始测试用例中已经存在的用例，如果没有改动就不要加粗\n"
            f"   - 只有根据评审意见新增或修改的部分才需要加粗\n"
            f"7. **⚠️ 输出顺序要求（必须严格执行）**：\n"
            f"   - **必须按用例编号从小到大的顺序输出**（如：001, 002, 003...或LOGIN_001, LOGIN_002, LOGIN_003...）\n"
            f"   - **绝对不能跳号、重复或乱序输出**\n"
            f"   - **编号必须连续，中间不能有遗漏**\n"
            f"   - **所有用例必须一次性完整输出，不能中断**\n"
            f"8. **必须输出完整**：请确保输出所有改进后的测试用例，不要因为篇幅原因省略任何用例，"
            f"即使是第30条、第40条甚至更多的用例，也必须完整输出。\n"
            f"9. **测试用例编号规则**：新增的测试用例必须按照原有编号规则继续编号（例如原最后一个用例是TC-003，新增的第一个用例应该是TC-004），"
            f"绝不能使用'新增'、'用例1'等作为编号，必须是正式的测试用例编号。\n\n"
            f"请直接输出改进后的完整测试用例，不要包含任何说明性文字。"
        )

        messages = [
            {"role": "system", "content": writer_prompt},
            {"role": "user", "content": user_message}
        ]

        # 流式调用API，确保正确关闭生成器
        # 使用配置的max_tokens，不硬编码限制
        generator = AIModelService.call_openai_compatible_api_stream(
            task.writer_model_config,
            messages,
            callback=callback
            # 不再硬编码max_tokens，使用配置文件中的值（如32000）
        )

        full_content = ""
        chunk_count = 0
        try:
            async for chunk in generator:
                full_content += chunk
                chunk_count += 1
        except Exception as e:
            logger.error(f"根据评审意见改进测试用例时出错: {e}")
            # 改进失败时返回原始用例
            return original_test_cases
        finally:
            # 确保生成器被正确关闭
            try:
                await generator.aclose()
            except Exception as close_error:
                logger.warning(f"关闭generator时出错: {close_error}")

        logger.info(f"流式改进完成: 总chunk数={chunk_count}, 总字符数={len(full_content)}")

        # 统计改进后的用例数量
        case_count = full_content.count('TC-') + full_content.count('**TC-') + full_content.count('测试用例')
        logger.info(f"改进用例统计: 约检测到{case_count}个用例编号标记")

        return full_content

    @staticmethod
    def sort_test_cases_by_id(test_cases_content: str) -> str:
        """
        按照测试用例编号排序测试用例内容

        Args:
            test_cases_content: 测试用例内容（字符串）

        Returns:
            str: 排序后的测试用例内容
        """
        if not test_cases_content:
            return test_cases_content

        import re

        # 按行分割内容
        lines = test_cases_content.split('\n')

        # 识别用例块：每个用例从包含编号的行开始
        # 支持多种编号格式：TC-001, TC001, TEST-001, 测试用例1, 1. 等
        case_pattern = re.compile(r'^(#{1,6}\s+)?(?:TC[-_]?\d+|TEST[-_]?\d+|测试用例\d+|\d+[\.\、]\s*[:：]?\s*\S+)', re.IGNORECASE | re.MULTILINE)

        # 找到所有用例块的起始位置
        case_starts = []
        for i, line in enumerate(lines):
            if case_pattern.match(line):
                case_starts.append(i)

        # 如果没有找到编号，返回原内容
        if len(case_starts) < 2:
            logger.info(f"未检测到足够的用例编号（只找到{len(case_starts)}个），保持原顺序")
            return test_cases_content

        # 提取每个用例块
        case_blocks = []
        for i in range(len(case_starts)):
            start = case_starts[i]
            # 下一个用例的开始位置，或者文件末尾
            end = case_starts[i + 1] if i + 1 < len(case_starts) else len(lines)
            block_lines = lines[start:end]
            block_content = '\n'.join(block_lines)
            case_blocks.append({
                'start': start,
                'content': block_content,
                'first_line': block_lines[0] if block_lines else ''
            })

        # 提取编号用于排序
        def extract_case_id(block):
            first_line = block['first_line']
            # 尝试匹配各种编号格式
            # TC-001, TC001, TEST-001, 测试用例1, 1. xxx 等
            match = re.search(r'(?:TC[-_]?|TEST[-_]?|测试用例)?(\d+)', first_line, re.IGNORECASE)
            if match:
                return int(match.group(1))
            return 0

        # 按编号排序
        try:
            case_blocks.sort(key=extract_case_id)
            logger.info(f"成功对{len(case_blocks)}个测试用例按编号排序")
        except Exception as e:
            logger.warning(f"排序失败: {e}，保持原顺序")

        # 重新组合内容
        sorted_content = '\n'.join([block['content'] for block in case_blocks])

        return sorted_content

    @staticmethod
    def fix_incomplete_last_case(test_cases_content: str) -> str:
        """
        检测并修复不完整的最后一条测试用例

        Args:
            test_cases_content: 测试用例内容

        Returns:
            str: 修复后的测试用例内容
        """
        if not test_cases_content:
            return test_cases_content

        lines = test_cases_content.split('\n')

        # 检查最后几行，找到最后一个表格行
        table_lines = []
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if line.startswith('|') and line.endswith('|'):
                table_lines.insert(0, (i, line))
                # 只检查最后10行
                if len(table_lines) >= 10:
                    break

        if not table_lines:
            return test_cases_content

        # 检查最后一个表格行是否完整（应该有7个|，即7列）
        last_line_index, last_line = table_lines[-1]
        column_count = last_line.count('|')

        # 正常的表格应该有7个|（开头+结尾+5个分隔符）
        if column_count < 7:
            logger.warning(f"检测到最后一条用例不完整: 只有{column_count}列，应该是7列")
            # 删除不完整的最后一条用例
            # 找到完整的上一条用例
            for i in range(len(table_lines) - 2, -1, -1):
                prev_index, prev_line = table_lines[i]
                if prev_line.count('|') >= 7:
                    # 截断到上一条完整用例的位置
                    fixed_content = '\n'.join(lines[:prev_index + 1])
                    logger.info(f"已删除不完整的最后一条用例，保留了{prev_index + 1}行")
                    return fixed_content

            # 如果找不到完整的上一条，直接删除最后5行
            fixed_content = '\n'.join(lines[:-5])
            logger.info(f"删除最后5行不完整的内容")
            return fixed_content

        return test_cases_content

    @staticmethod
    def renumber_test_cases(test_cases_content: str) -> str:
        """
        重新编号测试用例，使其编号连续

        Args:
            test_cases_content: 测试用例内容（字符串）

        Returns:
            str: 重新编号后的测试用例内容
        """
        if not test_cases_content:
            return test_cases_content

        import re

        lines = test_cases_content.split('\n')

        # 找到表格分隔线
        separator_line = None
        separator_index = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('|') and '|' in line and '---' in line:
                separator_line = line
                separator_index = i
                break

        if not separator_line:
            logger.warning("未找到表格分隔线，无法重新编号")
            return test_cases_content

        # 计算列数
        column_count = separator_line.count('|')

        # 找到第一个数据行（包含编号的行）
        first_data_index = -1
        for i in range(separator_index + 1, len(lines)):
            line = lines[i]
            if line.strip().startswith('|') and line.count('|') == column_count:
                first_data_index = i
                break

        if first_data_index == -1:
            logger.warning("未找到任何数据行")
            return test_cases_content

        # 从第一个数据行中提取编号格式
        first_line = lines[first_data_index]
        parts = first_line.split('|')
        if len(parts) < 2:
            logger.warning("无法解析第一列")
            return test_cases_content

        # 获取第一列的编号（例如：IMMSG001）
        first_id = parts[1].strip()

        # 提取编号格式前缀（例如：IMMSG）
        id_match = re.match(r'^([A-Z]+)(\d+)$', first_id)
        if not id_match:
            logger.warning(f"无法识别编号格式: {first_id}")
            return test_cases_content

        prefix = id_match.group(1)  # 例如：IMMSG
        total_cases = 0

        # 重新编号所有数据行
        result_lines = lines[:first_data_index]
        i = first_data_index

        while i < len(lines):
            line = lines[i]

            # 检查是否是数据行
            if not line.strip().startswith('|'):
                # 不是表格行，添加并继续
                result_lines.append(line)
                i += 1
                continue

            # 检查列数是否正确
            if line.count('|') != column_count:
                # 列数不对，可能是空行或其他内容
                result_lines.append(line)
                i += 1
                continue

            # 这是一个数据行，重新编号
            total_cases += 1
            new_id = f"{prefix}{total_cases:03d}"  # 格式：IMMSG001

            # 替换第一列的编号，保持原有格式
            parts = line.split('|')
            if len(parts) >= 2:
                # 保持第一列（空）和第二列（编号）之间的空格
                # 只替换编号部分
                parts[1] = f" {new_id} "
                new_line = '|'.join(parts)
                result_lines.append(new_line)

            i += 1

        renumbered_content = '\n'.join(result_lines)
        logger.info(f"重新编号完成: 共{total_cases}条测试用例，编号范围: {prefix}001-{prefix}{total_cases:03d}")

        return renumbered_content

    @staticmethod
    def extract_uncertain_items_from_review(review_text: str) -> str:
        """
        从评审报告中提取「待人工确认项清单」中的不确定项，
        并格式化为 human_feedback 存储格式。

        Args:
            review_text: AI评审报告的完整文本

        Returns:
            str: 格式化后的 human_feedback 字符串（空字符串表示无不确定项）
        """
        import re

        if not review_text:
            return ""

        # 定位「## ⚠️ 待人工确认项清单」章节
        # 支持各种变体：## ⚠️ 待人工确认项清单 / ## 待人工确认项清单 / ### ⚠️ 待人工确认项清单
        patterns = [
            r'##\s*⚠️\s*待人工确认项清单\s*\n(.*?)(?=\n##\s|\Z)',
            r'##\s*待人工确认项清单\s*\n(.*?)(?=\n##\s|\Z)',
            r'###\s*⚠️\s*待人工确认项清单\s*\n(.*?)(?=\n##|\n###|\Z)',
        ]

        items_text = None
        from_section = False
        for pattern in patterns:
            match = re.search(pattern, review_text, re.DOTALL)
            if match:
                items_text = match.group(1).strip()
                from_section = True
                break

        if not items_text:
            # 没有独立的「待人工确认项清单」章节，回退到全文搜索 ⚠️ 待确认 行
            logger.info("评审报告中未找到「待人工确认项清单」章节，回退全文搜索 ⚠️ 待确认 行")
            items_text = review_text  # 全量文本作为搜索范围

        # 只有从独立章节提取时才检查"无"（全文回退不会误判）
        if from_section and (items_text.startswith("无") or items_text == "无（所有评审点均可确定）"):
            logger.info("评审报告标注：无不确定项")
            return ""

        # 提取所有 ⚠️ 待确认 行
        # 格式：- ⚠️ 待确认：xxx  或  ⚠️ 待确认：xxx  或 1. ⚠️ 待确认：xxx
        item_patterns = [
            r'[-*]*\s*⚠️\s*待确认[：:]\s*(.+?)(?=\n[-*\d]|\n$|\Z)',
            r'[-*\d]+[\.\)]\s*⚠️\s*待确认[：:]\s*(.+?)(?=\n[-*\d]|\n$|\Z)',
        ]

        items = []
        for pattern in item_patterns:
            matches = re.findall(pattern, items_text, re.DOTALL)
            items.extend([m.strip() for m in matches if m.strip()])

        # 去重
        seen = set()
        unique_items = []
        for item in items:
            if item not in seen:
                seen.add(item)
                unique_items.append(item)

        if not unique_items:
            logger.info("未从待确认项清单中提取到有效问题")
            return ""

        # 格式化为 human_feedback 格式
        feedback_parts = []
        for i, question in enumerate(unique_items, 1):
            feedback_parts.append(
                f"【确认项 #{i}】\n不确定需求：{question}\n确认回复：(未填写)"
            )

        result = "\n\n".join(feedback_parts)
        logger.info(f"从评审报告中提取了 {len(unique_items)} 个不确定项")
        return result


class ModaoPrototype(models.Model):
    """墨刀技能 - 需求来源（墨刀原型 / 需求文本），承载 5 阶段工作流状态与产物。"""
    SOURCE_CHOICES = [
        ('modao', '墨刀原型'),
        ('webshare', 'webshare 页面树'),
        ('text', '需求文本/文档'),
    ]
    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('extracting', '读取中'),
        ('extracted', '已读取'),
        ('structuring', '结构化中'),
        ('clarifying', '澄清中'),
        ('designing', '用例设计中'),
        ('done', '完成'),
        ('failed', '失败'),
    ]

    uuid = models.CharField(max_length=32, unique=True, db_index=True, verbose_name='UUID')
    title = models.CharField(max_length=200, verbose_name='标题', default='墨刀需求梳理')
    url = models.TextField(verbose_name='原型链接', blank=True)
    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='modao', verbose_name='来源类型')
    auth_cookie = models.TextField(blank=True, verbose_name='登录Cookie(JSON)')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    current_stage = models.IntegerField(default=0, verbose_name='当前阶段(0-4)')
    # 各阶段产物（文本/JSON 字符串）
    extracted_json = models.TextField(blank=True, verbose_name='阶段0-逐页提取')
    requirement_summary = models.TextField(blank=True, verbose_name='阶段1-需求摘要')
    clarification_log = models.TextField(blank=True, verbose_name='阶段2-澄清记录')
    module_split = models.TextField(blank=True, verbose_name='阶段3.1-模块拆分')
    risks_json = models.TextField(blank=True, verbose_name='阶段3-风险')
    pci_json = models.TextField(blank=True, verbose_name='阶段3-PCI')
    final_testpoints_json = models.TextField(blank=True, verbose_name='阶段3-合并测试点')
    dedup_audit_json = models.TextField(default='[]', blank=True, verbose_name='阶段3-去重审计记录')
    testcases_json = models.TextField(blank=True, verbose_name='阶段3-用例')
    smoke_json = models.TextField(blank=True, verbose_name='阶段3-冒烟')
    quality_report_json = models.TextField(blank=True, verbose_name='阶段3-质量报告')
    excel_path = models.CharField(max_length=500, blank=True, verbose_name='Excel路径')
    stage_confirmations = models.TextField(default='{}', verbose_name='阶段确认JSON')
    stage4_decision = models.CharField(max_length=20, blank=True, verbose_name='阶段4决策')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    work_log = models.TextField(blank=True, verbose_name='工作日志(各阶段进度)')
    qa_log = models.TextField(default='[]', verbose_name='人工答疑记录(JSON数组)')
    feature_module = models.ForeignKey('feature_modules.FeatureModule', on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='modao_prototypes',
                                       verbose_name='同步的顶层功能模块')
    version = models.ForeignKey('versions.Version', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='modao_prototypes', verbose_name='关联版本')
    project = models.ForeignKey('projects.Project', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='关联项目')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='modao_prototypes', verbose_name='创建者')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'modao_prototype'
        verbose_name = '墨刀原型'
        verbose_name_plural = '墨刀原型'
        ordering = ['-created_at']

    def __str__(self):
        return f'Modao#{self.uuid}'

    def get_confirmations(self):
        try:
            return json.loads(self.stage_confirmations or '{}')
        except Exception:
            return {}

    def set_confirmation(self, stage: int, confirmed: bool = True):
        conf = self.get_confirmations()
        conf[f'stage{stage}_confirmed'] = confirmed
        self.stage_confirmations = json.dumps(conf, ensure_ascii=False)

    def clarification_items(self):
        """Return structured clarification items; legacy free text has no items."""
        raw = (self.clarification_log or '').strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            return []
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def unresolved_clarifications(self):
        """Items requiring a human conclusion before case generation."""
        unresolved = []
        for index, item in enumerate(self.clarification_items()):
            resolution = str(item.get('resolution') or item.get('answer') or '').strip()
            if not resolution:
                unresolved.append({
                    'index': index,
                    'type': item.get('type') or '待确认',
                    'location': item.get('location') or '',
                    'issue': item.get('issue') or item.get('suggested_question') or '',
                })
        return unresolved

    def case_generation_fingerprint(self):
        """Bind human approval to the exact clarification and test-point inputs."""
        content = '\n---CLARIFICATIONS---\n'.join([
            self.clarification_log or '', self.final_testpoints_json or ''
        ])
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def case_generation_gate(self):
        conf = self.get_confirmations()
        unresolved = self.unresolved_clarifications()
        current_fingerprint = self.case_generation_fingerprint()
        approved = bool(conf.get('case_generation_approved'))
        fingerprint_matches = (
            approved and conf.get('case_generation_fingerprint') == current_fingerprint
        )
        stage2_confirmed = bool(conf.get('stage2_confirmed'))
        reasons = []
        if unresolved:
            reasons.append(f'仍有 {len(unresolved)} 条位置/需求问题未填写人工结论')
        if not stage2_confirmed:
            reasons.append('阶段2尚未人工确认')
        if not approved:
            reasons.append('尚未批准生成最终测试用例')
        elif not fingerprint_matches:
            reasons.append('澄清结论或测试点已修改，原生成批准已失效')
        return {
            'allowed': not unresolved and stage2_confirmed and fingerprint_matches,
            'unresolved_count': len(unresolved),
            'unresolved_items': unresolved,
            'stage2_confirmed': stage2_confirmed,
            'approved': approved,
            'fingerprint_matches': fingerprint_matches,
            'reasons': reasons,
        }

class ModaoPage(models.Model):
    """墨刀技能 - 原型单页提取结果。"""
    prototype = models.ForeignKey(ModaoPrototype, on_delete=models.CASCADE, related_name='pages')
    page_no = models.IntegerField(verbose_name='页码')
    page_name = models.CharField(max_length=200, blank=True, verbose_name='页面名')
    text = models.TextField(blank=True, verbose_name='可见文本')
    annotations = models.TextField(default='[]', verbose_name='注释/标注(JSON)')
    screenshot = models.CharField(max_length=500, blank=True, verbose_name='截图路径')

    class Meta:
        db_table = 'modao_page'
        verbose_name = '墨刀页面'
        verbose_name_plural = '墨刀页面'
        ordering = ['page_no']

    def __str__(self):
        return f'P{self.page_no}-{self.page_name}'



    @staticmethod
    async def audit_knowledge_base(
        task: TestCaseGenerationTask,
        test_cases: str,
        review_feedback: str = ""
    ) -> str:
        """
        智能知识库审计：基于AI评审结果和生成的测试用例，发现知识库的不足和需要更新的地方。

        三层校验逻辑：
        1. 评审驱动：从 ⚠️ 待确认项反向推断知识库缺失
        2. 用例对比：将已生成用例与知识库内容对比，发现未覆盖的业务规则
        3. 综合建议：给出增/改/删的结构化建议

        Args:
            task: 生成任务对象（含项目关联、知识库路径等）
            test_cases: 生成的测试用例内容
            review_feedback: AI评审报告的完整文本（可选）

        Returns:
            str: 知识库变更建议的Markdown格式文本
        """
        try:
            # 1. 收集知识库内容
            kb_context = AIModelService.build_knowledge_context(task)
            if not kb_context:
                logger.info(f"[KB审计] 任务 {task.task_id} 无可用知识库，跳过审计")
                return ""

            # 2. 提取评审中的不确定项作为审计线索
            uncertain_items = AIModelService.extract_uncertain_items_from_review(review_feedback)
            uncertain_hint = ""
            if uncertain_items:
                uncertain_hint = (
                    "【评审中发现的不确定项（知识库缺失线索）】\n"
                    f"{uncertain_items}\n\n"
                )

            # 3. 调用AI进行知识库审计
            reviewer_config = task.reviewer_model_config
            if not reviewer_config:
                # 回退到 writer 配置
                reviewer_config = task.writer_model_config
            if not reviewer_config:
                logger.warning(f"[KB审计] 任务 {task.task_id} 无可用模型配置")
                return ""

            system_prompt = (
                "你是一个知识库管理专家。你的任务是审查项目知识库的完整性和准确性。"
                "请基于测试用例和评审反馈，发现知识库中的缺失、过时或不准确的内容。"
            )

            user_message = (
                "【知识库审计任务】\n\n"
                f"{uncertain_hint}"
                "请对比以下三部分内容，找出知识库需要补充或修正的地方：\n\n"
                "【当前知识库内容】\n"
                f"{kb_context}\n\n"
                "【已生成的测试用例】\n"
                f"{test_cases[:8000]}\n\n"
                f"【AI评审反馈】\n"
                f"{review_feedback[:4000]}\n\n"
                "【输出要求】\n"
                "请按以下格式输出知识库变更建议：\n\n"
                "## 🔍 知识库审计报告\n\n"
                "### 一、发现的知识缺口\n"
                "列出测试用例中涉及、但知识库中未覆盖的业务规则、边界条件或异常场景。每条用以下格式：\n"
                "- **缺口**：[描述缺失的内容]\n"
                "  - 📍 证据：[来自评审或测试用例的具体引用]\n"
                "  - 💡 建议：建议补充到知识库的哪个模块\n\n"
                "### 二、建议变更清单\n"
                "对每条建议，使用以下结构化格式：\n"
                "| 操作 | 目标文件/条目 | 变更内容 | 优先级 | 依据 |\n"
                "|------|-------------|---------|--------|------|\n"
                "| 新增 | 目录/文件名 | 具体补充内容 | 高/中/低 | 来自评审第X条/用例TC-XXX |\n"
                "| 修改 | 目录/文件名 | 原内容 → 建议修改为 | 高/中/低 | 依据说明 |\n\n"
                "### 三、无需变更项\n"
                "列出经分析后确认无需修改的部分（可选，避免误报）。\n\n"
                "**重要提示**：\n"
                "- 优先关注评审中 ⚠️待确认 的问题，这些问题往往源于知识库信息不全\n"
                "- 如果知识库已经完善，请明确输出「知识库当前完善，无需变更」\n"
                "- 建议要具体、可执行，不要泛泛而谈"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]

            response = await AIModelService.call_openai_compatible_api(reviewer_config, messages)
            result = response['choices'][0]['message']['content']
            logger.info(f"[KB审计] 任务 {task.task_id} 审计完成，结果长度={len(result) if result else 0}")
            return result

        except Exception as e:
            logger.error(f"[KB审计] 任务 {task.task_id} 审计失败: {e}")
            traceback.print_exc()
            return ""

    @staticmethod
    def auto_fill_knowledge_from_confirmations(
        confirmed_answers: list,
        project_id: int,
        user_id: int,
        model_config=None,
        version_tag='',
        module_tag=''
    ) -> dict:
        """
        基于需求拆解精炼阶段用户确认的问答对，自动将新知识回填到项目知识库（ProjectKnowledge）。
        
        逻辑：
        1. 获取项目现有知识库条目
        2. 调用 AI 判断哪些确认回答代表「新知识」（不在现有库中）
        3. 对每条新知识，创建 ProjectKnowledge 条目（去重：同 project+title 不重复创建）
        4. 返回 {created: [...], skipped: [...]} 统计
        
        Args:
            confirmed_answers: [{question, answer}, ...] 问答对列表
            project_id: 项目 ID
            user_id: 操作用户 ID
            model_config: 可选的 AI 模型配置（用于判断是否为新知识）
            
        Returns:
            dict: {'created_count': N, 'skipped_count': M, 'entries': [...]}
        """
        if not confirmed_answers or not project_id:
            return {'created_count': 0, 'skipped_count': 0, 'entries': []}

        scope_tag = ' / '.join([t for t in [module_tag, version_tag] if t]).strip()

        # 1. 获取现有知识库
        try:
            from apps.projects.models import ProjectKnowledge
            existing = list(ProjectKnowledge.objects.filter(
                project_id=project_id, is_active=True
            ).values_list('title', 'content'))
        except Exception as e:
            logger.warning(f'[KB自动填充] 获取现有知识库失败: {e}')
            existing = []

        # 2. 构建现有知识摘要（供 AI 去重参考）
        existing_summary = ''
        if existing:
            lines = ['【项目现有知识库条目】']
            for title, content in existing:
                lines.append(f'- {title}: {content[:100]}')
            existing_summary = '\n'.join(lines) + '\n'

        # 3. 构建 AI 判断请求
        answers_text = '\n'.join([
            f'{i+1}. 问题：{a.get("question","")}  确认回答：{a.get("answer","") or "采纳AI推测"}'
            for i, a in enumerate(confirmed_answers)
            if a.get('question', '').strip()
        ])

        if not answers_text.strip():
            return {'created_count': 0, 'skipped_count': 0, 'entries': []}

        # 尝试调用 AI 判断；若无模型则用简单规则兜底
        new_items = []
        if model_config:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    scope_instruction = ''
                    if scope_tag:
                        scope_instruction = (
                            f"\n重要：本条知识归属【{scope_tag}】。请在输出每条的 title 开头用"
                            f"【{scope_tag}】标注，并在 content 开头先点明适用的功能/版本范围，"
                            "便于后续按需求语义精确召回，避免与其他同名功能混淆。\n"
                        )
                    system_msg = (
                        "你是一个知识管理专家。你的任务是从用户在需求拆解阶段确认的问答中，"
                        "筛选出值得沉淀到项目知识库的「新业务知识」。\n\n"
                        "判断标准：\n"
                        "- 只筛选**业务决策/规则/约束/约定**类回答（如「统一推荐」「不会影响」「必须XX」）\n"
                        "- 排除临时性操作说明、个人偏好、与测试无关的闲聊\n"
                        "- 与已有知识高度相似的不要重复收录\n"
                        + scope_instruction +
                        "输出格式（严格JSON数组）：\n"
                        '[{"title":"简短标题(10字内，含【功能/版本】前缀)","category":"constraints|test_focus|notes|terminology|background", "content":"完整内容（开头点明适用功能/版本）"}]'
                    )
                    user_msg = f"{existing_summary}\n【待分析的确认问答】\n{answers_text}\n\n请只输出JSON数组，不要其他文字。"
                    result = loop.run_until_complete(
                        AIModelService.call_openai_compatible_api(model_config, [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg}
                        ], max_tokens=2048)
                    )
                    text = result['choices'][0]['message']['content'].strip()
                    # 提取 JSON
                    import json
                    if text.startswith('```'):
                        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                    new_items = json.loads(text)
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f'[KB自动填充] AI判断失败，使用简单规则兜底: {e}')

        # 兜底：无AI或AI失败时，简单规则——所有带明确结论的回答都入库
        if not new_items:
            prefix = f'【{scope_tag}】' if scope_tag else ''
            for a in confirmed_answers:
                q = (a.get('question') or '').strip()
                ans = (a.get('answer') or '').strip()
                if q and ans and len(ans) > 1:
                    # 取问题关键词作为标题
                    title = (prefix + q[:15 - len(prefix)]).replace('？', '').replace('?', '').strip() or f'{prefix}业务确认'
                    new_items.append({
                        'title': title,
                        'category': 'constraints',
                        'content': f'{prefix}**来源问题**：{q}\n**确认结论**：{ans}'
                    })

        # 4. 创建条目（去重）
        created_entries = []
        skipped = 0
        for item in new_items:
            if not isinstance(item, dict):
                continue
            title = (item.get('title') or '').strip()[:200]
            category = item.get('category', 'notes')
            content = (item.get('content') or '').strip()
            if not title or not content:
                continue

            # 去重：同一项目下相同标题不重复创建
            exists = ProjectKnowledge.objects.filter(
                project_id=project_id, title=title
            ).exists()
            if exists:
                skipped += 1
                continue

            try:
                entry = ProjectKnowledge.objects.create(
                    project_id=project_id,
                    title=title,
                    category=category,
                    content=content,
                    is_active=True,
                    sort_order=0,
                    created_by_id=user_id,
                )
                created_entries.append({
                    'id': entry.id, 'title': title, 'category': category
                })
                AIModelService.sync_kb_entry_to_vector(entry, 'upsert')
            except Exception as e:
                logger.warning(f'[KB自动填充] 创建条目失败({title}): {e}')
                skipped += 1

        result = {
            'created_count': len(created_entries),
            'skipped_count': skipped,
            'entries': created_entries,
        }
        logger.info(
            f'[KB自动填充] 项目{project_id}: 新增{len(created_entries)}条, '
            f'跳过已存在{skipped}条, 输入{len(confirmed_answers)}条问答'
        )
        return result
