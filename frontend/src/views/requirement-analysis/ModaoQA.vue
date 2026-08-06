<template>
  <div class="modao-qa">
    <div class="qa-head" @click="visible = !visible">
      <span>💬 疑点答疑（基于本阶段内容向 AI 提问）</span>
      <el-button size="small" type="text">{{ visible ? '收起 ▲' : '展开 ▼' }}</el-button>
    </div>
    <div v-show="visible" class="qa-body">
      <div v-for="(item, i) in list" :key="i" class="qa-item">
        <div class="qa-q"><b>问：</b>{{ item.question }}</div>
        <div class="qa-a"><b>答：</b><pre class="qa-ans">{{ item.answer }}</pre></div>
        <div v-if="item.ts" class="qa-ts">{{ item.ts }}</div>
      </div>
      <div v-if="!list.length" class="qa-empty">暂无答疑记录，在下方提问试试。</div>
      <el-input v-model="question" type="textarea" :rows="2"
        placeholder="对该阶段内容有疑问？输入问题，AI 将基于当前内容解答…" />
      <el-button size="small" type="primary" :loading="loading" class="mt" @click="send">发送提问</el-button>
    </div>
  </div>
</template>

<script>
import request from '@/utils/api'

export default {
  name: 'ModaoQA',
  props: {
    protoId: { type: [Number, String], required: true },
    stage: { type: Number, required: true },
    qaLog: { type: Array, default: () => [] },
  },
  data() {
    return { visible: false, question: '', loading: false, list: [] }
  },
  watch: {
    qaLog: { immediate: true, handler(v) { this.list = (v || []).slice() } },
  },
  methods: {
    base() { return '/requirement-analysis/api/modao' },
    async send() {
      const q = this.question.trim()
      if (!q) return
      this.loading = true
      try {
        const res = await request({
          url: `${this.base()}/${this.protoId}/ask/`, method: 'post',
          data: { stage: this.stage, question: q },
        })
        this.list = res.data.qa_log || []
        this.question = ''
        this.visible = true
      } catch (e) {
        this.$message.error('答疑失败：' + (e.response?.data?.detail || e.message))
      } finally {
        this.loading = false
      }
    },
  },
}
</script>

<style scoped>
.modao-qa { margin-top: 12px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fafbfc; }
.qa-head { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; cursor: pointer; font-size: 13px; color: #1f2937; }
.qa-body { padding: 0 12px 12px; }
.qa-item { border-top: 1px dashed #e5e7eb; padding: 8px 0; }
.qa-q { color: #1f2937; font-size: 13px; }
.qa-a { color: #374151; font-size: 13px; margin-top: 4px; }
.qa-ans { background: #fff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; margin: 4px 0 0; white-space: pre-wrap; font-family: inherit; font-size: 12.5px; line-height: 1.6; max-height: 320px; overflow: auto; }
.qa-ts { color: #9ca3af; font-size: 11px; margin-top: 4px; }
.qa-empty { color: #9ca3af; font-size: 12px; padding: 8px 0; }
.mt { margin-top: 8px; }
</style>
