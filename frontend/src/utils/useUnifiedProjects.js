import { ref, computed } from 'vue'
import { getAllUiProjects, ensureUiProject } from '@/api/ui_automation'

/**
 * 统一的 UI 自动化项目加载 composable
 * 合并 UiProject 和 AI 用例模块 Project，在所有 UI 自动化子页面中共用
 */
export function useUnifiedProjects() {
  // 原始合并列表 [{id: "ui_1", name: "xxx", source: "ui", real_id: 1}, ...]
  const allProjects = ref([])
  const loading = ref(false)

  // 仅 UI 自动化项目
  const uiProjects = computed(() => allProjects.value.filter(p => p.source === 'ui'))
  // 仅 AI 用例项目
  const aiProjects = computed(() => allProjects.value.filter(p => p.source === 'proj'))

  const loadProjects = async () => {
    loading.value = true
    try {
      const res = await getAllUiProjects()
      allProjects.value = res.data || []
    } catch (e) {
      console.error('Failed to load unified projects:', e)
      allProjects.value = []
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
    const project = allProjects.value.find(p => p.id === unifiedId)
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
