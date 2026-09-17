from django.urls import path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'specs', views.APISpecViewSet, basename='api-agent-spec')
router.register(r'endpoints', views.APIEndpointViewSet, basename='api-agent-endpoint')
router.register(r'changes', views.APIChangeViewSet, basename='api-agent-change')
router.register(r'mappings', views.EndpointMappingViewSet, basename='api-agent-mapping')
router.register(r'chat', views.AgentChatViewSet, basename='api-agent-chat')

urlpatterns = router.urls
