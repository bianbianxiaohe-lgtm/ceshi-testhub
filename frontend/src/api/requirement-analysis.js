/**
 * 需求分析模块相关 API
 */
import request from '@/utils/api'

// ==================== 生成行为配置 ====================

// 获取所有生成行为配置
export function getGenerationConfigs(params) {
  return request({
    url: '/requirement-analysis/api/generation-config/',
    method: 'get',
    params
  })
}

// 获取生成行为配置详情
export function getGenerationConfigDetail(id) {
  return request({
    url: `/requirement-analysis/api/generation-config/${id}/`,
    method: 'get'
  })
}

// 创建生成行为配置
export function createGenerationConfig(data) {
  return request({
    url: '/requirement-analysis/api/generation-config/',
    method: 'post',
    data
  })
}

// 更新生成行为配置
export function updateGenerationConfig(id, data) {
  return request({
    url: `/requirement-analysis/api/generation-config/${id}/`,
    method: 'put',
    data
  })
}

// 删除生成行为配置
export function deleteGenerationConfig(id) {
  return request({
    url: `/requirement-analysis/api/generation-config/${id}/`,
    method: 'delete'
  })
}

// 获取活跃的生成行为配置
export function getActiveGenerationConfig() {
  return request({
    url: '/requirement-analysis/api/generation-config/active/',
    method: 'get'
  })
}

// ==================== AI 模型配置 ====================

// 获取所有 AI 模型配置
export function getAIModelConfigs(params) {
  return request({
    url: '/requirement-analysis/api/ai-model-config/',
    method: 'get',
    params
  })
}

// 获取活跃的 AI 模型配置
export function getActiveAIModelConfig(modelType, role) {
  return request({
    url: '/requirement-analysis/api/ai-model-config/active/',
    method: 'get',
    params: { model_type: modelType, role }
  })
}

// 创建 AI 模型配置
export function createAIModelConfig(data) {
  return request({
    url: '/requirement-analysis/api/ai-model-config/',
    method: 'post',
    data
  })
}

// 更新 AI 模型配置
export function updateAIModelConfig(id, data) {
  return request({
    url: `/requirement-analysis/api/ai-model-config/${id}/`,
    method: 'put',
    data
  })
}

// 删除 AI 模型配置
export function deleteAIModelConfig(id) {
  return request({
    url: `/requirement-analysis/api/ai-model-config/${id}/`,
    method: 'delete'
  })
}

// ==================== 提示词配置 ====================

// 获取所有提示词配置
export function getPromptConfigs(params) {
  return request({
    url: '/requirement-analysis/api/prompt-config/',
    method: 'get',
    params
  })
}

// 获取活跃的提示词配置
export function getActivePromptConfig(promptType) {
  return request({
    url: '/requirement-analysis/api/prompt-config/active/',
    method: 'get',
    params: { prompt_type: promptType }
  })
}

// 创建提示词配置
export function createPromptConfig(data) {
  return request({
    url: '/requirement-analysis/api/prompt-config/',
    method: 'post',
    data
  })
}

// 更新提示词配置
export function updatePromptConfig(id, data) {
  return request({
    url: `/requirement-analysis/api/prompt-config/${id}/`,
    method: 'put',
    data
  })
}

// 删除提示词配置
export function deletePromptConfig(id) {
  return request({
    url: `/requirement-analysis/api/prompt-config/${id}/`,
    method: 'delete'
  })
}

// 将AI生成用例（需求分析模块）批量导入为UI自动化AI用例，导入后可直接执行
export function importGeneratedToAICase(data) {
  return request({
    url: '/ui-automation/ai-cases/import-from-generated/',
    method: 'post',
    data
  })
}

// 一键采纳墨刀流程生成的用例到用例库（按项目/版本/功能模块自动建模块，幂等）
export function adoptModaoToLibrary(pk, data = {}) {
  return request({
    url: `/requirement-analysis/api/modao/${pk}/adopt/`,
    method: 'post',
    data
  })
}

// 逐条采纳墨刀流程生成的单条测试用例到用例库（幂等）
export function adoptModaoSingleCase(pk, caseIndex) {
  return request({
    url: `/requirement-analysis/api/modao/${pk}/adopt-single/`,
    method: 'post',
    data: { index: caseIndex }
  })
}

// ==================== 需求拆解结果历史 ====================

// 获取拆解结果历史列表
export function getAnalysisResults(params) {
  return request({
    url: '/requirement-analysis/api/analysis-results/',
    method: 'get',
    params
  })
}

// 获取单条拆解结果详情（含完整内容）
export function getAnalysisResultDetail(id) {
  return request({
    url: `/requirement-analysis/api/analysis-results/${id}/`,
    method: 'get'
  })
}

// 保存拆解结果
export function createAnalysisResult(data) {
  return request({
    url: '/requirement-analysis/api/analysis-results/',
    method: 'post',
    data
  })
}

// 删除拆解结果
export function deleteAnalysisResult(id) {
  return request({
    url: `/requirement-analysis/api/analysis-results/${id}/`,
    method: 'delete'
  })
}

// 批量查询若干需求文档对应的最新拆解结果（重建前端 docAnalysisMap，刷新后持久化）
export function getAnalysisResultsByDocs(docIds) {
  return request({
    url: '/requirement-analysis/api/analysis-results/by-docs/',
    method: 'get',
    params: { doc_ids: (docIds || []).join(',') }
  })
}

// 基于精炼确认的问答对自动回填项目知识库（去重，避免重复不确定问题）
export function autoFillKnowledgeFromConfirmations(projectId, confirmedAnswers) {
  return request({
    url: '/requirement-analysis/api/analysis-results/auto-fill-knowledge/',
    method: 'post',
    data: {
      project_id: projectId,
      confirmed_answers: JSON.stringify(confirmedAnswers)
    }
  })
}

// ==================== 深度追问清单 ====================

// 获取某拆解结果下的全部追问项
export function getClarifications(params) {
  return request({
    url: '/requirement-analysis/api/clarifications/',
    method: 'get',
    params
  })
}

// 批量保存某拆解结果下的全部追问项（整体替换）
export function saveAllClarifications(data) {
  return request({
    url: '/requirement-analysis/api/clarifications/save-all/',
    method: 'post',
    data
  })
}

// ==================== 拆解结果精炼（带人工确认回复） ====================

// 基于人工确认回复精炼拆解结果（对齐 AI 用例评审的 resolve_replies 闭环）
export function refineAnalysis(data) {
  return request({
    url: '/requirement-analysis/api/refine-analysis/',
    method: 'post',
    data
  })
}
