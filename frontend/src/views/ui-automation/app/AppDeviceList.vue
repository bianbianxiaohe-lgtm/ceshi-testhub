<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">设备管理</h1>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon>
        添加设备
      </el-button>
    </div>

    <div class="card-container">
      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-input
          v-model="searchText"
          placeholder="搜索设备名称/UDID"
          clearable
          style="width: 240px"
          @clear="loadDevices"
          @keyup.enter="loadDevices"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select v-model="platformFilter" placeholder="平台" clearable style="width: 130px" @change="loadDevices">
          <el-option label="Android" value="android" />
          <el-option label="iOS" value="ios" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 130px" @change="loadDevices">
          <el-option label="在线" value="online" />
          <el-option label="离线" value="offline" />
          <el-option label="占用中" value="busy" />
          <el-option label="异常" value="error" />
        </el-select>
        <el-select v-model="typeFilter" placeholder="设备类型" clearable style="width: 130px" @change="loadDevices">
          <el-option label="真机" value="real" />
          <el-option label="模拟器" value="emulator" />
        </el-select>
        <el-button @click="loadDevices">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>

      <!-- 设备表格 -->
      <el-table :data="devices" v-loading="loading" stripe>
        <el-table-column prop="name" label="设备名称" min-width="140" />
        <el-table-column label="平台" width="100">
          <template #default="{ row }">
            <el-tag :type="row.platform === 'android' ? 'success' : 'primary'" size="small">
              {{ row.platform_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="platform_version" label="系统版本" width="100" />
        <el-table-column label="设备类型" width="90">
          <template #default="{ row }">
            {{ row.device_type_display }}
          </template>
        </el-table-column>
        <el-table-column prop="udid" label="UDID" min-width="160" show-overflow-tooltip />
        <el-table-column prop="adb_host" label="电脑IP(ADB)" width="140">
          <template #default="{ row }">
            <span v-if="row.adb_host">{{ row.adb_host }}</span>
            <el-tag v-else size="small" type="info">本机</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="statusTagType(row.status)"
              size="small"
              effect="dark"
            >
              {{ row.status_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="resolution" label="分辨率" width="110" />
        <el-table-column prop="appium_server_url" label="Appium Server" min-width="180" show-overflow-tooltip />
        <el-table-column prop="last_heartbeat" label="最后心跳" width="160">
          <template #default="{ row }">
            <span v-if="row.last_heartbeat">{{ formatTime(row.last_heartbeat) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button link type="warning" size="small" @click="handleSetStatus(row)">状态</el-button>
            <el-popconfirm title="确定删除该设备?" @confirm="handleDelete(row.id)">
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
          @size-change="loadDevices"
          @current-change="loadDevices"
        />
      </div>
    </div>

    <!-- 创建设备对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      :title="isEditing ? '编辑设备' : '添加设备'"
      width="600px"
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item label="设备名称" prop="name">
          <el-input v-model="form.name" placeholder="如：华为 P50 Pro" />
        </el-form-item>
        <el-form-item label="平台" prop="platform">
          <el-select v-model="form.platform" placeholder="选择平台">
            <el-option label="Android" value="android" />
            <el-option label="iOS" value="ios" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统版本" prop="platform_version">
          <el-input v-model="form.platform_version" placeholder="如：13.0" />
        </el-form-item>
        <el-form-item label="设备类型" prop="device_type">
          <el-radio-group v-model="form.device_type">
            <el-radio value="real">真机</el-radio>
            <el-radio value="emulator">模拟器</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="UDID" prop="udid">
          <el-input v-model="form.udid" placeholder="设备唯一标识" />
        </el-form-item>
        <el-form-item label="电脑IP(ADB)" prop="adb_host">
          <el-input v-model="form.adb_host" placeholder="手机USB所在电脑的IP，如 192.168.8.71（留空则用本机）" />
          <div class="form-hint">多人使用时必填：填你电脑的 IP，平台通过你电脑的 ADB 服务控制手机</div>
        </el-form-item>
        <el-form-item label="服务地址" prop="appium_server_url">
          <el-input
            v-model="form.appium_server_url"
            :placeholder="form.platform === 'ios' ? 'http://host:8100 (WDA地址)' : 'http://localhost:4723'"
          />
          <div class="form-hint">
            {{ form.platform === 'ios'
              ? 'iOS(Airtest)填 WDA 代理地址，如 http://host.docker.internal:8100'
              : 'Android/iOS(Appium)填 Appium Server 地址' }}
          </div>
        </el-form-item>
        <el-form-item label="分辨率" prop="resolution">
          <el-input v-model="form.resolution" placeholder="如：1080x2400" />
        </el-form-item>
        <el-form-item label="额外配置" prop="capabilities">
          <el-input
            v-model="capabilitiesText"
            type="textarea"
            :rows="4"
            placeholder='JSON格式，如：{"automationName": "UiAutomator2"}'
          />
        </el-form-item>
        <el-form-item label="备注" prop="notes">
          <el-input v-model="form.notes" type="textarea" :rows="2" placeholder="设备备注信息" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>

    <!-- 状态设置对话框 -->
    <el-dialog v-model="showStatusDialog" title="设置设备状态" width="400px">
      <el-form label-width="80px">
        <el-form-item label="当前状态">
          <el-tag :type="statusTagType(currentDevice?.status)" size="large">
            {{ currentDevice?.status_display }}
          </el-tag>
        </el-form-item>
        <el-form-item label="新状态">
          <el-select v-model="newStatus" placeholder="选择新状态" style="width: 200px">
            <el-option label="在线" value="online" />
            <el-option label="离线" value="offline" />
            <el-option label="占用中" value="busy" />
            <el-option label="异常" value="error" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showStatusDialog = false">取消</el-button>
        <el-button type="primary" @click="handleStatusChange" :loading="statusSubmitting">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getAppDevices, createAppDevice, updateAppDevice, deleteAppDevice, setDeviceStatus
} from '@/api/ui_automation'
import dayjs from 'dayjs'

// 列表数据
const devices = ref([])
const loading = ref(false)
const total = ref(0)
const searchText = ref('')
const platformFilter = ref('')
const statusFilter = ref('')
const typeFilter = ref('')
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
  platform_version: '',
  device_type: 'real',
  udid: '',
  adb_host: '',
  appium_server_url: 'http://localhost:4723',
  resolution: '',
  capabilities: {},
  notes: ''
}

const form = reactive({ ...defaultForm })
const capabilitiesText = ref('{}')

const rules = {
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  udid: [{ required: true, message: '请输入UDID', trigger: 'blur' }],
  appium_server_url: [{ required: true, message: '请输入Appium Server地址', trigger: 'blur' }]
}

// 状态对话框
const showStatusDialog = ref(false)
const currentDevice = ref(null)
const newStatus = ref('')
const statusSubmitting = ref(false)

const statusTagType = (status) => {
  const map = { online: 'success', offline: 'info', busy: 'warning', error: 'danger' }
  return map[status] || 'info'
}

const formatTime = (time) => {
  return time ? dayjs(time).format('YYYY-MM-DD HH:mm:ss') : '-'
}

const loadDevices = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.currentPage,
      page_size: pagination.pageSize,
      search: searchText.value || undefined,
      platform: platformFilter.value || undefined,
      status: statusFilter.value || undefined,
      device_type: typeFilter.value || undefined
    }
    const res = await getAppDevices(params)
    devices.value = res.data.results || res.data
    total.value = res.data.count || devices.value.length
  } catch (error) {
    ElMessage.error('获取设备列表失败')
  } finally {
    loading.value = false
  }
}

const resetForm = () => {
  Object.assign(form, { ...defaultForm })
  capabilitiesText.value = '{}'
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
    platform_version: row.platform_version || '',
    device_type: row.device_type || 'real',
    udid: row.udid,
    adb_host: row.adb_host || '',
    appium_server_url: row.appium_server_url,
    resolution: row.resolution || '',
    capabilities: row.capabilities || {},
    notes: row.notes || ''
  })
  capabilitiesText.value = JSON.stringify(row.capabilities || {}, null, 2)
  showCreateDialog.value = true
}

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  // 解析 capabilities
  let capabilities = {}
  try {
    capabilities = JSON.parse(capabilitiesText.value || '{}')
  } catch (e) {
    ElMessage.error('额外配置格式错误，请输入有效的JSON')
    return
  }

  submitting.value = true
  try {
    const data = { ...form, capabilities }
    if (isEditing.value) {
      await updateAppDevice(editingId.value, data)
      ElMessage.success('设备更新成功')
    } else {
      await createAppDevice(data)
      ElMessage.success('设备添加成功')
    }
    showCreateDialog.value = false
    await loadDevices()
  } catch (error) {
    ElMessage.error(isEditing.value ? '更新设备失败' : '添加设备失败')
  } finally {
    submitting.value = false
  }
}

const handleDelete = async (id) => {
  try {
    await deleteAppDevice(id)
    ElMessage.success('设备已删除')
    await loadDevices()
  } catch (error) {
    ElMessage.error('删除设备失败')
  }
}

const handleSetStatus = (row) => {
  currentDevice.value = row
  newStatus.value = row.status
  showStatusDialog.value = true
}

const handleStatusChange = async () => {
  if (!currentDevice.value) return
  statusSubmitting.value = true
  try {
    await setDeviceStatus(currentDevice.value.id, newStatus.value)
    ElMessage.success('状态更新成功')
    showStatusDialog.value = false
    await loadDevices()
  } catch (error) {
    ElMessage.error('状态更新失败')
  } finally {
    statusSubmitting.value = false
  }
}

onMounted(() => {
  loadDevices()
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

.form-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
  margin-top: 4px;
}
</style>
