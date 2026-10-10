<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">AI 测试报告</h1>
      <div class="header-actions">
        <el-button
          type="danger"
          :disabled="selectedRecords.length === 0"
          @click="batchDeleteRecords"
          :loading="isDeleting"
        >
          <el-icon><Delete /></el-icon>
          批量删除
        </el-button>
      </div>
    </div>

    <div class="card-container">
      <el-table 
        :data="records" 
        v-loading="loading" 
        style="width: 100%"
        @selection-change="handleSelectionChange"
        ref="tableRef"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column label="序号" width="80">
          <template #default="{ $index }">
            {{ getSerialNumber($index) }}
          </template>
        </el-table-column>
        <el-table-column prop="case_name" label="用例名称" min-width="200" show-overflow-tooltip />

        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusTag(row.status)">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="执行方式" width="140" align="center">
          <template #default="{ row }">
            <!-- 三种状态必须分开显示，否则用户会误判"固化根本没生效"：
                 ① 脚本回放        真零模型（定位类步骤按坐标点）
                 ② 回放失败→AI降级  试过回放但失败，本次实际烧了 token
                 ③ AI 探索         尚未固化（首次探索）
                 旧实现把 ② 也显示成「AI 探索」，用户反复重跑都看到这个标签，
                 就会以为固化没用、省钱没效果。 -->
            <el-tag v-if="row.replay_mode" type="success" size="small" effect="plain">
              脚本回放
            </el-tag>
            <el-tooltip
              v-else-if="row.replay_degraded"
              :content="degradedTip(row)"
              placement="top"
            >
              <el-tag type="danger" size="small" effect="plain">
                回放失败·AI降级
              </el-tag>
            </el-tooltip>
            <el-tag v-else type="warning" size="small" effect="plain">
              AI 探索
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模型消耗" width="150" align="center">
          <template #default="{ row }">
            <div v-if="row.model_calls || row.prompt_tokens">
              <div>{{ row.model_calls || 0 }} 次调用</div>
              <div style="color:#909399;font-size:12px;">
                {{ formatTokens(row) }} tokens
                <el-tooltip v-if="row.tokens_estimated" content="未拿到接口返回的真实用量，此处为按截图尺寸估算" placement="top">
                  <span style="color:#e6a23c;">≈</span>
                </el-tooltip>
              </div>
            </div>
            <!-- 真的 0 调用要分两种情况说清，否则用户以为"省了模型"
                 其实是这一轮没记录到统计（会让成本判断失真）。 -->
            <el-tooltip v-else :content="zeroModelTip(row)" placement="top">
              <span :style="{ color: row.replay_mode ? '#67c23a' : '#e6a23c' }">
                {{ zeroModelText(row) }}
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="duration" label="耗时(秒)" width="120">
          <template #default="{ row }">
            {{ row.duration ? row.duration.toFixed(2) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="start_time" label="开始时间" width="180" :formatter="formatDate" />
        <el-table-column prop="executed_by.username" label="执行人" width="120" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewDetail(row)">
              查看详情
            </el-button>
            <el-button size="small" type="success" @click="viewReport(row)">
              查看报告
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="pagination.currentPage"
          v-model:page-size="pagination.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </div>

    <!-- 详情对话框 -->
    <el-dialog v-model="showDetailDialog" title="执行详情" :close-on-click-modal="false" :close-on-press-escape="false" :modal="true" :destroy-on-close="false" width="800px">
      <div v-if="currentRecord" class="record-detail">
        <div class="detail-item">
          <span class="label">用例名称:</span>
          <span class="value">{{ currentRecord.case_name }}</span>
        </div>

        <div class="detail-item">
          <span class="label">状态:</span>
          <el-tag :type="getStatusTag(currentRecord.status)">
            {{ getStatusText(currentRecord.status) }}
          </el-tag>
        </div>
        <div class="detail-item">
          <span class="label">开始时间:</span>
          <span>{{ formatDate(null, null, currentRecord.start_time) }}</span>
        </div>
        <div class="detail-item">
          <span class="label">耗时:</span>
          <span>{{ currentRecord.duration ? currentRecord.duration.toFixed(2) + ' 秒' : '未知' }}</span>
        </div>
        <div class="detail-item">
          <span class="label">执行方式:</span>
          <el-tag v-if="currentRecord.replay_mode" type="success" size="small">脚本回放（纯坐标）</el-tag>
          <el-tag v-else type="warning" size="small">AI 探索（定位/操作走视觉模型）</el-tag>
        </div>
        <div class="detail-item">
          <span class="label">模型消耗:</span>
          <span v-if="currentRecord.model_calls || currentRecord.prompt_tokens">
            {{ currentRecord.model_calls || 0 }} 次调用 ·
            {{ formatTokens(currentRecord) }} tokens
            <span v-if="currentRecord.tokens_estimated" style="color:#e6a23c;">（估算）</span>
          </span>
          <span v-else>
            {{ zeroModelText(currentRecord) }}
            <el-tooltip :content="zeroModelTip(currentRecord)" placement="top">
              <span style="color:#909399;cursor:help;"> ⓘ</span>
            </el-tooltip>
          </span>
        </div>

        <!-- 任务描述 -->
        <div v-if="currentRecord.task_description" class="detail-item mt-15">
          <span class="label">任务描述:</span>
        </div>
        <div v-if="currentRecord.task_description" class="task-description-container">
          <div class="task-description-content">{{ currentRecord.task_description }}</div>
        </div>

        <!-- 执行日志 -->
        <div class="detail-item mt-15">
          <span class="label">执行日志:</span>
        </div>
        <div class="log-container">
          <pre>{{ currentRecord.logs }}</pre>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button type="success" @click="openReportFromDetail">查看报告</el-button>
          <el-button @click="showDetailDialog = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 报告对话框 -->
    <AIExecutionReport
      v-model="showReportDialog"
      :record-id="reportRecordId"
    />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { getAIExecutionRecords, batchDeleteAIExecutionRecords } from '@/api/ui_automation'
import AIExecutionReport from './AIExecutionReport.vue'

const records = ref([])
const loading = ref(false)
const total = ref(0)
const pagination = reactive({
  currentPage: 1,
  pageSize: 20
})

const showDetailDialog = ref(false)
const currentRecord = ref(null)
let pollTimer = null

// token 数字可读化：1234 -> 1.2k，1234567 -> 1.2M
const formatTokens = (row) => {
  const n = (row?.prompt_tokens || 0) + (row?.completion_tokens || 0)
  if (!n) return '0'
  if (n < 1000) return String(n)
  if (n < 1000000) return (n / 1000).toFixed(1) + 'k'
  return (n / 1000000).toFixed(2) + 'M'
}

// 「回放失败·AI降级」的悬浮说明：把"回放试过了、为什么失败"讲清楚。
// 用户看到这个标签才知道"固化确实生效了，只是回放没点通"，而不是"固化没用"。
const degradedTip = (row) => {
  const reason = row?.replay_fail_reason
  return '本次已尝试纯坐标回放，但回放过程中失败，已自动降级为 AI 探索重跑'
    + '（所以本次仍消耗了模型 token）。'
    + (reason ? '\n回放失败原因：' + reason : '')
    + '\n常见原因：App 未回到预期起始页（回放不做启动/复位）、界面改版或换了机型。'
    + '跑通后会重新固化坐标。'
}

// 「模型消耗为 0」时的文案与说明。
// 必须区分"真零调用（脚本回放）"和"没统计到"——否则用户会把
// 「AI 探索 + 0 调用」误读成"省了模型"，实际这次烧了 29k tokens。
const zeroModelText = (row) => (
  row && row.replay_mode ? '0 模型调用（脚本回放）' : '未记录到调用'
)

const zeroModelTip = (row) => {
  if (row && row.replay_mode) {
    return '本次按固化坐标回放，不调用视觉模型'
  }
  const head = (row && row.replay_degraded)
    ? '本次曾尝试纯坐标回放但失败（已自动降级为 AI 探索）。'
    : '本次执行方式为 AI 探索。'
  return head + '未采集到模型调用统计，通常是 LLM 用量代理'
    + '（MIDSCENE_LLM_PROXY_URL）未生效，'
    + '实际模型调用可能已发生（可查看执行详情里的日志确认）。'
    + '因此该列不能作为"零成本"的依据。'
}


const selectedRecords = ref([])
const isDeleting = ref(false)
const tableRef = ref(null)

// 报告相关状态
const showReportDialog = ref(false)
const reportRecordId = ref(null)

// 加载记录列表
const loadRecords = async () => {
  loading.value = true
  try {
    const response = await getAIExecutionRecords({
      page: pagination.currentPage,
      page_size: pagination.pageSize
    })

    records.value = response.data.results || []
    total.value = response.data.count || 0
    // 清空选择
    if (tableRef.value) {
      tableRef.value.clearSelection()
    }
  } catch (error) {
    console.error('获取执行记录失败:', error)
    ElMessage.error('获取执行记录失败')
  } finally {
    loading.value = false
  }
}

const handleSizeChange = () => {
  pagination.currentPage = 1
  loadRecords()
}

const handleCurrentChange = () => {
  loadRecords()
}

const viewDetail = (row) => {
  currentRecord.value = row
  showDetailDialog.value = true
}

// 查看报告
const viewReport = (row) => {
  reportRecordId.value = row.id
  showReportDialog.value = true
}

// 从详情页打开报告
const openReportFromDetail = () => {
  if (currentRecord.value) {
    reportRecordId.value = currentRecord.value.id
    showReportDialog.value = true
  }
}

const getStatusTag = (status) => {
  const map = {
    'pending': 'info',
    'running': 'warning',
    'passed': 'success',
    'failed': 'danger'
  }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = {
    'pending': '等待中',
    'running': '执行中',
    'passed': '成功',
    'failed': '失败'
  }
  return map[status] || status
}

const formatDate = (row, column, cellValue) => {
  if (!cellValue) return ''
  return new Date(cellValue).toLocaleString()
}

// 获取序号
const getSerialNumber = (index) => {
  return (pagination.currentPage - 1) * pagination.pageSize + index + 1
}

// 处理选择变化
const handleSelectionChange = (selection) => {
  selectedRecords.value = selection
}

// 批量删除
const batchDeleteRecords = async () => {
  if (selectedRecords.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedRecords.value.length} 条记录吗？此操作不可恢复。`,
      '批量删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: '警告'
      }
    )

    isDeleting.value = true
    const ids = selectedRecords.value.map(item => item.id)
    await batchDeleteAIExecutionRecords(ids)

    ElMessage.success('删除成功')

    // 如果当前页数据全部被删除，且不是第一页，则跳转到上一页
    if (records.value.length === ids.length && pagination.currentPage > 1) {
      pagination.currentPage--
    }

    loadRecords()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除失败:', error)
      ElMessage.error('批量删除失败')
    }
  } finally {
    isDeleting.value = false
  }
}



// 轮询更新状态
const startPolling = () => {
  let pollingActive = false  // 防止轮询请求堆积
  pollTimer = setInterval(() => {
    // 只有在第一页且没有打开详情框且没有正在加载时才轮询
    if (pagination.currentPage === 1 && !showDetailDialog.value && !loading.value && !pollingActive) {
      // 优化：检查当前列表是否有正在运行的任务，如果没有运行中的任务，则不轮询
      const hasActiveTasks = records.value.some(r => r.status === 'running' || r.status === 'pending')
      if (!hasActiveTasks) {
        return
      }

      pollingActive = true
      getAIExecutionRecords({
        page: 1,
        page_size: pagination.pageSize
      }).then(response => {
        // 只有当没有选中项时才更新列表，避免干扰用户选择
        if (selectedRecords.value.length === 0) {
          records.value = response.data.results || []
          total.value = response.data.count || 0
        }
      }).catch(console.error).finally(() => {
        pollingActive = false
      })
    }
  }, 5000)
}

onMounted(() => {
  loadRecords()
  startPolling()
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
  }
})
</script>

<style lang="scss" scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  
  .page-title {
    font-size: 20px;
    font-weight: 600;
    margin: 0;
  }
  
  .header-actions {
    display: flex;
    align-items: center;
  }
}

.card-container {
  background-color: #fff;
  border-radius: 4px;
  padding: 20px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.pagination-container {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.record-detail {
  .detail-item {
    margin-bottom: 15px;
    .label {
      font-weight: bold;
      margin-right: 10px;
    }
  }

  .log-container {
    background-color: #1e1e1e;
    color: #fff;
    padding: 15px;
    border-radius: 4px;
    max-height: 400px;
    overflow-y: auto;
    font-family: monospace;

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
  }

  .task-description-container {
    background-color: #f5f7fa;
    border: 1px solid #e4e7ed;
    border-radius: 4px;
    padding: 12px 15px;
    margin-top: 8px;

    .task-description-content {
      color: #606266;
      line-height: 1.6;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
  }
}

.mt-15 {
  margin-top: 15px;
}
</style>
