from rest_framework import serializers

from .models import (
    CoverageItem,
    CoverageReport,
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

    class Meta:
        model = ZentaoConfig
        fields = [
            'id', 'name', 'base_url', 'account', 'password', 'has_password',
            'product_id', 'execution_id', 'build_id', 'build_name', 'opened_build_keyword',
            'project', 'version', 'is_enabled', 'created_at', 'updated_at',
            'coverage_target', 'bug_count', 'last_sync_status',
        ]
        read_only_fields = [
            'id', 'has_password', 'created_at', 'updated_at',
            'bug_count', 'last_sync_status',
        ]

    def get_has_password(self, obj) -> bool:
        return bool(obj.password)

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
        if not password:
            # 同地址同账号：沿用已保存过的密码，避免每次新建配置都要重新输入
            existing = ZentaoConfig.objects.filter(
                base_url=validated_data.get('base_url', ''),
                account=validated_data.get('account', ''),
            ).exclude(password='').order_by('-id').first()
            if existing:
                password = existing.password
        return ZentaoConfig.objects.create(**validated_data, password=password)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:
            instance.password = password
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

    class Meta(CoverageReportListSerializer.Meta):
        fields = CoverageReportListSerializer.Meta.fields + ['items', 'improvement_suggestions', 'detail']
