<template>
  <div class="modao-list-page">
    <el-card class="history-card" shadow="never">
      <template #header>
        <div class="history-header">
          <span><b>📋 墨刀需求分析 · 任务列表</b>（点击「继续」进入画布工作页；状态为「部分读取」时，按钮变为「继续读取」，进入后点页面上的「继续读取（补齐剩余画布）」从断点续读）</span>
          <div class="history-filters">
            <el-select v-model="filterProject" size="small" clearable placeholder="选择项目" style="width:160px"
              :loading="loadingProjects" @change="onFilterProjectChange">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-select v-model="filterVersion" size="small" clearable placeholder="选择版本" style="width:160px"
              :disabled="!filterProject" @change="loadHistory">
              <el-option v-for="v in filterVersions" :key="v.id" :label="v.name" :value="v.id" />
            </el-select>
            <el-button size="small" @click="loadHistory" :loading="loadingHistory">刷新</el-button>
            <el-button size="small" type="primary" @click="onCreate">+ 新建需求任务</el-button>
          </div>
        </div>
      </template>
      <div v-if="history.length === 0 && !loadingHistory" class="empty-hint">
        暂无历史记录，点击右上角「新建需求任务」开始吧。
      </div>
      <el-table v-else :data="history" size="small" stripe style="width: 100%" row-key="id"
        :expand-row-keys="expandedRows" @row-click="toggleExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-detail">
              <div v-if="row.work_log" class="log-section">
                <h4>工作日志</h4>
                <pre class="log-box">{{ row.work_log }}</pre>
              </div>
              <div v-if="row.error_message" class="log-section error-section">
                <h4>错误信息</h4>
                <pre class="log-box error-box">{{ row.error_message }}</pre>
              </div>
              <div v-if="!row.work_log && !row.error_message" class="empty-hint" style="padding:8px 0">
                暂无工作日志
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column label="来源" width="90">
          <template #default="{ row }">{{ row.source_type === 'text' ? '需求文本' : row.source_type === 'webshare' ? 'webshare页面树' : '墨刀链接' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="120">
          <template #default="{ row }">阶段{{ row.current_stage }} · {{ stageLabel(row.current_stage) }}</template>
        </el-table-column>
        <el-table-column v-if="isAdmin" prop="created_by_name" label="创建人" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.created_by_name || '未知' }}</template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="160" />
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <!-- partial（读取超时但已保留部分画布）：按钮文案明确指向「进去补齐」，
                 避免用户误点旁边的「重走」把已读画布清空重来。 -->
            <el-button size="small" type="success" @click="onContinue(row)">
              {{ row.status === 'partial' ? '继续读取' : '继续' }}
            </el-button>
            <el-button v-if="row.source_type !== 'text'" size="small" type="warning" plain
              @click="onResetWorkflow(row)">重走</el-button>
            <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script>
import request from '@/utils/api'

