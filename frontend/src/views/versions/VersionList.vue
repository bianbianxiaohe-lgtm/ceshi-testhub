<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">版本管理</h1>
      <div class="header-actions">
        <el-button
          v-if="selectedVersions.length > 0"
          type="danger"
          @click="batchDeleteVersions"
          :disabled="isDeleting">
          <el-icon><Delete /></el-icon>
          批量删除 ({{ selectedVersions.length }})
        </el-button>
        <el-button type="primary" @click="createVersion">
          <el-icon><Plus /></el-icon>
          新建版本
        </el-button>
      </div>
    </div>

    <div class="card-container">
      <div class="filter-bar">
        <el-row :gutter="20">
          <el-col :span="6">
            <el-input
              v-model="searchText"
              placeholder="搜索版本名称"
              clearable
              @input="handleSearch"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
          </el-col>
          <el-col :span="4">
            <el-select v-model="projectFilter" placeholder="关联项目" clearable @change="handleFilter">
              <el-option
                v-for="project in projects"
                :key="project.id"
                :label="project.name"
                :value="project.id"
              />
            </el-select>
          </el-col>
          <el-col :span="3">
            <el-select v-model="baselineFilter" placeholder="版本类型" clearable @change="handleFilter">
              <el-option label="基线版本" :value="true" />
              <el-option label="普通版本" :value="false" />
            </el-select>
          </el-col>
        </el-row>
      </div>

      <el-table
        :data="versions"
        v-loading="loading"
        style="width: 100%"
        @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" />
        <el-table-column type="index" label="序号" width="80" :index="getSerialNumber" />
        <el-table-column prop="name" label="版本名称" min-width="100">
          <template #default="{ row }">
            <div class="version-name">
              <span>{{ row.name }}</span>
              <el-tag v-if="row.is_baseline" type="warning" size="small" class="baseline-tag">基线</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="projects" label="关联项目" width="300">
          <template #default="{ row }">
            <div v-if="row.projects && row.projects.length > 0" class="project-tags">
              <el-tag
                v-for="project in row.projects.slice(0, 2)"
                :key="project.id"
                size="small"
                type="primary"
                class="project-tag"
              >
                {{ project.name }}
              </el-tag>
              <el-tooltip v-if="row.projects.length > 2" :content="getProjectsTooltip(row.projects)">
                <el-tag size="small" type="info" class="project-tag">
                  +{{ row.projects.length - 2 }}
                </el-tag>
              </el-tooltip>
            </div>
            <span v-else class="no-project">未关联项目</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column prop="testcases_count" label="用例数量" width="100">
          <template #default="{ row }">
            <el-tag type="info" size="small">{{ row.testcases_count }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_by.username" label="创建者" width="120" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="editVersion(row)">编辑</el-button>
            <el-button size="small" type="info" @click="openManageModules(row)">管理模块</el-button>
            <el-button size="small" type="danger" @click="deleteVersion(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="handlePageChange"
        />
      </div>
    </div>

    <!-- 版本表单对话框 -->
    <el-dialog
      v-model="versionDialogVisible"
      :title="isEdit ? '编辑版本' : '创建版本'"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :modal="true"
      :destroy-on-close="false"
      width="600px"
    >
      <el-form :model="versionForm" :rules="versionRules" ref="versionFormRef" label-width="120px">
        <el-form-item label="版本名称" prop="name">
          <el-input v-model="versionForm.name" placeholder="请输入版本名称" />
        </el-form-item>

        <el-form-item label="关联项目" prop="project_ids">
          <el-select
            v-model="versionForm.project_ids"
            placeholder="请选择项目（可多选）"
            multiple
            style="width: 100%"
          >
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="版本描述">
          <el-input
            v-model="versionForm.description"
            type="textarea"
            :rows="3"
            placeholder="请输入版本描述"
          />
        </el-form-item>

        <el-form-item>
          <el-checkbox v-model="versionForm.is_baseline">设为基线版本</el-checkbox>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="versionDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveVersion" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 管理模块和测试点弹窗 -->
    <el-dialog
      v-model="manageDialogVisible"
      :title="`管理模块和测试点 - ${manageVersion?.name || ''}`"
      width="720px"
      :close-on-click-modal="false"
      :destroy-on-close="true"
    >
      <div class="manage-dialog-content">
        <!-- 关联项目 -->
        <div class="manage-section">
          <span class="section-label">关联项目：</span>
          <el-tag v-for="p in manageVersion?.projects" :key="p.id" size="small" type="primary" class="project-tag">{{ p.name }}</el-tag>
          <span v-if="!manageVersion?.projects?.length" class="no-data-text">未关联项目</span>
        </div>

        <!-- 新增功能模块按钮 -->
        <div class="manage-actions">
          <el-button type="primary" size="small" @click="openCreateModuleDialog" :disabled="!manageVersion?.projects?.length">
            <el-icon><Plus /></el-icon> 新增功能模块
          </el-button>
        </div>

        <!-- 功能模块列表 -->
        <div v-if="moduleLoading" class="loading-wrapper">
          <el-loading />
        </div>
        <div v-else-if="!hasModules" class="empty-modules">
          <el-empty description="暂无功能模块，点击上方按钮创建" />
        </div>
        <div v-else class="modules-list">
          <template v-for="grp in moduleGroups" :key="grp.label">
            <div v-if="grp.modules.length" class="module-group">
              <div class="module-group-header">
                <span class="group-title">{{ grp.label }}</span>
                <span class="group-count">{{ grp.modules.length }}</span>
                <span v-if="grp.unassociated" class="group-hint">未关联版本，可在「编辑」中关联到本版本</span>
              </div>
              <div v-for="module in grp.modules" :key="module.id" class="module-card">
                <div class="module-header" @click="toggleModule(module.id)">
                  <el-icon class="toggle-icon" :class="{ expanded: expandedModules.has(module.id) }">
                    <ArrowRight />
                  </el-icon>
                  <span class="module-name">{{ module.name }}</span>
                  <span class="module-project">{{ module.project?.name }}</span>
                  <el-tag size="small" type="info">{{ module.test_points_count || 0 }} 个测试点</el-tag>
                  <div class="module-actions" @click.stop>
                    <el-button size="small" text type="primary" @click="openEditModule(module)"><el-icon><Edit /></el-icon></el-button>
                    <el-button size="small" text type="danger" @click="deleteModule(module)"><el-icon><Delete /></el-icon></el-button>
                    <el-button size="small" text type="success" @click="openCreateTestPoint(module)"><el-icon><Plus /></el-icon>测试点</el-button>
                  </div>
                </div>
                <div v-show="expandedModules.has(module.id)" class="module-body">
                  <div v-if="module.testPointsLoading" class="loading-small">
                    <el-loading text="加载测试点中..." />
                  </div>
                  <div v-else-if="!module.testPoints?.length" class="no-testpoints">
                    暂无测试点，点击上方「+ 测试点」按钮创建
                  </div>
                  <div v-else class="testpoints-list">
                    <div v-for="tp in module.testPoints" :key="tp.id" class="testpoint-item">
                      <span class="tp-name">{{ tp.name }}</span>
                      <span v-if="tp.description" class="tp-desc">{{ tp.description }}</span>
                      <div class="tp-actions" @click.stop>
                        <el-button size="small" text type="primary" @click="openEditTestPoint(tp, module)"><el-icon><Edit /></el-icon></el-button>
                        <el-button size="small" text type="danger" @click="deleteTestPoint(tp, module)"><el-icon><Delete /></el-icon></el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </el-dialog>

    <!-- 新增/编辑功能模块弹窗 -->
    <el-dialog v-model="createModuleVisible" :title="editingModuleId ? '编辑功能模块' : '新增功能模块'" width="500px" :close-on-click-modal="false">
      <el-form :model="moduleForm" ref="moduleFormRef" label-width="90px" :rules="moduleRules">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="moduleForm.project_id" placeholder="请选择项目" style="width: 100%">
            <el-option
              v-for="p in manageVersion?.projects || []"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模块名称" prop="name">
          <el-input v-model="moduleForm.name" placeholder="请输入功能模块名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="模块描述">
          <el-input v-model="moduleForm.description" type="textarea" :rows="2" placeholder="可选填描述" />
        </el-form-item>
        <el-form-item label="关联版本">
          <el-checkbox-group v-model="moduleForm.version_ids" style="width: 100%">
            <el-checkbox
              v-for="v in allVersionsForModule"
              :key="v.id"
              :label="v.id"
              :value="v.id"
            >{{ v.name }}</el-checkbox>
          </el-checkbox-group>
          <div style="color: #909399; font-size: 12px; margin-top: 4px">选择该功能模块所属的版本（可多选）</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createModuleVisible = false">取消</el-button>
        <el-button type="primary" @click="saveModule" :loading="moduleSaving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新增/编辑测试点弹窗 -->
    <el-dialog v-model="createTestPointVisible" :title="editingTestPointId ? '编辑测试点' : '新增测试点'" width="450px" :close-on-click-modal="false">
      <el-form :model="testPointForm" ref="testPointFormRef" label-width="90px" :rules="testPointRules">
        <el-form-item label="所属模块">
          <el-input :model-value="selectedModule?.name" disabled />
        </el-form-item>
        <el-form-item label="测试点名称" prop="name">
          <el-input v-model="testPointForm.name" placeholder="请输入测试点名称" maxlength="200" />
        </el-form-item>
        <el-form-item label="测试点描述">
          <el-input v-model="testPointForm.description" type="textarea" :rows="2" placeholder="可选填描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createTestPointVisible = false">取消</el-button>
        <el-button type="primary" @click="saveTestPoint" :loading="testPointSaving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Delete, ArrowRight, Edit } from '@element-plus/icons-vue'
import api from '@/utils/api'
import dayjs from 'dayjs'

const loading = ref(false)
const versions = ref([])
const projects = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const searchText = ref('')
const projectFilter = ref('')
const baselineFilter = ref('')
const selectedVersions = ref([])
const isDeleting = ref(false)

const versionDialogVisible = ref(false)
const versionFormRef = ref()
const saving = ref(false)
const isEdit = ref(false)
const editingVersionId = ref(null)

const versionForm = reactive({
  name: '',
  description: '',
  project_ids: [],
  is_baseline: false
})

const versionRules = {
  name: [{ required: true, message: '请输入版本名称', trigger: 'blur' }],
  project_ids: [{ required: true, message: '请选择关联项目', trigger: 'change' }]
}

// ========== 管理模块弹窗 ==========
const manageDialogVisible = ref(false)
const manageVersion = ref(null)
const modulesList = ref([])
const moduleLoading = ref(false)
// 模块管理弹窗中的分组：属于本版本的归「已关联」，未填写版本的归「未关联版本」
const moduleGroups = computed(() => {
  const vid = manageVersion.value?.id
  const matched = []
  const unassociated = []
  for (const m of modulesList.value) {
    const versions = m.versions || []
    if (vid && versions.some(v => v.id === vid)) matched.push(m)
    else if (versions.length === 0) unassociated.push(m)
  }
  return [
    { label: `已关联「${manageVersion.value?.name || ''}」`, modules: matched, unassociated: false },
    { label: '未关联版本', modules: unassociated, unassociated: true }
  ]
})
const hasModules = computed(() => moduleGroups.value.some(g => g.modules.length))
const expandedModules = ref(new Set())

const fetchModulesForVersion = async () => {
  if (!manageVersion.value?.projects?.length) {
    modulesList.value = []
    return
  }
  moduleLoading.value = true
  try {
    const projectIds = manageVersion.value.projects.map(p => p.id)
    const allModules = []
    for (const pid of projectIds) {
      try {
        // 传 version_id 参数，只返回该版本关联的模块
        const res = await api.get(`/feature-modules/projects/${pid}/modules/`, {
          params: { version_id: manageVersion.value.id }
        })
        allModules.push(...(res.data || []))
      } catch (e) {
        console.error(`加载项目 ${pid} 的模块失败:`, e)
      }
    }
    // 去重并按名称排序
    const seen = new Set()
    modulesList.value = allModules.filter(m => {
      if (seen.has(m.id)) return false
      seen.add(m.id)
      return true
    }).sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
    // 为每个模块计算测试点数量
    for (const m of modulesList.value) {
      try {
        const tpRes = await api.get(`/feature-modules/modules/${m.id}/test-points/`)
        m.test_points_count = (tpRes.data || []).length
      } catch {
        m.test_points_count = 0
      }
    }
  } catch (error) {
    ElMessage.error('加载功能模块失败')
  } finally {
    moduleLoading.value = false
  }
}

const openManageModules = (version) => {
  manageVersion.value = version
  manageDialogVisible.value = true
  expandedModules.value = new Set()
  nextTick(() => fetchModulesForVersion())
}

const toggleModule = async (moduleId) => {
  const module = modulesList.value.find(m => m.id === moduleId)
  if (!module) return
  if (expandedModules.value.has(moduleId)) {
    expandedModules.value.delete(moduleId)
    return
  }
  expandedModules.value.add(moduleId)
  // 加载测试点
  if (!module.testPoints) {
    module.testPointsLoading = true
    try {
      const res = await api.get(`/feature-modules/modules/${moduleId}/test-points/`)
      module.testPoints = res.data || []
    } catch {
      module.testPoints = []
    } finally {
      module.testPointsLoading = false
    }
  }
}

// ========== 创建/编辑功能模块 ==========
const createModuleVisible = ref(false)
const editingModuleId = ref(null)
const moduleFormRef = ref()
const moduleSaving = ref(false)
const moduleForm = reactive({
  name: '',
  description: '',
  project_id: null,
  version_ids: []
})
const moduleRules = {
  project_id: [{ required: true, message: '请选择所属项目', trigger: 'change' }],
  name: [{ required: true, message: '请输入模块名称', trigger: 'blur' }]
}
const allVersionsForModule = ref([])

const fetchAllVersionsForModule = async () => {
  try {
    const res = await api.get('/versions/')
    const all = res.data.results || res.data || []
    // 只保留与当前版本所属项目相关的版本
    const projectIds = (manageVersion.value?.projects || []).map(p => p.id)
    if (projectIds.length > 0) {
      allVersionsForModule.value = all.filter(v => {
        if (!v.projects || !Array.isArray(v.projects)) return false
        return v.projects.some(p => projectIds.includes(p.id))
      }).map((v) => ({ id: v.id, name: v.name }))
    } else {
      allVersionsForModule.value = all.map((v) => ({ id: v.id, name: v.name }))
    }
  } catch {}
}

const openCreateModuleDialog = async () => {
  editingModuleId.value = null
  moduleForm.name = ''
  moduleForm.description = ''
  moduleForm.project_id = manageVersion.value?.projects?.[0]?.id || null
  moduleForm.version_ids = manageVersion.value ? [manageVersion.value.id] : []
  createModuleVisible.value = true
  await fetchAllVersionsForModule()
  nextTick(() => moduleFormRef.value?.resetFields())
}

const openEditModule = async (module) => {
  editingModuleId.value = module.id
  moduleForm.name = module.name
  moduleForm.description = module.description || ''
  moduleForm.project_id = module.project?.id || module.project_id
  // 编辑时从模块已有的版本列表中提取 id
  if (module.versions && Array.isArray(module.versions)) {
    moduleForm.version_ids = module.versions.map((v) => v.id || v)
  } else {
    moduleForm.version_ids = manageVersion.value ? [manageVersion.value.id] : []
  }
  createModuleVisible.value = true
  await fetchAllVersionsForModule()
  nextTick(() => moduleFormRef.value?.clearValidate())
}

const deleteModule = async (module) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除功能模块「${module.name}」吗？`,
      '删除确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await api.delete(`/feature-modules/${module.id}/`)
    ElMessage.success('功能模块已删除')
    // 关闭展开状态
    expandedModules.value.delete(module.id)
    await fetchModulesForVersion()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除功能模块失败')
    }
  }
}

const saveModule = async () => {
  if (!moduleFormRef.value) return
  try {
    await moduleFormRef.value.validate()
    moduleSaving.value = true
    const payload = {
      name: moduleForm.name.trim(),
      description: moduleForm.description.trim(),
      project_id: moduleForm.project_id,
      // 使用用户在复选框中选择的版本
      version_ids: moduleForm.version_ids
    }
    if (editingModuleId.value) {
      await api.put(`/feature-modules/${editingModuleId.value}/`, payload)
      ElMessage.success('功能模块更新成功')
    } else {
      await api.post('/feature-modules/', payload)
      ElMessage.success('功能模块创建成功')
    }
    createModuleVisible.value = false
    editingModuleId.value = null
    await fetchModulesForVersion()
  } catch (error) {
    if (error.response?.data) {
      const detail = error.response.data.detail || error.response.data.name || '操作失败'
      ElMessage.error(Array.isArray(detail) ? detail[0] : detail)
    } else if (error !== 'cancel') {
      ElMessage.error('操作功能模块失败')
    }
  } finally {
    moduleSaving.value = false
  }
}

// ========== 创建/编辑测试点 ==========
const createTestPointVisible = ref(false)
const editingTestPointId = ref(null)
const testPointFormRef = ref()
const testPointSaving = ref(false)
const selectedModule = ref(null)
const testPointForm = reactive({
  name: '',
  description: ''
})
const testPointRules = {
  name: [{ required: true, message: '请输入测试点名称', trigger: 'blur' }]
}

const openCreateTestPoint = (module) => {
  editingTestPointId.value = null
  selectedModule.value = module
  testPointForm.name = ''
  testPointForm.description = ''
  createTestPointVisible.value = true
  nextTick(() => testPointFormRef.value?.resetFields())
}

const openEditTestPoint = (tp, module) => {
  editingTestPointId.value = tp.id
  selectedModule.value = module
  testPointForm.name = tp.name
  testPointForm.description = tp.description || ''
  createTestPointVisible.value = true
  nextTick(() => testPointFormRef.value?.clearValidate())
}

const deleteTestPoint = async (tp, module) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除测试点「${tp.name}」吗？`,
      '删除确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await api.delete(`/feature-modules/test-points/${tp.id}/`)
    ElMessage.success('测试点已删除')
    // 刷新该模块的测试点列表
    const m = modulesList.value.find(m => m.id === module.id)
    if (m) {
      const tpRes = await api.get(`/feature-modules/modules/${module.id}/test-points/`)
      m.testPoints = tpRes.data || []
      m.test_points_count = m.testPoints.length
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除测试点失败')
    }
  }
}

