<template>
  <div class="device-management">
    <!-- 页面标题和操作按钮 -->
    <div class="device-header">
      <h3>{{ $t('appAutomation.device.title') }}</h3>
      <div class="device-actions">
        <el-button
          type="primary"
          :icon="Refresh"
          :loading="refreshing"
          @click="refreshDevices"
        >
          {{ $t('appAutomation.device.refreshDevice') }}
        </el-button>
        <el-button
          type="success"
          :icon="Plus"
          @click="showAddRemoteDialog"
        >
          {{ $t('appAutomation.device.addRemoteDevice') }}
        </el-button>
        <el-button
          type="warning"
          :icon="Monitor"
          @click="showRegisterHostDialog"
        >
          登记 ADB 主机
        </el-button>
      </div>
    </div>

    <!-- 设备列表 -->
    <el-table
      v-loading="loading"
      :data="devices"
      style="width: 100%; margin-top: 20px"
      :empty-text="emptyText"
    >
      <el-table-column prop="name" :label="$t('appAutomation.device.deviceName')" min-width="150">
        <template #default="{ row }">
          <span>{{ row.name || row.device_id }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="device_id" :label="$t('appAutomation.device.serialNumber')" min-width="180">
        <template #default="{ row }">
          <span v-if="isPlaceholder(row)">{{ row.adb_host }}</span>
          <span v-else>{{ row.device_id }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="status" :label="$t('appAutomation.common.status')" width="100">
        <template #default="{ row }">
          <el-tag :type="getStatusType(row.status)" size="small">
            {{ getStatusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="locked_by" :label="$t('appAutomation.device.lockedUser')" width="120">
        <template #default="{ row }">
          <span v-if="row.locked_by_name">
            {{ row.locked_by_name }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>

      <el-table-column prop="locked_at" :label="$t('appAutomation.device.lockedTime')" width="180">
        <template #default="{ row }">
          <span v-if="row.locked_at">
            {{ formatDate(row.locked_at) }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>

      <el-table-column prop="android_version" :label="$t('appAutomation.device.androidVersion')" width="120" />

      <el-table-column prop="connection_type" :label="$t('appAutomation.device.connectionType')" width="120">
        <template #default="{ row }">
          <el-tag v-if="isPlaceholder(row)" type="info" size="small">ADB主机</el-tag>
          <el-tag
            v-else
            :type="getConnectionType(row.connection_type) === 'local' ? 'primary' : 'warning'"
            size="small"
          >
            {{ getConnectionTypeName(row.connection_type) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="ip_address" :label="$t('appAutomation.device.ipAddress')" width="150">
        <template #default="{ row }">
          <span v-if="row.ip_address">
            {{ row.ip_address }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>

      <el-table-column prop="adb_host" label="电脑IP(ADB)" width="150">
        <template #default="{ row }">
          <el-input
            v-if="editingAdbHostId === row.id"
            v-model="row.adb_host"
            size="small"
            placeholder="如 192.168.8.71"
            style="width: 140px"
            @blur="saveAdbHost(row)"
            @keyup.enter="saveAdbHost(row)"
          />
          <span
            v-else
            style="cursor: pointer; color: #409eff"
            @click="startEditAdbHost(row)"
          >
            <span v-if="row.adb_host">{{ row.adb_host }}</span>
            <el-tag v-else size="small" type="info">点击设置</el-tag>
          </span>
        </template>
      </el-table-column>

      <el-table-column prop="usage_count" :label="$t('appAutomation.device.usageCount')" width="100" />

      <el-table-column prop="updated_at" :label="$t('appAutomation.common.updateTime')" width="180">
        <template #default="{ row }">
          {{ formatDate(row.updated_at) }}
        </template>
      </el-table-column>

      <el-table-column :label="$t('appAutomation.common.operation')" width="250" fixed="right">
        <template #default="{ row }">
          <template v-if="isPlaceholder(row)">
            <el-button
              link
              size="small"
              type="danger"
              @click="handleDeleteDevice(row)"
            >
              删除
            </el-button>
          </template>
          <template v-else>
            <el-button
              v-if="row.status === 'available' || row.status === 'online'"
              link
              size="small"
              type="primary"
              @click="lockDevice(row)"
            >
              {{ $t('appAutomation.device.lock') }}
            </el-button>
            <el-button
              v-if="row.status === 'locked'"
              link
              size="small"
              type="success"
              @click="unlockDevice(row)"
            >
              {{ $t('appAutomation.device.unlock') }}
            </el-button>
            <el-button
              v-if="isRemoteDevice(row.connection_type) && row.status === 'offline'"
              link
              size="small"
              type="warning"
              :loading="reconnectingDevices[row.id]"
              @click="reconnectDevice(row)"
            >
              {{ $t('appAutomation.device.reconnect') }}
            </el-button>
            <el-button
              link
              size="small"
              @click="viewDeviceInfo(row)"
            >
              {{ $t('appAutomation.common.details') }}
            </el-button>
            <el-button
              v-if="isRemoteDevice(row.connection_type) && (row.status === 'online' || row.status === 'available')"
              link
              size="small"
              type="warning"
              @click="disconnectDevice(row)"
            >
              {{ $t('appAutomation.common.disconnect') }}
            </el-button>
            <el-button
              link
              size="small"
              type="danger"
              @click="handleDeleteDevice(row)"
            >
              {{ $t('appAutomation.common.delete') }}
            </el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <!-- 添加远程设备对话框 -->
    <el-dialog
      v-model="addRemoteDialogVisible"
      :title="$t('appAutomation.device.addRemoteDevice')"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="remoteDeviceFormRef"
        :model="remoteDeviceForm"
        :rules="remoteDeviceRules"
        label-width="100px"
      >
        <el-form-item :label="$t('appAutomation.device.ipAddress')" prop="ip_address">
          <el-input
            v-model="remoteDeviceForm.ip_address"
            :placeholder="$t('appAutomation.device.ipAddressPlaceholder')"
          />
        </el-form-item>

        <el-form-item :label="$t('appAutomation.device.port')" prop="port">
          <el-input-number
            v-model="remoteDeviceForm.port"
            :min="1"
            :max="65535"
            :placeholder="$t('appAutomation.device.portPlaceholder')"
            style="width: 100%"
          />
        </el-form-item>

        <el-alert
          :title="$t('appAutomation.device.tip')"
          type="info"
          :closable="false"
          style="margin-top: 10px"
        >
          <div>{{ $t('appAutomation.device.remoteTipTitle') }}</div>
          <div>{{ $t('appAutomation.device.remoteTip1') }}</div>
          <div>{{ $t('appAutomation.device.remoteTip2') }}</div>
          <div>{{ $t('appAutomation.device.remoteTip3') }}</div>
        </el-alert>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="addRemoteDialogVisible = false">{{ $t('appAutomation.common.cancel') }}</el-button>
          <el-button
            type="primary"
            :loading="connecting"
            @click="connectRemoteDevice"
          >
            {{ $t('appAutomation.common.connect') }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 登记 ADB 主机对话框 -->
    <el-dialog
      v-model="registerHostVisible"
      title="登记 ADB 主机"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="hostFormRef"
        :model="hostForm"
        :rules="hostRules"
        label-width="100px"
      >
        <el-form-item label="电脑IP(ADB)" prop="adb_host">
          <el-input
            v-model="hostForm.adb_host"
            placeholder="如 192.168.8.71"
          />
        </el-form-item>

        <el-form-item label="ADB端口" prop="adb_port">
          <el-input-number
            v-model="hostForm.adb_port"
            :min="1"
            :max="65535"
            controls-position="right"
            style="width: 160px"
          />
          <span style="margin-left: 10px; color: #909399; font-size: 12px">默认 5037</span>
        </el-form-item>

        <el-alert
          type="info"
          :closable="false"
          style="margin-top: 10px"
        >
          <div>填写手机所插电脑的局域网 IP。</div>
          <div>该电脑需已运行：<code>adb -a -P {{ hostForm.adb_port }} nodaemon server</code></div>
          <div>且防火墙已放行 {{ hostForm.adb_port }} 端口。</div>
          <div>若 5037 被模拟器占用，可改用其它端口（如 5038）。</div>
          <div>登记后平台会自动扫描该电脑上的所有手机。</div>
        </el-alert>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="registerHostVisible = false">{{ $t('appAutomation.common.cancel') }}</el-button>
          <el-button
            type="primary"
            :loading="registering"
            @click="submitRegisterHost"
          >
            登记
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 设备详情对话框 -->
    <el-dialog
      v-model="deviceInfoDialogVisible"
      :title="$t('appAutomation.device.deviceDetail')"
      width="600px"
    >
      <el-descriptions v-if="selectedDevice" :column="2" border>
        <el-descriptions-item :label="$t('appAutomation.device.deviceName')">
          {{ selectedDevice.name || selectedDevice.device_id }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.serialNumber')">
          {{ selectedDevice.device_id }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.common.status')">
          <el-tag :type="getStatusType(selectedDevice.status)" size="small">
            {{ getStatusText(selectedDevice.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.lockedUser')">
          {{ selectedDevice.locked_by_name || '-' }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.lockedTime')">
          {{ selectedDevice.locked_at ? formatDate(selectedDevice.locked_at) : '-' }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.androidVersion')">
          {{ selectedDevice.android_version || '-' }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.connectionType')">
          <el-tag
            :type="getConnectionType(selectedDevice.connection_type) === 'local' ? 'primary' : 'warning'"
            size="small"
          >
            {{ getConnectionTypeName(selectedDevice.connection_type) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.ipAddress')">
          {{ selectedDevice.ip_address || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="电脑IP(ADB)">
          <span v-if="selectedDevice.adb_host">{{ selectedDevice.adb_host }}</span>
          <el-tag v-else size="small" type="info">未设置</el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.port')">
          {{ selectedDevice.port || '-' }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.device.usageCount')">
          {{ selectedDevice.usage_count || 0 }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.common.createTime')">
          {{ formatDate(selectedDevice.created_at) }}
        </el-descriptions-item>
        <el-descriptions-item :label="$t('appAutomation.common.updateTime')">
          {{ formatDate(selectedDevice.updated_at) }}
        </el-descriptions-item>
      </el-descriptions>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="deviceInfoDialogVisible = false">{{ $t('appAutomation.common.close') }}</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Plus, Monitor } from '@element-plus/icons-vue'
import {
  getDeviceList,
  discoverDevices,
  lockDevice as apiLockDevice,
  unlockDevice as apiUnlockDevice,
  connectDevice,
  disconnectDevice as apiDisconnectDevice,
  deleteDevice,
  updateDevice,
  registerAdbHost
} from '@/api/app-automation'
import { getDeviceStatusType, getDeviceStatusText, formatDateTime } from '@/utils/app-automation-helpers'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// Refs
const remoteDeviceFormRef = ref(null)
const hostFormRef = ref(null)
const registerHostVisible = ref(false)
const registering = ref(false)
const hostForm = ref({ adb_host: '', adb_port: 5037 })

const hostRules = computed(() => ({
  adb_host: [
    { required: true, message: '请输入电脑 IP 地址', trigger: 'blur' },
    {
      pattern: /^(\d{1,3}\.){3}\d{1,3}$/,
      message: '请输入有效的 IPv4 地址，如 192.168.8.71',
      trigger: 'blur'
    }
  ],
  adb_port: [
    { required: true, message: '请输入 ADB 端口', trigger: 'blur' }
  ]
}))

// 响应式数据
const devices = ref([])
const loading = ref(false)
const refreshing = ref(false)
const connecting = ref(false)
const reconnectingDevices = ref({})
const addRemoteDialogVisible = ref(false)
const deviceInfoDialogVisible = ref(false)
const selectedDevice = ref(null)
const emptyText = ref(t('appAutomation.device.emptyText'))
const refreshTimer = ref(null)
const editingAdbHostId = ref(null)  // 正在编辑 adb_host 的设备 ID
const originalAdbHost = ref('')      // 编辑前的原值（用于取消恢复）

const remoteDeviceForm = ref({
  ip_address: '',
  port: 5555
})

const remoteDeviceRules = computed(() => ({
  ip_address: [
    { required: true, message: t('appAutomation.device.rules.ipRequired'), trigger: 'blur' },
    {
      pattern: /^(\d{1,3}\.){3}\d{1,3}$/,
      message: t('appAutomation.device.rules.ipInvalid'),
      trigger: 'blur'
    }
  ],
  port: [
    { required: true, message: t('appAutomation.device.rules.portRequired'), trigger: 'blur' }
  ]
}))

// 方法
const getDevices = async () => {
  loading.value = true
  try {
    const res = await getDeviceList({ page: 1, page_size: 1000 })
    devices.value = res.data.results || []
    if (devices.value.length === 0) {
      emptyText.value = t('appAutomation.device.emptyText')
    }
  } catch (error) {
    console.error('获取设备列表失败:', error)
    ElMessage.error(t('appAutomation.device.messages.loadFailed') + ': ' + (error.message || t('appAutomation.device.unknownError')))
  } finally {
    loading.value = false
  }
}

const refreshDevices = async () => {
  refreshing.value = true
  try {
    const res = await discoverDevices()
    if (res.data.success) {
      devices.value = res.data.devices || []
      ElMessage.success(res.data.message || t('appAutomation.device.messages.refreshedSuccess'))
    } else {
      ElMessage.error(res.data.message || t('appAutomation.device.messages.refreshFailed'))
    }
  } catch (error) {
    console.error('刷新设备列表失败:', error)
    ElMessage.error(t('appAutomation.device.messages.refreshFailed') + ': ' + (error.message || t('appAutomation.device.unknownError')))
  } finally {
    refreshing.value = false
  }
}

const showAddRemoteDialog = () => {
  addRemoteDialogVisible.value = true
  remoteDeviceForm.value = {
    ip_address: '',
    port: 5555
  }
  if (remoteDeviceFormRef.value) {
    remoteDeviceFormRef.value.clearValidate()
  }
}

const showRegisterHostDialog = () => {
  registerHostVisible.value = true
  hostForm.value = { adb_host: '', adb_port: 5037 }
  if (hostFormRef.value) {
    hostFormRef.value.clearValidate()
  }
}

const submitRegisterHost = () => {
  if (!hostFormRef.value) return

  hostFormRef.value.validate(async (valid) => {
    if (!valid) return

    registering.value = true
    try {
      const res = await registerAdbHost(hostForm.value.adb_host, hostForm.value.adb_port)
      if (res.data.success) {
        ElMessage.success(res.data.message || '登记成功')
        registerHostVisible.value = false
        await getDevices()
      } else {
        ElMessage.error(res.data.message || '登记失败')
      }
    } catch (error) {
      const errMsg = error.response?.data?.message || error.message || '登记失败'
      ElMessage.error(errMsg)
    } finally {
      registering.value = false
    }
  })
}

const connectRemoteDevice = async () => {
  if (!remoteDeviceFormRef.value) return
  
  remoteDeviceFormRef.value.validate(async (valid) => {
    if (!valid) return
    
    connecting.value = true
    try {
      const res = await connectDevice({
        ip_address: remoteDeviceForm.value.ip_address,
        port: remoteDeviceForm.value.port
      })
      
      if (res.data.success) {
        ElMessage.success(res.data.message || t('appAutomation.device.messages.connectSuccess'))
        addRemoteDialogVisible.value = false
        await getDevices()
      } else {
        ElMessage.error(res.data.message || t('appAutomation.device.messages.connectFailed'))
      }
    } catch (error) {
      console.error('连接远程设备失败:', error)
      // 优先提取后端返回的具体错误信息
      const errMsg = error.response?.data?.message || error.message || t('appAutomation.device.unknownError')
      ElMessage.error(t('appAutomation.device.messages.connectFailed') + ': ' + errMsg)
    } finally {
      connecting.value = false
    }
  })
}

const reconnectDevice = async (device) => {
  if (!device.ip_address || !device.port) {
    ElMessage.error(t('appAutomation.device.messages.incompleteInfo'))
    return
  }

  reconnectingDevices.value[device.id] = true

  try {
    const res = await connectDevice({
      ip_address: device.ip_address,
      port: device.port
    })

    if (res.data.success) {
      ElMessage.success(t('appAutomation.device.messages.reconnectSuccess'))
      await getDevices()
    } else {
      ElMessage.error(res.data.message || t('appAutomation.device.messages.reconnectFailed'))
    }
  } catch (error) {
    console.error('设备重连失败:', error)
    ElMessage.error(t('appAutomation.device.messages.reconnectFailed'))
  } finally {
    reconnectingDevices.value[device.id] = false
  }
}

const disconnectDevice = async (device) => {
  try {
    await ElMessageBox.confirm(
      t('appAutomation.device.messages.disconnectConfirm', { name: device.name || device.device_id }),
      t('appAutomation.device.tip'),
      {
        confirmButtonText: t('appAutomation.common.confirm'),
        cancelButtonText: t('appAutomation.common.cancel'),
        type: 'warning'
      }
    )

    const res = await apiDisconnectDevice(device.id)

    if (res.data.success) {
      ElMessage.success(t('appAutomation.device.messages.disconnected'))
      await getDevices()
    } else {
      ElMessage.error(res.data.message || t('appAutomation.device.messages.disconnectFailed'))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('断开设备失败:', error)
      ElMessage.error(t('appAutomation.device.messages.disconnectFailed') + ': ' + (error.message || t('appAutomation.device.unknownError')))
    }
  }
}

const viewDeviceInfo = (device) => {
  selectedDevice.value = device
  deviceInfoDialogVisible.value = true
}

const lockDevice = async (device) => {
  try {
    await ElMessageBox.confirm(
      t('appAutomation.device.messages.lockConfirm', { name: device.name || device.device_id }),
      t('appAutomation.device.tip'),
      {
        confirmButtonText: t('appAutomation.common.confirm'),
        cancelButtonText: t('appAutomation.common.cancel'),
        type: 'warning'
      }
    )

    const res = await apiLockDevice(device.id)

    if (res.data.success) {
      ElMessage.success(t('appAutomation.device.messages.locked'))
      await getDevices()
    } else {
      ElMessage.error(res.data.message || t('appAutomation.device.messages.lockFailed'))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('锁定设备失败:', error)
      ElMessage.error(t('appAutomation.device.messages.lockFailed') + ': ' + (error.message || t('appAutomation.device.unknownError')))
    }
  }
}

const unlockDevice = async (device) => {
  try {
    await ElMessageBox.confirm(
      t('appAutomation.device.messages.unlockConfirm', { name: device.name || device.device_id }),
      t('appAutomation.device.tip'),
      {
        confirmButtonText: t('appAutomation.common.confirm'),
        cancelButtonText: t('appAutomation.common.cancel'),
        type: 'warning'
      }
    )

    const res = await apiUnlockDevice(device.id)

    if (res.data.success) {
      ElMessage.success(t('appAutomation.device.messages.unlocked'))
      await getDevices()
    } else {
      ElMessage.error(res.data.message || t('appAutomation.device.messages.unlockFailed'))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('解锁设备失败:', error)
      ElMessage.error(t('appAutomation.device.messages.unlockFailed') + ': ' + (error.message || t('appAutomation.device.unknownError')))
    }
  }
}

const handleDeleteDevice = async (device) => {
  try {
    await ElMessageBox.confirm(
      t('appAutomation.device.messages.deleteConfirm', { name: device.name || device.device_id }),
      t('appAutomation.device.messages.deleteDeviceTitle'),
      {
        confirmButtonText: t('appAutomation.common.confirm'),
        cancelButtonText: t('appAutomation.common.cancel'),
        type: 'warning',
        dangerouslyUseHTMLString: false
      }
    )

    const res = await deleteDevice(device.id)

    if (res.status === 204 || res.status === 200) {
      ElMessage.success(t('appAutomation.device.messages.deleted'))
      await getDevices()
    } else {
      ElMessage.error(res.data?.message || t('appAutomation.device.messages.deleteFailed'))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除设备失败:', error)
      ElMessage.error(t('appAutomation.device.messages.deleteFailed') + ': ' + (error.message || t('appAutomation.device.unknownError')))
    }
  }
}

const formatDate = formatDateTime
const getStatusType = getDeviceStatusType
const getStatusText = getDeviceStatusText

// --- 电脑IP(ADB) 内联编辑 ---
const startEditAdbHost = (device) => {
  editingAdbHostId.value = device.id
  originalAdbHost.value = device.adb_host || ''
  if (device.adb_host === null || device.adb_host === undefined) {
    device.adb_host = ''
  }
}

const saveAdbHost = async (device) => {
  const newValue = device.adb_host || null
  editingAdbHostId.value = null
  try {
    await updateDevice(device.id, { adb_host: newValue })
    ElMessage.success('电脑IP已保存')
  } catch (error) {
    device.adb_host = originalAdbHost.value
    console.error('保存电脑IP失败:', error)
    ElMessage.error('保存失败: ' + (error.response?.data?.message || error.message))
  }
}

const getConnectionType = (type) => {
  // emulator, remote_emulator, remote, usb 等
  if (type === 'emulator' || type === 'usb') {
    return 'local'
  }
  return 'remote'
}

const getConnectionTypeName = (type) => {
  const typeKey = {
    'emulator': 'emulator',
    'remote_emulator': 'remoteEmulator',
    'remote': 'remote',
    'usb': 'usb'
  }[type]
  return typeKey ? t(`appAutomation.device.connectionTypes.${typeKey}`) : type
}

const isRemoteDevice = (type) => {
  return type === 'remote_emulator' || type === 'remote'
}

// 是否为「ADB 主机占位记录」（仅登记了电脑 IP，尚未发现真实设备）
const isPlaceholder = (device) => {
  return device && typeof device.device_id === 'string' && device.device_id.startsWith('adb-host:')
}

// 生命周期：进入页面自动扫描 ADB 发现已连接设备（无需手动点刷新）
onMounted(async () => {
  // 先自动发现 ADB 已连接的设备并写入数据库
  await refreshDevices()

  // 再加载完整列表（含数据库中已有的设备）
  getDevices()

  // 30秒自动刷新设备列表（仅读库，避免频繁调 ADB）
  refreshTimer.value = setInterval(() => {
    getDevices()
  }, 30000)
})

onBeforeUnmount(() => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
  }
})
</script>

<style scoped lang="scss">
.device-management {
  padding: 20px;
}

.device-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;

  h3 {
    margin: 0;
    font-size: 20px;
    color: #303133;
  }
}

.device-actions {
  display: flex;
  gap: 10px;
}

.dialog-footer {
  text-align: right;
}
</style>
