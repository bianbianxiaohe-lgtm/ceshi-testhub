import { ref, computed } from 'vue'
import { getAllUiProjects, ensureUiProject } from '@/api/ui_automation'

/**
 * 统一的 UI 自动化项目加载 composable
 * 合并 UiProject 和 AI 用例模块 Project，在所有 UI 自动化子页面中共用。
 *
 * ⚠️ 对外暴露的 allProjects 已按名称去重（同名项目只保留一份，UiProject 优先），
 * 这样所有页面的项目下拉都不会重复展示同一项目。原始合并列表（含重复）仅内部
 * resolveUiProjectId 使用，不对外暴露。
 */
export function useUnifiedProjects() {
  // 原始合并列表 [{id: "ui_1", name: "xxx", source: "ui", real_id: 1}, ...]
  // 可能包含同名重复项（UiProject 与 Project 各一份）
  const rawProjects = ref([])
  const loading = ref(false)

  // 去重后的列表（对外主接口）：按 name 去重，优先保留 AI 项目（source='proj'）。
  // 业务源头是 AI 生成用例模块：先创建 AI 项目，再由它衍生出 UI 自动化等功能。
  // 因此同名项目只保留 AI 那份，不再额外展示/派生 UiProject 副本，避免下拉重复。
  const allProjects = computed(() => {
    const byName = new Map()
    for (const p of rawProjects.value) {
      const exist = byName.get(p.name)
      if (!exist) {
        byName.set(p.name, p)
        continue
      }
      // 已存在一份，AI 项目优先（保留源头项目，丢弃衍生的 UiProject 副本）
      if (exist.source !== 'proj' && p.source === 'proj') {
        byName.set(p.name, p)
      }
    }
    return Array.from(byName.values())
  })

  // 仅 UI 自动化项目（基于去重后列表，避免同名项目重复展示）
  const uiProjects = computed(() => allProjects.value.filter(p => p.source === 'ui'))
  // 仅 AI 用例项目（基于去重后列表）
  const aiProjects = computed(() => allProjects.value.filter(p => p.source === 'proj'))

  const loadProjects = async () => {
    loading.value = true
    try {
      const res = await getAllUiProjects()
      rawProjects.value = res.data || []
    } catch (e) {
      console.error('Failed to load unified projects:', e)
      rawProjects.value = []
    } finally {
      loading.value = false
    }
  }

  /**
   * 将带前缀的项目 ID 解析为纯 UiProject ID
   * @param {string} unifiedId - 如 "ui_1" 或 "proj_2"
   * @returns {Promise<number|null>} UiProject 的纯数字 ID
   */
  const resolveUiProjectId = async (unifiedId) => {
    if (!unifiedId) return null
    // 用原始列表解析（因为 AI 项目可能因同名被去重，但用户若显式传入 proj_<id> 仍需能解析）
    const project = rawProjects.value.find(p => p.id === unifiedId)
    if (!project) return null

    if (project.source === 'ui') {
      return project.real_id
    }

    // AI 项目：自动创建对应的 UiProject
    if (project.source === 'proj') {
      try {
        const res = await ensureUiProject(project.real_id)
        // 后台静默刷新项目列表，不阻塞当前操作（避免 el-select 选项重建导致选中态丢失）
        loadProjects().catch(() => {})
        return res.data.id
      } catch (e) {
        console.error('Failed to ensure UI project:', e)
        return null
      }
    }

    return null
  }

  return {
    allProjects,
    uiProjects,
    aiProjects,
    loading,
    loadProjects,
    resolveUiProjectId
  }
}