const saveTestPoint = async () => {
  if (!testPointFormRef.value) return
  try {
    await testPointFormRef.value.validate()
    testPointSaving.value = true
    const payload = {
      name: testPointForm.name.trim(),
      description: testPointForm.description.trim(),
      feature_module_id: selectedModule.value.id
    }
    if (editingTestPointId.value) {
      await api.put(`/feature-modules/test-points/${editingTestPointId.value}/`, payload)
      ElMessage.success('测试点更新成功')
    } else {
      await api.post('/feature-modules/test-points/', payload)
      ElMessage.success('测试点创建成功')
    }
    createTestPointVisible.value = false
    editingTestPointId.value = null
    // 刷新当前模块的测试点
    const module = modulesList.value.find(m => m.id === selectedModule.value.id)
    if (module) {
      const tpRes = await api.get(`/feature-modules/modules/${module.id}/test-points/`)
      module.testPoints = tpRes.data || []
      module.test_points_count = module.testPoints.length
      expandedModules.value.add(module.id)
    }
  } catch (error) {
    if (error.response?.data) {
      const detail = error.response.data.detail || error.response.data.name || '操作失败'
      ElMessage.error(Array.isArray(detail) ? detail[0] : detail)
    } else if (error !== 'cancel') {
      ElMessage.error('操作测试点失败')
    }
  } finally {
    testPointSaving.value = false
  }
}

