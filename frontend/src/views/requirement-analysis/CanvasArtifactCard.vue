<template>
  <el-card class="artifact-card" :class="{ 'has-content': !!rawText }">
    <template #header>
      <div class="ac-head">
        <b>{{ icon }} {{ title }}</b>
        <div class="ac-actions">
          <template v-if="!editing">
            <span v-if="itemCount" class="ac-count">{{ itemCount }} 条</span>
            <el-button size="small" type="primary" plain @click="startEdit">✏️ 编辑</el-button>
          </template>
          <template v-else>
            <el-button size="small" @click="cancelEdit">取消</el-button>
            <el-button v-if="isJson" size="small" @click="formatDraft">格式化</el-button>
            <el-button size="small" type="primary" :loading="saving" @click="saveDraft">💾 保存</el-button>
          </template>
        </div>
      </div>
    </template>

    <!-- 编辑态：原文编辑（澄清保留逐条视图入口） -->
    <div v-if="editing" class="ac-edit">
      <el-alert v-if="!jsonValid" type="error" :closable="false" show-icon
        title="当前内容不是合法 JSON，保存会被后端拒绝" />
      <div class="ac-tip">
        编辑的是<b>本画布</b>的产物；保存后任务级合并视图会自动重算。
      </div>
      <el-input v-model="draft" type="textarea" :autosize="{ minRows: 10, maxRows: 26 }" class="ac-textarea" />
    </div>

    <!-- 澄清：逐条视图 + 人工结论 -->
    <div v-else-if="kind === 'clarify' && clarifyItems.length" class="ac-clarify">
      <div v-for="(it, i) in clarifyItems" :key="i" class="ci-item">
        <div class="ci-head">
          <el-tag size="mini" :type="typeTag(it.type)">{{ it.type || '待确认' }}</el-tag>
          <span class="ci-loc">{{ it.location || '未标注位置' }}</span>
          <el-tag v-if="it.evidence_valid === false" size="mini" type="warning">证据未匹配原文</el-tag>
          <el-tag v-if="(it.resolution || it.answer || '').trim()" size="mini" type="success">已填结论</el-tag>
        </div>
        <div v-if="it.evidence" class="ci-row"><label>原文依据</label><span>{{ it.evidence }}</span></div>
        <div v-if="it.issue || it.uncertainty" class="ci-row"><label>问题</label><span>{{ it.issue || it.uncertainty }}</span></div>
        <div v-if="it.suggested_question" class="ci-row"><label>建议提问</label><span>{{ it.suggested_question }}</span></div>
        <div v-if="it.impact" class="ci-row"><label>影响范围</label><span>{{ it.impact }}</span></div>
        <el-input v-model="clarifyReplies[i]" type="textarea" :rows="2" class="ci-input"
          placeholder="填写人工结论（保存后写入该条 resolution，供后续用例生成引用）" />
      </div>
      <el-button size="small" type="primary" :loading="saving" class="ci-save" @click="saveClarify">💾 保存全部结论</el-button>
    </div>

    <!-- 结构化卡片视图（测试点 / 用例 / 冒烟 / 其它 JSON） -->
    <div v-else-if="structuredItems.length" class="ac-structured">
      <div v-for="(item, i) in structuredItems" :key="i" class="obj-card">
        <div class="obj-no">#{{ i + 1 }}</div>
        <div class="obj-rows">
          <div v-for="(row, j) in flatten(item)" :key="j" class="obj-row">
            <label>{{ row[0] }}</label><span>{{ row[1] }}</span>
          </div>
        </div>
      </div>
      <div v-if="itemCount > structuredItems.length" class="ac-more">
        仅展示前 {{ structuredItems.length }} 条，共 {{ itemCount }} 条，完整内容请点「编辑」查看
      </div>
    </div>

    <pre v-else-if="rawText" class="stage-pre">{{ rawText }}</pre>
    <el-empty v-else description="尚未生成" :image-size="60" />
  </el-card>
</template>

<script>
import request from '@/utils/api'

/** 字段名 → 中文标签（未命中的字段直接显示原名） */
const FIELD_LABELS = {
  id: 'ID', case_id: '用例ID', module: '模块', feature_module: '功能模块',
  title: '标题', name: '名称', case_name: '用例名', description: '描述', desc: '描述',
  priority: '优先级', type: '类型', test_type: '测试类型', category: '分类',
  precondition: '前置条件', preconditions: '前置条件', pre_condition: '前置条件',
  steps: '步骤', test_steps: '步骤', expected: '预期结果', expected_result: '预期结果',
  pass_criteria: '通过标准', notes: '备注', remark: '备注', requirement_ref: '需求引用',
  location: '位置', evidence: '原文依据', issue: '问题', uncertainty: '不确定点',
  suggested_question: '建议提问', impact: '影响范围', resolution: '人工结论', answer: '结论',
  audit_kind: '审计类型', evidence_valid: '证据匹配', smoke: '冒烟', source: '来源',
  risk_level: '风险等级', tags: '标签', testcase: '用例', design_method: '设计方法',
  is_smoke: '冒烟用例', cover_points: '覆盖测试点', points: '测试点', content: '内容',
}

