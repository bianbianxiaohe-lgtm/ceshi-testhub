<template>
  <div class="midscene-web-playground">
    <div class="page-header">
      <h1>🚀 Midscene Web Playground</h1>
      <p class="subtitle">
        用自然语言调试 Web 页面操作，实时查看执行日志与页面截图；确认稳定后，再把验证过的 Prompt 沉淀到正式测试框架（AI 用例管理）。
      </p>
    </div>

    <div class="pg-layout">
      <!-- 左侧：控制面板 -->
      <div class="pg-panel">
        <el-form label-position="top">
          <el-form-item label="目标页面 URL">
            <el-input v-model="form.url" placeholder="https://example.com" clearable />
          </el-form-item>

          <el-form-item label="操作类型">
            <el-radio-group v-model="form.action">
              <el-radio value="aiAct">aiAct（自然语言执行）</el-radio>
              <el-radio value="aiTap">aiTap（点击）</el-radio>
              <el-radio value="aiInput">aiInput（输入）</el-radio>
              <el-radio value="aiQuery">aiQuery（提取）</el-radio>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="自然语言指令">
            <el-input
              v-model="form.prompt"
              type="textarea"
              :rows="4"
              placeholder="用语义描述，禁止写坐标！例如：点击右上角的「登录」按钮"
            />
            <div class="prompt-examples">
              <span class="examples-label">示例：</span>
              <el-tag
                v-for="ex in promptExamples"
                :key="ex"
                size="small"
                class="example-tag"
                @click="form.prompt = ex"
              >{{ ex }}</el-tag>
            </div>
          </el-form-item>

          <template v-if="form.action === 'aiInput'">
            <el-form-item label="定位提示（可选）">
              <el-input v-model="form.selector_hint" placeholder="aiInput 优先用此定位，如「搜索框」" />
            </el-form-item>
            <el-form-item label="输入值">
              <el-input v-model="form.value" placeholder="要输入到该输入框的内容" />
            </el-form-item>
          </template>

          <el-button
            type="primary"
            :loading="running"
            :disabled="!form.url || !form.prompt.trim()"
            @click="runPlayground"
          >
            {{ running ? '执行中...' : '▶ 执行' }}
          </el-button>
          <el-button
            type="success"
            :disabled="!form.prompt.trim()"
            @click="openSaveActionDialog"
          >
            保存为业务动作
          </el-button>
          <el-button
            type="warning"
            :disabled="!form.prompt.trim()"
            @click="openSaveStepDialog"
          >
            追加到用例
          </el-button>
        </el-form>

        <!-- 追加到用例对话框（沉淀为 midscene_web 结构化步骤） -->
        <el-dialog
          v-model="saveStepDialogVisible"
          title="追加到 AI 用例（固化步骤）"
          width="520px"
          :close-on-click-modal="false"
        >
          <el-form label-width="100px">
            <el-form-item label="目标用例" required>
              <el-select
                v-model="saveStepForm.ai_case_id"
                placeholder="选择要追加步骤的 Midscene Web 用例"
                filterable
                style="width: 100%"
              >
                <el-option
                  v-for="c in aiCases"
                  :key="c.id"
                  :label="c.name"
                  :value="c.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="步骤名">
              <el-input v-model="saveStepForm.name" placeholder="可选，留空自动编号" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="saveStepDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="savingStep" @click="saveStepToCase">追加</el-button>
          </template>
        </el-dialog>

        <!-- 保存为业务动作对话框 -->
        <el-dialog
          v-model="saveActionDialogVisible"
          title="保存为业务动作"
          width="480px"
          :close-on-click-modal="false"
        >
          <el-form label-width="100px">
            <el-form-item label="动作名" required>
              <el-input v-model="saveActionForm.name" placeholder="如 login / search-product（英文、唯一）" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="saveActionForm.description" type="textarea" :rows="2" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="saveActionDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="savingAction" @click="saveBusinessAction">保存</el-button>
          </template>
        </el-dialog>
      </div>

      <!-- 中间：执行日志 -->
      <div class="pg-logs">
        <div class="logs-title">执行日志</div>
        <div class="logs-content" v-if="logs.length">{{ logs.join('\n') }}</div>
        <div class="logs-content logs-empty" v-else>暂无日志，执行后可在此查看运行过程</div>
        <div v-if="resultError" class="result-error">{{ resultError }}</div>
      </div>

      <!-- 右侧：页面截图 -->
      <div class="pg-preview">
        <div class="preview-title">页面截图</div>
        <div class="preview-body">
          <img v-if="screenshot" :src="'data:image/png;base64,' + screenshot" class="preview-img" />
          <div v-else class="preview-empty">
            <el-icon :size="48"><Monitor /></el-icon>
            <p>执行后将在此显示页面截图</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Monitor } from '@element-plus/icons-vue'
import {
  createBusinessAction,
  saveMidsceneWebStep,
  getAICases
} from '@/api/ui_automation'
import api from '@/utils/api'

const promptExamples = [
  '点击右上角的「登录」按钮',
  '在搜索框中输入「软件测试」',
  '提取当前页面的商品名称与价格',
  '勾选列表中所有未完成的待办项',
  '展开页面左侧的导航菜单',
]

const form = reactive({
  url: '',
  action: 'aiAct',
  prompt: '',
  selector_hint: '',
  value: '',
})

const running = ref(false)
const screenshot = ref('')
const logs = ref([])
const resultError = ref('')

// 保存为业务动作
const saveActionDialogVisible = ref(false)
const savingAction = ref(false)
const saveActionForm = reactive({
  name: '',
  description: '',
  action: 'aiAct',
  prompt: '',
  selector_hint: '',
  value: '',
})