// ========== 原有版本管理逻辑 ==========
const fetchVersions = async () => {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      search: searchText.value,
      projects: projectFilter.value,
      is_baseline: baselineFilter.value
    }
    const response = await api.get('/versions/', { params })
    versions.value = response.data.results || []
    total.value = response.data.count || 0
  } catch (error) {
    ElMessage.error('获取版本列表失败')
  } finally {
    loading.value = false
  }
}

const fetchProjects = async () => {
  try {
    const response = await api.get('/projects/')
    projects.value = response.data.results || response.data || []
  } catch (error) {
    ElMessage.error('获取项目列表失败')
  }
}

const handleSearch = () => {
  currentPage.value = 1
  fetchVersions()
}

const handleFilter = () => {
  currentPage.value = 1
  fetchVersions()
}

const handlePageChange = () => {
  fetchVersions()
}

const createVersion = () => {
  isEdit.value = false
  resetVersionForm()
  versionDialogVisible.value = true
}

const editVersion = (version) => {
  isEdit.value = true
  editingVersionId.value = version.id

  versionForm.name = version.name
  versionForm.description = version.description
  versionForm.project_ids = version.projects.map(p => p.id)
  versionForm.is_baseline = version.is_baseline

  versionDialogVisible.value = true
}

const saveVersion = async () => {
  if (!versionFormRef.value) return

  try {
    await versionFormRef.value.validate()
    saving.value = true

    if (isEdit.value) {
      await api.put(`/versions/${editingVersionId.value}/`, versionForm)
      ElMessage.success('版本更新成功')
    } else {
      await api.post('/versions/', versionForm)
      ElMessage.success('版本创建成功')
    }

    versionDialogVisible.value = false
    fetchVersions()

  } catch (error) {
    if (error.response?.data) {
      const errors = Object.values(error.response.data).flat()
      ElMessage.error(errors[0] || '保存失败')
    } else {
      ElMessage.error('保存失败')
    }
  } finally {
    saving.value = false
  }
}

