<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">应用配置</h1>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon>
        添加应用
      </el-button>
    </div>

    <div class="card-container">
      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-input
          v-model="searchText"
          placeholder="搜索应用名称/包名"
          clearable
          style="width: 240px"
          @clear="loadConfigs"
          @keyup.enter="loadConfigs"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select v-model="platformFilter" placeholder="平台" clearable style="width: 130px" @change="loadConfigs">
          <el-option label="Android" value="android" />
          <el-option label="iOS" value="ios" />
        </el-select>
        <el-select v-model="projectFilter" placeholder="所属项目" clearable filterable style="width: 180px" @change="loadConfigs">
          <el-option
            v-for="p in allProjectsForSelect"
            :key="p.id"
            :label="p.name"
            :value="p.id"
          />
        </el-select>
        <el-button @click="loadConfigs">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>

      <!-- 应用配置表格 -->
      <el-table :data="configs" v-loading="loading" stripe>
        <el-table-column prop="name" label="应用名称" min-width="140" />
        <el-table-column label="平台" width="100">
          <template #default="{ row }">
            <el-tag :type="row.platform === 'android' ? 'success' : 'primary'" size="small">
              {{ row.platform_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="package_name" label="包名/Bundle ID" min-width="180" show-overflow-tooltip />
        <el-table-column prop="app_activity" label="启动Activity" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.app_activity">{{ row.app_activity }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="app_path" label="应用路径" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.app_path">{{ row.app_path }}</span>
            <span v-else class="text-muted">使用已安装应用</span>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="90">
          <template #default="{ row }">
            <span v-if="row.version">{{ row.version }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="所属项目" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.display_project_name" type="info" size="small">{{ row.display_project_name }}</el-tag>
            <span v-else class="text-muted">未关联</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="handleEdit(row)">编辑</el-button>
            <el-popconfirm title="确定删除该应用配置?" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="pagination.currentPage"
          v-model:page-size="pagination.pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @size-change="loadConfigs"
          @current-change="loadConfigs"
        />
      </div>
    </div>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      :title="isEditing ? '编辑应用配置' : '添加应用配置'"
      width="600px"
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="应用名称" prop="name">
          <div style="display: flex; gap: 8px; width: 100%;">
            <el-input v-model="form.name" placeholder="如：微信" style="flex: 1" />
            <el-select
              v-model="selectedProjectName"
              placeholder="从项目关联"
              clearable
              filterable
              style="width: 160px"
              @change="onProjectNameSelect"
            >
              <el-option
                v-for="p in projects"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              />
              <template #empty>
                <div style="padding: 10px; text-align: center; color: #909399;">
                  <p>暂无可用项目</p>
                  <p style="font-size: 12px; margin-top: 4px;">请先在"UI自动化项目"或"AI用例项目"中创建项目</p>
                </div>
              </template>
            </el-select>
          </div>
          <div class="form-tip">可从已有项目快速关联名称和所属项目</div>
        </el-form-item>
        <el-form-item label="平台" prop="platform">
          <el-select v-model="form.platform" placeholder="选择平台">
            <el-option label="Android" value="android" />
            <el-option label="iOS" value="ios" />
          </el-select>
        </el-form-item>
        <el-form-item label="包名/Bundle ID" prop="package_name">
          <el-input v-model="form.package_name" placeholder="如：com.tencent.mm" />
        </el-form-item>
        <el-form-item label="启动Activity" prop="app_activity">
          <el-input
            v-model="form.app_activity"
            placeholder="如：.ui.LauncherUI（仅Android）"
            :disabled="form.platform === 'ios'"
          />
          <div class="form-tip">仅Android需要，iOS自动忽略</div>
        </el-form-item>
        <el-form-item label="应用文件路径" prop="app_path">
          <el-input v-model="form.app_path" placeholder="APK/IPA文件路径，留空使用已安装应用" />
        </el-form-item>
        <el-form-item label="应用版本" prop="version">
          <el-input v-model="form.version" placeholder="如：8.0.48" />
        </el-form-item>
        <el-form-item label="所属项目" prop="project">
          <el-select v-model="form.project" placeholder="选择项目（可选）" clearable filterable>
            <el-option-group label="UI自动化项目">
              <el-option
                v-for="p in uiProjects"
                :key="p.id"
                :label="p.name"
                :value="'ui_' + p.id"
              />
            </el-option-group>
            <el-option-group label="AI用例项目">
              <el-option
                v-for="p in aiProjects"
                :key="p.id"
                :label="p.name"
                :value="'proj_' + p.id"
              />
            </el-option-group>
            <template #empty>
              <div style="padding: 10px; text-align: center; color: #909399;">
                <p>暂无可用项目</p>
                <p style="font-size: 12px; margin-top: 4px;">请先在"UI自动化项目"或"AI用例项目"中创建项目</p>
              </div>
            </template>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getAppConfigs, createAppConfig, updateAppConfig, deleteAppConfig
} from '@/api/ui_automation'
import { getUiProjects } from '@/api/ui_automation'
import { getAllProjects } from '@/api/core'

// 列表数据
const configs = ref([])
const loading = ref(false)
const total = ref(0)
const searchText = ref('')
const platformFilter = ref('')
const projectFilter = ref(null)
// 合并后的项目列表（含 AI用例模块的 Project + UI自动化的 UiProject）
const projects = ref([])
// UI自动化项目（用于所属项目下拉框）
const uiProjects = computed(() => projects.value.filter(p => p.source === 'ui'))
// AI用例项目（用于所属项目下拉框）
const aiProjects = computed(() => projects.value.filter(p => p.source === 'proj'))
// 筛选栏用的项目列表（合并所有项目，value为字符串 "ui_xxx" 或 "proj_xxx"）
const allProjectsForSelect = computed(() => projects.value.map(p => ({
  id: p.id,
  name: p.name
})))
const selectedProjectName = ref(null)
const pagination = reactive({ currentPage: 1, pageSize: 10 })

// 对话框
const showCreateDialog = ref(false)
const isEditing = ref(false)
const editingId = ref(null)
const submitting = ref(false)
const formRef = ref(null)

const defaultForm = {
  name: '',
  platform: 'android',
  package_name: '',
  app_activity: '',
  app_path: '',
  version: '',
  project: null,
  ai_project: null
}

const form = reactive({ ...defaultForm })

const rules = {
  name: [{ required: true, message: '请输入应用名称', trigger: 'blur' }],
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  package_name: [{ required: true, message: '请输入包名/Bundle ID', trigger: 'blur' }]
}

const loadConfigs = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.currentPage,
      page_size: pagination.pageSize,
      search: searchText.value || undefined,
      platform: platformFilter.value || undefined,
      project: projectFilter.value || undefined
    }
    const res = await getAppConfigs(params)
    configs.value = res.data.results || res.data
    total.value = res.data.count || configs.value.length
  } catch (error) {
    ElMessage.error('获取应用配置列表失败')
  } finally {
    loading.value = false
  }
}

