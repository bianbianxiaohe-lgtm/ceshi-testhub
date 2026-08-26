<template>
  <div class="midscene-playground">
    <div class="page-header">
      <h1>🛝 Midscene Playground</h1>
      <p class="subtitle">
        用自然语言调试 APP 真机操作。确认稳定后，再把验证过的 Prompt 沉淀到正式测试框架（AI 用例管理）。
      </p>
    </div>

    <div class="pg-layout">
      <!-- 左侧：控制面板 -->
      <div class="pg-panel">
        <el-form label-position="top">
          <el-form-item label="应用配置">
            <el-select v-model="form.app_config_id" placeholder="选择应用" style="width: 100%">
              <el-option
                v-for="cfg in appConfigs"
                :key="cfg.id"
                :label="cfg.name + (cfg.package_name ? ' (' + cfg.package_name + ')' : '')"
                :value="cfg.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="执行设备">
            <el-select v-model="form.device_id" placeholder="选择设备" style="width: 100%">
              <el-option
                v-for="dev in devices"
                :key="dev.id"
                :label="dev.name + (dev.udid ? ' (' + dev.udid + ')' : '')"
                :value="dev.id"
              />
            </el-select>
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
              placeholder="用语义描述，禁止写坐标！例如：点击右下角的「我的」Tab，进入个人中心"
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
            <div class="prompt-warn">⚠️ 禁止写死像素/坐标（如 980,2100），否则换机型会失效，系统会拦截。</div>
          </el-form-item>

          <template v-if="form.action === 'aiInput'">
            <el-form-item label="定位提示（可选）">
              <el-input v-model="form.selector_hint" placeholder="aiInput 优先用此定位，如「搜索框」" />
            </el-form-item>
            <el-form-item label="输入值">
              <el-input v-model="form.value" placeholder="要输入到该输入框的内容" />
            </el-form-item>
          </template>

          <el-form-item>
            <el-checkbox v-model="form.launch_app">执行前先启动应用</el-checkbox>
          </el-form-item>

          <el-button
            type="primary"
            :loading="running"
            :disabled="!form.app_config_id || !form.device_id || !form.prompt.trim()"
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

        <!-- 追加到用例对话框（沉淀为 midscene 结构化步骤） -->
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
                placeholder="选择要追加步骤的 Midscene 用例"
                filterable
                style="width: 100%"
              >
                <el-option
                  v-for="c in aiCases"
                  :key="c.id"
                  :label="c.name + (c.execution_mode === 'midscene' ? '（midscene）' : '（text）')"
                  :value="c.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="步骤名">
              <el-input v-model="saveStepForm.name" placeholder="可选，留空自动编号" />
            </el-form-item>
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="将把当前操作类型与自然语言指令作为一条步骤追加到该用例；用例会自动切换为 midscene 模式。后续可直接执行该用例重放，无需重新试错。"
            />
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
          width="520px"
          :close-on-click-modal="false"
        >
          <el-form label-width="100px">
            <el-form-item label="动作名" required>
              <el-input
                v-model="saveActionForm.name"
                placeholder="如 login / select-product（英文、唯一）"
              />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="saveActionForm.description" placeholder="可选，业务动作说明" />
            </el-form-item>
            <el-form-item label="动作类型">
              <el-select v-model="saveActionForm.action" style="width: 100%">
                <el-option value="aiAct" label="aiAct（自然语言执行）" />
                <el-option value="aiTap" label="aiTap（点击）" />
                <el-option value="aiInput" label="aiInput（输入）" />
                <el-option value="aiQuery" label="aiQuery（提取）" />
                <el-option value="assert" label="assert（断言）" />
              </el-select>
            </el-form-item>
            <el-form-item label="语义指令">
              <el-input v-model="saveActionForm.prompt" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item label="定位提示">
              <el-input v-model="saveActionForm.selector_hint" placeholder="可选" />
            </el-form-item>
            <el-form-item label="输入值">
              <el-input v-model="saveActionForm.value" placeholder="aiInput 用，可选" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="saveActionDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="savingAction" @click="saveBusinessAction">保存</el-button>
          </template>
        </el-dialog>

        <div v-if="logs.length" class="pg-logs">
          <div class="logs-title">执行日志</div>
          <pre class="logs-content">{{ logs.join('\n') }}</pre>
        </div>
      </div>

      <!-- 右侧：截图回看 -->
      <div class="pg-preview">
        <div class="preview-title">真机截图</div>
        <div v-if="screenshot" class="preview-body">
          <img :src="screenshot" alt="screenshot" class="preview-img" />
        </div>
        <div v-else class="preview-empty">
          <el-icon :size="48"><Monitor /></el-icon>
          <p>执行后将在此显示真机截图</p>
        </div>
        <el-alert
          v-if="resultError"
          :title="'执行出错: ' + resultError"
          type="error"
          show-icon
          :closable="false"
          style="margin-top: 12px"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Monitor } from '@element-plus/icons-vue'