const MAX_STRUCTURED_ITEMS = 60

export default {
  name: 'CanvasArtifactCard',
  props: {
    /** 卡片标题 */
    title: { type: String, required: true },
    icon: { type: String, default: '' },
    /** 后端字段名（page_summary / page_clarification / ...） */
    field: { type: String, required: true },
    /** 原文 */
    raw: { type: [String, null], default: '' },
    /** text | clarify | json */
    kind: { type: String, default: 'json' },
    protoId: { type: [String, Number], required: true },
    pageId: { type: [String, Number], required: true },
  },
  data() {
    return {
      editing: false,
      draft: '',
      saving: false,
      clarifyItems: [],
      clarifyReplies: [],
    }
  },
  computed: {
    rawText() {
      return String(this.raw || '')
    },
    isJson() {
      return String(this.field).endsWith('_json')
    },
    jsonValid() {
      if (!this.isJson) return true
      const t = (this.draft || '').trim()
      if (!t) return true
      try { JSON.parse(t); return true } catch (e) { return false }
    },
    /** 解析出的 JSON 数组（用于条数统计与结构化展示） */
    parsedArray() {
      const t = this.rawText.trim()
      if (!t) return []
      try {
        const v = JSON.parse(t)
        if (Array.isArray(v)) return v
        if (v && Array.isArray(v.smoke_testcases)) return v.smoke_testcases
        if (v && Array.isArray(v.data)) return v.data
      } catch (e) { /* 非纯 JSON */ }
      return []
    },
    structuredItems() {
      if (this.kind === 'clarify') return []
      return this.parsedArray.filter(x => x && typeof x === 'object')
        .slice(0, MAX_STRUCTURED_ITEMS)
    },
    itemCount() {
      if (this.kind === 'clarify') return this.clarifyItems.length
      return this.parsedArray.length
    },
  },
  watch: {
    raw: {
      immediate: true,
      handler() { this.parseClarify() },
    },
  },
  methods: {
    base() {
      return '/requirement-analysis/api/modao'
    },
    lbl(k) {
      return FIELD_LABELS[k] || k
    },
    typeTag(t) {
      const m = { '模糊点': 'warning', '缺失点': 'danger', '边界点': 'info' }
      return m[t] || ''
    },
    /** 从原文解析澄清数组：纯 JSON / ```json 代码块 / 首个 [...] 片段，三种策略兼容 */
    _parseClarifyArray(raw) {
      const text = String(raw || '')
      if (!text.trim()) return []
      try {
        const v = JSON.parse(text)
        if (Array.isArray(v) && v.length) return v
      } catch (e) { /* 继续下一种策略 */ }
      const m = text.match(/```(?:json|yaml|yml)?\s*\n([\s\S]*?)(?:```|$)/i)
      if (m) {
        try {
          const v = JSON.parse(m[1].trim())
          if (Array.isArray(v) && v.length) return v
        } catch (e) { /* noop */ }
      }
      const arrMatch = text.match(/\[[\s\S]*?\](?=\s*[\n]|$)/)
      if (arrMatch) {
        try {
          const v = JSON.parse(arrMatch[0])
          if (Array.isArray(v) && v.length) return v
        } catch (e) { /* noop */ }
      }
      return []
    },
    /** 把新数组文本写回原文：纯 JSON 整体替换；markdown 包裹时只替换其中的 JSON 片段 */
    _replaceClarifyJsonInRaw(raw, newText) {
      const text = String(raw || '')
      if (!text.trim()) return newText
      try {
        const v = JSON.parse(text)
        if (Array.isArray(v)) return newText
      } catch (e) { /* 走片段替换 */ }
      const m = text.match(/```(?:json|yaml|yml)?\s*\n([\s\S]*?)(?:```|$)/i)
      if (m) {
        return text.slice(0, m.index) + m[0].replace(m[1], () => newText) + text.slice(m.index + m[0].length)
      }
      const arrMatch = text.match(/\[[\s\S]*?\](?=\s*[\n]|$)/)
      if (arrMatch) {
        return text.slice(0, arrMatch.index) + newText + text.slice(arrMatch.index + arrMatch[0].length)
      }
      return newText
    },
    parseClarify() {
      if (this.kind !== 'clarify') return
      const items = this._parseClarifyArray(this.rawText)
      if (items.length && items[0] && typeof items[0] === 'object') {
        this.clarifyItems = items
        this.clarifyReplies = items.map(it => (it && (it.resolution || it.answer)) || '')
      } else {
        this.clarifyItems = []
        this.clarifyReplies = []
      }
    },
    /** 把任意层级的对象摊平成 [标签, 值] 行，兼容 {module, testcase:{...}} 这类嵌套结构 */
    flatten(obj, prefix = '') {
      const out = []
      for (const [k, v] of Object.entries(obj || {})) {
        if (v === null || v === undefined || v === '') continue
        if (k === 'evidence_valid' && v === true) continue
        const label = (prefix ? prefix + ' · ' : '') + this.lbl(k)
        if (Array.isArray(v)) {
          const txt = v.map(x => (x && typeof x === 'object' ? JSON.stringify(x) : String(x))).join(' / ')
          if (txt) out.push([label, txt])
        } else if (typeof v === 'object') {
          out.push(...this.flatten(v, label))
        } else {
          out.push([label, String(v)])
        }
      }
      return out
    },
    startEdit() {
      this.draft = this.rawText
      this.editing = true
    },
    cancelEdit() {
      this.editing = false
      this.draft = ''
    },
    formatDraft() {
      try {
        this.draft = JSON.stringify(JSON.parse(this.draft), null, 2)
      } catch (e) {
        this.$message.warning('无法格式化：当前内容不是合法 JSON')
      }
    },
    saveDraft() {
      if (!this.jsonValid) {
        this.$message.error('内容不是合法 JSON，请先修正')
        return
      }
      this.saveValue(this.draft).then(ok => { if (ok) this.editing = false })
    },
    saveClarify() {
      if (!this.clarifyItems.length) return
      const items = this.clarifyItems.map((it, i) => ({
        ...it,
        resolution: String(this.clarifyReplies[i] || '').trim(),
      }))
      const value = this._replaceClarifyJsonInRaw(
        this.rawText, JSON.stringify(items, null, 2))
      this.saveValue(value).then(ok => { if (ok) this.clarifyReplies = items.map(it => it.resolution) })
    },
    async saveValue(value) {
      this.saving = true
      try {
        const res = await request({
          url: `${this.base()}/${this.protoId}/pages/${this.pageId}/edit/`,
          method: 'patch',
          data: { field: this.field, value },
        })
        const d = res.data || {}
        this.$message.success(d.detail || '已保存')
        if (d.stale_stages && d.stale_stages.length) {
          this.$message.warning('该画布下游产物基于旧内容，建议重跑对应阶段')
        }
        const g = d.gate
        if (g && g.approved && g.fingerprint_matches === false) {
          this.$message.warning('内容已变更，原「批准生成」已失效，需重新批准后再生成最终用例')
        }
        this.$emit('saved', d)
        return true
      } catch (e) {
        this.$message.error('保存失败：' + (e.response?.data?.detail || e.message))
        return false
      } finally {
        this.saving = false
      }
    },
  },
}
</script>

