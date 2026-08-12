<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">AI 用例管理</h1>
    </div>

    <div class="card-container">
      <div class="filter-bar">
        <el-select
          v-model="selectedProject"
          placeholder="选择项目"
          filterable
          clearable
          style="width: 260px;"
          @change="handleProjectChange"
        >
          <el-option
            v-for="p in allProjects"
            :key="p.id"
            :label="`${p.name}（${p.source === 'ui' ? 'UI' : 'AI'}）`"
            :value="p.id"
          />
        </el-select>
        <el-input
          v-model="searchText"
          placeholder="搜索用例名称或描述"
          clearable
          @input="handleSearch"
          style="width: 300px; margin-left: 12px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="openCreate" style="margin-left: 12px;">
          <el-icon><Plus /></el-icon>
          新建用例
        </el-button>
      </div>

      <el-table :data="cases" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="用例名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="执行模式" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.execution_mode === 'midscene'" type="warning" size="small">
              Midscene
            </el-tag>
            <el-tag v-else type="info" size="small">文本模式</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="140" show-overflow-tooltip />
        <el-table-column prop="task_description" label="任务描述" min-width="200" show-overflow-tooltip />
        <el-table-column prop="created_at" label="创建时间" width="170" :formatter="formatDate" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="runCase(row)">
              <el-icon><VideoPlay /></el-icon>
              执行
            </el-button>
            <el-button size="small" type="primary" @click="editCase(row)">
              <el-icon><Edit /></el-icon>
              编辑
            </el-button>
            <el-button size="small" type="danger" @click="deleteCase(row.id)">
              <el-icon><Delete /></el-icon>
              删除
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

    <!-- 编辑对话框 -->
    <el-dialog v-model="showEditDialog" :title="currentCaseId ? '编辑 AI 用例' : '新建 AI 用例'" :close-on-click-modal="false" :close-on-press-escape="false" :modal="true" :destroy-on-close="false" width="860px">
      <el-form :model="editForm" :rules="formRules" ref="editFormRef" label-width="100px">
        <el-form-item label="用例名称" prop="name">
          <el-input v-model="editForm.name" placeholder="请输入用例名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="editForm.description" type="textarea" placeholder="请输入用例描述" />
        </el-form-item>

        <el-form-item label="执行模式" prop="execution_mode">
          <el-radio-group v-model="editForm.execution_mode">
            <el-radio value="text">文本模式(browser-use)</el-radio>
            <el-radio value="midscene">Midscene APP 自动化</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- 文本模式：自然语言任务描述 -->
        <template v-if="editForm.execution_mode === 'text'">
          <el-form-item label="任务描述" prop="task_description" :rules="[{ required: true, message: '请输入自然语言任务描述', trigger: 'blur' }]">
            <el-input
              v-model="editForm.task_description"
              type="textarea"
              :rows="6"
              placeholder="请输入自然语言任务描述"
            />
          </el-form-item>
        </template>

        <!-- Midscene 模式：应用/设备/结构化步骤 -->
        <template v-else>
          <el-form-item label="应用配置" prop="app_config" :rules="[{ required: true, message: '请选择被测应用', trigger: 'change' }]">
            <el-select v-model="editForm.app_config" placeholder="选择被测应用" filterable style="width: 100%;">
              <el-option
                v-for="cfg in appConfigs"
                :key="cfg.id"
                :label="`${cfg.name}（${cfg.platform}）`"
                :value="cfg.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="执行设备" prop="device" :rules="[{ required: true, message: '请选择执行设备', trigger: 'change' }]">
            <el-select v-model="editForm.device" placeholder="选择真机/模拟器" filterable style="width: 100%;">
              <el-option
                v-for="dev in devices"
                :key="dev.id"
                :label="`${dev.name}（${dev.udid}）`"
                :value="dev.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="结构化步骤">
            <div class="steps-editor">
              <div class="steps-toolbar">
                <el-button size="small" @click="loadNeutralExample">载入中性示例</el-button>
                <el-button size="small" type="primary" @click="addStep">+ 新增步骤</el-button>
                <span class="hint">业务无关：步骤里的 extract 可提取任意数据写入上下文，后续步骤用 <code>${{ '{' }}key{{ '}' }}</code> 引用</span>
              </div>

              <div v-for="(step, idx) in editForm.steps" :key="idx" class="step-card">
                <div class="step-head">
                  <span class="step-no">步骤 {{ idx + 1 }}</span>
                  <el-button size="small" type="danger" text @click="removeStep(idx)">删除</el-button>
                </div>
                <el-row :gutter="12">
                  <el-col :span="8">
                    <el-form-item label="动作" :prop="`steps.${idx}.action`" label-width="50px" :required="true">
                      <el-select v-model="step.action" placeholder="action">
                        <el-option label="aiTap 点击" value="aiTap" />
                        <el-option label="aiInput 输入" value="aiInput" />
                        <el-option label="aiAct 操作" value="aiAct" />
                        <el-option label="aiQuery 查询" value="aiQuery" />
                        <el-option label="assert 断言" value="assert" />
                        <el-option label="launch 启动" value="launch" />
                        <el-option label="back 返回" value="back" />
                        <el-option label="home 主页" value="home" />
                        <el-option label="wait 等待" value="wait" />
                        <el-option label="screenshot 截图" value="screenshot" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                  <el-col :span="16">
                    <el-form-item label="名称" :prop="`steps.${idx}.name`" label-width="50px" :required="true">
                      <el-input v-model="step.name" placeholder="步骤说明（仅展示）" />
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-form-item label="提示词" :prop="`steps.${idx}.prompt`" label-width="50px" :required="!['launch','back','home','wait','screenshot'].includes(step.action)">
                  <el-input v-model="step.prompt" type="textarea" :rows="2" placeholder="如：点击右下角的“我的”标签；支持 ${{ '{' }}key{{ '}' }} 引用上下文" />
                </el-form-item>
                <el-row :gutter="12">
                  <el-col :span="12">
                    <el-form-item label="输入值" :prop="`steps.${idx}.value`" label-width="50px" :required="step.action === 'aiInput'">
                      <el-input v-model="step.value" placeholder="aiInput 时填入；支持 ${{ '{' }}key{{ '}' }}" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="等待(ms)" :prop="`steps.${idx}.wait_ms`" label-width="70px">
                      <el-input-number v-model="step.wait_ms" :min="0" :step="500" controls-position="right" />
                    </el-form-item>
                  </el-col>
                </el-row>

                <!-- extract：提取业务数据到上下文 -->
                <el-form-item label="提取" label-width="50px">
                  <div class="extract-list">
                    <div v-for="(ex, ei) in (step.extract || [])" :key="ei" class="extract-row">
                      <el-input v-model="ex.key" placeholder="上下文变量名 key" style="width: 130px;" />
                      <el-input v-model="ex.prompt" placeholder="提取提示词（问页面要什么）" style="flex: 1;" />
                      <el-select v-model="ex.type" style="width: 110px;">
                        <el-option label="string" value="string" />
                        <el-option label="number" value="number" />
                        <el-option label="boolean" value="boolean" />
                        <el-option label="json" value="json" />
                      </el-select>
                      <el-checkbox v-model="ex.required">必填</el-checkbox>
                      <el-button size="small" text type="danger" @click="removeExtract(step, ei)">×</el-button>
                    </div>
                    <el-button size="small" @click="addExtract(step)">+ 提取项</el-button>
                  </div>
                </el-form-item>

                <!-- assert：断言 -->
                <el-form-item label="断言" label-width="50px" :required="step.action === 'assert'">
                  <div class="assert-row">
                    <el-input v-model="step.assert.prompt" placeholder="断言提示词（如：当前页面显示“登录成功”）" style="flex: 1;" />
                    <el-input v-model="step.assert.expect" placeholder="期望结论（选填）" style="width: 160px;" />
                  </div>
                </el-form-item>
              </div>

              <el-empty v-if="!editForm.steps.length" description="暂无步骤，点击「载入中性示例」或「新增步骤」" />
            </div>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showEditDialog = false">取消</el-button>
          <el-button type="primary" @click="confirmEdit" :loading="saving">保存</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, VideoPlay, Edit, Delete, Plus } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import {
  getAICases,
  createAICase,
  updateAICase,
  deleteAICase,
  runAICase,
  getAppConfigs,
  getAppDevices
} from '@/api/ui_automation'
import { useUnifiedProjects } from '@/utils/useUnifiedProjects'

