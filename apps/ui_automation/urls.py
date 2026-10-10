from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from .element_picker_views import (
    dump_device_elements,
    save_picked_elements,
    learn_locator,
    match_steps_to_elements,
)
from .views import (
    UiProjectViewSet,
    LocatorStrategyViewSet,
    ElementGroupViewSet,
    ElementViewSet,
    TestScriptViewSet,
    PageObjectViewSet,
    ScriptStepViewSet,
    TestSuiteViewSet,
    TestExecutionViewSet,
    ScreenshotViewSet,
    TestCaseViewSet,
    TestCaseStepViewSet,
    TestCaseExecutionViewSet,
    UiScheduledTaskViewSet,
    AIExecutionRecordViewSet,
    AICaseViewSet,
    UiNotificationLogViewSet,
    OperationRecordViewSet,
    UiDashboardViewSet,
    AppDeviceViewSet,
    AppConfigViewSet,
    BusinessActionViewSet,
    get_all_projects_unified,
    ensure_ui_project,
    learn_elements,
    save_knowledge,
    start_recording,
    recording_page,
    record_action,
    stop_recording,
    generate_recording_case,
    import_airtest_script,
    device_agent_register,
    llm_proxy,
    ios_dump_elements,
)
from .views_config import EnvironmentConfigViewSet, AIIntelligentModeConfigViewSet
from .pipeline_views import AppPipelineRunViewSet

router = DefaultRouter()
router.register(r'dashboard', UiDashboardViewSet, basename='dashboard')
router.register(r'projects', UiProjectViewSet)
router.register(r'locator-strategies', LocatorStrategyViewSet)
router.register(r'element-groups', ElementGroupViewSet)
router.register(r'elements', ElementViewSet)
router.register(r'test-scripts', TestScriptViewSet)
router.register(r'page-objects', PageObjectViewSet)
router.register(r'steps', ScriptStepViewSet)
router.register(r'test-suites', TestSuiteViewSet)
router.register(r'test-executions', TestExecutionViewSet)
router.register(r'screenshots', ScreenshotViewSet)
router.register(r'test-cases', TestCaseViewSet)
router.register(r'test-case-steps', TestCaseStepViewSet)
router.register(r'test-case-executions', TestCaseExecutionViewSet)
router.register(r'scheduled-tasks', UiScheduledTaskViewSet)
router.register(r'ai-execution-records', AIExecutionRecordViewSet)
router.register(r'ai-cases', AICaseViewSet, basename='ai-cases')
router.register(r'ai-case-generation', AICaseViewSet, basename='ai-case-generation')
router.register(r'notification-logs', UiNotificationLogViewSet)
router.register(r'operation-records', OperationRecordViewSet)


# Configuration Center APIs
router.register(r'config/environment', EnvironmentConfigViewSet, basename='config-environment')
router.register(r'config/ai-mode', AIIntelligentModeConfigViewSet, basename='config-ai-mode')
router.register(r'ai-models', AIIntelligentModeConfigViewSet, basename='ai-models')

# App 自动化设备管理
router.register(r'app-devices', AppDeviceViewSet)
router.register(r'app-configs', AppConfigViewSet)
router.register(r'app-pipelines', AppPipelineRunViewSet)
router.register(r'business-actions', BusinessActionViewSet)

urlpatterns = [
    # ⚠️ 元素拾取器必须排在 router 之前！
    #    router 注册了 `elements`（ElementViewSet），会生成 `elements/<pk>/`，
    #    排在前面就会把 `elements/dump/` 当成 pk='dump' 吃掉 → 返回 405。
    path('elements/dump/', dump_device_elements, name='elements-dump'),
    path('elements/save-picked/', save_picked_elements, name='elements-save-picked'),
    path('elements/learn-locator/', learn_locator, name='elements-learn-locator'),
    # 用元素库校正步骤的定位（自然语言用例 → 真元素定位）
    path('elements/match-steps/', match_steps_to_elements, name='elements-match-steps'),


    path('', include(router.urls)),
    path('all-projects/', get_all_projects_unified, name='all-projects-unified'),
    path('ensure-ui-project/', ensure_ui_project, name='ensure-ui-project'),
    path('learn-elements/', learn_elements, name='learn-elements'),
    path('save-knowledge/', save_knowledge, name='save-knowledge'),
    path('recording/start/', start_recording, name='recording-start'),
    path('recording/page/', recording_page, name='recording-page'),
    path('recording/action/', record_action, name='recording-action'),
    path('recording/stop/', stop_recording, name='recording-stop'),
    path('recording/generate/', generate_recording_case, name='recording-generate'),
    path('airtest/import/', import_airtest_script, name='airtest-import'),
    path('device-agent/register/', device_agent_register, name='device-agent-register'),
    # LLM 用量统计代理：OpenAI 兼容转发，顺带把 usage 记到执行记录上
    path('llm-proxy/', llm_proxy, name='llm-proxy'),
    path('llm-proxy/<path:rest>', llm_proxy, name='llm-proxy-rest'),
    # 导出 iOS 当前页面的可访问性元素树（排查「精确定位该填什么」）
    path('ios-dump-elements/', ios_dump_elements, name='ios-dump-elements'),
]

# 添加媒体文件路由
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)