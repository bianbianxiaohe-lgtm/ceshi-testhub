"""
App 自动化流水线运行记录 ViewSet
================================
提供:
  GET  /api/ui-automation/app-pipelines/           列表 (支持 ?app_config= 过滤)
  GET  /api/ui-automation/app-pipelines/<id>/      详情 (轮询状态/日志)
  POST /api/ui-automation/app-pipelines/run/       触发一次新运行 {app_config_id, device_id?, stages?}
  POST /api/ui-automation/app-pipelines/<id>/rerun/ 基于历史重跑

执行在后台线程中进行 (见 app_pipeline.start_pipeline / rerun_pipeline),
HTTP 请求立即返回记录; 前端周期轮询详情接口获取实时 status / log。
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import AppPipelineRun, AppConfig, AppDevice
from .serializers import AppPipelineRunSerializer
from .app_pipeline import start_pipeline, rerun_pipeline, VALID_STAGES


class AppPipelineRunViewSet(viewsets.ModelViewSet):
    """App 自动化流水线运行记录"""
    queryset = AppPipelineRun.objects.all()
    serializer_class = AppPipelineRunSerializer
    permission_classes = [IsAuthenticated]
    ordering = ['-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        app_config_id = self.request.query_params.get('app_config')
        if app_config_id:
            qs = qs.filter(app_config_id=app_config_id)
        return qs

    @action(detail=False, methods=['post'])
    def run(self, request):
        """触发一次新的流水线运行。"""
        app_config_id = request.data.get('app_config_id')
        device_id = request.data.get('device_id')
        stages = request.data.get('stages') or VALID_STAGES

        if not app_config_id:
            return Response({'error': 'app_config_id 必填'}, status=status.HTTP_400_BAD_REQUEST)

        app_config = get_object_or_404(AppConfig, id=app_config_id)
        device = None
        if device_id:
            device = get_object_or_404(AppDevice, id=device_id)

        invalid = [s for s in stages if s not in VALID_STAGES]
        if invalid:
            return Response(
                {'error': f'非法阶段: {invalid}，可选: {VALID_STAGES}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        record = start_pipeline(app_config, device, stages, user=request.user)
        return Response(
            AppPipelineRunSerializer(record).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        """基于历史记录重跑 (复制其 app/device/阶段配置)。"""
        record = self.get_object()
        new_rec = rerun_pipeline(record.id, user=request.user)
        return Response(
            AppPipelineRunSerializer(new_rec).data,
            status=status.HTTP_201_CREATED
        )