const router = useRouter()
const { allProjects, loadProjects } = useUnifiedProjects()
const cases = ref([])
const loading = ref(false)
const searchText = ref('')
const total = ref(0)
const pagination = reactive({
  currentPage: 1,
  pageSize: 20
})

// 当前选中的统一项目（"ui_1" / "proj_2" / 空）
const selectedProject = ref('')

const appConfigs = ref([])
const devices = ref([])

const showEditDialog = ref(false)
const saving = ref(false)
const currentCaseId = ref(null)
const editForm = reactive({
  name: '',
  description: '',
  execution_mode: 'text',
  task_description: '',
  app_config: null,
  device: null,
  steps: []
})
const editFormRef = ref(null)

const formRules = {
  name: [{ required: true, message: '请输入用例名称', trigger: 'blur' }],
  execution_mode: [{ required: true, message: '请选择执行模式', trigger: 'change' }]
}

// 中性示例（业务无关，内容型 App 演示 extract + ${{key}} 上下文传递）
const NEUTRAL_EXAMPLE = [
  {
    action: 'launch',
    name: '启动应用',
    prompt: '',
    value: '',
    wait_ms: 3000,
    extract: [],
    assert: { prompt: '', expect: '' }
  },
  {
    action: 'aiTap',
    name: '进入内容列表',
    prompt: '点击首页的“推荐”入口',
    value: '',
    wait_ms: 1500,
    extract: [],
    assert: { prompt: '推荐列表已展示', expect: '' }
  },
  {
    action: 'aiTap',
    name: '打开第一条内容',
    prompt: '点击列表中第一条内容卡片',
    value: '',
    wait_ms: 1500,
    extract: [
      { key: 'contentTitle', prompt: '当前打开内容的标题是什么？', type: 'string', required: true }
    ],
    assert: { prompt: '', expect: '' }
  },
  {
    action: 'aiAct',
    name: '操作并使用上下文',
    prompt: '对标题为“${{contentTitle}}”的内容执行点赞操作',
    value: '',
    wait_ms: 1000,
    extract: [],
    assert: { prompt: '点赞状态已变为已点赞', expect: '' }
  }
]

