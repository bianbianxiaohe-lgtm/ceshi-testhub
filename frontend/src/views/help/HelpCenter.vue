<template>
  <div class="help-center">
    <div class="help-header">
      <div class="help-header-inner">
        <div class="help-title">
          <el-icon class="title-icon"><Reading /></el-icon>
          <div>
            <h1>帮助中心</h1>
            <p>按业务线分列的操作文档 · 共 {{ docs.length }} 篇</p>
          </div>
        </div>
        <el-button @click="goHome">
          <el-icon><HomeFilled /></el-icon>
          返回首页
        </el-button>
      </div>
    </div>

    <div class="help-body">
      <aside class="help-nav">
        <div v-for="g in groups" :key="g.key" class="nav-group">
          <div class="nav-group-title">{{ g.label }}</div>
          <a
            v-for="d in g.items"
            :key="d.id"
            href="javascript:void(0)"
            class="nav-item"
            :class="{ active: d.id === currentId }"
            @click="selectDoc(d.id)"
          >
            <span class="nav-item-title">{{ d.title }}</span>
            <span v-if="d.updated" class="nav-item-date">{{ d.updated }}</span>
          </a>
        </div>
      </aside>

      <main class="help-main">
        <div v-if="!current" class="empty">暂无文档</div>
        <template v-else>
          <div class="doc-head">
            <h2 class="doc-title">{{ current.title }}</h2>
            <div class="doc-meta">
              <el-tag size="small" effect="light">{{ categoryLabel(current.category) }}</el-tag>
              <span v-if="current.updated">更新于 {{ current.updated }}</span>
            </div>
          </div>

          <div class="doc-layout">
            <div ref="bodyRef" class="md-body" v-html="html"></div>
            <div v-if="anchors.length" class="doc-toc">
              <div class="toc-title">本页目录</div>
              <a v-for="a in anchors" :key="a.id" :href="`#${a.id}`" class="toc-item">{{ a.text }}</a>
            </div>
          </div>
        </template>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import { Reading, HomeFilled } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const CATEGORY_LABELS = {
  ai: 'AI 用例生成',
  modao: '墨刀原型解析',
  other: '通用'
}

const files = import.meta.glob('./docs/*.md', { query: '?raw', import: 'default', eager: true })

const parseFrontmatter = (raw) => {
  const matched = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(raw)
  const meta = {}
  let body = raw
  if (matched) {
    body = raw.slice(matched[0].length)
    matched[1].split(/\r?\n/).forEach((line) => {
      const idx = line.indexOf(':')
      if (idx > 0) {
        meta[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
      }
    })
  }
  return { meta, body }
}

const docs = Object.entries(files)
  .map(([path, raw]) => {
    const { meta, body } = parseFrontmatter(raw)
    const id = path.split('/').pop().replace(/\.md$/, '')
    return {
      id,
      title: meta.title || id,
      category: meta.category || 'other',
      order: Number(meta.order) || 99,
      updated: meta.updated || '',
      desc: meta.desc || '',
      body
    }
  })
  .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title))

const groups = computed(() => {
  const map = new Map()
  docs.forEach((d) => {
    if (!map.has(d.category)) {
      map.set(d.category, [])
    }
    map.get(d.category).push(d)
  })
  return Array.from(map.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([key, items]) => ({ key, label: CATEGORY_LABELS[key] || key, items }))
})

const categoryLabel = (key) => CATEGORY_LABELS[key] || key

const currentId = ref(route.query.doc && docs.some((d) => d.id === route.query.doc) ? route.query.doc : docs[0]?.id)
const current = computed(() => docs.find((d) => d.id === currentId.value) || null)
const html = computed(() => (current.value ? marked.parse(current.value.body) : ''))

const bodyRef = ref(null)
const anchors = ref([])

const buildAnchors = () => {
  nextTick(() => {
    const el = bodyRef.value
    if (!el) return
    const list = []
    el.querySelectorAll('h2').forEach((h, i) => {
      const id = `sec-${i}`
      h.setAttribute('id', id)
      list.push({ id, text: h.textContent || '' })
    })
    anchors.value = list
  })
}

const selectDoc = (id) => {
  currentId.value = id
  router.replace({ path: '/help', query: { doc: id } })
}

watch(() => current.value?.id, buildAnchors)
onMounted(buildAnchors)

const goHome = () => {
  router.push('/home')
}
</script>

<style scoped lang="scss">
.help-center {
  min-height: 100vh;
  background: #f5f7fa;
}