export default {
  name: 'ModaoListView',
  data() {
    return {
      history: [],
      isAdmin: false,
      loadingHistory: false,
      expandedRows: [],
      projects: [],
      versions: [],
      loadingProjects: false,
      filterProject: null,
      filterVersion: null,
    }
  },
  computed: {
    filterVersions() {
      if (!this.filterProject) return []
      return this.versions.filter(v => v.project === this.filterProject || v.project_id === this.filterProject || String(v.project) === String(this.filterProject))
    },
  },
  methods: {
    // ⚠️ 必须带 `/api` 前缀（后端真实路由为 `api/requirement-analysis/`）。
    base() { return '/requirement-analysis/api/modao' },
    statusLabel(s) {
      // 注意：本列表与 ModaoSkillView.vue 各有一套 statusLabel/statusType，
      // 新增状态（如 partial）必须**两处同步**，否则列表会把原始英文值直接显示出来。
      const m = { pending: '待处理', extracting: '读取中', extracted: '已读取', partial: '部分读取', structuring: '结构化中', clarifying: '澄清中', designing: '用例设计中', done: '已完成', failed: '失败' }
      return m[s] || s
    },
    statusType(s) {
      const m = { pending: 'info', extracting: 'warning', extracted: 'success', partial: 'warning', structuring: 'warning', clarifying: 'warning', designing: 'warning', done: 'success', failed: 'danger' }
      return m[s] || 'info'
    },
    stageLabel(n) {
      const m = { 0: '原型接入', 1: '需求通读', 2: '需求澄清', 3: '用例设计', 4: '冒烟执行' }
      return m[n] || ''
    },
    async loadProjects() {
      this.loadingProjects = true
      try {
        const res = await request({ url: '/projects/all/', method: 'get' })
        this.projects = (Array.isArray(res.data) ? res.data : (res.data.results || []))
      } catch (e) {
        this.projects = []
      } finally {
        this.loadingProjects = false
      }
    },
    async loadHistory() {
      this.loadingHistory = true
      try {
        const params = {}
        if (this.filterProject) params.project = this.filterProject
        if (this.filterVersion) params.version = this.filterVersion
        const res = await request({ url: `${this.base()}/list/`, method: 'get', params })
        const data = res.data
        if (Array.isArray(data)) {
          this.history = data
          this.isAdmin = false
        } else {
          this.history = (data && data.results) || []
          this.isAdmin = !!(data && data.is_admin)
        }
      } catch (e) {
        this.$message.error('加载历史失败：' + (e.response?.data?.detail || e.message))
      } finally {
        this.loadingHistory = false
      }
    },
    async onFilterProjectChange(pid) {
      this.filterVersion = null
      this.versions = []
      if (!pid) {
        this.loadHistory()
        return
      }
      try {
        const res = await request({ url: `/versions/projects/${pid}/versions/`, method: 'get' })
        this.versions = res.data.results || res.data || []
      } catch (e) {
        this.versions = []
      }
      this.loadHistory()
    },
    toggleExpand(row) {
      const idx = this.expandedRows.indexOf(row.id)
      if (idx >= 0) {
        this.expandedRows.splice(idx, 1)
      } else {
        if (!row.work_log && !row.error_message) {
          request({ url: `${this.base()}/${row.id}/`, method: 'get' }).then(res => {
            const target = this.history.find(h => h.id === row.id)
            if (target) Object.assign(target, res.data)
          }).catch(() => {})
        }
        this.expandedRows.push(row.id)
      }
    },
    onContinue(row) {
      // partial（读取超时、已保留部分画布）：必须进 **工作页 ModaoCanvas**，
      // 那里才有「继续读取（补齐剩余画布）」按钮触发断点续读；
      // 画布看板（ModaoCanvasBoard）只有画布卡片，没有续读入口。
      // 其余状态维持原行为（看板），避免改变既有习惯。
      const name = row.status === 'partial' ? 'ModaoCanvas' : 'ModaoCanvasBoard'
      this.$router.push({ name, params: { id: row.id } })
    },
    onCreate() {
      // 新建任务进入 ModaoSkillView 空态（标题「新建需求任务」表单），
      // 而非画布看板——看板需要有效的数字 pk，传 'new' 会触发 loadDetail 404。
      this.$router.push({ name: 'ModaoCanvas', params: { id: 'new' } })
    },
    async onResetWorkflow(row) {
      try {
        await this.$confirm(
          `确认将「${row.title}」退回第一步并重新走完整流程？该任务的读取结果、结构化内容、澄清答案、测试点和用例将被清空；已采纳到用例库的数据不会删除。`,
          '重新走完整流程',
          { type: 'warning', confirmButtonText: '确认重走', cancelButtonText: '取消' }
        )
      } catch (e) { return }
      try {
        await request({ url: `${this.base()}/${row.id}/reset/`, method: 'post' })
        this.$message.success('已重置，正在重新读取…')
        // 重置后自动触发一次完整读取，等价于「重新走流程」，避免清空后停在空白看板页
        try {
          await request({ url: `${this.base()}/${row.id}/extract/`, method: 'post' })
        } catch (ex) {
          this.$message.warning('重置成功，但自动读取启动失败，请进入任务页手动点击「开始读取」')
        }
        // 跳转到带「开始读取」按钮的主工作页（ModaoSkillView），而非无按钮的画布看板页
        this.$router.push({ name: 'ModaoCanvas', params: { id: row.id } })
      } catch (e) {
        this.$message.error('重置失败：' + (e.response?.data?.detail || e.message))
      }
    },
    async onDelete(row) {
      try {
        await this.$confirm(`确认删除「${row.title}」？`, '提示', { type: 'warning' })
      } catch (e) { return }
      try {
        await request({ url: `${this.base()}/${row.id}/`, method: 'delete' })
        await this.loadHistory()
        this.$message.success('已删除')
      } catch (e) {
        this.$message.error('删除失败：' + (e.response?.data?.detail || e.message))
      }
    },
  },
  mounted() {
    this.loadProjects().then(() => this.loadHistory())
  },
}
</script>

<style scoped>
.modao-list-page {
  padding: 16px;
}
.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.history-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.empty-hint {
  color: #909399;
  font-size: 13px;
  padding: 12px 0;
}
.expand-detail {
  padding: 4px 8px;
}
.log-box {
  background: #f5f7fa;
  border-radius: 4px;
  padding: 8px;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
}
.error-box {
  background: #fef0f0;
  color: #f56c6c;
}
</style>
