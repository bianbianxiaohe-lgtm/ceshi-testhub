<template>
  <template v-for="node in nodes" :key="node.path">
    <!-- 目录 -->
    <div
      v-if="node.type === 'directory'"
      class="kb-fs-dir"
      :style="{ paddingLeft: depth * 12 + 'px' }"
    >
      <div
        class="kb-fs-dir-name"
        :class="{ active: expandedDirs.has(node.path) }"
        @click="toggleDir(node.path)"
      >
        <span class="kb-fs-dir-arrow" :class="{ expanded: expandedDirs.has(node.path) }">
          <el-icon :size="12"><CaretRight /></el-icon>
        </span>
        <span class="kb-fs-dir-icon">
          <el-icon v-if="expandedDirs.has(node.path)" :size="16" color="#e6a23c"><FolderOpened /></el-icon>
          <el-icon v-else :size="16" color="#e6a23c"><Folder /></el-icon>
        </span>
        <span class="kb-fs-dir-label">{{ node.name }}</span>
      </div>
      <div v-show="expandedDirs.has(node.path)" class="kb-fs-dir-children">
        <KnowledgeTreeNode
          v-if="node.children && node.children.length"
          :nodes="node.children"
          :expanded-dirs="expandedDirs"
          :selected-file="selectedFile"
          :depth="depth + 1"
          @toggle-dir="(path) => $emit('toggleDir', path)"
          @select-file="(node) => $emit('selectFile', node)"
        />
      </div>
    </div>

    <!-- 文件 -->
    <div
      v-else
      class="kb-fs-file"
      :class="{ active: selectedFile === node.path }"
      :style="{ paddingLeft: depth * 12 + 20 + 'px' }"
      @click="$emit('selectFile', node)"
    >
      <span class="kb-fs-file-icon">
        <el-icon :size="15" :color="isMarkdown(node.name) ? '#409eff' : '#909399'">
          <Document v-if="isMarkdown(node.name)" />
          <DocumentCopy v-else />
        </el-icon>
      </span>
      <span class="kb-fs-file-name">{{ node.title || node.name }}</span>
    </div>
  </template>
</template>

<script setup>
import { FolderOpened, Folder, Document, DocumentCopy, CaretRight } from '@element-plus/icons-vue'

defineProps({
  nodes: { type: Array, required: true },
  expandedDirs: { type: Set, required: true },
  selectedFile: { type: String, default: '' },
  depth: { type: Number, default: 0 },
})

defineEmits(['toggleDir', 'selectFile'])

const isMarkdown = (name) => name.toLowerCase().endsWith('.md')
</script>

<style scoped>
.kb-fs-dir {
  user-select: none;
}

.kb-fs-dir-name {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.kb-fs-dir-name:hover {
  background: #f0f2f5;
}

.kb-fs-dir-name.active {
  background: #f5f7fa;
}

.kb-fs-dir-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  color: #909399;
  transition: transform 0.2s;
}

.kb-fs-dir-arrow.expanded {
  transform: rotate(90deg);
}

.kb-fs-dir-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.kb-fs-dir-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.4;
}

.kb-fs-dir-children {
  padding-left: 0;
}

.kb-fs-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  font-size: 13px;
  color: #606266;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s, color 0.15s;
  user-select: none;
}

.kb-fs-file:hover {
  background: #ecf5ff;
}

.kb-fs-file.active {
  background: #d9ecff;
  color: #409eff;
  font-weight: 600;
}

.kb-fs-file.active .kb-fs-file-icon {
  color: #409eff;
}

.kb-fs-file-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.kb-fs-file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.4;
}
</style>
