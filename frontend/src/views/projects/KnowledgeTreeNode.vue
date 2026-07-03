<template>
  <template v-for="node in nodes" :key="node.path">
    <!-- 目录 -->
    <div v-if="node.type === 'directory'" class="kb-fs-dir" :style="{ paddingLeft: depth * 12 + 'px' }">
      <div class="kb-fs-dir-name" @click="toggleDir(node.path)">
        <el-icon><FolderOpened v-if="expandedDirs.has(node.path)" /><Folder v-else /></el-icon>
        {{ node.name }}
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
      :style="{ paddingLeft: depth * 12 + 'px' }"
      @click="$emit('selectFile', node)"
    >
      <el-icon><Document /></el-icon>
      <span class="kb-fs-file-name">{{ node.title || node.name }}</span>
    </div>
  </template>
</template>

<script setup>
import { FolderOpened, Folder, Document } from '@element-plus/icons-vue'

defineProps({
  nodes: { type: Array, required: true },
  expandedDirs: { type: Set, required: true },
  selectedFile: { type: String, default: '' },
  depth: { type: Number, default: 0 },
})

defineEmits(['toggleDir', 'selectFile'])
</script>