<style scoped lang="scss">
.artifact-card {
  margin-bottom: 14px;
  &.stage-current { border: 1px solid #409eff; box-shadow: 0 0 8px rgba(64,158,255,.25); }

  .ac-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .ac-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    .ac-count { color: #909399; font-size: 12px; }
  }
  .ac-edit {
    .ac-tip { font-size: 12px; color: #909399; margin: 8px 0; }
    .ac-textarea :deep(textarea) {
      font-family: Consolas, Monaco, 'Courier New', monospace;
      font-size: 12px;
      line-height: 1.6;
    }
  }
  .stage-pre {
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 360px;
    overflow: auto;
    background: #fafafa;
    padding: 10px;
    border-radius: 6px;
    font-size: 12px;
    margin: 0;
  }

  /* 澄清逐条 */
  .ci-item {
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 10px;
    background: #fcfcfd;
    .ci-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
    .ci-loc { font-size: 12px; color: #606266; font-weight: 600; }
    .ci-row {
      display: flex;
      gap: 8px;
      font-size: 12px;
      line-height: 1.7;
      label { flex: 0 0 60px; color: #909399; }
      span { flex: 1; color: #303133; word-break: break-word; }
    }
    .ci-input { margin-top: 8px; }
  }
  .ci-save { margin-bottom: 4px; }

  /* 结构化卡片 */
  .obj-card {
    display: flex;
    gap: 10px;
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 10px;
    background: #fcfcfd;
    .obj-no { flex: 0 0 34px; font-size: 12px; color: #c0c4cc; }
    .obj-rows { flex: 1; }
    .obj-row {
      display: flex;
      gap: 8px;
      font-size: 12px;
      line-height: 1.7;
      label { flex: 0 0 88px; color: #909399; }
      span { flex: 1; color: #303133; word-break: break-word; white-space: pre-wrap; }
    }
  }
  .ac-more { font-size: 12px; color: #909399; }
}
</style>
