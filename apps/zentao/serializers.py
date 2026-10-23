from rest_framework import serializers

from .models import (
    CoverageItem,
    CoverageReport,
    DefectReviewReport,
    ZentaoBug,
    ZentaoConfig,
    ZentaoProductMapping,
    ZentaoSyncLog,
)


class ZentaoConfigSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_password = serializers.SerializerMethodField()
    bug_count = serializers.SerializerMethodField()
    last_sync_status = serializers.SerializerMethodField()

    # 数据库只读连接：密码只写不读（与禅道密码同等处理）
    db_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_db_password = serializers.SerializerMethodField()
    db_ready = serializers.SerializerMethodField()

    class Meta:
        model = ZentaoConfig
        fields = [
            'id', 'name', 'base_url', 'account', 'password', 'has_password',
            'product_id', 'execution_id', 'build_id', 'build_name', 'opened_build_keyword',
            'project', 'version', 'is_enabled', 'created_at', 'updated_at',
            'coverage_target', 'bug_count', 'last_sync_status',
            'db_host', 'db_port', 'db_name', 'db_user', 'db_password',
            'has_db_password', 'db_prefix', 'db_ready',
        ]
        read_only_fields = [
            'id', 'has_password', 'created_at', 'updated_at',
            'bug_count', 'last_sync_status', 'has_db_password', 'db_ready',
        ]

    def get_has_password(self, obj) -> bool:
        return bool(obj.password)

    def get_has_db_password(self, obj) -> bool:
        return bool(obj.db_password)

    def get_db_ready(self, obj) -> bool:
        """只判断"配置是否齐全"，不在此发起网络连接（列表接口不能被拖慢）。"""
        from .db_reader import ZentaoReadOnlyDB, ZentaoDBError

        try:
            ZentaoReadOnlyDB.from_config(obj)
        except ZentaoDBError:
            return False
        return True

    def get_bug_count(self, obj) -> int:
        # 禅道 build 参数不精确过滤，因此按 openedBuild 精确匹配 build_name 来统计
        # （与 run_coverage_analysis / fetch_bugs_by_build 口径一致）
        qs = ZentaoBug.objects.filter(config=obj, is_active=True)
        build_name = (obj.build_name or '').strip()
        if build_name:
            target = build_name.replace('&amp;', '&').replace('&AMP;', '&')
            matched_ids = [
                b.id for b in qs
                if (b.opened_build or '').replace('&amp;', '&').replace('&AMP;', '&').strip() == target
            ]
            return len(matched_ids)
        return qs.count()

    def get_last_sync_status(self, obj):
        log = obj.sync_logs.order_by('-started_at').first()
        if not log:
            return None
        return {
            'status': log.status,
            'message': log.message,
            'started_at': log.started_at,
            'finished_at': log.finished_at,
        }

    def create(self, validated_data):
        password = validated_data.pop('password', '') or ''
        db_password = validated_data.pop('db_password', '') or ''
        if not password:
            # 同地址同账号：沿用已保存过的密码，避免每次新建配置都要重新输入
            existing = ZentaoConfig.objects.filter(
                base_url=validated_data.get('base_url', ''),
                account=validated_data.get('account', ''),
            ).exclude(password='').order_by('-id').first()
            if existing:
                password = existing.password
        if not db_password:
            # 同库地址同账号：沿用已保存的只读库密码
            existing_db = ZentaoConfig.objects.filter(
                db_host=validated_data.get('db_host', ''),
                db_user=validated_data.get('db_user', ''),
            ).exclude(db_password='').order_by('-id').first()
            if existing_db:
                db_password = existing_db.db_password
        return ZentaoConfig.objects.create(
            **validated_data, password=password, db_password=db_password
        )

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:
            instance.password = password
        db_password = validated_data.pop('db_password', None)
        if db_password:
            instance.db_password = db_password
        return super().update(instance, validated_data)


class ZentaoBugSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZentaoBug
        fields = [
            'id', 'config', 'version', 'zentao_id', 'title', 'steps',
            'severity', 'pri', 'status', 'bug_type', 'execution', 'product',
            'opened_build', 'opened_by', 'opened_date', 'assigned_to',
            'resolved_by', 'resolution', 'resolved_date', 'is_active',
            'first_seen_at', 'last_seen_at', 'updated_at',
        ]


class ZentaoSyncLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZentaoSyncLog
        fields = [
            'id', 'config', 'status', 'total_count', 'new_count',
            'updated_count', 'deactivated_count', 'message', 'detail',
            'started_at', 'finished_at',
        ]


class ZentaoProductMappingSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True, default=None)

    class Meta:
        model = ZentaoProductMapping
        fields = [
            'id', 'project', 'project_name', 'zentao_product_name',
            'zentao_product_id', 'created_at', 'updated_at',
        ]