.help-header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 18px 32px;
  position: sticky;
  top: 0;
  z-index: 10;
}

.help-header-inner {
  max-width: 1180px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.help-title {
  display: flex;
  align-items: center;
  gap: 12px;

  h1 {
    font-size: 20px;
    font-weight: 500;
    margin: 0;
    color: #2c3e50;
  }

  p {
    margin: 2px 0 0;
    font-size: 13px;
    color: #909399;
  }
}

.title-icon {
  font-size: 26px;
  color: #409eff;
}

.help-body {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 32px 64px;
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

.help-nav {
  flex: 0 0 220px;
  position: sticky;
  top: 92px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px;
}

.nav-group + .nav-group {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #f0f2f5;
}

.nav-group-title {
  font-size: 12px;
  color: #909399;
  padding: 0 8px 6px;
  font-weight: 500;
}

.nav-item {
  display: block;
  padding: 7px 8px;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
  text-decoration: none;

  &:hover {
    background: #ecf5ff;
    color: #409eff;
  }

  &.active {
    background: #ecf5ff;
    color: #409eff;
    font-weight: 500;
  }
}

.nav-item-title {
  display: block;
}

.nav-item-date {
  display: block;
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 2px;
}

.help-main {
  flex: 1 1 auto;
  min-width: 0;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 20px 28px 32px;
}

.doc-head {
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f2f5;
}

.doc-title {
  font-size: 18px;
  font-weight: 500;
  margin: 0 0 8px;
  color: #2c3e50;
}

.doc-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #909399;
}

.doc-layout {
  display: flex;
  gap: 24px;
  align-items: flex-start;
  margin-top: 16px;
}

.md-body {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 13px;
  color: #303133;
  line-height: 1.8;

  :deep(h1) {
    font-size: 20px;
    font-weight: 500;
    margin: 0 0 16px;
    scroll-margin-top: 96px;
  }

  :deep(h2) {
    font-size: 16px;
    font-weight: 500;
    margin: 28px 0 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid #f0f2f5;
    scroll-margin-top: 96px;
  }

  :deep(h3) {
    font-size: 14px;
    font-weight: 500;
    margin: 20px 0 8px;
    scroll-margin-top: 96px;
  }

  :deep(p) {
    margin: 0 0 10px;
  }

  :deep(ul),
  :deep(ol) {
    margin: 0 0 12px;
    padding-left: 22px;
  }

  :deep(li) {
    margin-bottom: 4px;
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 16px;
    font-size: 12.5px;
  }

  :deep(th),
  :deep(td) {
    border: 1px solid #e4e7ed;
    padding: 7px 10px;
    text-align: left;
    vertical-align: top;
  }

  :deep(th) {
    background: #fafafa;
    font-weight: 500;
    color: #606266;
    white-space: nowrap;
  }

  :deep(code) {
    font-family: ui-monospace, Consolas, monospace;
    font-size: 12px;
    background: #f4f4f5;
    padding: 1px 5px;
    border-radius: 4px;
    color: #476582;
  }

  :deep(blockquote) {
    margin: 10px 0 16px;
    padding: 8px 14px;
    background: #fdf6ec;
    border-left: 3px solid #e6a23c;
    color: #606266;

    p {
      margin: 0;
    }
  }

  :deep(strong) {
    font-weight: 500;
    color: #2c3e50;
  }

  :deep(hr) {
    border: none;
    border-top: 1px solid #f0f2f5;
    margin: 24px 0;
  }

  :deep(a) {
    color: #409eff;
    text-decoration: none;
  }
}

.doc-toc {
  flex: 0 0 160px;
  position: sticky;
  top: 152px;

  .toc-title {
    font-size: 12px;
    color: #909399;
    padding-bottom: 6px;
  }

  .toc-item {
    display: block;
    font-size: 12px;
    color: #606266;
    padding: 5px 0 5px 8px;
    border-left: 2px solid #e4e7ed;
    text-decoration: none;

    &:hover {
      color: #409eff;
      border-left-color: #409eff;
    }
  }
}

.empty {
  padding: 40px;
  text-align: center;
  color: #909399;
}

@media screen and (max-width: 1100px) {
  .doc-toc {
    display: none;
  }
}

@media screen and (max-width: 900px) {
  .help-body {
    padding: 16px;
    flex-direction: column;
  }

  .help-nav {
    position: static;
    flex: none;
    width: 100%;
  }
}
</style>
