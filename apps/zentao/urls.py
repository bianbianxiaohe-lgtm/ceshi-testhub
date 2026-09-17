from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CoverageReportViewSet,
    ZentaoBugViewSet,
    ZentaoConfigViewSet,
    ZentaoProductMappingViewSet,
)

router = DefaultRouter()
router.register('configs', ZentaoConfigViewSet, basename='zentao-config')
router.register('bugs', ZentaoBugViewSet, basename='zentao-bug')
router.register('product-mappings', ZentaoProductMappingViewSet, basename='zentao-product-mapping')
router.register('reports', CoverageReportViewSet, basename='zentao-report')

urlpatterns = [
    path('', include(router.urls)),
]
