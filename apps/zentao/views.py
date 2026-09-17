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
    ZentaoBug,
    ZentaoConfig,
    ZentaoProductMapping,
)
from .serializers import (
    CoverageReportDetailSerializer,
    CoverageReportListSerializer,
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

    @action(detail=True, methods=['post'])
    def push_knowledge(self, request, pk=None):
        """把未覆盖缺陷与调优建议写入项目知识库。"""
        report = self.get_object()
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
