import api from '@/utils/api'

export function getZentaoConfigs(params = {}) {
  return api.get('/zentao/configs/', { params })
}

export function createZentaoConfig(data) {
  return api.post('/zentao/configs/', data)
}

export function updateZentaoConfig(id, data) {
  return api.put(`/zentao/configs/${id}/`, data)
}

export function testZentaoConnection(id) {
  return api.get(`/zentao/configs/${id}/projects/`)
}

export function getZentaoProjects(id) {
  return api.get(`/zentao/configs/${id}/projects/`)
}

export function getZentaoBuildsByProduct(id, productId) {
  return api.get(`/zentao/configs/${id}/builds_by_product/`, { params: { product_id: productId } })
}

export function getProductMappings(params = {}) {
  return api.get('/zentao/product-mappings/', { params })
}

export function saveProductMapping(data) {
  return api.post('/zentao/product-mappings/', data)
}

export function deleteProductMapping(id) {
  return api.delete(`/zentao/product-mappings/${id}/`)
}

export function probeZentaoProducts(data) {
  return api.post('/zentao/configs/probe_products/', data)
}

export function probeZentaoExecutions(data) {
  return api.post('/zentao/configs/probe_executions/', data)
}

export function probeZentaoBuildsByProduct(data) {
  return api.post('/zentao/configs/probe_builds_by_product/', data)
}

export function triggerZentaoSync(id) {
  return api.post(`/zentao/configs/${id}/sync/`)
}

export function triggerCoverage(id) {
  return api.post(`/zentao/configs/${id}/coverage/`)
}

export function getZentaoBugs(params = {}) {
  return api.get('/zentao/bugs/', { params })
}

export function getCoverageReports(params = {}) {
  return api.get('/zentao/reports/', { params })
}

export function getCoverageReport(id) {
  return api.get(`/zentao/reports/${id}/`)
}

export function getCoverageReportLogs(id, limit = 300) {
  return api.get(`/zentao/reports/${id}/logs/`, { params: { limit } })
}

export function deleteCoverageReport(id) {
  return api.delete(`/zentao/reports/${id}/`)
}

export function pushReportToKnowledge(id, data = {}) {
  return api.post(`/zentao/reports/${id}/push_knowledge/`, data)
}

// 编辑/追加「提高覆盖率建议」：{ content } 整体替换，{ append } 追加
export function editReportSuggestions(id, data) {
  return api.post(`/zentao/reports/${id}/edit-suggestions/`, data)
}

export function reviewCoverageItem(reportId, data) {
  return api.post(`/zentao/reports/${reportId}/review-item/`, data)
}

// ---- 历史缺陷复盘（整合历史 Bug → 提炼测试点 → 生成更精准的用例）----

export function getDefectReviews(params = {}) {
  return api.get('/zentao/defect-reviews/', { params })
}

export function getDefectReview(id) {
  return api.get(`/zentao/defect-reviews/${id}/`)
}

export function createDefectReview(data) {
  return api.post('/zentao/defect-reviews/', data)
}

export function deleteDefectReview(id) {
  return api.delete(`/zentao/defect-reviews/${id}/`)
}

// 编辑单条测试点：{ tp_id, title?, description?, checks?, keywords? }
export function editDefectReviewTestpoint(reportId, data) {
  return api.post(`/zentao/defect-reviews/${reportId}/edit-testpoint/`, data)
}

// 批量勾选：{ tp_ids: [], selected: bool }
export function selectDefectReviewTestpoints(reportId, data) {
  return api.post(`/zentao/defect-reviews/${reportId}/batch-select/`, data)
}

// 预览注入生成链路的 prompt 片段：{ report_id, requirement_text?, domains?, max_points? }
export function previewDefectReviewPrompt(data) {
  return api.post('/zentao/defect-reviews/preview-prompt/', data)
}

// 反向查询：这份复盘报告被哪些生成任务用过、各命中哪几条测试点
export function getDefectReviewUsage(reportId) {
  return api.get(`/zentao/defect-reviews/${reportId}/usage/`)
}

// 测试禅道数据库只读连接
export function pingZentaoDb(configId) {
  return api.get(`/zentao/configs/${configId}/db-ping/`)
}

// 读取禅道库产品列表（复盘取数范围用）
export function getZentaoDbProducts(configId) {
  return api.get(`/zentao/configs/${configId}/db-products/`)
}

export function getZentaoSyncLogs(configId) {
  return api.get(`/zentao/configs/${configId}/sync-logs/`).catch(() => {
    // 兼容旧版（无独立 sync-logs 路由时返回空）
    return { data: [] }
  })
}
