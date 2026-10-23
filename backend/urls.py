import re

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.views.decorators.csrf import csrf_exempt
from apps.requirement_analysis.modao_views import modao_log_viewer, modao_log_raw
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    path('api/auth/', include('apps.users.urls')),
    path('api/projects/', include('apps.projects.urls')),
    path('api/testcases/', include('apps.testcases.urls')),
    path('api/testsuites/', include('apps.testsuites.urls')),
    path('api/executions/', include('apps.executions.urls')),
    path('api/reports/', include('apps.reports.urls')),
    path('api/reviews/', include('apps.reviews.urls')),
    path('api/versions/', include('apps.versions.urls')),
    path('api/feature-modules/', include('apps.feature_modules.urls')),
    path('api/assistant/', include('apps.assistant.urls')),
    path('api/users/', include('apps.users.urls')),
    path('api/requirement-analysis/', include('apps.requirement_analysis.urls')),
    path('api/ui-automation/', include('apps.ui_automation.urls')),
    path('api/', include('apps.api_testing.urls')),
    path('api/core/', include('apps.core.urls')),
    path('api/defects/', include('apps.defects.urls')),
    path('api/data-factory/', include('apps.data_factory.urls')),
    path('api/analytics/', include('apps.analytics.urls')),
    path('api/app-automation/', include('apps.app_automation.urls')),
    path('api/agent/', include('apps.api_agent.urls')),
    path('api/zentao/', include('apps.zentao.urls')),
    # 日志查看器（直接注册，匹配前端 /requirement-analysis/api/modao/... 路径）
    path('requirement-analysis/api/modao/log-viewer/', modao_log_viewer, name='modao-log-viewer-root'),
    path('requirement-analysis/api/modao/log-raw/', modao_log_raw, name='modao-log-raw-root'),
]

# ⚠️ 不能用 `if settings.DEBUG: urlpatterns += static(...)`：
# django.conf.urls.static.static() 在 DEBUG=False 时**直接返回空列表**，
# 于是生产环境 /media/ 全部 404。
# 2026-10-22 关闭生产 DEBUG 后立刻暴露：墨刀 89 的 34 张画布截图文件都在，
# 但 /media/modao/xxx/page_1.jpg 返回 404 ⇒ 前端"能点但没画布"。
# 这里改为无条件用 serve 挂载（与本文件下方 app-automation 两个路径同样写法）。
urlpatterns += [
    re_path(r'^%s(?P<path>.*)$' % re.escape(settings.MEDIA_URL.lstrip('/')), serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
    # 同理挂载 /static/：DEBUG=False 时 django.contrib.staticfiles 不再自动服务，
    # 表现为 /admin/ 能打开但完全没有样式（/static/admin/css/base.css 404）。
    # 依赖 docker_start.py 里 collectstatic 产出的 STATIC_ROOT。
    re_path(r'^%s(?P<path>.*)$' % re.escape(settings.STATIC_URL.lstrip('/')), serve, {
        'document_root': settings.STATIC_ROOT,
    }),
]

# APP自动化 Template 目录静态访问
import os
urlpatterns += [
    path('app-automation-templates/<path:path>',
         serve,
         {'document_root': os.path.join(settings.BASE_DIR, 'apps', 'app_automation', 'Template')}),
]

# APP自动化 Allure 报告访问
urlpatterns += [
    path('app-automation-reports/<path:path>',
         serve,
         {'document_root': os.path.join(settings.MEDIA_ROOT, 'app-automation', 'allure-reports')}),
]