const deleteVersion = async (version) => {
  try {
    await ElMessageBox.confirm('确定要删除这个版本吗？', '警告', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })

    await api.delete(`/versions/${version.id}/`)
    ElMessage.success('版本删除成功')
    fetchVersions()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('版本删除失败')
    }
  }
}

const handleSelectionChange = (selection) => {
  selectedVersions.value = selection
}

const getSerialNumber = (index) => {
  return (currentPage.value - 1) * pageSize.value + index + 1
}

const batchDeleteVersions = async () => {
  if (selectedVersions.value.length === 0) {
    ElMessage.warning('请先选择要删除的版本')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedVersions.value.length} 个版本吗？此操作不可恢复。`,
      '警告',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    isDeleting.value = true
    let successCount = 0
    let failCount = 0

    for (const version of selectedVersions.value) {
      try {
        await api.delete(`/versions/${version.id}/`)
        successCount++
      } catch (error) {
        console.error(`删除版本 ${version.id} 失败:`, error)
        failCount++
      }
    }

    if (successCount > 0) {
      ElMessage.success(`成功删除 ${successCount} 个版本${failCount > 0 ? `，${failCount} 个失败` : ''}`)
    } else {
      ElMessage.error('删除失败')
    }

    selectedVersions.value = []
    fetchVersions()

  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除失败:', error)
      ElMessage.error('批量删除失败: ' + (error.message || '未知错误'))
    }
  } finally {
    isDeleting.value = false
  }
}

const resetVersionForm = () => {
  versionForm.name = ''
  versionForm.description = ''
  versionForm.project_ids = []
  versionForm.is_baseline = false
  editingVersionId.value = null
}

const formatDate = (dateString) => {
  return dayjs(dateString).format('YYYY-MM-DD HH:mm')
}

const getProjectsTooltip = (projects) => {
  return projects.map(p => p.name).join('、')
}

onMounted(() => {
  fetchProjects()
  fetchVersions()
})
</script>

<style lang="scss" scoped>
.filter-bar {
  margin-bottom: 20px;
}

.pagination-container {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.version-name {
  display: flex;
  align-items: center;
  gap: 8px;

  .baseline-tag {
    font-size: 12px;
  }
}

.project-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;

  .project-tag {
    margin: 0;
  }
}

.no-project {
  color: #909399;
  font-size: 12px;
  font-style: italic;
}

/* 管理弹窗样式 */
.manage-dialog-content {
  .manage-section {
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;

    .section-label {
      color: #606266;
      font-size: 14px;
    }
  }

  .manage-actions {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #e4e7ed;
  }

  .loading-wrapper {
    padding: 40px 0;
    text-align: center;
  }

  .empty-modules {
    padding: 20px 0;
  }

  .modules-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .module-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .module-group-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 0 2px;
    padding: 4px 8px;
    background: var(--el-fill-color-light, #f5f7fa);
    border-radius: 4px;
    font-size: 13px;
    font-weight: 600;
    color: var(--el-text-color-primary, #303133);
  }

  .module-group-header .group-count {
    color: var(--el-color-primary, #409eff);
  }

  .module-group-header .group-hint {
    font-weight: 400;
    font-size: 12px;
    color: var(--el-text-color-secondary, #909399);
  }


  .module-card {
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    overflow: hidden;

    .module-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      background: #f5f7fa;
      cursor: pointer;
      transition: background 0.2s;

      &:hover {
        background: #eef1f6;
      }

      .toggle-icon {
        transition: transform 0.2s;
        color: #909399;

        &.expanded {
          transform: rotate(90deg);
        }
      }

      .module-name {
        font-weight: 500;
        color: #303133;
        flex: 1;
      }

      .module-project {
        color: #909399;
        font-size: 12px;
      }

      .add-tp-btn {
        margin-left: auto;
      }
    }

    .module-body {
      padding: 12px 16px;
      background: #fff;
    }

    .loading-small {
      padding: 16px 0;
      text-align: center;
      color: #909399;
    }

    .no-testpoints {
      color: #909399;
      font-size: 13px;
      padding: 8px 0;
    }

    .testpoints-list {
      display: flex;
      flex-direction: column;
      gap: 6px;

      .testpoint-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        background: #f5f7fa;
        border-radius: 4px;
        font-size: 13px;

        .tp-name {
          color: #303133;
        }

        .tp-desc {
          color: #909399;
          font-size: 12px;
          margin-left: 8px;
        }
      }
    }
  }
}

.no-data-text {
  color: #909399;
  font-size: 13px;
}

/* 关联已有模块弹窗 */
.link-module-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 8px;

  .link-module-project {
    color: #909399;
    font-size: 12px;
    margin-left: auto;
  }
}
</style>