import {
  getAppConfigs,
  getAppDevices,
  getAICases,
  createBusinessAction,
  saveMidsceneStep
} from '@/api/ui_automation'
import api from '@/utils/api'

const appConfigs = ref([])
const devices = ref([])
const aiCases = ref([])

const form = reactive({
  app_config_id: null,
  device_id: null,
  action: 'aiAct',
  prompt: '',
  selector_hint: '',
  value: '',
  launch_app: true
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
  value: ''
})

// 追加到用例（沉淀为 midscene 结构化步骤）
const saveStepDialogVisible = ref(false)
const savingStep = ref(false)
const saveStepForm = reactive({
  ai_case_id: null,
  name: ''
})

const promptExamples = [
  '点击右下角的「我的」Tab，进入个人中心',
  '在顶部搜索框输入「天气」并搜索',
  '点击页面中间的「立即体验」按钮',
  '返回上一页'
]

const loadOptions = async () => {
  try {
    const [cfgRes, devRes, caseRes] = await Promise.all([
      getAppConfigs({ page_size: 200 }),
      getAppDevices({ page_size: 200 }),
      getAICases({ page_size: 200 })
    ])
    appConfigs.value = cfgRes.data.results || []
    devices.value = devRes.data.results || []
    aiCases.value = caseRes.data.results || []
  } catch (e) {
    console.error('加载应用/设备失败', e)
    ElMessage.error('加载应用配置或设备失败')
  }
}

const runPlayground = async () => {
  running.value = true
  screenshot.value = ''
  logs.value = []
  resultError.value = ''
  try {
    const res = await api.post('/ui-automation/ai-cases/midscene-playground/', {
      app_config_id: form.app_config_id,
      device_id: form.device_id,
      action: form.action,
      prompt: form.prompt,
      launch_app: form.launch_app
    }, {
      // 连真机执行（含 Midscene 首次自举 npm install）可能耗时数分钟，单独放宽超时
      timeout: 0
    })
    const data = res.data || {}
    screenshot.value = data.screenshot_base64 || ''
    logs.value = data.logs || []
    if (data.query_result !== undefined) {
      logs.value.push('[aiQuery 返回] ' + JSON.stringify(data.query_result))
    }
    if (data.status === 'failed') {
      resultError.value = data.error || '未知错误'
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
  // aiInput 时把当前表单的输入值与定位提示带上，避免清空丢失
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
    ElMessage.warning('语义指令不能为空')
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
      value: saveActionForm.value
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
  saveStepDialogVisible.value = true
}

const saveStepToCase = async () => {
  if (!saveStepForm.ai_case_id) {
    ElMessage.warning('请选择目标用例')
    return
  }
  savingStep.value = true
  try {
    const res = await saveMidsceneStep({
      ai_case_id: saveStepForm.ai_case_id,
      action: form.action,
      prompt: form.prompt,
      selector_hint: form.selector_hint || '',
      value: form.value || '',
      name: saveStepForm.name
    })
    ElMessage.success(res.data?.message || '已追加到用例步骤')
    saveStepDialogVisible.value = false
  } catch (e) {
    console.error('追加步骤失败', e)
    ElMessage.error('追加失败: ' + (e.response?.data?.error || e.message))
  } finally {
    savingStep.value = false
  }
}

onMounted(loadOptions)
</script>

<style lang="scss" scoped>
.midscene-playground {
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
  .prompt-warn {
    margin-top: 8px;
    font-size: 12px;
    color: #e6a23c;
  }
  .pg-logs {
    margin-top: 16px;
    .logs-title { font-weight: 600; margin-bottom: 6px; }
    .logs-content {
      background: #1e1e1e;
      color: #d4d4d4;
      padding: 10px;
      border-radius: 6px;
      font-size: 12px;
      max-height: 220px;
      overflow: auto;
      white-space: pre-wrap;
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
