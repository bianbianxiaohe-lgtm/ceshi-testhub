<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">用例详情</h1>
      <div class="header-actions">
        <el-button @click="$router.back()">返回</el-button>
        <el-button-group v-if="neighborIds.length > 0" class="nav-group">
          <el-tooltip :content="hasPrev ? `上一个：${getNeighborTitle(currentIndex - 1)}` : '已是第一个'" placement="bottom">
            <el-button :disabled="!hasPrev" @click="goToNeighbor(-1)">← 上一个</el-button>
          </el-tooltip>
          <el-tooltip :content="hasNext ? `下一个：${getNeighborTitle(currentIndex + 1)}` : '已是最后一个'" placement="bottom">
            <el-button :disabled="!hasNext" @click="goToNeighbor(1)">下一个 →</el-button>
          </el-tooltip>
        </el-button-group>
        <span v-if="neighborIds.length > 0" class="nav-hint">{{ currentIndex + 1 }} / {{ neighborIds.length }}</span>
        <el-button type="primary" @click="editTestCase">编辑</el-button>
        <el-button type="success" @click="openExecuteDialog">执行</el-button>
        <el-button type="danger" @click="confirmDelete">删除</el-button>
      </div>
    </div>
    
    <div class="card-container" v-if="testcase">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="用例标题" :span="2">{{ testcase.title }}</el-descriptions-item>
        <el-descriptions-item label="优先级">
          <el-tag :class="`priority-tag ${testcase.priority}`">{{ getPriorityText(testcase.priority) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(testcase.status)">{{ getStatusText(testcase.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="最新执行结果">
          <el-tag v-if="testcase.latest_execution_result === 'pass'" type="success">✅ 通过</el-tag>
          <el-tag v-else-if="testcase.latest_execution_result === 'fail'" type="danger">❌ 失败</el-tag>
          <span v-else class="no-version">未执行</span>
        </el-descriptions-item>
        <el-descriptions-item label="测试类型">{{ getTypeText(testcase.test_type) }}</el-descriptions-item>
        <el-descriptions-item label="归属项目">{{ testcase.project?.name || '未关联项目' }}</el-descriptions-item>
        <el-descriptions-item label="关联版本" :span="2">
          <div v-if="testcase.versions && testcase.versions.length > 0" class="version-tags">
            <el-tag 
              v-for="version in testcase.versions" 
              :key="version.id" 
              size="small" 
              :type="version.is_baseline ? 'warning' : 'info'"
              class="version-tag"
            >
              {{ version.name }}
            </el-tag>
          </div>
          <span v-else class="no-version">未关联版本</span>
        </el-descriptions-item>
        <el-descriptions-item label="功能模块" :span="2">
          <div v-if="testcase.feature_modules && testcase.feature_modules.length > 0" class="version-tags">
            <el-tag 
              v-for="fm in testcase.feature_modules" 
              :key="fm.id" 
              size="small" 
              type="success"
              class="version-tag"
            >
              {{ fm.name }}
            </el-tag>
          </div>
          <span v-else class="no-version">未关联功能模块</span>
        </el-descriptions-item>
        <el-descriptions-item label="作者">{{ testcase.author?.username }}</el-descriptions-item>
        <el-descriptions-item label="创建时间" :span="2">{{ formatDate(testcase.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="用例描述" :span="2">{{ testcase.description || '暂无描述' }}</el-descriptions-item>
        <el-descriptions-item label="前置条件" :span="2">
          <div v-html="testcase.preconditions || '无'"></div>
        </el-descriptions-item>
        <el-descriptions-item label="操作步骤" :span="2">
          <el-alert v-if="testcase.steps && testcase.steps.includes('【步骤缺失')" type="error" :closable="false" show-icon title="步骤缺失，请补充操作步骤" style="margin-bottom:8px" />
          <div class="steps-content" v-html="testcase.steps || '无'"></div>
        </el-descriptions-item>
        <el-descriptions-item label="预期结果" :span="2">
          <div v-html="testcase.expected_result || '无'"></div>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- ==================== 执行日志 ==================== -->
    <div class="card-container" v-if="testcase" style="margin-top: 20px">
      <div class="execution-log-header">
        <h3 class="section-title">📋 执行日志</h3>
        <el-button type="success" size="small" @click="openExecuteDialog">+ 新增执行</el-button>
      </div>
      
      <div v-if="executionLogs.length === 0" class="empty-log">
        暂无执行记录，点击"新增执行"开始记录
      </div>
      
      <el-timeline v-else style="margin-top: 16px">
        <el-timeline-item
          v-for="log in executionLogs"
          :key="log.id"
          :timestamp="formatDate(log.executed_at)"
          placement="top"
          :type="log.result === 'pass' ? 'success' : 'danger'"
          :icon="log.result === 'pass' ? Check : Close"
          :color="log.result === 'pass' ? '#67c23a' : '#f56c6c'"
          :hollow="true"
        >
          <div class="log-item">
            <div class="log-result">
              <el-tag :type="log.result === 'pass' ? 'success' : 'danger'" size="small">
                {{ log.result === 'pass' ? '✅ 通过' : '❌ 失败' }}
              </el-tag>
              <span class="log-executor">{{ log.executed_by_name }}</span>
            </div>
            <div v-if="log.notes" class="log-notes">{{ log.notes }}</div>
            <div v-else class="log-notes no-notes">无备注</div>
          </div>
        </el-timeline-item>
      </el-timeline>
    </div>

    <!-- 执行用例弹窗 -->
    <el-dialog v-model="showExecuteDialog" title="执行测试用例" width="420px" :close-on-click-modal="false">
      <div class="execute-info">
        <p><strong>用例：</strong>{{ testcase?.title }}</p>
        <el-form label-width="80px" style="margin-top: 16px">
          <el-form-item label="执行结果" required>
            <el-radio-group v-model="executeForm.result">
              <el-radio value="pass">✅ 通过</el-radio>
              <el-radio value="fail">❌ 失败</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="executeForm.notes" type="textarea" :rows="3" placeholder="可选：备注信息" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="showExecuteDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmExecute" :loading="executing">
          {{ executing ? '提交中...' : '确认执行' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Close } from '@element-plus/icons-vue'
import api from '@/utils/api'
import dayjs from 'dayjs'

const route = useRoute()
const router = useRouter()
const testcase = ref(null)

// 执行日志
const executionLogs = ref([])
const loadingLogs = ref(false)

const fetchExecutionLogs = async () => {
  if (!testcase.value?.id) return
  loadingLogs.value = true
  try {
    const response = await api.get(`/testcases/${testcase.value.id}/executions/`)
    executionLogs.value = response.data || []
  } catch {
    executionLogs.value = []
  } finally {
    loadingLogs.value = false
  }
}

// 上下文导航：同项目+同版本下的用例ID列表
const neighborIds = ref([])
const neighborTitles = ref({})  // id -> title 快速查找

const currentIndex = computed(() => {
  const id = Number(route.params.id)
  return neighborIds.value.indexOf(id)
})

const hasPrev = computed(() => currentIndex.value > 0)
const hasNext = computed(() => currentIndex.value >= 0 && currentIndex.value < neighborIds.value.length - 1)

const getNeighborTitle = (idx) => {
  if (idx < 0 || idx >= neighborIds.value.length) return ''
  const id = neighborIds.value[idx]
  return neighborTitles.value[id] || `#${id}`
}

// 翻页拉全：循环请求直到没有 next，避免被单页条数截断
const fetchNeighborPages = async (params) => {
  const allItems = []
  let page = 1
  while (true) {
    const p = { ...params, page }
    const response = await api.get('/testcases/', { params: p })
    const items = response.data.results || []
    if (items.length === 0) break
    allItems.push(...items)
    if (!response.data.next) break
    page += 1
    if (page > 1000) break // 安全阀，防止极端情况下死循环
  }
  return allItems
}

// 写入导航列表（id + title）
const setNeighborData = (items) => {
  neighborIds.value = items.map(t => t.id)
  const titleMap = {}
  items.forEach(t => { titleMap[t.id] = t.title })
  neighborTitles.value = titleMap
}

// 按用例自身的 project+version（带 fallback）拉取导航列表
const loadNeighborByCaseContext = async () => {
  const currentId = Number(route.params.id)
  // 没有筛选条件时：先全量拉取，与列表页保持一致
  let items = await fetchNeighborPages({ page_size: 1000 })
  if (items.length > 0 && items.map(t => t.id).indexOf(currentId) === -1) {
    // 极端情况：当前用例不在全量结果中（理论上不会），回退到 project+version
    const projectId = testcase.value?.project?.id
    const versions = testcase.value?.versions || []
    const versionId = versions.length > 0 ? versions[0].id : null
    const p = { page_size: 1000 }
    if (projectId) p.project = projectId
    if (versionId) p.version = versionId
    items = await fetchNeighborPages(p)
  }
  setNeighborData(items)
}

// 加载导航列表：优先使用从列表页带入的筛选条件（route.query），否则按用例自身 project+version
const loadNeighborList = async () => {
  try {
    const q = route.query || {}
    const filterKeys = ['search', 'project', 'priority', 'status', 'version', 'feature_module', 'test_point']
    const hasFilters = filterKeys.some(k => q[k])
    if (hasFilters) {
      const params = { page_size: 1000 }
      filterKeys.forEach(k => { if (q[k]) params[k] = q[k] })
      const items = await fetchNeighborPages(params)
      setNeighborData(items)
      const currentId = Number(route.params.id)
      // 极端情况：当前用例不在筛选结果内（理论上不会，因从筛选列表进入），回退到用例上下文
      if (items.length > 0 && neighborIds.value.indexOf(currentId) === -1) {
        await loadNeighborByCaseContext()
      }
      return
    }
    await loadNeighborByCaseContext()
  } catch {
    neighborIds.value = []
    neighborTitles.value = {}
  }
}

const fetchTestCase = async () => {
  try {
    const response = await api.get(`/testcases/${route.params.id}/`)
    testcase.value = response.data
    // 获取导航列表（优先使用从列表页带入的筛选条件）
    await loadNeighborList()
    // 加载执行日志
    fetchExecutionLogs()
  } catch (error) {
    ElMessage.error('获取用例详情失败')
  }
}

// 路由参数变化时重新加载
watch(() => route.params.id, (newId) => {
  if (newId) fetchTestCase()
})

// =============== 执行用例 ===============
const showExecuteDialog = ref(false)
const executing = ref(false)
const executeForm = reactive({
  result: 'pass',
  notes: ''
})

const openExecuteDialog = () => {
  executeForm.result = 'pass'
  executeForm.notes = ''
  showExecuteDialog.value = true
}

const confirmExecute = async () => {
  if (!executeForm.result) {
    ElMessage.warning('请选择执行结果')
    return
  }
  executing.value = true
  try {
    await api.post(`/testcases/${testcase.value.id}/execute/`, {
      testcase: testcase.value.id,
      result: executeForm.result,
      notes: executeForm.notes
    })
    ElMessage.success(`执行完成：${executeForm.result === 'pass' ? '通过 ✅' : '失败 ❌'}`)
    showExecuteDialog.value = false
    await fetchTestCase()
    await fetchExecutionLogs()
  } catch (error) {
    ElMessage.error('执行失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    executing.value = false
  }
}

const goToNeighbor = (delta) => {
  const idx = currentIndex.value + delta
  if (idx < 0 || idx >= neighborIds.value.length) return
  const targetId = neighborIds.value[idx]
  if (!targetId) {
    ElMessage.warning('目标用例 ID 不存在')
    return
  }
  // 用 replace 而非 push：切换用例不新增历史记录，保证「返回」回到列表页
  // 保留 route.query 中的筛选条件，确保上下翻始终在同一筛选集合内
  router.replace({ path: `/ai-generation/testcases/${targetId}`, query: { ...route.query } })
}

const confirmDelete = () => {
  ElMessageBox.confirm('确定要删除这个测试用例吗？此操作不可恢复。', '确认删除', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
    confirmButtonClass: 'el-button--danger',
  }).then(() => handleDelete())
}

const handleDelete = async () => {
  const currentId = route.params.id
  try {
    await api.delete(`/testcases/${currentId}/`)
    ElMessage.success('用例已删除')
    // 从邻居列表中移除当前 ID
    const idx = neighborIds.value.indexOf(Number(currentId))
    if (idx > -1) neighborIds.value.splice(idx, 1)
    // 跳转：优先下一条，没有则上一条，都没有回列表
    if (idx < neighborIds.value.length) {
      router.replace({ path: `/ai-generation/testcases/${neighborIds.value[idx]}`, query: { ...route.query } })
    } else if (neighborIds.value.length > 0) {
      router.replace({ path: `/ai-generation/testcases/${neighborIds.value[neighborIds.value.length - 1]}`, query: { ...route.query } })
    } else {
      router.replace({ path: '/ai-generation/testcases', query: { ...route.query } })
    }
  } catch (error) {
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

const editTestCase = () => {
  router.push({ path: `/ai-generation/testcases/${route.params.id}/edit`, query: { ...route.query } })
}

const getPriorityText = (priority) => {
  const textMap = {
    low: '低',
    medium: '中',
    high: '高',
    critical: '紧急'
  }
  return textMap[priority] || priority
}

const getStatusType = (status) => {
  const typeMap = {
    draft: 'info',
    active: 'success',
    deprecated: 'warning'
  }
  return typeMap[status] || 'info'
}

const getStatusText = (status) => {
  const textMap = {
    draft: '草稿',
    active: '激活',
    deprecated: '废弃'
  }
  return textMap[status] || status
}

const getTypeText = (type) => {
  const textMap = {
    functional: '功能测试',
    integration: '集成测试',
    api: 'API测试',
    ui: 'UI测试',
    performance: '性能测试',
    security: '安全测试'
  }
  return textMap[type] || '-'
}

const formatDate = (dateString) => {
  return dayjs(dateString).format('YYYY-MM-DD HH:mm')
}

onMounted(() => {
  fetchTestCase()
})
</script>

<style lang="scss" scoped>
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.nav-group {
  margin: 0 4px;
}

.nav-hint {
  font-size: 13px;
  color: #909399;
  white-space: nowrap;
  margin: 0 4px;
}

.priority-tag {
  &.low { color: #67c23a; }
  &.medium { color: #e6a23c; }
  &.high { color: #f56c6c; }
  &.critical { color: #f56c6c; font-weight: bold; }
}

.version-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  
  .version-tag {
    margin: 0;
  }
}

.no-version {
  color: #909399;
  font-size: 14px;
  font-style: italic;
}

.steps-content {
  white-space: pre-wrap;
  line-height: 1.6;
  color: #303133;
  font-family: inherit;
}

/* ===== 执行日志样式 ===== */
.execution-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.empty-log {
  text-align: center;
  color: #909399;
  padding: 40px 0;
  font-size: 14px;
}

.log-item {
  .log-result {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 4px;
  }
  .log-executor {
    font-size: 13px;
    color: #606266;
  }
  .log-notes {
    font-size: 13px;
    color: #303133;
    background: #f5f7fa;
    padding: 8px 12px;
    border-radius: 6px;
    margin-top: 4px;
    white-space: pre-wrap;
  }
  .log-notes.no-notes {
    color: #c0c4cc;
    font-style: italic;
  }
}
</style>
