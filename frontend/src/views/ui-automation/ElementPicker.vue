<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">元素拾取器</h1>
      <div class="header-actions">
        <el-button :loading="dumping" type="primary" @click="doDump">
          <el-icon><Refresh /></el-icon>
          {{ elements.length ? '重新抓取' : '抓取当前页面元素' }}
        </el-button>
        <el-button :disabled="!picked.length" type="success" @click="doSave">
          <el-icon><Plus /></el-icon>
          存入元素库（{{ picked.length }}）
        </el-button>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="这里做的是「真正的元素定位」"
      description="先在设备上把 App 操作到目标页面，再点「抓取」。列表里会显示设备上实际存在的元素和文字——选中的元素可以存进元素库，之后写用例时直接引用，不用再靠自然语言描述让 AI 猜。Android / iOS 都支持。"
      style="margin-bottom: 14px"
    />

    <!-- 设备 / 应用 / 项目 选择 -->
    <div class="card-container">
      <el-row :gutter="14">
        <el-col :span="7">
          <div class="field-label">设备</div>
          <el-select v-model="deviceId" filterable placeholder="选择设备" style="width: 100%" @change="onDeviceChange">
            <el-option
              v-for="d in devices"
              :key="d.id"
              :label="`${d.name}（${platformLabel(d.platform)}）${d.status === 'online' ? '' : ' · ' + d.status}`"
              :value="d.id"
            />
          </el-select>
        </el-col>
        <el-col :span="6">
          <div class="field-label">被测应用</div>
          <el-select v-model="appConfigId" filterable clearable placeholder="Android 需要选择" style="width: 100%">
            <el-option
              v-for="c in appConfigs"
              :key="c.id"
              :label="`${c.name}（${c.platform}）`"
              :value="c.id"
            />
          </el-select>
        </el-col>
        <el-col :span="6">
          <div class="field-label">存入项目</div>
          <el-select v-model="projectId" filterable placeholder="选择项目" style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-col>
        <el-col :span="5">
          <div class="field-label">页面名（存入分组）</div>
          <el-input v-model="pageName" placeholder="如：日记本 / 首页" clearable />
        </el-col>
      </el-row>
    </div>

    <!-- 元素列表 -->
    <div class="card-container" style="margin-top: 14px">
      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="按元素文字/名称过滤"
          clearable
          style="width: 260px"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-checkbox v-model="onlyClickable" style="margin-left: 12px">只看可点击</el-checkbox>
        <!-- 坐标类元素默认被排除：定位值换设备就失效，写进用例必错位。
             仍给一个开关，让用户能"看见"它们的存在（排查用），但默认关闭。 -->
        <el-tooltip
          content="坐标类元素的定位值只在当前设备分辨率下成立，换设备/换机型会点错位置，因此默认不参与拾取。仅排查时打开。"
          placement="top"
        >
          <el-checkbox v-model="includeUnportable" style="margin-left: 12px">包含坐标类元素</el-checkbox>
        </el-tooltip>
        <el-checkbox v-model="onlyWithText" style="margin-left: 12px">只看有文字的</el-checkbox>
        <span class="hint" style="margin-left: 12px">
          共 {{ filtered.length }} 个{{ filtered.length !== elements.length ? '（已过滤）' : '' }}
        </span>
        <el-button size="small" text type="primary" style="margin-left: 12px" @click="pickAllVisible">
          全选当前可见
        </el-button>
      </div>

      <el-table
        ref="tableRef"
        :data="filtered"
        v-loading="dumping"
        height="460"
        style="width: 100%"
        @selection-change="onSelectionChange"
        @row-click="onRowClick"
      >
        <el-table-column type="selection" width="46" />
        <el-table-column label="元素文字" min-width="200">
          <template #default="{ row }">
            <span v-if="row.text || row.name">{{ row.text || row.name }}</span>
            <span v-else class="muted">（无文字）</span>
          </template>
        </el-table-column>
        <el-table-column label="控件类型" width="160">
          <template #default="{ row }">
            <el-tag size="small" :type="row.clickable ? 'success' : 'info'">
              {{ shortClass(row.class_name) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="定位策略" width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.strategy }}</span>
          </template>
        </el-table-column>
        <el-table-column label="定位值（会存入元素库）" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono">{{ row.value }}</span>
          </template>
        </el-table-column>
        <el-table-column label="坐标" width="120">
          <template #default="{ row }">
            <span class="mono">{{ row.center_x }},{{ row.center_y }}</span>
          </template>
        </el-table-column>
        <!-- 可跨设备：坐标类元素不能写进用例（换设备必错位），
             必须在"存进元素库之前"就让用户看见 -->
        <el-table-column label="可跨设备" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.cross_device === false" size="small" type="danger" effect="plain">
              不可用
            </el-tag>
            <el-tag v-else size="small" type="success" effect="plain">可</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!dumping && !elements.length"
        description="还没有数据。把设备上的 App 操作到目标页面，然后点右上角「抓取当前页面元素」"
      />
    </div>

    <!-- 元素库（同项目+平台） -->
    <div class="card-container" style="margin-top: 14px">
      <div class="section-head">
        <span class="section-title">元素库（当前项目 / {{ platformLabel(currentPlatform) }}）</span>
        <el-button size="small" text type="primary" @click="loadLibrary">刷新</el-button>
      </div>
      <el-table :data="library" v-loading="libLoading" style="width: 100%" max-height="260">
        <el-table-column prop="name" label="元素名" min-width="180" />
        <el-table-column prop="page" label="页面" width="140" />
        <el-table-column label="策略" width="140">
          <template #default="{ row }">{{ row.locator_strategy_name || row.locator_strategy }}</template>
        </el-table-column>
        <el-table-column prop="locator_value" label="定位值" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.validation_status === 'VALID' ? 'success' : 'info'">
              {{ row.validation_status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!libLoading && !library.length" description="元素库还是空的，先抓取并存入" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search, Plus } from '@element-plus/icons-vue'
import request from '../../utils/api'
import { dumpDeviceElements, savePickedElements } from '../../api/element-picker'

const devices = ref([])
const appConfigs = ref([])
const projects = ref([])

const deviceId = ref(null)
const appConfigId = ref(null)
const projectId = ref(null)
const pageName = ref('')

const dumping = ref(false)
const elements = ref([])
const picked = ref([])
const keyword = ref('')
const onlyClickable = ref(false)
// 是否包含坐标类元素（默认否，见模板里的说明）
const includeUnportable = ref(false)
const onlyWithText = ref(false)
const tableRef = ref(null)

const library = ref([])
const libLoading = ref(false)

const platformLabel = (p) => ({
  ios: 'iOS', android: 'Android', harmony: '鸿蒙', web: 'Web'
}[String(p || '').toLowerCase()] || (p || '—'))

const shortClass = (c) => String(c || '')
  .replace('XCUIElementType', '')
  .replace('android.widget.', '')
  .replace('androidx.recyclerview.widget.', '') || '—'

const currentPlatform = computed(() => {
  const d = devices.value.find((x) => x.id === deviceId.value)
  return d ? d.platform : ''
})

// 过滤逻辑放在前端：一次抓取后用户可反复筛，不用重新连设备（连一次要几秒）
const filtered = computed(() => {
  let list = elements.value
  if (onlyClickable.value) list = list.filter((e) => e.clickable)
  if (onlyWithText.value) list = list.filter((e) => e.text || e.name)
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    list = list.filter((e) => String(e.text || '').toLowerCase().includes(kw)
      || String(e.name || '').toLowerCase().includes(kw))
  }
  return list
})

const onSelectionChange = (rows) => { picked.value = rows }

const onRowClick = (row) => {
  // 点行即切换勾选，少点一次
  tableRef.value?.toggleRowSelection(row)
}

const pickAllVisible = () => {
  const visible = filtered.value
  const allPicked = visible.every((r) => picked.value.includes(r))
  visible.forEach((r) => tableRef.value?.toggleRowSelection(r, !allPicked))
}

const loadDevices = async () => {
  try {
    const res = await request({ url: '/ui-automation/app-devices/', method: 'get', params: { page_size: 200 } })
    devices.value = res.data.results || res.data || []
    if (!deviceId.value && devices.value.length) {
      const online = devices.value.find((d) => d.status === 'online')
      deviceId.value = (online || devices.value[0]).id
    }
  } catch {
    devices.value = []
  }
}

const loadAppConfigs = async () => {
  try {
    const res = await request({ url: '/ui-automation/app-configs/', method: 'get', params: { page_size: 200 } })
    appConfigs.value = res.data.results || res.data || []
  } catch {
    appConfigs.value = []
  }
}

const loadProjects = async () => {
  try {
    const res = await request({ url: '/projects/', method: 'get', params: { page_size: 200 } })
    projects.value = res.data.results || res.data || []
    if (!projectId.value && projects.value.length) projectId.value = projects.value[0].id
  } catch {
    projects.value = []
  }
}

// 存进元素库的 project 必须是真实数字 id。
// 这个页面用的是 /projects/（本来就是真实 id），但统一项目源（all-projects）
// 会给 `ui_9` / `proj_2` 这类带前缀的 id —— 万一将来换成统一源，
// 这里能挡住而不是让后端抛 ValueError 500。
const rawProjectId = (v) => {
  if (v === null || v === undefined || v === '') return null
  if (typeof v === 'number') return v
  const s = String(v)
  if (/^\d+$/.test(s)) return Number(s)
  const m = s.match(/(\d+)$/)
  return m ? Number(m[1]) : null
}

const loadLibrary = async () => {
  if (!projectId.value) return
  libLoading.value = true
  try {
    const params = { page_size: 200, project: projectId.value }
    if (currentPlatform.value) params.platform = currentPlatform.value
    const res = await request({ url: '/ui-automation/elements/', method: 'get', params })
    library.value = res.data.results || res.data || []
  } catch {
    library.value = []
  } finally {
    libLoading.value = false
  }
}

const onDeviceChange = () => {
  // 切设备后清空上一次的结果，避免"看着是 iOS 的元素其实来自 Android"
  elements.value = []
  picked.value = []
  loadLibrary()
}

const doDump = async () => {
  if (!deviceId.value) {
    ElMessage.warning('请先选择设备')
    return
  }
  dumping.value = true
  elements.value = []
  picked.value = []
  try {
    const res = await dumpDeviceElements({
      device_id: deviceId.value,
      app_config_id: appConfigId.value || undefined,
      include_unportable: includeUnportable.value
    })
    if (res.data.error) {
      ElMessage.error(`抓取失败：${res.data.error}`)
      return
    }
    elements.value = res.data.elements || []
    if (!elements.value.length) {
      ElMessage.warning('没抓到元素。请确认 App 已经打开在目标页面（可以先用手机手动操作到这个页面）')
    } else {
      // 被排除的坐标类元素要**明确告知**，否则用户会以为拾取器漏抓了
      const excluded = res.data.excluded_unportable || 0
      ElMessage.success(excluded
        ? `抓到 ${elements.value.length} 个元素（另有 ${excluded} 个仅坐标可定位的元素已排除，换设备会错位）`
        : `抓到 ${elements.value.length} 个元素`)
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '抓取失败，请检查设备连接')
  } finally {
    dumping.value = false
  }
}

const doSave = async () => {
  if (!projectId.value) {
    ElMessage.warning('请先选择要存入的项目')
    return
  }
  if (!picked.value.length) {
    ElMessage.warning('请先勾选要保存的元素')
    return
  }
  const pid = rawProjectId(projectId.value)
  if (!pid) {
    ElMessage.warning('项目 id 无法识别，请重新选择「存入项目」')
    return
  }
  try {
    const res = await savePickedElements({
      project_id: pid,
      platform: currentPlatform.value,
      page: pageName.value.trim(),
      device_id: deviceId.value,
      elements: picked.value.map((e) => ({
        name: (e.text || e.name || '').trim(),
        strategy: e.strategy,
        value: e.value,
        text: e.text,
        center_x: e.center_x,
        center_y: e.center_y,
        class_name: e.class_name
      }))
    })
    ElMessage.success(`已存入元素库：新增 ${res.data.created}，更新 ${res.data.updated}`)
    picked.value = []
    loadLibrary()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  }
}

onMounted(async () => {
  await Promise.all([loadDevices(), loadAppConfigs(), loadProjects()])
  loadLibrary()
})
</script>

<style lang="scss" scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.field-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.filter-bar {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
}
.hint {
  font-size: 12px;
  color: #909399;
}
.muted {
  color: #c0c4cc;
  font-size: 12px;
}
.mono {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.section-title {
  font-weight: 600;
}
</style>
