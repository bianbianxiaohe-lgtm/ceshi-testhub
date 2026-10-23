import json
import logging
import os
import threading

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

# 正在运行的覆盖率分析任务：{report_id: threading.Event}，用于 DELETE 报告时协作式取消后台任务
_RUNNING_COVERAGE: dict = {}
_RUNNING_COVERAGE_LOCK = threading.Lock()


def _register_coverage_task(report_id: int) -> threading.Event:
    """注册一个正在运行的分析任务并返回其 cancel Event。"""
    event = threading.Event()
    with _RUNNING_COVERAGE_LOCK:
        _RUNNING_COVERAGE[report_id] = event
    return event


def _unregister_coverage_task(report_id: int) -> None:
    with _RUNNING_COVERAGE_LOCK:
        _RUNNING_COVERAGE.pop(report_id, None)


def _request_cancel_coverage(report_id: int) -> bool:
    """请求取消指定 report_id 的分析任务。返回 True 表示确实发起了取消请求。"""
    with _RUNNING_COVERAGE_LOCK:
        event = _RUNNING_COVERAGE.get(report_id)
    if event is None:
        return False
    event.set()
    return True

from .models import (
    CoverageItem,
    CoverageReport,
    DefectReviewReport,
    ZentaoBug,
    ZentaoConfig,
    ZentaoProductMapping,
)
from .serializers import (
    CoverageReportDetailSerializer,
    CoverageReportListSerializer,
    DefectReviewCreateSerializer,
    DefectReviewDetailSerializer,
    DefectReviewListSerializer,
    DefectReviewTestpointUpdateSerializer,
    ZentaoBugSerializer,
    ZentaoConfigSerializer,
    ZentaoProductMappingSerializer,
    ZentaoSyncLogSerializer,
)
from .services import (
    promote_report_knowledge_to_global,
    push_report_to_knowledge,
    run_coverage_analysis,
    sync_zentao_bugs,
    ZentaoClient,
)

logger = logging.getLogger(__name__)


