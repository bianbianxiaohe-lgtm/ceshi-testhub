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

export function pushReportToKnowledge(id) {
  return api.post(`/zentao/reports/${id}/push_knowledge/`)
}

export function reviewCoverageItem(reportId, data) {
  return api.post(`/zentao/reports/${reportId}/review-item/`, data)
}

export function getZentaoSyncLogs(configId) {
  return api.get(`/zentao/configs/${configId}/sync-logs/`).catch(() => {
    // 兼容旧版（无独立 sync-logs 路由时返回空）
    return { data: [] }
  })
}