const loadProjects = async () => {
  try {
    // 并行加载两种项目源
    const [uiRes, allRes] = await Promise.allSettled([
      getUiProjects({ page_size: 999 }),
      getAllProjects()
    ])
    
    const mergedMap = new Map()
    
    // 加载 UI自动化项目 (UiProject)，用 ui_ 前缀区分
    if (uiRes.status === 'fulfilled') {
      const uiProjects = uiRes.value.data.results || uiRes.value.data || []
      uiProjects.forEach(p => {
        mergedMap.set('ui_' + p.id, { id: 'ui_' + p.id, name: p.name, source: 'ui' })
      })
    }
    
    // 加载 AI用例模块项目 (Project)，用 proj_ 前缀区分
    if (allRes.status === 'fulfilled') {
      const allProjects = allRes.value.data || []
      allProjects.forEach(p => {
        mergedMap.set('proj_' + p.id, { id: 'proj_' + p.id, name: p.name, source: 'proj' })
      })
    }
    
    projects.value = Array.from(mergedMap.values())
  } catch (error) {
    // 项目列表加载失败不影响主功能
  }
}

const onProjectNameSelect = (mergedId) => {
  if (!mergedId) {
    selectedProjectName.value = null
    return
  }
  const project = projects.value.find(p => p.id === mergedId)
  if (project) {
    // 自动填充应用名称为项目名称
    form.name = project.name
    // 自动关联所属项目
    if (project.source === 'ui') {
      form.project = 'ui_' + project.id
      form.ai_project = null
    } else if (project.source === 'proj') {
      form.ai_project = 'proj_' + project.id
      form.project = null
    }
  }
  selectedProjectName.value = null
}

const resetForm = () => {
  Object.assign(form, { ...defaultForm })
  selectedProjectName.value = null
  isEditing.value = false
  editingId.value = null
  formRef.value?.resetFields()
}

const handleEdit = (row) => {
  isEditing.value = true
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    platform: row.platform,
    package_name: row.package_name || '',
    app_activity: row.app_activity || '',
    app_path: row.app_path || '',
    version: row.version || '',
    project: row.project ? 'ui_' + row.project : null,
    ai_project: row.ai_project ? 'proj_' + row.ai_project : null
  })
  showCreateDialog.value = true
}

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const data = {
      ...form,
      // 解析所属项目：根据前缀判断是 UiProject 还是 AI Project
      project: form.project && form.project.startsWith('ui_') ? parseInt(form.project.replace('ui_', '')) : null,
      ai_project: form.ai_project && form.ai_project.startsWith('proj_') ? parseInt(form.ai_project.replace('proj_', '')) : null,
      app_activity: form.platform === 'ios' ? '' : form.app_activity
    }
    if (isEditing.value) {
      await updateAppConfig(editingId.value, data)
      ElMessage.success('应用配置更新成功')
    } else {
      await createAppConfig(data)
      ElMessage.success('应用配置添加成功')
    }
    showCreateDialog.value = false
    await loadConfigs()
  } catch (error) {
    ElMessage.error(isEditing.value ? '更新应用配置失败' : '添加应用配置失败')
  } finally {
    submitting.value = false
  }
}

const handleDelete = async (id) => {
  try {
    await deleteAppConfig(id)
    ElMessage.success('应用配置已删除')
    await loadConfigs()
  } catch (error) {
    ElMessage.error('删除应用配置失败')
  }
}

onMounted(() => {
  loadConfigs()
  loadProjects()
})
</script>

<style scoped>
.page-container {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.card-container {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  align-items: center;
}

.pagination-container {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.text-muted {
  color: #c0c4cc;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
