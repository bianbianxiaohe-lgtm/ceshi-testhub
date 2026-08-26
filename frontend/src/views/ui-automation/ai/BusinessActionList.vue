<template>
  <div class="business-action-list">
    <div class="page-header">
      <h3>业务动作库</h3>
      <p class="subtitle">
        一个动作 = 一个明确的自然语言业务操作。Prompt 与代码分离，正式用例可用 <code>{ref: 动作名}</code> 引用。
      </p>
      <div class="header-actions">
        <el-button type="primary" :icon="Plus" @click="openCreate">新建动作</el-button>
        <el-button :icon="Refresh" @click="loadList">刷新</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" style="width: 100%">
      <el-table-column prop="name" label="动作名" width="160">
        <template #default="{ row }">
          <code style="color: #409eff">{{ row.name }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
      <el-table-column prop="action" label="动作类型" width="160">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.action_display || row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="prompt" label="语义指令" min-width="280" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="170">
        <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑业务动作' : '新建业务动作'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="动作名" prop="name">
          <el-input v-model="form.name" placeholder="如 login / select-product（英文、唯一）" :disabled="!!editingId" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" placeholder="可选" />
        </el-form-item>
        <el-form-item label="动作类型" prop="action">
          <el-select v-model="form.action" style="width: 100%">
            <el-option value="aiAct" label="aiAct（自然语言执行）" />
            <el-option value="aiTap" label="aiTap（点击）" />
            <el-option value="aiInput" label="aiInput（输入）" />
            <el-option value="aiQuery" label="aiQuery（提取）" />
            <el-option value="assert" label="assert（断言）" />
          </el-select>
        </el-form-item>
        <el-form-item label="语义指令" prop="prompt">
          <el-input v-model="form.prompt" type="textarea" :rows="3" placeholder="用语义描述，禁止写坐标" />
        </el-form-item>
        <el-form-item label="定位提示">
          <el-input v-model="form.selector_hint" placeholder="可选，aiTap/aiInput 优先用此定位" />
        </el-form-item>
        <el-form-item label="输入值">
          <el-input v-model="form.value" placeholder="aiInput 用，可选，支持 ${{key}}" />
        </el-form-item>
        <el-form-item label="等待毫秒">
          <el-input-number v-model="form.wait_ms" :min="0" :step="500" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  getBusinessActions,
  createBusinessAction,
  updateBusinessAction,
  deleteBusinessAction
} from '@/api/ui_automation'

const list = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const formRef = ref(null)

const emptyForm = () => ({
  name: '',
  description: '',
  action: 'aiAct',
  prompt: '',
  selector_hint: '',
  value: '',
  wait_ms: 0
})
const form = reactive(emptyForm())

const rules = {
  name: [{ required: true, message: '请填写动作名', trigger: 'blur' }],
  prompt: [{ required: true, message: '请填写语义指令', trigger: 'blur' }]
}

const formatDate = (s) => {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

const loadList = async () => {
  loading.value = true
  try {
    const res = await getBusinessActions({ page_size: 200 })
    list.value = res.data.results || []
  } catch (e) {
    console.error('加载业务动作失败', e)
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

const openEdit = (row) => {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    description: row.description,
    action: row.action,
    prompt: row.prompt,
    selector_hint: row.selector_hint || '',
    value: row.value || '',
    wait_ms: row.wait_ms || 0
  })
  dialogVisible.value = true
}

const save = async () => {
  if (!formRef.value) return
  await formRef.value.validate()
  saving.value = true
  try {
    if (editingId.value) {
      await updateBusinessAction(editingId.value, {
        description: form.description,
        action: form.action,
        prompt: form.prompt,
        selector_hint: form.selector_hint,
        value: form.value,
        wait_ms: form.wait_ms
      })
      ElMessage.success('已更新')
    } else {
      await createBusinessAction({ ...form })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await loadList()
  } catch (e) {
    if (e?.response?.data?.name) {
      ElMessage.error('动作名已存在或非法: ' + e.response.data.name)
    } else {
      ElMessage.error('保存失败: ' + (e?.response?.data?.message || e?.message || ''))
    }
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除业务动作「${row.name}」？`, '提示', { type: 'warning' })
    await deleteBusinessAction(row.id)
    ElMessage.success('已删除')
    await loadList()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e?.response?.data?.message || e?.message || ''))
    }
  }
}

onMounted(loadList)
</script>

<style scoped lang="scss">
.business-action-list {
  padding: 20px;
  .page-header {
    margin-bottom: 16px;
    h3 { margin: 0 0 4px; font-size: 20px; color: #303133; }
    .subtitle { margin: 0 0 12px; color: #888; font-size: 13px; code { background: #f4f4f5; padding: 1px 4px; border-radius: 3px; } }
    .header-actions { display: flex; gap: 10px; }
  }
}
</style>