const loadAppOptions = async () => {
  try {
    const params = { page_size: 200 }
    if (selectedProject.value) {
      params.project = selectedProject.value
    }
    const [cfgRes, devRes] = await Promise.all([
      getAppConfigs(params),
      getAppDevices({ page_size: 200 })
    ])
    appConfigs.value = cfgRes.data.results || []
    devices.value = devRes.data.results || []
  } catch (e) {
    console.error('加载应用/设备失败', e)
  }
}

// 切换项目时重新拉取该项目下的应用配置
const handleProjectChange = () => {
  loadAppOptions()
}

// 加载用例列表
const loadCases = async () => {
  loading.value = true
  try {
    const response = await getAICases({
      page: pagination.currentPage,
      page_size: pagination.pageSize,
      search: searchText.value
    })

    cases.value = response.data.results || []
    total.value = response.data.count || 0
  } catch (error) {
    console.error('获取用例列表失败:', error)
    ElMessage.error('获取用例列表失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  pagination.currentPage = 1
  loadCases()
}

const handleSizeChange = () => {
  pagination.currentPage = 1
  loadCases()
}

const handleCurrentChange = () => {
  loadCases()
}

const resetSteps = () => {
  editForm.steps = []
}

const addStep = () => {
  editForm.steps.push({
    action: 'aiTap',
    name: '',
    prompt: '',
    value: '',
    wait_ms: 0,
    extract: [],
    assert: { prompt: '', expect: '' }
  })
}

const removeStep = (idx) => {
  editForm.steps.splice(idx, 1)
}

const addExtract = (step) => {
  if (!step.extract) step.extract = []
  step.extract.push({ key: '', prompt: '', type: 'string', required: false })
}

const removeExtract = (step, ei) => {
  step.extract.splice(ei, 1)
}

const loadNeutralExample = () => {
  editForm.steps = JSON.parse(JSON.stringify(NEUTRAL_EXAMPLE))
  ElMessage.success('已载入中性示例步骤')
}

// 新建用例：打开空白对话框
const openCreate = () => {
  currentCaseId.value = null
  editForm.name = ''
  editForm.description = ''
  editForm.execution_mode = 'text'
  editForm.task_description = ''
  editForm.app_config = null
  editForm.device = null
  editForm.steps = []
  showEditDialog.value = true
}

// 编辑用例
const editCase = (row) => {
  currentCaseId.value = row.id
  editForm.name = row.name
  editForm.description = row.description
  editForm.execution_mode = row.execution_mode || 'text'
  editForm.task_description = row.task_description
  editForm.app_config = row.app_config || null
  editForm.device = row.device || null
  // 深拷贝 steps，确保每步都有 extract/assert 结构
  editForm.steps = Array.isArray(row.steps)
    ? row.steps.map(s => ({
        action: s.action || 'aiTap',
        name: s.name || '',
        prompt: s.prompt || '',
        value: s.value || '',
        wait_ms: s.wait_ms || 0,
        extract: (s.extract || []).map(e => ({ ...e })),
        assert: { prompt: (s.assert && s.assert.prompt) || '', expect: (s.assert && s.assert.expect) || '' }
      }))
    : []
  showEditDialog.value = true
}

const confirmEdit = async () => {
  if (!editFormRef.value) return

  await editFormRef.value.validate(async (valid) => {
    if (valid) {
      saving.value = true
      try {
        const payload = {
          name: editForm.name,
          description: editForm.description,
          execution_mode: editForm.execution_mode
        }
        if (editForm.execution_mode === 'text') {
          payload.task_description = editForm.task_description
        } else {
          payload.app_config = editForm.app_config
          payload.device = editForm.device
          // 清理空 extract/assert，保持数据干净
          payload.steps = editForm.steps.map(s => ({
            action: s.action,
            name: s.name,
            prompt: s.prompt,
            value: s.value,
            wait_ms: s.wait_ms || 0,
            extract: (s.extract || []).filter(e => e.key && e.prompt),
            assert: (s.assert && s.assert.prompt)
              ? { prompt: s.assert.prompt, expect: s.assert.expect }
              : null
          }))
        }

        if (currentCaseId.value) {
          await updateAICase(currentCaseId.value, payload)
          ElMessage.success('更新成功')
        } else {
          await createAICase(payload)
          ElMessage.success('创建成功')
        }

        showEditDialog.value = false
        loadCases()
      } catch (error) {
        console.error('保存失败:', error)
        ElMessage.error('保存失败')
      } finally {
        saving.value = false
      }
    }
  })
}

// 删除用例
const deleteCase = async (id) => {
  try {
    await ElMessageBox.confirm('确定要删除该用例吗?', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })

    await deleteAICase(id)
    ElMessage.success('删除成功')
    loadCases()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      ElMessage.error('删除失败')
    }
  }
}

