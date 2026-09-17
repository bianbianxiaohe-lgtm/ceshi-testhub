<template>
  <div class="business-action-list">
    <div class="page-header">
      <h3>公共步骤库</h3>
      <p class="subtitle">
        一个步骤 = 一个可复用的自然语言操作（如「登录」「清空缓存」）。
        在 AI 用例的步骤里选择「引用公共步骤」即可使用；<b>改一次，所有引用它的用例同步生效</b>。
      </p>
      <div class="header-actions">
        <el-select v-model="categoryFilter" placeholder="全部分类" clearable style="width: 150px" @change="loadList">
          <el-option v-for="c in CATEGORIES" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-input v-model="searchText" placeholder="搜索名称/指令" clearable style="width: 200px" @clear="loadList" @keyup.enter="loadList" />
        <el-button type="primary" :icon="Plus" @click="openCreate">新建步骤</el-button>
        <el-button :icon="Refresh" @click="loadList">刷新</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" style="width: 100%">
      <el-table-column prop="name" label="名称" width="170">
        <template #default="{ row }">
          <code style="color: #409eff">{{ row.name }}</code>
        </template>
      </el-table-column>
      <el-table-column label="分类" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="categoryTagType(row.category)">
            {{ row.category_display || '未分类' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="action" label="动作类型" width="150">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.action_display || row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="prompt" label="语义指令" min-width="260" show-overflow-tooltip />
      <el-table-column label="被引用" width="90" align="center">
        <template #default="{ row }">
          <el-tooltip v-if="row.used_by_count" :content="`${row.used_by_count} 条用例引用了它，修改会同时影响这些用例`">
            <el-tag size="small" type="warning">{{ row.used_by_count }} 条</el-tag>
          </el-tooltip>
          <span v-else class="text-muted">未使用</span>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="165">
        <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑公共步骤' : '新建公共步骤'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如 login / clear-cache（英文、唯一）" :disabled="!!editingId" />
          <div class="form-hint">用例里就是靠这个名字引用它，创建后不建议改</div>
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <el-select v-model="form.category" style="width: 100%">
            <el-option v-for="c in CATEGORIES" :key="c.value" :label="c.label" :value="c.value">
              <span>{{ c.label }}</span>
              <span class="option-desc">{{ c.desc }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" placeholder="可选，说明这个步骤做什么" />
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
          <el-input v-model="form.value" placeholder="aiInput 用，可选，支持 ${{ '{' }}key{{ '}' }} 上下文变量" />
        </el-form-item>
        <el-form-item label="等待毫秒">
          <el-input-number v-model="form.wait_ms" :min="0" :step="500" style="width: 100%" />
        </el-form-item>

        <el-alert
          v-if="editingId && currentUsedBy"
          type="warning"
          :closable="false"
          show-icon
          :title="`该步骤正被 ${currentUsedBy} 条用例引用，保存后这些用例都会使用新内容`"
        />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  getBusinessActions,
  createBusinessAction,
  updateBusinessAction,
  deleteBusinessAction
} from '@/api/ui_automation'

const CATEGORIES = [
  { value: 'precondition', label: '前置准备', desc: '登录 / 切账号 / 开权限' },
  { value: 'business', label: '业务操作', desc: '下单 / 搜索 / 加入购物车' },
  { value: 'extract', label: '数据提取', desc: '问页面要数据写入上下文' },
  { value: 'teardown', label: '收尾清理', desc: '退出登录 / 清缓存' },
  { value: 'other', label: '其他', desc: '暂未归类' }
]

const list = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const editingUsedBy = ref(0)
const formRef = ref(null)
const categoryFilter = ref('')
const searchText = ref('')

const currentUsedBy = computed(() => editingUsedBy.value)

const emptyForm = () => ({
  name: '',
  category: 'business',
  description: '',
  action: 'aiAct',
  prompt: '',
  selector_hint: '',
  value: '',
  wait_ms: 0
})
const form = reactive(emptyForm())

const rules = {
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
  category: [{ required: true, message: '请选择分类', trigger: 'change' }],
  prompt: [{ required: true, message: '请填写语义指令', trigger: 'blur' }]
}

const categoryTagType = (c) => {
  const map = { precondition: 'success', business: 'primary', extract: 'info', teardown: 'warning', other: '' }
  return map[c] || ''
}

const formatDate = (s) => {
  if (!s) return '-'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

const loadList = async () => {
  loading.value = true
  try {
    const params = { page_size: 500 }
    if (categoryFilter.value) params.category = categoryFilter.value
    if (searchText.value) params.search = searchText.value
    const res = await getBusinessActions(params)
    list.value = res.data.results || res.data || []
  } catch (e) {
    console.error('加载公共步骤失败', e)
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editingId.value = null
  editingUsedBy.value = 0
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

const openEdit = (row) => {
  editingId.value = row.id
  editingUsedBy.value = row.used_by_count || 0
  Object.assign(form, {
    name: row.name,
    category: row.category || 'business',
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
    const payload = {
      category: form.category,
      description: form.description,
      action: form.action,
      prompt: form.prompt,
      selector_hint: form.selector_hint,
      value: form.value,
      wait_ms: form.wait_ms
    }
    if (editingId.value) {
      await updateBusinessAction(editingId.value, payload)
      ElMessage.success('已更新')
    } else {
      await createBusinessAction({ ...form })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await loadList()
  } catch (e) {
    if (e?.response?.data?.name) {
      ElMessage.error('名称已存在或非法: ' + e.response.data.name)
    } else {
      ElMessage.error('保存失败: ' + (e?.response?.data?.message || e?.message || ''))
    }
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  const used = row.used_by_count || 0
  const tip = used
    ? `「${row.name}」正被 ${used} 条用例引用，删除后这些用例执行时会报「公共步骤不存在」并跳过该步。
确认删除？`
    : `确认删除公共步骤「${row.name}」？`
  try {
    await ElMessageBox.confirm(tip, '提示', { type: 'warning' })
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
    .subtitle {
      margin: 0 0 12px; color: #888; font-size: 13px;
      code { background: #f4f4f5; padding: 1px 4px; border-radius: 3px; }
    }
    .header-actions { display: flex; gap: 10px; align-items: center; }
  }
  .form-hint { font-size: 12px; color: #909399; line-height: 1.4; margin-top: 4px; }
  .text-muted { color: #c0c4cc; font-size: 12px; }
}
.option-desc { float: right; color: #a8abb2; font-size: 12px; margin-left: 12px; }
</style>