class ZentaoConfigViewSet(viewsets.ModelViewSet):
    queryset = ZentaoConfig.objects.select_related('project', 'version').all()
    permission_classes = [IsAuthenticated]
    serializer_class = ZentaoConfigSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        version_id = self.request.query_params.get('version_id')
        project_id = self.request.query_params.get('project_id')
        if version_id:
            qs = qs.filter(version_id=version_id)
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    @action(detail=False, methods=['post'])
    def probe_products(self, request):
        """用临时填写的地址/账号/密码直接探测禅道产品（无需先保存配置）。"""
        base_url = request.data.get('base_url')
        account = request.data.get('account')
        password = request.data.get('password')
        if not all([base_url, account, password]):
            return Response(
                {'error': '请填写禅道地址、账号、密码'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            client = ZentaoClient(base_url, account, password)
            client.login()
            return Response({'products': client.get_products()})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def probe_executions(self, request):
        """用临时填写的凭证探测指定产品的执行列表（无需先保存配置）。"""
        base_url = request.data.get('base_url')
        account = request.data.get('account')
        password = request.data.get('password')
        product_id = request.data.get('product_id')
        if not all([base_url, account, password, product_id]):
            return Response(
                {'error': '请填写禅道地址、账号、密码、产品ID'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            client = ZentaoClient(base_url, account, password)
            client.login()
            return Response({'executions': client.get_executions(str(product_id))})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def probe_builds_by_product(self, request):
        """用临时填写的凭证探测指定产品的版本(Build)列表（无需先保存配置）。

        用于"新建配置 + 选产品后自动加载版本下拉"的场景：用户在保存配置前
        就能看到该产品下的全部 Build，选好后再保存。
        """
        base_url = request.data.get('base_url')
        account = request.data.get('account')
        password = request.data.get('password')
        product_id = request.data.get('product_id')
        if not all([base_url, account, password, product_id]):
            return Response(
                {'error': '请填写禅道地址、账号、密码、产品ID'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            client = ZentaoClient(base_url, account, password)
            client.login()
            return Response({'builds': client.get_builds_by_product(str(product_id))})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        """测试连接并列出禅道产品。"""
        config = self.get_object()
        try:
            client = ZentaoClient(config.base_url, config.account, config.password)
            client.login()
            products = client.get_products()
            return Response({'products': products})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='db-ping')
    def db_ping(self, request, pk=None):
        """测试禅道数据库只读连接（历史缺陷复盘的数据源）。"""
        from .db_reader import ZentaoDBError, ZentaoReadOnlyDB

        config = self.get_object()
        try:
            db = ZentaoReadOnlyDB.from_config(config)
            try:
                info = db.ping()
            finally:
                db.close()
            return Response({'ok': True, **info})
        except ZentaoDBError as exc:
            # kind 让前端能区分"网络不通/认证失败/库不存在/权限不足"
            return Response(
                {'ok': False, 'error': str(exc), 'kind': exc.kind},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['get'], url_path='db-products')
    def db_products(self, request, pk=None):
        """列出禅道库里的产品（含 ID 与名称），供复盘选择取数范围。

        每个产品附带 ``bug_count``（有效缺陷数）。原因：禅道配置里的
        ``product_id`` 由覆盖率线自动回填，可能指向一个从未录入缺陷的产品；
        前端若直接预选它，复盘只会产出一份空报告，用户无法区分「选错产品」
        和「该产品确实没缺陷」。带上数量后前端可以明确标出 0 条的产品。
        """
        from .db_reader import ZentaoDBError, ZentaoReadOnlyDB

        config = self.get_object()
        try:
            db = ZentaoReadOnlyDB.from_config(config)
            try:
                products = db.fetch_products(with_bug_count=True)
            finally:
                db.close()
            return Response({'products': products})
        except ZentaoDBError as exc:
            return Response(
                {'ok': False, 'error': str(exc), 'kind': exc.kind},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['get'])
    def projects(self, request, pk=None):
        """列出禅道产品/项目（项目与产品同一份数据），用于按名称自动匹配。"""
        config = self.get_object()
        try:
            client = ZentaoClient(config.base_url, config.account, config.password)
            client.login()
            return Response({'projects': client.get_products()})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def builds_by_product(self, request, pk=None):
        """获取产品下全部版本（build）列表（用于下拉选择，按版本精确拉 Bug）。"""
        config = self.get_object()
        product_id = request.query_params.get('product_id') or config.product_id
        if not product_id:
            return Response(
                {'error': '请先选择产品'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            client = ZentaoClient(config.base_url, config.account, config.password)
            client.login()
            return Response({'builds': client.get_builds_by_product(product_id)})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """触发禅道 Bug 同步（后台执行）。"""
        config = self.get_object()
        if not config.product_id or not config.build_id:
            return Response(
                {
                    'error': (
                        f'配置「{config.name}」尚未选择产品与版本(Build)，无法同步。'
                        '请在「产品映射」中匹配项目，并选择版本后保存'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        thread = threading.Thread(target=sync_zentao_bugs, args=(config,), daemon=True)
        thread.start()
        return Response({'message': '同步任务已启动，请稍后查看同步记录'})

    @action(detail=True, methods=['post'])
    def coverage(self, request, pk=None):
        """触发覆盖率分析（后台执行，调用 AI 判定）。"""
        config = self.get_object()
        if not ZentaoBug.objects.filter(config=config, is_active=True).exists():
            return Response(
                {'error': '请先点击“同步Bug”并等待同步完成，再执行覆盖率分析'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report = CoverageReport.objects.create(
            config=config,
            version=config.version,
            status='running',
            created_by=request.user if request.user.is_authenticated else None,
        )
        cancel_event = _register_coverage_task(report.id)

        def _run():
            try:
                run_coverage_analysis(
                    config, user=request.user, report=report,
                    build_name=config.build_name or '',
                    cancel_event=cancel_event,
                )
            finally:
                _unregister_coverage_task(report.id)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return Response({'report_id': report.id, 'message': '覆盖率分析已启动'})

    @action(detail=True, methods=['get'])
    def bugs(self, request, pk=None):
        config = self.get_object()
        bugs = ZentaoBug.objects.filter(config=config).order_by('-opened_date', '-id')
        is_active = request.query_params.get('is_active')
        if is_active is not None:
            bugs = bugs.filter(is_active=is_active.lower() in ('1', 'true', 'yes'))
        page = self.paginate_queryset(bugs)
        if page is not None:
            serializer = ZentaoBugSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(ZentaoBugSerializer(bugs, many=True).data)

    @action(detail=True, methods=['get'])
    def sync_logs(self, request, pk=None):
        """最近同步记录。"""
        config = self.get_object()
        logs = config.sync_logs.all()[:5]
        return Response(ZentaoSyncLogSerializer(logs, many=True).data)


class ZentaoBugViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ZentaoBug.objects.select_related('config', 'version').all()
    permission_classes = [IsAuthenticated]
    serializer_class = ZentaoBugSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        config_id = self.request.query_params.get('config_id')
        version_id = self.request.query_params.get('version_id')
        search = self.request.query_params.get('search')
        is_active = self.request.query_params.get('is_active')
        if config_id:
            qs = qs.filter(config_id=config_id)
        if version_id:
            qs = qs.filter(version_id=version_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('1', 'true', 'yes'))
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(steps__icontains=search))
        return qs


class ZentaoProductMappingViewSet(viewsets.ModelViewSet):
    """TestHub 项目 ↔ 禅道产品名称映射。"""

    queryset = ZentaoProductMapping.objects.select_related('project').all()
    permission_classes = [IsAuthenticated]
    serializer_class = ZentaoProductMappingSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project_id')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def create(self, request, *args, **kwargs):
        """同项目已有映射则更新，实现 upsert。"""
        project_id = request.data.get('project')
        if project_id:
            existing = ZentaoProductMapping.objects.filter(project_id=project_id).first()
            if existing:
                serializer = self.get_serializer(existing, data=request.data)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                return Response(serializer.data)
        return super().create(request, *args, **kwargs)


class CoverageReportViewSet(viewsets.ModelViewSet):
    queryset = CoverageReport.objects.select_related('config', 'version').prefetch_related(
        'items__bug', 'items__matched_testcase'
    )
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        return Response(
            {'error': '报告由覆盖率分析自动生成，不支持手动创建'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        return Response(
            {'error': '报告不支持手动修改'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        return Response(
            {'error': '报告不支持手动修改'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CoverageReportDetailSerializer
        return CoverageReportListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        version_id = self.request.query_params.get('version_id')
        config_id = self.request.query_params.get('config_id')
        if version_id:
            qs = qs.filter(version_id=version_id)
        if config_id:
            qs = qs.filter(config_id=config_id)
        return qs

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """返回该报告在分析日志里对应的实时日志行（按 report 标识过滤）。"""
        report = self.get_object()
        marker = f'report={report.id}'
        lines = []
        log_path = os.path.join(settings.BASE_DIR, 'logs', 'django.log')
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                # 读取整个文件，按行过滤出包含该 report 标识的日志
                for line in f:
                    if marker in line:
                        lines.append(line.rstrip('\n'))
        except FileNotFoundError:
            pass
        except Exception as exc:
            return Response(
                {'error': f'读取日志失败: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        # 只返回最后 N 行，避免一次性传太多
        limit = min(int(request.query_params.get('limit', 300)), 1000)
        return Response({'report_id': report.id, 'status': report.status, 'lines': lines[-limit:]})

    def destroy(self, request, *args, **kwargs):
        """删除报告：若报告仍在 running，先发起协作式取消后台任务再删除。"""
        report = self.get_object()
        was_running = False
        if report.status == 'running':
            cancelled = _request_cancel_coverage(report.id)
            was_running = cancelled or _RUNNING_COVERAGE.get(report.id) is not None
            # 给线程一点时间响应取消（最多 3 秒）
            import time as _time
            for _ in range(30):
                if report.id not in _RUNNING_COVERAGE:
                    break
                _time.sleep(0.1)
        # 记录取消原因（线程如仍在跑，except 块会写 failed，但用户已要求删除，无需关心最终状态）
        if was_running and report.status == 'running':
            report.status = 'failed'
            report.error_message = '用户删除报告：任务已取消'
            report.finished_at = timezone.now()
            try:
                report.save(update_fields=['status', 'error_message', 'finished_at'])
            except Exception:
                pass
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='edit-suggestions')
    def edit_suggestions(self, request, pk=None):
        """人工编辑/追加「提高覆盖率建议」。

        传入 content 表示整体替换；传 append 表示在现有建议后追加一段。
        原始 AI 建议保留在 detail.improvement_suggestions_ai，便于追溯。
        """
        report = self.get_object()
        if request.data.get('content') is not None:
            content = str(request.data.get('content') or '').strip()
        elif request.data.get('append') is not None:
            extra = str(request.data.get('append') or '').strip()
            if not extra:
                return Response(
                    {'error': '追加内容不能为空'}, status=status.HTTP_400_BAD_REQUEST
                )
            base = (report.detail or {}).get('improvement_suggestions') or ''
            content = (base.rstrip() + '\n\n' + extra) if base.strip() else extra
        else:
            return Response(
                {'error': '缺少 content（整体替换）或 append（追加）'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        detail = dict(report.detail or {})
        if 'improvement_suggestions_ai' not in detail:
            # 首次编辑时留档 AI 原文，后续编辑不覆盖
            detail['improvement_suggestions_ai'] = detail.get('improvement_suggestions') or ''
        detail['improvement_suggestions'] = content
        detail['improvement_suggestions_edited_by'] = (
            request.user.username if request.user.is_authenticated else 'unknown'
        )
        detail['improvement_suggestions_edited_at'] = timezone.now().isoformat()
        report.detail = detail
        report.save(update_fields=['detail'])
        return Response({
            'message': '建议已保存',
            'improvement_suggestions': content,
            'edited_by': detail['improvement_suggestions_edited_by'],
            'edited_at': detail['improvement_suggestions_edited_at'],
        })

    @action(detail=True, methods=['post'])
    def push_knowledge(self, request, pk=None):
        """把未覆盖缺陷与调优建议写入项目知识库。

        可传 improvement_suggestions 覆盖本次写入调优建议的正文（前端编辑后直接写入，
        避免"先保存再写入"两次请求）；不传则使用报告里已保存的建议。
        """
        report = self.get_object()
        override = request.data.get('improvement_suggestions')
        if override is not None:
            content = str(override or '').strip()
            detail = dict(report.detail or {})
            if 'improvement_suggestions_ai' not in detail:
                detail['improvement_suggestions_ai'] = detail.get('improvement_suggestions') or ''
            detail['improvement_suggestions'] = content
            detail['improvement_suggestions_edited_by'] = (
                request.user.username if request.user.is_authenticated else 'unknown'
            )
            detail['improvement_suggestions_edited_at'] = timezone.now().isoformat()
            report.detail = detail
            report.save(update_fields=['detail'])
        try:
            result = push_report_to_knowledge(report, request.user)
            return Response(result)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='promote-knowledge-global')
    def promote_knowledge_global(self, request, pk=None):
        """把本次报告沉淀的「覆盖缺失重点」升级为跨版本通用，供新版本生成用例语义召回。

        默认只升级命中通用测试维度（边界/异常/权限/兼容等）的易漏点；
        传 only_universal=false 可把本次沉淀全部升级为跨版本通用。
        """
        report = self.get_object()
        only_universal = str(request.data.get('only_universal', 'true')).lower() not in (
            '0', 'false', 'no', 'n'
        )
        try:
            result = promote_report_knowledge_to_global(
                report, request.user, only_universal=only_universal
            )
            return Response(result)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='review-item')
    def review_item(self, request, pk=None):
        """人工复核单条覆盖判定：修正 covered/reason，回写后影响后续知识库写入。"""
        report = self.get_object()
        item_id = request.data.get('item_id')
        covered = request.data.get('covered')
        note = str(request.data.get('note') or '').strip()
        if item_id is None or covered is None:
            return Response(
                {'error': '缺少 item_id 或 covered'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(covered, bool):
            return Response(
                {'error': 'covered 必须是布尔值'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            item = CoverageItem.objects.select_related('bug').get(report=report, id=item_id)
        except CoverageItem.DoesNotExist:
            return Response(
                {'error': '未找到该判定条目'},
                status=status.HTTP_404_NOT_FOUND,
            )

        reviewer = request.user.username if request.user.is_authenticated else 'unknown'
        try:
            prev = json.loads(item.suggestion) if item.suggestion else {}
        except (ValueError, TypeError):
            prev = {}
        prev.update({
            'manual_reviewed_by': reviewer,
            'manual_reviewed_at': timezone.now().isoformat(),
            'manual_note': note,
            'manual_covered': covered,
        })
        item.covered = covered
        item.reason = (
            f'[人工复核] 原判定：{item.reason or "无"}；'
            f'人工修正为：{"已覆盖" if covered else "未覆盖"}'
            + (f'；备注：{note}' if note else '')
        )
        item.suggestion = json.dumps(prev, ensure_ascii=False)
        item.save(update_fields=['covered', 'reason', 'suggestion'])

        # 重算报告级统计，保持与明细一致
        covered_count = CoverageItem.objects.filter(report=report, covered=True).count()
        total = CoverageItem.objects.filter(report=report).count()
        report.covered_bugs = covered_count
        report.uncovered_bugs = total - covered_count
        report.coverage_rate = round(covered_count / total * 100, 2) if total else 0.0
        report.save(update_fields=['covered_bugs', 'uncovered_bugs', 'coverage_rate'])

        return Response({
            'message': '复核已保存，报告统计已更新',
            'item_id': item.id,
            'covered': covered,
            'covered_bugs': report.covered_bugs,
            'uncovered_bugs': report.uncovered_bugs,
            'coverage_rate': report.coverage_rate,
        })


# ---------------------------------------------------------------------------
# 历史缺陷复盘（整合历史缺陷 → 提炼测试点 → 供新版本生成更精准的用例）
# ---------------------------------------------------------------------------
class DefectReviewViewSet(viewsets.ModelViewSet):
    """历史缺陷复盘报告。

    与 CoverageReportViewSet 的分工：
      - 覆盖率报告：评估"已生成的用例覆盖了哪些历史 Bug"
      - 缺陷复盘：从历史 Bug 反推"未来该测哪些点"，产物是测试点
    """

    queryset = DefectReviewReport.objects.select_related(
        'project', 'version', 'config', 'created_by'
    ).all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return DefectReviewDetailSerializer
        if self.action == 'create':
            return DefectReviewCreateSerializer
        return DefectReviewListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project_id')
        version_id = self.request.query_params.get('version_id')
        if project_id:
            qs = qs.filter(project_id=project_id)
        if version_id:
            qs = qs.filter(version_id=version_id)
        return qs

    def create(self, request, *args, **kwargs):
        """创建并启动复盘任务（后台线程跑，前端轮询状态）。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        config = None
        config_id = data.get('config')
        if config_id:
            config = ZentaoConfig.objects.filter(id=config_id).first()
            if not config:
                return Response({'error': '禅道配置不存在'}, status=status.HTTP_404_NOT_FOUND)

        project_id = data.get('project') or (config.project_id if config else None)
        if not project_id:
            return Response(
                {'error': '缺少 TestHub 项目：测试点需要落到具体项目下'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        version_id = data.get('version') or (config.version_id if config else None)

        product_ids = [int(p) for p in (data.get('product_ids') or [])]
        if not product_ids and config and config.product_id:
            product_ids = [int(config.product_id)]

        # 口径：默认全收（用户要求"数字要能对上禅道"）。
        # external（外部原因）等也纳入，改由报告里的 resolution 分布体现，
        # 不再静默过滤——否则禅道 143 vs 复盘 132 会让人以为统计有问题。
        excluded = [] if data.get('include_ui_types', True) else ['interfaceoptimize']
        if data.get('include_external', True):
            resolutions = None      # None = 不按 resolution 过滤
        else:
            resolutions = ['fixed', 'bydesign']
        report = DefectReviewReport.objects.create(
            name=data.get('name') or '',
            config=config,
            project_id=project_id,
            version_id=version_id,
            status='running',
            product_ids=product_ids,
            date_from=data.get('date_from'),
            date_to=data.get('date_to'),
            excluded_types=excluded,
            created_by=request.user if request.user.is_authenticated else None,
        )

        def _run():
            from .defect_review import build_defect_review

            try:
                result = build_defect_review(
                    config=config,
                    product_ids=product_ids,
                    date_from=report.date_from,
                    date_to=report.date_to,
                    exclude_types=excluded,
                    resolutions=resolutions,
                )
                stats = result.get('stats') or {}
                tps = result.get('testpoints') or []
                report.status = 'success'
                # 把实际使用的 resolution 口径记进 excluded_types 旁的 stats，
                # 保证"这份报告按什么口径算的"可追溯
                report.excluded_types = excluded
                report.bug_total = stats.get('bug_eligible', 0)
                report.domain_count = stats.get('domain_count', 0)
                report.testpoint_count = len(tps)
                report.stats_json = stats
                report.testpoints_json = tps
                report.llm_model = ''
                # 读到 0 条时把原因写进 error_message（复用为"提示信息"字段）：
                # 页面必须能看到"为什么是 0"，不能静默显示"完成 0 缺陷"。
                report.error_message = result.get('empty_reason') or ''
                report.finished_at = timezone.now()
                report.save(update_fields=[
                    'status', 'bug_total', 'domain_count', 'testpoint_count',
                    'stats_json', 'testpoints_json', 'llm_model',
                    'error_message', 'excluded_types', 'finished_at',
                ])
                logger.info('缺陷复盘完成: report=%s bugs=%s tps=%s',
                            report.id, report.bug_total, report.testpoint_count)
            except Exception as exc:
                logger.exception('缺陷复盘失败: report=%s', report.id)
                report.status = 'failed'
                report.error_message = (str(exc) or repr(exc))[:2000]
                report.finished_at = timezone.now()
                report.save(update_fields=['status', 'error_message', 'finished_at'])

        threading.Thread(target=_run, daemon=True).start()
        return Response(
            {'report_id': report.id, 'message': '复盘已启动，正在读取禅道历史缺陷'},
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        return Response(
            {'error': '复盘报告不支持整体修改'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'], url_path='edit-testpoint')
    def edit_testpoint(self, request, pk=None):
        """编辑单条测试点（人工校准后再用于生成用例）。"""
        report = self.get_object()
        serializer = DefectReviewTestpointUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tp_id = data['tp_id']

        tps = list(report.testpoints_json or [])
        target = None
        for tp in tps:
            if str(tp.get('tp_id')) == str(tp_id):
                target = tp
                break
        if target is None:
            return Response({'error': f'未找到测试点 {tp_id}'}, status=status.HTTP_404_NOT_FOUND)

        for field in ('title', 'description', 'checks', 'keywords'):
            if field in data:
                target[field] = data[field]
        target['edited_by'] = request.user.username if request.user.is_authenticated else 'unknown'
        target['edited_at'] = timezone.now().isoformat()

        report.testpoints_json = tps
        report.save(update_fields=['testpoints_json'])
        return Response({'message': '测试点已保存', 'testpoint': target})

    @action(detail=True, methods=['post'], url_path='batch-select')
    def batch_select(self, request, pk=None):
        """批量勾选/取消测试点（selected 字段），用于"只把选中的测试点拿去生成用例"。"""
        report = self.get_object()
        tp_ids = [str(x) for x in (request.data.get('tp_ids') or [])]
        selected = bool(request.data.get('selected', True))
        tps = list(report.testpoints_json or [])
        hit = 0
        for tp in tps:
            if str(tp.get('tp_id')) in tp_ids:
                tp['selected'] = selected
                hit += 1
        report.testpoints_json = tps
        report.save(update_fields=['testpoints_json'])
        return Response({'message': f'已更新 {hit} 条测试点的选择状态', 'updated': hit})

    @action(detail=False, methods=['post'], url_path='preview-prompt')
    def preview_prompt(self, request):
        """预览「注入用例生成」的 prompt 片段。

        这是"历史测试点 → 新版本用例"的可见出口：用户能先看到 AI 会收到什么，
        再决定是否生成，避免黑盒。
        """
        from .defect_review import (
            DEFAULT_RELEVANCE_MODE,
            DETAIL_LEVELS,
            RELEVANCE_MODES,
            SCALE_MAX_POINTS,
            assess_defect_relevance,
            build_testpoint_prompt_block,
            detect_change_intent,
            estimate_prompt_tokens,
            scope_by_relevance,
            suggest_domains_for_requirement,
        )

        report_id = request.data.get('report_id')
        report = DefectReviewReport.objects.filter(id=report_id).first()
        if not report:
            return Response({'error': '复盘报告不存在'}, status=status.HTTP_404_NOT_FOUND)

        tps = list(report.testpoints_json or [])
        # 默认只注入被勾选的；没勾过任何一条时退回全部
        selected = [tp for tp in tps if tp.get('selected')]
        pool = selected or tps

        requirement_text = str(request.data.get('requirement_text') or '')
        domains = [d for d in (request.data.get('domains') or []) if d]

        # ⚠️ 推荐必须用**全量**测试点算，不能用已勾选收窄后的 pool：
        # 否则用户只勾了 3 条（都不属于需求涉及的域）时，推荐结果为 empty，
        # 导致"按需求自动筛选"静默失效（2026-10-22 实测踩到）。
        suggested = []
        if not domains and requirement_text:
            suggested = suggest_domains_for_requirement(requirement_text, tps)
            domains = suggested

        # 档位默认值必须和注入侧一致：注入侧在用户未指定时按改动规模自动选
        # （小改动 → brief）。若这里硬编码 standard，"只改文案"这类需求会出现
        # 预览 288 字符 / 实际注入 196 字符的落差，用户会以为内容被吞了。
        detail_level = str(request.data.get('detail_level') or '')
        if detail_level not in DETAIL_LEVELS:
            detail_level = 'brief' if detect_change_intent(requirement_text).get('scale') == 'small' else 'standard'
        max_points = int(request.data.get('max_points') or 20)
        change_scale = str(request.data.get('change_scale') or '')
        relevance_mode = str(request.data.get('relevance_mode') or DEFAULT_RELEVANCE_MODE)
        if relevance_mode not in RELEVANCE_MODES:
            relevance_mode = DEFAULT_RELEVANCE_MODE

        # 严格模式：预览结果必须与真正注入时完全一致（同样用全量测试点判相关性），
        # 否则会出现"预览有内容、生成时被闸门拦掉"的黑盒落差。
        relevance = assess_defect_relevance(requirement_text, tps, mode=relevance_mode)

        # 「报告视角」预览：未带需求文本时不代表「需求无关」，而是「尚未与任何需求比对」。
        # 此时应展示这份报告自身能提供的测试点，而不是返回空内容并标记为已拦截
        # （用户 2026-10-23 反馈：需求属于生成任务，报告页不该要求填需求）。
        report_scope = not requirement_text
        if report_scope:
            relevance = dict(relevance)
            relevance['relevant'] = True
            relevance['reason'] = (
                '未提供需求文本：以下按报告全量测试点展示，'
                '实际注入会在生成用例时用该次需求筛选'
            )


        # ⚠️ 收窄顺序必须和注入侧（ai_model_service._build_defect_review_section）
        # 一模一样，否则两边会筛出不同结果：
        #   注入侧：pool(勾选或全量) --scope_by_relevance--> --build_testpoint_prompt_block(domains)-->
        #   预览侧必须同样：**不要**在这里提前按 domains 手工裁剪 scoped，
        #   否则 build_testpoint_prompt_block 内部再筛一次时输入已经不同，结果必然不一致
        #   （实测偏差达 20%：196 vs 288 / 728 vs 592 / 986 vs 789）。
        # 之前那行 `scoped = [... if tp.get('domain') in set(domains)]` 就是不一致的根因。
        if not domains:
            # 用户没手选域时，用相关性给出的域（与注入侧一致）
            domains = relevance['matched_domains']
        if report_scope:
            # 报告视角没有需求可比对，不该被 "无落点→3 条兜底" 这类收窄规则砍掉，
            # 直接按用户设定的条数上限展示整份报告。
            scoped, effective_max = pool, max_points
        else:
            scoped, effective_max = scope_by_relevance(pool, relevance, max_points)
        max_points = effective_max

        if relevance['relevant']:
            block = build_testpoint_prompt_block(
                scoped,
                domains=domains,
                max_points=max_points,
                detail_level=detail_level,
                requirement_text=requirement_text,
                change_scale=change_scale,
            )
        else:
            block = ''

        # 变更意图分析结果返回给前端，让用户看到"为什么只注入这几条"并可人工覆盖
        intent = detect_change_intent(requirement_text)
        if change_scale in SCALE_MAX_POINTS:
            intent['scale'] = change_scale
            intent['suggested_max_points'] = SCALE_MAX_POINTS[change_scale]

        # 三档体量对照：让用户在预览时就能判断"会不会太长"，而不是提交后才发现
        size_compare = {
            lv: (
                estimate_prompt_tokens(
                    build_testpoint_prompt_block(
                        scoped, domains=domains, max_points=max_points, detail_level=lv,
                        requirement_text=requirement_text, change_scale=change_scale,
                    )
                ) if relevance['relevant'] else 0
            )
            for lv in DETAIL_LEVELS
        }
        # used_count 要反映**真正出现在注入文本里的条数**，而不是候选池大小：
        # 走进 build_testpoint_prompt_block 后还会按域/意图/名额再筛一次，
        # 若这里直接报 len(scoped)，用户会看到"用了 20 条"但实际只注入 3 条。
        injected_count = block.count('\n- ') + (1 if block.startswith('- ') else 0)

        return Response({
            'prompt_block': block,
            'detail_level': detail_level,
            'max_points': max_points,
            'estimated_tokens': estimate_prompt_tokens(block),
            'size_compare': size_compare,
            'testpoint_total': len(tps),
            'selected_count': len(selected),
            'candidate_count': len(scoped),
            'used_count': injected_count if relevance['relevant'] else 0,
            'domains': domains,
            'suggested_domains': suggested,
            # 严格模式相关性闸门：前端据此提示"本次不会注入历史测试点及原因"
            'relevance': {
                'mode': relevance['mode'],
                'relevant': relevance['relevant'],
                'reason': relevance['reason'],
                'matched_domains': relevance['matched_domains'],
                'matched_scenes': relevance['matched_scenes'],
                'irrelevant_hits': relevance['irrelevant_hits'],
            },
            'change_intent': {
                'intents': intent.get('intents', []),
                'scale': intent.get('scale', 'medium'),
                'scale_reason': intent.get('scale_reason', ''),
                'suggested_max_points': intent.get('suggested_max_points', 20),
                'matched_scenes': sorted(intent.get('scenes', set())),
            },
            'available_domains': sorted({tp.get('domain') for tp in tps if tp.get('domain')}),
        })

    @action(detail=True, methods=['get'], url_path='usage')
    def usage(self, request, pk=None):
        """反向查询：这份复盘报告被哪些用例生成任务用过、各命中哪几条测试点。

        预览只能回答「理论上会注入什么」，这里回答「实际注入后发生了什么」。
        数据来自 TestCaseGenerationTask.defect_review_used 审计快照。
        """
        from apps.requirement_analysis.models import TestCaseGenerationTask

        report = self.get_object()
        qs = (
            TestCaseGenerationTask.objects
            .filter(defect_review_id=report.id)
            .select_related('project', 'version', 'created_by')
            .order_by('-id')
        )
        rows = []
        injected_total = 0
        for t in qs:
            audit = t.defect_review_used or None
            used = int((audit or {}).get('used_count') or 0)
            injected_total += used
            rows.append({
                'task_id': t.id,
                'task_no': (getattr(t, 'task_id', '') or '') or ('#%s' % t.id),
                'title': t.title or getattr(t, 'feature_module_name', '') or '',
                'project_id': getattr(t, 'project_id', None),
                'project_name': getattr(getattr(t, 'project', None), 'name', '') or '',
                'created_by': getattr(getattr(t, 'created_by', None), 'username', '') or '',
                'created_at': t.created_at,
                'status': t.status,
                # audit 为 None = 该任务早于审计功能上线，或尚未执行到注入环节
                'audited': audit is not None,
                'injected': bool((audit or {}).get('injected')),
                'reason': (audit or {}).get('reason') or '',
                'matched_domains': (audit or {}).get('matched_domains') or [],
                'used_count': used,
                'detail_level': (audit or {}).get('detail_level') or '',
                'prompt_chars': int((audit or {}).get('prompt_chars') or 0),
                'items': (audit or {}).get('items') or [],
                'at': (audit or {}).get('at') or '',
            })
        return Response({
            'report_id': report.id,
            'report_name': report.name,
            'task_total': len(rows),
            'injected_task_total': len([r for r in rows if r['injected']]),
            'injected_point_total': injected_total,
            'results': rows,
        })
