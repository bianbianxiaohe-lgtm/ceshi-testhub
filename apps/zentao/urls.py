from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CoverageReportViewSet,
    DefectReviewViewSet,
    ZentaoBugViewSet,
    ZentaoConfigViewSet,
    ZentaoProductMappingViewSet,
)

router = DefaultRouter()
router.register('configs', ZentaoConfigViewSet, basename='zentao-config')
router.register('bugs', ZentaoBugViewSet, basename='zentao-bug')
router.register('product-mappings', ZentaoProductMappingViewSet, basename='zentao-product-mapping')
router.register('reports', CoverageReportViewSet, basename='zentao-report')
# 历史缺陷复盘：整合历史 Bug → 提炼测试点 → 供生成用例
router.register('defect-reviews', DefectReviewViewSet, basename='zentao-defect-review')

urlpatterns = [
    path('', include(router.urls)),
]
