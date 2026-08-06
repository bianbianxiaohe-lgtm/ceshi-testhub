<template>
  <div class="execution-list">
    <!-- 工具栏 -->
    <el-card class="toolbar" shadow="never">
      <el-row :gutter="20">
        <el-col :span="4">
          <el-select v-model="projectFilter" placeholder="全部项目" clearable filterable @change="loadExecutions">
            <el-option v-for="p in projectList" :key="p.id" :label="p.name" :value="p.real_id" />
          </el-select>
        </el-col>
        <el-col :span="8">
          <el-input
            v-model="searchQuery"
            placeholder="搜索用例名称 / 错误信息"
            clearable
            @clear="loadExecutions"
            @keyup.enter="loadExecutions"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>
        <el-col :span="12" class="text-right">
          <el-select
            v-model="statusFilter"
            placeholder="状态筛选"
            clearable
            style="width: 150px; margin-right: 10px"
            @change="loadExecutions"
          >
            <el-option label="全部" value="" />
            <el-option label="通过" value="passed" />
            <el-option label="失败" value="failed" />
            <el-option label="执行中" value="running" />
            <el-option label="待执行" value="pending" />
            <el-option label="错误" value="error" />
          </el-select>
          <el-button @click="loadExecutions">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- 执行记录列表 -->
    <el-card class="table-card" shadow="never">
      <el-table
        v-loading="loading"
        :data="executions"
        stripe
        style="width: 100%"
      >
        <el-table-column prop="test_case_name" label="测试用例" min-width="180">
          <template #default="{ row }">
            <span class="case-name" @click="viewDetail(row)">{{ row.test_case_name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="引擎" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.engine === 'airtest' ? 'warning' : 'primary'">
              {{ engineLabel(row.engine) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="步骤结果" width="180">
          <template #default="{ row }">
            <div v-if="row.step_results && row.step_results.length" class="step-stats">
              <span class="stat-item success">通过: {{ passedCount(row) }}</span>
              <span class="stat-item danger">失败: {{ failedCount(row) }}</span>
              <span class="stat-item">共: {{ row.step_results.length }}</span>
            </div>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">
            {{ row.execution_time ? row.execution_time + 's' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="执行人" width="90">
          <template #default="{ row }">
            {{ row.created_by_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="160">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" text @click="viewDetail(row)">
              详情
            </el-button>
            <el-button
              v-if="row.error_message"
              type="danger" size="small" text @click="viewError(row)"
            >
              错误
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="loadExecutions"
          @current-change="loadExecutions"
        />
      </div>
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      :title="'执行详情 - ' + (currentExecution?.test_case_name || '')"
      width="800px"
      top="5vh"
      destroy-on-close
    >
      <div v-if="currentExecution" class="detail-content">
        <!-- 基本信息 -->
        <el-descriptions :column="3" border size="small" class="info-section">
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(currentExecution.status)" size="small">{{ statusText(currentExecution.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="引擎">{{ engineLabel(currentExecution.engine) }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ currentExecution.execution_time ? currentExecution.execution_time + 's' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="执行人">{{ currentExecution.created_by_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(currentExecution.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(currentExecution.finished_at) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 标签页：步骤结果 / 执行日志 / 截图 / 错误信息 -->
        <el-tabs v-model="detailActiveTab" class="detail-tabs">
          <!-- 步骤结果 -->
          <el-tab-pane label="步骤结果" name="steps">
            <div v-if="currentExecution.step_results && currentExecution.step_results.length" class="step-list">
              <div
                v-for="(step, idx) in currentExecution.step_results"
                :key="idx"
                class="step-item"
                :class="{ 'step-failed': !step.success }"
              >
                <el-tag :type="step.success ? 'success' : 'danger'" size="small">
                  {{ step.success ? '通过' : '失败' }}
                </el-tag>
                <span class="step-name">第{{ idx + 1 }}步: {{ step.description || step.action_type || '-' }}</span>
                <!-- 每步截图缩略图：点击查看步骤详情（大图+操作步骤） -->
                <div v-if="step.screenshot" class="step-screenshot" @click.stop="openStepDetail(step, idx)">
                  <el-image
                    :src="step.screenshot"
                    fit="cover"
                    :preview-src-list="getStepPreviewList()"
                    :initial-index="getStepPreviewIndex(idx)"
                    :hide-on-click-modal="true"
                  />
                  <span class="step-screenshot-tip">查看</span>
                </div>
                <span v-if="step.error" class="step-error">{{ step.error }}</span>
              </div>
            </div>
            <el-empty v-else description="暂无步骤结果" :image-size="60" />
          </el-tab-pane>

          <!-- 执行日志 -->
          <el-tab-pane label="执行日志" name="logs">
            <div v-if="currentExecution.execution_logs" class="log-content">
              <pre>{{ currentExecution.execution_logs }}</pre>
            </div>
            <el-empty v-else description="暂无执行日志" :image-size="60" />
          </el-tab-pane>

          <!-- 截图 -->
          <el-tab-pane v-if="currentExecution.screenshots && currentExecution.screenshots.length" label="截图" name="screenshots">
            <div class="screenshot-list">
              <div
                v-for="(shot, idx) in currentExecution.screenshots"
                :key="idx"
                class="screenshot-item"
              >
                <el-image
                  :src="getImageUrl(shot)"
                  fit="contain"
                  :preview-src-list="getScreenshotUrls(currentExecution.screenshots)"
                  :initial-index="idx"
                  style="max-width: 100%; max-height: 400px; border-radius: 4px;"
                />
                <div v-if="shot.name || shot.step_name" class="screenshot-caption">
                  {{ shot.name || shot.step_name }}
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- 错误信息 -->
          <el-tab-pane v-if="currentExecution.error_message" label="错误信息" name="error">
            <div class="error-content">
              <pre>{{ currentExecution.error_message }}</pre>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>

    <!-- 错误信息对话框（独立） -->
    <el-dialog
      v-model="errorDialogVisible"
      title="错误信息"
      width="600px"
    >
      <div class="error-content">
        <pre>{{ currentError }}</pre>
      </div>
      <template #footer>
        <el-button type="primary" @click="errorDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 步骤详情弹窗：大图 + 操作步骤 -->
    <el-dialog
      v-model="stepDetailVisible"
      :title="'步骤详情 - 第' + (currentStepIndex + 1) + '步'"
      width="640px"
      top="6vh"
      destroy-on-close
    >
      <div v-if="currentStep" class="step-detail">
        <!-- 操作步骤信息 -->
        <el-descriptions :column="1" border size="small" class="step-info">
          <el-descriptions-item label="状态">
            <el-tag :type="currentStep.success ? 'success' : 'danger'" size="small">
              {{ currentStep.success ? '通过' : '失败' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="操作类型">
            {{ stepActionText(currentStep.action_type) }}
            <span class="step-raw-type">（{{ currentStep.action_type }}）</span>
          </el-descriptions-item>
          <el-descriptions-item label="步骤描述">
            {{ currentStep.description || '-' }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 该步截图 -->
        <div class="step-detail-shot">
          <div class="shot-label">操作截图</div>
          <el-image
            :src="currentStep.screenshot"
            fit="contain"
            :preview-src-list="[currentStep.screenshot]"
            style="width: 100%; max-height: 460px; border-radius: 4px; border: 1px solid #ebeef5;"
          />
        </div>

        <!-- 错误信息 -->
        <div v-if="currentStep.error" class="step-detail-error">
          <div class="shot-label error">错误信息</div>
          <pre class="error-message">{{ currentStep.error }}</pre>
        </div>
      </div>
      <template #footer>
        <el-button @click="stepDetailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getTestCaseExecutions,
  getTestCaseExecution,
  getAllUiProjects,
} from '@/api/ui_automation'
import { Search, Refresh } from '@element-plus/icons-vue'

const loading = ref(false)
const executions = ref([])
const searchQuery = ref('')
const statusFilter = ref('')
const projectFilter = ref(null)
const projectList = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

// 详情弹窗
const detailVisible = ref(false)
const currentExecution = ref(null)
const detailActiveTab = ref('steps')

// 独立错误弹窗
const errorDialogVisible = ref(false)
const currentError = ref('')

// 步骤详情弹窗
const stepDetailVisible = ref(false)
const currentStep = ref(null)
const currentStepIndex = ref(0)

let refreshTimer = null

// ---- 工具函数 ----

const statusMap = {
  pending: { text: '待执行', type: 'info' },
  running: { text: '执行中', type: 'warning' },
  passed: { text: '通过', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  error: { text: '错误', type: 'danger' },
}

const statusTagType = (status) => statusMap[status]?.type || 'info'
const statusText = (status) => statusMap[status]?.text || status

const engineLabel = (engine) => {
  const map = { airtest: 'Airtest', appium: 'Appium', playwright: 'Playwright', selenium: 'Selenium' }
  return map[engine] || (engine || '-')
}

const formatTime = (t) => {
  if (!t) return '-'
  const d = new Date(t)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const passedCount = (row) => (row.step_results || []).filter(s => s.success).length
const failedCount = (row) => (row.step_results || []).filter(s => !s.success).length

const getImageUrl = (shot) => {
  if (!shot) return ''
  if (shot.url) return shot.url
  if (typeof shot === 'string') return shot
  if (shot.path) return `/media/${shot.path}`
  return ''
}

// 每步截图预览辅助
const getStepPreviewList = () => {
  if (!currentExecution.value?.step_results) return []
  return currentExecution.value.step_results
    .map(s => s.screenshot)
    .filter(Boolean)
}
const getStepPreviewIndex = (idx) => {
  // 当前步骤在有截图的步骤列表中的索引
  let screenshotIdx = -1
  for (let i = 0; i <= idx; i++) {
    if (currentExecution.value?.step_results[i]?.screenshot) screenshotIdx++
  }
  return Math.max(0, screenshotIdx)
}

const getScreenshotUrls = (shots) => shots.map(s => getImageUrl(s)).filter(Boolean)

// ---- 数据加载 ----

const loadExecutions = async () => {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value,
      search: searchQuery.value,
      ordering: '-created_at',
    }
    if (statusFilter.value) params.status = statusFilter.value
    if (projectFilter.value) params.project = projectFilter.value

    const res = await getTestCaseExecutions(params)
    const data = res.data
    executions.value = data.results || data || []
    total.value = data.count || 0
  } catch (error) {
    console.error('加载执行记录失败:', error)
    ElMessage.error('加载执行记录失败')
  } finally {
    loading.value = false
  }
}

// 查看详情
const viewDetail = async (row) => {
  detailVisible.value = true
  detailActiveTab.value = 'steps'
  // 先用列表数据快速展示，再异步加载完整数据
  currentExecution.value = { ...row }
  try {
    const res = await getTestCaseExecution(row.id)
    currentExecution.value = res.data
  } catch (e) {
    // 保持列表数据即可
  }
}

// 查看错误
const viewError = (execution) => {
  currentError.value = execution.error_message
  errorDialogVisible.value = true
}

// 打开步骤详情（大截图 + 操作步骤）
const openStepDetail = (step, idx) => {
  currentStep.value = step
  currentStepIndex.value = idx
  stepDetailVisible.value = true
}

// 步骤操作类型中文映射
const stepActionText = (actionType) => {
  const map = {
    click: '点击', tap: '轻触', double_tap: '双击', long_press: '长按',
    fill: '填写', input: '输入', clear: '清空', getText: '获取文本',
    waitFor: '等待元素', hover: '悬停', scroll: '滚动', swipe: '滑动',
    screenshot: '截图', assert: '断言', wait: '等待', switchTab: '切换标签页',
    launch_app: '启动应用', close_app: '关闭应用', back: '返回', home: '主页',
  }
  return map[actionType] || actionType || '-'
}

// 自动刷新执行中的记录
const startAutoRefresh = () => {
  refreshTimer = setInterval(() => {
    const hasRunning = executions.value.some(e => ['running', 'pending'].includes(e.status))
    if (hasRunning) loadExecutions()
  }, 5000)
}

const stopAutoRefresh = () => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

onMounted(() => {
  getAllUiProjects().then(res => { projectList.value = (res.data || []).filter(p => p.source === 'ui') }).catch(() => {})
  loadExecutions()
  startAutoRefresh()
})

onUnmounted(() => stopAutoRefresh())
</script>

<style scoped lang="scss">
.execution-list {
  padding: 20px;
}

.toolbar {
  margin-bottom: 20px;

  .text-right {
    text-align: right;
  }
}

.table-card {
  .pagination {
    margin-top: 20px;
    display: flex;
    justify-content: flex-end;
  }
}

.case-name {
  color: #409eff;
  cursor: pointer;
  &:hover { text-decoration: underline; }
}

.text-muted { color: #c0c4cc; }

.step-stats {
  display: flex;
  gap: 8px;
  font-size: 12px;

  .stat-item {
    &.success { color: #67c23a; }
    &.danger { color: #f56c6c; }
  }
}

/* 详情弹窗 */
.detail-content {
  .info-section { margin-bottom: 16px; }
}

.detail-tabs {
  :deep(.el-tabs__content) { padding-top: 12px; }
}

/* 步骤结果 */
.step-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 400px;
  overflow-y: auto;
}
.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-size: 13px;

  &.step-failed {
    background: #fef0f0;
    border-color: #fbc4c4;
  }

  .step-name { flex: 1; }
  .step-screenshot {
    flex: 0 0 auto;
    width: 80px;
    height: 48px;
    border-radius: 4px;
    overflow: hidden;
    cursor: pointer;
    border: 1px solid #dcdfe6;
    transition: border-color 0.2s;
    position: relative;

    &:hover { border-color: #409eff; }

    :deep(.el-image) {
      width: 100%;
      height: 100%;
      display: block;
    }

    .step-screenshot-tip {
      position: absolute;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.55);
      color: #fff;
      font-size: 10px;
      line-height: 14px;
      padding: 0 4px;
      border-top-left-radius: 4px;
    }
  }
  .step-error {
    color: #f56c6c;
    font-size: 12px;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

/* 步骤详情弹窗 */
.step-detail {
  .step-info { margin-bottom: 16px; }

  .step-raw-type {
    color: #c0c4cc;
    font-size: 12px;
    margin-left: 4px;
  }

  .step-detail-shot { margin-bottom: 16px; }

  .shot-label {
    font-size: 13px;
    font-weight: 600;
    color: #303133;
    margin-bottom: 8px;

    &.error {
      color: #f56c6c;
    }
  }

  .step-detail-error {
    .error-message {
      margin: 0;
      padding: 12px;
      background: #fef0f0;
      border: 1px solid #fbc4c4;
      border-radius: 4px;
      color: #f56c6c;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 200px;
      overflow-y: auto;
    }
  }
}

/* 执行日志 */
.log-content {
  pre {
    background: #f5f7fa;
    padding: 15px;
    border-radius: 4px;
    font-family: 'Courier New', Courier, monospace;
    font-size: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-wrap: break-word;
    max-height: 400px;
    overflow-y: auto;
  }
}

/* 截图 */
.screenshot-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 450px;
  overflow-y: auto;
  align-items: center;
}
.screenshot-caption {
  text-align: center;
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

/* 错误信息 */
.error-content {
  max-height: 400px;
  overflow-y: auto;

  pre {
    background: #f5f7fa;
    padding: 15px;
    border-radius: 4px;
    font-family: 'Courier New', Courier, monospace;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
}
</style>
