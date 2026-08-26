/**
 * App 自动化流水线运行 API
 * 后端: /api/ui-automation/app-pipelines/ (apps.ui_automation)
 * 应用配置 / 设备复用 ui_automation 的 app-configs / app-devices
 */
import request from '../utils/api'

// 应用配置 (带 package_name + app_activity)
export function getAppConfigs(params) {
  return request({ url: '/ui-automation/app-configs/', method: 'get', params })
}
export function createAppConfig(data) {
  return request({ url: '/ui-automation/app-configs/', method: 'post', data })
}

// 设备
export function getAppDevices(params) {
  return request({ url: '/ui-automation/app-devices/', method: 'get', params })
}

// 流水线运行记录
export function getPipelineRuns(params) {
  return request({ url: '/ui-automation/app-pipelines/', method: 'get', params })
}
export function getPipelineDetail(id) {
  return request({ url: `/ui-automation/app-pipelines/${id}/`, method: 'get' })
}
export function runPipeline(data) {
  return request({ url: '/ui-automation/app-pipelines/run/', method: 'post', data })
}
export function rerunPipeline(id) {
  return request({ url: `/ui-automation/app-pipelines/${id}/rerun/`, method: 'post' })
}