class CoverageItemSerializer(serializers.ModelSerializer):
    bug = ZentaoBugSerializer(read_only=True)

    class Meta:
        model = CoverageItem
        fields = [
            'id', 'bug', 'covered', 'matched_testcase', 'matched_case_title',
            'match_score', 'matched_score', 'judge_confidence', 'candidates',
            'reason', 'suggestion',
        ]


class CoverageReportListSerializer(serializers.ModelSerializer):
    version_name = serializers.CharField(source='version.name', read_only=True, default=None)
    project_name = serializers.CharField(
        source='config.project.name', read_only=True, default=None
    )
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, default=None)

    class Meta:
        model = CoverageReport
        fields = [
            'id', 'config', 'version', 'version_name', 'status', 'total_bugs',
            'project_name', 'covered_bugs', 'uncovered_bugs', 'coverage_rate',
            'matched_by', 'case_count', 'error_message', 'created_at', 'finished_at',
            'created_by_name',
        ]


class CoverageReportDetailSerializer(CoverageReportListSerializer):
    items = CoverageItemSerializer(many=True, read_only=True)
    improvement_suggestions = serializers.CharField(
        source='detail.improvement_suggestions', read_only=True, default=''
    )
    improvement_suggestions_ai = serializers.CharField(
        source='detail.improvement_suggestions_ai', read_only=True, default=''
    )
    suggestions_edited_by = serializers.CharField(
        source='detail.improvement_suggestions_edited_by', read_only=True, default=''
    )
    suggestions_edited_at = serializers.DateTimeField(
        source='detail.improvement_suggestions_edited_at', read_only=True, default=None
    )

    class Meta(CoverageReportListSerializer.Meta):
        fields = CoverageReportListSerializer.Meta.fields + [
            'items', 'improvement_suggestions', 'improvement_suggestions_ai',
            'suggestions_edited_by', 'suggestions_edited_at', 'detail',
        ]


# ---------------------------------------------------------------------------
# 历史缺陷复盘
# ---------------------------------------------------------------------------
class DefectReviewListSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(
        source='project.name', read_only=True, default=None
    )
    version_name = serializers.CharField(
        source='version.name', read_only=True, default=None
    )
    created_by_name = serializers.CharField(
        source='created_by.username', read_only=True, default=None
    )

    class Meta:
        model = DefectReviewReport
        fields = [
            'id', 'name', 'status', 'project', 'project_name', 'version', 'version_name',
            'product_ids', 'date_from', 'date_to', 'excluded_types',
            'bug_total', 'domain_count', 'testpoint_count',
            'error_message', 'llm_model', 'created_at', 'finished_at', 'created_by_name',
        ]


class DefectReviewDetailSerializer(DefectReviewListSerializer):
    class Meta(DefectReviewListSerializer.Meta):
        fields = DefectReviewListSerializer.Meta.fields + ['stats_json', 'testpoints_json']


class DefectReviewCreateSerializer(serializers.Serializer):
    """创建复盘任务入参。config 与 product_ids 至少给一个。"""

    name = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    config = serializers.IntegerField(required=False, allow_null=True)
    project = serializers.IntegerField(required=False, allow_null=True)
    version = serializers.IntegerField(required=False, allow_null=True)
    product_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True, default=list
    )
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)
    # 口径开关（2026-10-22）：默认全部纳入，保证与禅道页面数字一致
    include_ui_types = serializers.BooleanField(required=False, default=True)
    include_external = serializers.BooleanField(required=False, default=True)
    # 兼容旧字段：True 表示排除界面优化类
    exclude_ui_types = serializers.BooleanField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if not attrs.get('config') and not attrs.get('product_ids'):
            raise serializers.ValidationError('请选择禅道配置，或至少指定一个禅道产品')
        if not attrs.get('config') and not attrs.get('project'):
            raise serializers.ValidationError('未选择禅道配置时必须指定 TestHub 项目（测试点需落到项目下）')
        date_from, date_to = attrs.get('date_from'), attrs.get('date_to')
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError('起始日期不能晚于截止日期')
        # 旧字段优先：exclude_ui_types=True 等价于 include_ui_types=False
        if attrs.get('exclude_ui_types') is not None:
            attrs['include_ui_types'] = not attrs['exclude_ui_types']
        attrs.pop('exclude_ui_types', None)
        return attrs


class DefectReviewTestpointUpdateSerializer(serializers.Serializer):
    """编辑单条测试点：按 tp_id 定位，只允许改 title/description/checks/keywords。"""

    tp_id = serializers.CharField(max_length=50)
    title = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    checks = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False
    )
    keywords = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False
    )

    def validate(self, attrs):
        editable = {'title', 'description', 'checks', 'keywords'}
        if not (editable & set(attrs.keys())):
            raise serializers.ValidationError('没有需要修改的字段')
        return attrs
