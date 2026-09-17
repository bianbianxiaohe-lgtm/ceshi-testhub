<template>
  <div class="pipeline-run">
    <div class="page-header">
      <h3>App 自动化流水线</h3>
      <span class="subtitle">选择应用与设备，自定义要执行的阶段，运行后可从历史记录一键重跑</span>
    </div>

    <el-card shadow="never" class="config-card">
      <el-form label-width="90px" :model="form">
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="项目">
              <el-select v-model="selectedProject" placeholder="选择项目" filterable clearable style="width:100%" @change="handleProjectChange">
                <el-option v-for="p in allProjects" :key="p.id" :label="`${p.name}（${p.source === 'ui' ? 'UI' : 'AI'}）`" :value="p.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="应用">
              <div class="inline-select">
                <el-select v-model="form.app_config_id" placeholder="选择应用" filterable style="width:100%">
                  <el-option v-for="a in appConfigs" :key="a.id" :label="`${a.name} (${a.package_name})`" :value="a.id" />
                </el-select>
                <el-button :icon="Plus" circle @click="openCreateApp" title="新建应用配置" />
              </div>
              <div v-if="appConfigs.length === 0" class="hint">暂无应用配置，请先「新建」并填写包名与启动 Activity</div>
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="设备">
              <el-select v-model="form.device_id" placeholder="自动(默认设备)" clearable filterable style="width:100%">
                <el-option v-for="d in devices" :key="d.id" :label="`${d.name || d.udid} (${d.udid})`" :value="d.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="执行阶段">
          <el-checkbox-group v-model="form.stages">
            <el-checkbox v-for="s in stageOptions" :key="s.value" :value="s.value" border>{{ s.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :icon="VideoPlay" :loading="running" @click="handleRun">运行流水线</el-button>
          <el-button :icon="Refresh" :loading="loadingRuns" @click="loadRuns">刷新记录</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="history-card">
      <template #header>
        <span>运行记录</span>
      </template>
      <el-table :data="runs" v-loading="loadingRuns" style="width:100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="应用" min-width="160">
          <template #default="{ row }">{{ row.app_config_name }}</template>
        </el-table-column>
        <el-table-column label="设备" min-width="140">
          <template #default="{ row }">{{ row.device_name || row.device_udid || '自动' }}</template>
        </el-table-column>
        <el-table-column label="阶段" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="s in row.stages" :key="s" size="small" class="stage-tag">{{ stageLabel(s) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ row.status_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">{{ row.duration ? row.duration.toFixed(1) + 's' : '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openLog(row)">日志</el-button>
            <el-button link type="primary" size="small" :loading="row._rerunning" @click="handleRerun(row)">重跑</el-button>
            <el-button v-if="row.report_url" link type="success" size="small" @click="openReport(row)">报告</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 日志弹窗 -->
    <el-dialog v-model="logVisible" :title="`运行日志 #${currentLog?.id}`" width="70%" top="5vh">
      <pre class="log-box">{{ currentLog?.log || '（暂无日志）' }}</pre>
      <template #footer>
        <el-button @click="logVisible = false">关闭</el-button>
        <el-button v-if="currentLog?.report_url" type="primary" @click="openReport(currentLog)">查看报告</el-button>
      </template>
    </el-dialog>

    <!-- 新建应用配置 -->
    <el-dialog v-model="appDialogVisible" title="新建应用配置" width="480px">
      <el-form :model="appForm" label-width="100px">
        <el-form-item label="所属项目">
          <el-select v-model="appForm.project" placeholder="选择项目（可选）" clearable filterable style="width:100%">
            <el-option v-for="p in allProjects" :key="p.id" :label="`${p.name}（${p.source === 'ui' ? 'UI' : 'AI'}）`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="应用名称" required>
          <el-input v-model="appForm.name" placeholder="如：万年历" />
        </el-form-item>
        <el-form-item label="包名" required>
          <el-input v-model="appForm.package_name" placeholder="如：com.youloft.calendar" />
        </el-form-item>
        <el-form-item label="启动Activity">
          <el-input v-model="appForm.app_activity" placeholder="如：com.youloft.LauncherActivity（为空将自动探测）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="appDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingApp" @click="submitApp">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'
import {
  getAppConfigs, createAppConfig, getAppDevices,
  getPipelineRuns, getPipelineDetail, runPipeline, rerunPipeline
} from '@/api/app-pipeline'
import { useUnifiedProjects } from '@/utils/useUnifiedProjects'

const stageOptions = [
  { value: 'capture', label: '抓取快照' },
  { value: 'gen_pytest', label: '生成用例' },
  { value: 'run_pytest', label: '执行测试' },
  { value: 'allure', label: '生成报告' },
]
const stageLabel = (v) => stageOptions.find(s => s.value === v)?.label || v
const statusType = (s) => ({ pending: 'info', running: 'warning', success: 'success', failed: 'danger' }[s] || 'info')
const formatTime = (t) => t ? new Date(t).toLocaleString() : '-'

const form = reactive({
  app_config_id: null,
  device_id: null,
  stages: ['capture', 'gen_pytest', 'run_pytest', 'allure'],
})

const { allProjects, loadProjects } = useUnifiedProjects()
const selectedProject = ref('')

const appConfigs = ref([])
const devices = ref([])
const runs = ref([])
const running = ref(false)
const loadingRuns = ref(false)
const logVisible = ref(false)
const currentLog = ref(null)
const appDialogVisible = ref(false)
const savingApp = ref(false)
const appForm = reactive({ project: null, name: '', package_name: '', app_activity: '' })

// 切换项目时刷新应用列表
const handleProjectChange = () => {
  loadApps()
}

let pollTimer = null

const loadApps = async () => {
  try {
    const res = await getAppConfigs({ page_size: 200, project: selectedProject.value || undefined })
    const data = res.data?.results || res.data?.data || res.data || []
    appConfigs.value = Array.isArray(data) ? data : (data.results || [])
  } catch (e) { /* 忽略 */ }
}
const loadDevices = async () => {
  try {
    const res = await getAppDevices({ page_size: 200 })
    const data = res.data?.results || res.data?.data || res.data || []
    devices.value = Array.isArray(data) ? data : (data.results || [])
  } catch (e) { /* 忽略 */ }
}
const loadRuns = async () => {
  loadingRuns.value = true
  try {
    const res = await getPipelineRuns({ page_size: 50 })
    const data = res.data?.results || res.data?.data || res.data || []
    runs.value = Array.isArray(data) ? data : (data.results || [])
  } catch (e) {
    ElMessage.error('加载运行记录失败')
  } finally {
    loadingRuns.value = false
  }
}

const handleRun = async () => {
  if (!form.app_config_id) {
    ElMessage.warning('请选择应用')
    return
  }
  running.value = true
  try {
    const res = await runPipeline({
      app_config_id: form.app_config_id,
      device_id: form.device_id || null,
      stages: form.stages,
    })
    ElMessage.success('已提交，流水线在后台执行')
    await loadRuns()
    const id = res.data?.id
    if (id) startPoll(id)
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '运行失败')
  } finally {
    running.value = false
  }
}

const handleRerun = async (row) => {
  row._rerunning = true
  try {
    const res = await rerunPipeline(row.id)
    ElMessage.success('已提交重跑')
    await loadRuns()
    const id = res.data?.id
    if (id) startPoll(id)
  } catch (e) {
    ElMessage.error('重跑失败')
  } finally {
    row._rerunning = false
  }
}

// 轮询最新一条运行记录直到终态
const startPoll = (id) => {
  stopPoll()
  pollTimer = setInterval(async () => {
    try {
      const res = await getPipelineDetail(id)
      const rec = res.data
      const idx = runs.value.findIndex(r => r.id === id)
      if (idx >= 0) runs.value[idx] = { ...runs.value[idx], ...rec }
      if (rec.status === 'success' || rec.status === 'failed') {
        stopPoll()
      }
    } catch (e) { /* 忽略轮询错误 */ }
  }, 3000)
}
const stopPoll = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }

const openLog = async (row) => {
  currentLog.value = row
  logVisible.value = true
  // 实时刷新日志
  stopPoll()
  pollTimer = setInterval(async () => {
    try {
      const res = await getPipelineDetail(row.id)
      currentLog.value = res.data
      const i = runs.value.findIndex(r => r.id === row.id)
      if (i >= 0) runs.value[i] = { ...runs.value[i], ...res.data }
      if (res.data.status === 'success' || res.data.status === 'failed') stopPoll()
    } catch (e) { /* 忽略 */ }
  }, 3000)
}

const openReport = (row) => {
  if (row.report_url) window.open(row.report_url, '_blank')
}

const openCreateApp = () => {
  appForm.project = selectedProject.value || null
  appForm.name = ''
  appForm.package_name = ''
  appForm.app_activity = ''
  appDialogVisible.value = true
}
const submitApp = async () => {
  if (!appForm.name || !appForm.package_name) {
    ElMessage.warning('请填写应用名称和包名')
    return
  }
  savingApp.value = true
  try {
    // 解析所属项目：根据前缀判断是 UiProject 还是 AI Project
    const project = appForm.project && appForm.project.startsWith('ui_') ? parseInt(appForm.project.replace('ui_', '')) : null
    const ai_project = appForm.project && appForm.project.startsWith('proj_') ? parseInt(appForm.project.replace('proj_', '')) : null
    await createAppConfig({
      name: appForm.name,
      package_name: appForm.package_name,
      app_activity: appForm.app_activity,
      project,
      ai_project
    })
    ElMessage.success('应用配置已保存')
    appDialogVisible.value = false
    await loadApps()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingApp.value = false
  }
}

onMounted(() => {
  loadProjects()
  loadApps()
  loadDevices()
  loadRuns()
})
onBeforeUnmount(stopPoll)
</script>

<style scoped lang="scss">
.pipeline-run { padding: 20px; }
.page-header { margin-bottom: 16px; h3 { margin: 0 0 4px; } }
.subtitle { color: #909399; font-size: 13px; }
.config-card { margin-bottom: 16px; }
.inline-select { display: flex; gap: 8px; align-items: center; }
.hint { color: #e6a23c; font-size: 12px; margin-top: 4px; }
.stage-tag { margin-right: 4px; }
.history-card { margin-top: 8px; }
.log-box {
  background: #1e1e1e; color: #d4d4d4; padding: 12px;
  border-radius: 4px; max-height: 60vh; overflow: auto;
  white-space: pre-wrap; font-family: monospace; font-size: 12px;
}
</style>