// 追加到 AI 用例
const saveStepDialogVisible = ref(false)
const savingStep = ref(false)
const saveStepForm = reactive({
  ai_case_id: null,
  name: '',
})
const aiCases = ref([])

const loadAICases = async () => {
  try {
    const res = await getAICases({ execution_mode: 'midscene_web' })
    aiCases.value = res.data?.results || res.data || []
  } catch (e) {
    console.error('加载 Midscene Web 用例失败', e)
  }
}

const runPlayground = async () => {
  running.value = true
  screenshot.value = ''
  logs.value = []
  resultError.value = ''
  try {
    const res = await api.post('/ui-automation/ai-cases/midscene-web-playground/', {
      url: form.url,
      action: form.action,
      prompt: form.prompt,
      selector_hint: form.selector_hint,
      value: form.value,
    })
    const data = res.data || {}
    screenshot.value = data.screenshot_base64 || ''
    logs.value = data.logs || []
    if (data.query_result !== undefined) {
      logs.value.push('[aiQuery 结果] ' + JSON.stringify(data.query_result))
    }
    if (data.status === 'failed') {
      resultError.value = data.error || '执行失败'
    } else {
      ElMessage.success('执行成功')
    }
  } catch (e) {
    console.error('Playground 执行失败', e)
    resultError.value = e.response?.data?.error || e.message
    ElMessage.error('执行失败: ' + (e.response?.data?.error || e.message))
  } finally {
    running.value = false
  }
}

const openSaveActionDialog = () => {
  saveActionForm.name = ''
  saveActionForm.description = ''
  saveActionForm.action = form.action
  saveActionForm.prompt = form.prompt
  saveActionForm.selector_hint = form.selector_hint || ''
  saveActionForm.value = form.value || ''
  saveActionDialogVisible.value = true
}

const saveBusinessAction = async () => {
  if (!saveActionForm.name.trim()) {
    ElMessage.warning('请填写动作名')
    return
  }
  if (!saveActionForm.prompt.trim()) {
    ElMessage.warning('请填写语义指令')
    return
  }
  savingAction.value = true
  try {
    await createBusinessAction({
      name: saveActionForm.name.trim(),
      description: saveActionForm.description,
      action: saveActionForm.action,
      prompt: saveActionForm.prompt,
      selector_hint: saveActionForm.selector_hint,
      value: saveActionForm.value,
      execution_mode: 'midscene_web',
    })
    ElMessage.success('已保存为业务动作: ' + saveActionForm.name.trim())
    saveActionDialogVisible.value = false
  } catch (e) {
    console.error('保存业务动作失败', e)
    ElMessage.error('保存失败: ' + (e.response?.data?.name?.[0] || e.response?.data?.message || e.message))
  } finally {
    savingAction.value = false
  }
}

const openSaveStepDialog = () => {
  saveStepForm.ai_case_id = null
  saveStepForm.name = ''
  loadAICases()
  saveStepDialogVisible.value = true
}

const saveStepToCase = async () => {
  if (!saveStepForm.ai_case_id) {
    ElMessage.warning('请先选择目标用例')
    return
  }
  savingStep.value = true
  try {
    const res = await saveMidsceneWebStep({
      ai_case_id: saveStepForm.ai_case_id,
      action: form.action,
      prompt: form.prompt,
      selector_hint: form.selector_hint || '',
      value: form.value || '',
      name: saveStepForm.name,
    })
    ElMessage.success(res.data?.message || '已追加到用例')
    saveStepDialogVisible.value = false
  } catch (e) {
    console.error('保存步骤失败', e)
    ElMessage.error('保存失败: ' + (e.response?.data?.error || e.message))
  } finally {
    savingStep.value = false
  }
}

onMounted(() => {})
</script>

<style lang="scss" scoped>
.midscene-web-playground {
  .page-header {
    margin-bottom: 16px;
    h1 { margin: 0 0 4px; font-size: 22px; }
    .subtitle { margin: 0; color: #888; font-size: 13px; }
  }
  .pg-layout {
    display: flex;
    gap: 16px;
    align-items: flex-start;
  }
  .pg-panel {
    flex: 1;
    min-width: 360px;
    max-width: 480px;
    background: #fff;
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  }
  .prompt-examples {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    .examples-label { color: #888; font-size: 12px; }
    .example-tag {
      cursor: pointer;
      user-select: none;
      &:hover { opacity: 0.8; }
    }
  }
  .pg-logs {
    flex: 1;
    min-width: 300px;
    margin-top: 0;
    .logs-title { font-weight: 600; margin-bottom: 6px; }
    .logs-content {
      background: #1e1e1e;
      color: #d4d4d4;
      padding: 10px;
      border-radius: 6px;
      font-size: 12px;
      max-height: 400px;
      overflow: auto;
      white-space: pre-wrap;
    }
    .logs-empty { color: #888; text-align: center; padding: 30px; }
    .result-error {
      margin-top: 8px;
      color: #f56c6c;
      font-size: 13px;
      font-weight: 500;
    }
  }
  .pg-preview {
    flex: 1;
    min-width: 320px;
    background: #fff;
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
    .preview-title { font-weight: 600; margin-bottom: 12px; }
    .preview-body { text-align: center; }
    .preview-img {
      max-width: 100%;
      border: 1px solid #eee;
      border-radius: 8px;
    }
    .preview-empty {
      height: 320px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: #bbb;
      border: 1px dashed #ddd;
      border-radius: 8px;
      p { margin-top: 10px; }
    }
  }
}
</style>