// 执行用例
const runCase = async (row) => {
  try {
    await runAICase(row.id)
    ElMessage.success('用例开始执行')
    // 跳转到执行记录页面
    router.push('/ai-intelligent-mode/execution-records')
  } catch (error) {
    console.error('执行失败:', error)
    ElMessage.error('执行失败')
  }
}

const formatDate = (row, column, cellValue) => {
  if (!cellValue) return ''
  return new Date(cellValue).toLocaleString()
}

onMounted(() => {
  loadProjects()
  loadCases()
  loadAppOptions()
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
}

.card-container {
  background-color: #fff;
  border-radius: 4px;
  padding: 20px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.filter-bar {
  margin-bottom: 20px;
}

.pagination-container {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.steps-editor {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 12px;
  width: 100%;

  .steps-toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    flex-wrap: wrap;

    .hint {
      color: #909399;
      font-size: 12px;

      code {
        background: #f4f4f5;
        padding: 0 4px;
        border-radius: 3px;
        color: #c4561c;
      }
    }
  }

  .step-card {
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 12px;
    margin-bottom: 12px;
    background: #fafafa;

    .step-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;

      .step-no {
        font-weight: 600;
        color: #409eff;
      }
    }
  }

  .extract-list {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .extract-row {
      display: flex;
      align-items: center;
      gap: 8px;
    }
  }

  .assert-row {
    display: flex;
    gap: 8px;
  }
}
</style>
