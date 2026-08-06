<template>
  <div class="requirement-analysis">
    <div class="page-header">
      <h1>智能测试用例生成</h1>
      <p>基于需求描述或文档，AI将直接为您生成高质量的测试用例</p>
    </div>

    <!-- 配置引导弹出窗口 -->
    <div v-if="showConfigGuide && !checkingConfig" class="modal-overlay" @click.self="showConfigGuide = false" :key="modalKey">
      <div class="guide-config-modal">
      <div class="guide-header">
        <svg class="guide-icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
          <path d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm0 820c-205.4 0-372-166.6-372-372s166.6-372 372-372 372 166.6 372 372-166.6 372-372 372z" fill="#f59e0b"/>
          <path d="M464 336a48 48 0 1 0 96 0 48 48 0 1 0-96 0zm72 112h-48c-4.4 0-8 3.6-8 8v272c0 4.4 3.6 8 8 8h48c4.4 0 8-3.6 8-8V456c0-4.4-3.6-8-8-8z" fill="#f59e0b"/>
        </svg>
        <div class="guide-title">
          <h2>开始使用AI用例生成功能</h2>
          <p>在使用前，请先完成以下配置：</p>
        </div>
      </div>

      <div class="config-groups">
        <!-- 模型配置行 -->
        <div class="config-group">
          <div class="group-label">模型配置</div>
          <div class="config-items-row">
            <div class="config-item-inline" :class="getConfigItemClass('writer_model')">
              <span class="status-symbol" v-html="getStatusSymbol('writer_model')"></span>
              <span class="config-label">用例编写</span>
              <span class="config-name" v-if="configStatus.writer_model.name">{{ configStatus.writer_model.name }}</span>
              <span class="status-text" v-if="!configStatus.writer_model.configured">未配置</span>
              <span class="status-text warning" v-else-if="!configStatus.writer_model.enabled">已禁用</span>
            </div>

            <div class="config-item-inline" :class="getConfigItemClass('reviewer_model')">
              <span class="status-symbol" v-html="getStatusSymbol('reviewer_model')"></span>
              <span class="config-label">用例评审</span>
              <span class="config-name" v-if="configStatus.reviewer_model.name">{{ configStatus.reviewer_model.name }}</span>
              <span class="status-text" v-if="!configStatus.reviewer_model.configured">未配置</span>
              <span class="status-text warning" v-else-if="!configStatus.reviewer_model.enabled">已禁用</span>
            </div>
          </div>
        </div>

        <!-- 提示词配置行 -->
        <div class="config-group">
          <div class="group-label">提示词配置</div>
          <div class="config-items-row">
            <div class="config-item-inline" :class="getConfigItemClass('writer_prompt')">
              <span class="status-symbol" v-html="getStatusSymbol('writer_prompt')"></span>
              <span class="config-label">用例编写</span>
              <span class="config-name" v-if="configStatus.writer_prompt.name">{{ configStatus.writer_prompt.name }}</span>
              <span class="status-text" v-if="!configStatus.writer_prompt.configured">未配置</span>
              <span class="status-text warning" v-else-if="!configStatus.writer_prompt.enabled">已禁用</span>
            </div>

            <div class="config-item-inline" :class="getConfigItemClass('reviewer_prompt')">
              <span class="status-symbol" v-html="getStatusSymbol('reviewer_prompt')"></span>
              <span class="config-label">用例评审</span>
              <span class="config-name" v-if="configStatus.reviewer_prompt.name">{{ configStatus.reviewer_prompt.name }}</span>
              <span class="status-text" v-if="!configStatus.reviewer_prompt.configured">未配置</span>
              <span class="status-text warning" v-else-if="!configStatus.reviewer_prompt.enabled">已禁用</span>
            </div>
          </div>
        </div>

        <!-- 生成行为配置行 -->
        <div class="config-group">
          <div class="group-label">生成行为配置</div>
          <div class="config-items-row">
            <div class="config-item-inline" :class="getConfigItemClass('generation_config')">
              <span class="status-symbol" v-html="getStatusSymbol('generation_config')"></span>
              <span class="config-label">生成配置</span>
              <span class="config-name" v-if="configStatus.generation_config && configStatus.generation_config.name">{{ configStatus.generation_config.name }}</span>
              <span class="status-text" v-if="!configStatus.generation_config || !configStatus.generation_config.configured">未配置</span>
            </div>
          </div>
        </div>
      </div>

        <div class="guide-actions">
          <button class="generate-manual-btn" @click="goToConfig">
            去配置
          </button>
          <div class="skip-action" @click="showConfigGuide = false">
            稍后配置
          </div>
        </div>
      </div>
    </div>

    <!-- 输出模式选择器 - 全局设置 -->
    <div class="output-mode-section" v-if="!isGenerating && !showResults">
      <div class="output-mode-card">
        <h3>📤 输出模式设置</h3>
        <p class="mode-section-desc">选择测试用例生成的输出方式（适用于手动输入和文档上传两种方式）</p>
        <div class="output-mode-selector">
          <label class="mode-option" :class="{ active: globalOutputMode === 'stream' }">
            <input type="radio" v-model="globalOutputMode" value="stream">
            <div class="mode-content">
              <div class="mode-title">⚡ 实时流式输出</div>
              <div class="mode-desc">内容逐字显示，体验流畅，适合大需求文档</div>
            </div>
          </label>
          <label class="mode-option" :class="{ active: globalOutputMode === 'complete' }">
            <input type="radio" v-model="globalOutputMode" value="complete">
            <div class="mode-content">
              <div class="mode-title">📄 完整输出</div>
              <div class="mode-desc">完成后一次性展示，适合简单需求</div>
            </div>
          </label>
        </div>
      </div>
    </div>

    <div class="main-content">
      <!-- 手动输入需求描述区域 -->
      <div class="manual-input-section" v-if="!isGenerating && !showResults">
        <div class="manual-input-card">
          <h2>✍️ 手动输入需求描述</h2>
          <div class="input-form">
            <div class="form-group">
              <label>需求标题 <span class="required">*</span></label>
              <input 
                v-model="manualInput.title" 
                type="text" 
                class="form-input"
                placeholder="请输入需求标题，如：用户登录功能需求">
            </div>
            
            <div class="form-group">
              <label>需求描述 <span class="required">*</span></label>
              <textarea 
                v-model="manualInput.description" 
                class="form-textarea"
                rows="8"
                placeholder="请详细描述您的需求，包括功能描述、使用场景、业务流程等。例如：&#10;&#10;1. 用户可以通过用户名和密码登录系统&#10;2. 系统需要验证用户身份&#10;3. 登录成功后跳转到主页面&#10;4. 支持记住登录状态&#10;5. 登录失败要给出明确提示..."></textarea>
              <div class="char-count">{{ manualInput.description.length }}/2000</div>
            </div>
            
            <div class="form-group">
              <label>关联项目（可选）</label>
              <select v-model="manualInput.selectedProject" class="form-select">
                <option value="">请选择项目</option>
                <option v-for="project in projects" :key="project.id" :value="project.id">
                  {{ project.name }}
                </option>
              </select>
            </div>

            <div class="form-group">
              <label>关联版本（可选）</label>
              <div class="version-select-row">
                <select v-model="selectedVersion" class="form-select version-select">
                  <option value="">不关联版本</option>
                  <option v-for="ver in availableVersions" :key="ver.id" :value="ver.id">
                    {{ ver.name }}{{ ver.is_baseline ? ' (基线)' : '' }}
                  </option>
                </select>
                <button class="quick-create-ver-btn" @click="openQuickCreateVersion(manualInput.selectedProject)" title="快速新建版本">+</button>
              </div>
            </div>

            <button
              class="generate-manual-btn"
              @click="generateFromManualInput"
              :disabled="!canGenerateManual || isGenerating || (currentResultId && hasUnconfirmedItems)"
              :title="(currentResultId && hasUnconfirmedItems) ? '请先在拆解结果中逐项确认所有待确认项' : ''">
              <span v-if="isGenerating">🔄 生成中...</span>
              <span v-else>🚀 生成测试用例</span>
            </button>
            <div v-if="currentResultId && hasUnconfirmedItems" class="gen-gate-hint">
              ⚠️ 拆解结果有 {{ uncertainItems.filter(i => !i.confirmed).length }} 条待确认项未确认，请先在上方逐项确认后再生成测试用例
            </div>

            <button
              class="analyze-btn"
              @click="analyzeRequirement"
              :disabled="analyzeLoading || (!manualInput.description.trim() && analyzeImages.length === 0)">
              <span v-if="analyzeLoading">🔄 拆解中...</span>
              <span v-else>🧩 需求拆解</span>
            </button>

            <!-- 需求截图上传（多模态分析） -->
            <div class="form-group analyze-image-group" v-if="!analyzeResult">
              <label>需求截图（可选，支持多模态分析）</label>
              <input
                type="file"
                accept="image/*"
                multiple
                class="form-input"
                @change="onAnalyzeImageChange">
              <div class="analyze-image-list" v-if="analyzeImages.length">
                <div class="analyze-image-item" v-for="(img, idx) in analyzeImages" :key="idx">
                  <img :src="img" alt="需求截图" />
                  <button class="analyze-image-remove" @click="removeAnalyzeImage(idx)" title="移除">×</button>
                </div>
              </div>
            </div>

          </div>
        </div>
      </div>

      <!-- 拆解结果（独立区域，不受输入区显隐控制） -->
      <div class="analyze-result-card" v-if="analyzeResult">
        <div class="analyze-result-header">
          <h3>🧩 需求拆解结果</h3>
          <div class="analyze-result-actions">
            <button :class="['analyze-action-btn', { active: isEditingResult }]" @click="isEditingResult = !isEditingResult" :title="isEditingResult ? '预览模式' : '编辑内容'">
              {{ isEditingResult ? '👁️ 预览' : '✏️ 编辑' }}
            </button>
            <button class="analyze-action-btn" @click="copyAnalyzeResult">📋 复制</button>
            <button class="analyze-action-btn primary" @click="showMatrixModal = true" title="查看结构化插接矩阵">📊 插接矩阵</button>
            <button class="analyze-action-btn primary" @click="toggleDeepQuestion">💬 深度追问</button>
            <button class="analyze-action-btn close" @click="analyzeResult = ''">收起 ✕</button>
          </div>
        </div>
        <div class="analyze-result-body">
          <!-- 编辑模式：可编辑文本框 -->
          <textarea v-if="isEditingResult"
            v-model="analyzeResult"
            class="result-edit-textarea"
            spellcheck="false"
            placeholder="在此编辑拆解结果..."></textarea>
          <!-- 预览模式：Markdown 渲染 -->
          <div v-else class="markdown-body" v-html="formatMarkdown(analyzeResult)"></div>
        </div>

        <!-- ⚠️ 待确认项确认弹窗（对齐 AI 用例评审 uncertain_items 逐项确认） -->
        <div v-if="uncertainItems.length" class="analyze-uncertain-trigger">
          <el-alert
            :title="`⚠️ 拆解结果有 ${uncertainItems.length} 条待确认项，请逐项确认后再生成测试用例（已确认 ${uncertainItems.filter(i => i.confirmed).length}/${uncertainItems.length}）`"
            type="warning"
            :closable="false"
            show-icon
            @click="showUncertainDialog = true"
            class="au-trigger-alert"
            style="cursor:pointer"
          />
        </div>

        <el-dialog
          v-model="showUncertainDialog"
          title="⚠️ 待确认项 — 逐一确认"
          width="720px"
          :close-on-click-modal="false"
          append-to-body
          destroy-on-close
          class="au-dialog">
          <template #header>
            <div style="display:flex;align-items:center;gap:10px">
              <span>⚠️ 待确认项</span>
              <el-tag type="warning" size="small">{{ uncertainItems.filter(i => !i.confirmed).length }} 条待确认</el-tag>
              <el-tag type="success" size="small" v-if="uncertainItems.some(i => i.confirmed)">{{ uncertainItems.filter(i => i.confirmed).length }} 条已确认</el-tag>
            </div>
          </template>
          <el-alert title="以下内容 AI 无法 100% 确定，请逐项确认后点击「✅ 全部确认并继续」" type="warning" :closable="false" style="margin-bottom:16px" />

          <div class="au-list">
            <div v-for="(item, idx) in uncertainItems" :key="item.id" :class="['au-item', { confirmed: item.confirmed }]">
              <div class="au-header">
                <el-tag :type="item.confirmed ? 'success' : 'warning'" size="small">待确认 {{ idx + 1 }}</el-tag>
                <span class="au-question">{{ item.question }}</span>
                <el-button v-if="!item.confirmed" type="primary" size="small" plain @click="item.confirmed = true">✓ 确认</el-button>
                <el-tag v-else type="success" size="small">已确认 ✓</el-tag>
              </div>
              <div v-if="item.context" class="au-context"><strong>AI 推测：</strong>{{ item.context }}</div>
              <el-input
                v-model="item.answer"
                type="textarea"
                :rows="2"
                placeholder="回复此问题（可选，留空则采纳 AI 推测）"
                style="margin-top:8px"
              />
            </div>
          </div>

          <template #footer>
            <el-button @click="showUncertainDialog = false">稍后处理</el-button>
            <el-button
              type="primary"
              :loading="refining"
              :disabled="!uncertainItems.some(i => i.confirmed)"
              @click="refineAndClose">
              ✅ {{ refining ? '精炼中...' : `确认并继续（${uncertainItems.filter(i => i.confirmed).length}/${uncertainItems.length}）` }}
            </el-button>
          </template>
        </el-dialog>

        <!-- 深度追问 Q&A 面板 -->
        <div v-if="showDeepQuestion" class="deep-question-panel">
          <!-- 模式切换 + 操作栏 -->
          <div class="qa-toolbar">
            <div class="qa-mode-tabs">
              <button :class="['qa-tab', { active: qaMode === 'table' }]" @click="switchQAMode('table')">
                📋 追问清单
              </button>
              <button :class="['qa-tab', { active: qaMode === 'chat' }]" @click="switchQAMode('chat')">
                💬 对话模式
              </button>
            </div>
            <div class="qa-actions">
              <button class="qa-action-btn" @click="generateClarificationQuestions" :disabled="qaGenerating || !analyzeResult" title="AI 重新生成追问">
                {{ qaGenerating ? '生成中...' : '🔄 重新生成' }}
              </button>
              <button class="qa-action-btn primary" @click="addManualQuestion" title="手动添加问题">+ 新增提问</button>
            </div>
          </div>

          <!-- ===== 表格模式：结构化 Q&A ===== -->
          <div v-if="qaMode === 'table'" class="qa-table-wrapper">
            <!-- 加载态 -->
            <div v-if="qaGenerating && clarificationItems.length === 0" class="qa-loading">
              <i class="el-icon-loading"></i> AI 正在分析需求，生成深度追问...
            </div>

            <!-- 空状态 -->
            <div v-else-if="clarificationItems.length === 0" class="qa-empty">
              <p>暂无追问项。点击「🔄 重新生成」让 AI 基于拆解结果自动生成追问清单。</p>
            </div>

            <!-- Q&A 表格 -->
            <div v-else class="qa-table">
              <!-- 表头 -->
              <div class="qa-table-header">
                <span class="col-q"># 问题</span>
                <span class="col-cat">分类</span>
                <span class="col-ans">人工回复 / 确认</span>
                <span class="col-status">状态</span>
                <span class="col-action">操作</span>
              </div>
              <!-- 行 -->
              <div v-for="(item, idx) in clarificationItems" :key="item.id"
                   :class="['qa-row', { confirmed: item.status === 'confirmed' }]">
                <!-- 问题列 -->
                <div class="col-q">
                  <span class="q-index">{{ idx + 1 }}</span>
                  <span class="q-text">{{ item.question }}</span>
                </div>
                <!-- 分类标签 -->
                <div class="col-cat">
                  <span :class="['cat-tag', `cat-${item.category}`]">{{ item.category }}</span>
                </div>
                <!-- 回复输入 -->
                <div class="col-ans">
                  <textarea
                    v-model="item.answer"
                    class="qa-answer-input"
                    placeholder="输入你的回复或确认..."
                    rows="2"
                    @input="item.status = item.answer.trim() ? 'answered' : 'pending'"
                    @blur="saveClarifications()"
                  ></textarea>
                </div>
                <!-- 状态 -->
                <div class="col-status">
                  <span :class="['status-dot', item.status]"></span>
                  <span class="status-label">{{ statusText(item.status) }}</span>
                </div>
                <!-- 操作 -->
                <div class="col-action">
                  <button
                    v-if="item.status !== 'confirmed'"
                    class="qa-confirm-btn"
                    :disabled="!item.answer.trim()"
                    @click="confirmAnswer(item.id)"
                    title="确认此回答"
                  >✓ 确认</button>
                  <span v-else class="confirmed-badge">已确认 ✓</span>
                  <button class="qa-delete-btn" @click="removeQAItem(item.id)" title="删除">✕</button>
                </div>
              </div>

              <!-- 统计栏 -->
              <div class="qa-summary">
                共 {{ clarificationItems.length }} 条追问 ·
                已回复 {{ clarificationItems.filter(i => i.status !== 'pending').length }} 条 ·
                已确认 {{ clarificationItems.filter(i => i.status === 'confirmed').length }} 条
              </div>
            </div>
          </div>

          <!-- ===== 聊天模式（保留原功能）===== -->
          <div v-else class="deep-question-messages" ref="deepQuestionScroll">
            <div v-for="(msg, idx) in deepChatMessages" :key="idx"
              :class="['chat-msg', msg.role]">
              <div class="chat-msg-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
              <div class="chat-msg-content markdown-body" v-html="msg.role === 'assistant' ? formatMarkdown(msg.content) : escapeHtml(msg.content)"></div>
            </div>
            <div v-if="deepChatLoading" class="chat-msg assistant">
              <div class="chat-msg-avatar">🤖</div>
              <div class="chat-msg-content streaming">
                <span class="typing-cursor"></span><span v-html="formatMarkdown(deepStreamingContent)"></span>
              </div>
            </div>
          </div>
          <div v-if="qaMode === 'chat'" class="deep-question-input-row">
            <input type="text" v-model="deepQuestionInput" class="deep-q-input"
              placeholder="输入追问问题..."
              @keydown.enter.exact="sendDeepQuestion"
              :disabled="deepChatLoading" />
            <button class="deep-q-send-btn" @click="sendDeepQuestion" :disabled="deepChatLoading || !deepQuestionInput.trim()">
              {{ deepChatLoading ? '思考中...' : '发送' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 分隔线 -->
      <div class="divider" v-if="!isGenerating && !showResults">
        <span>或</span>
      </div>

      <!-- 文档上传区域 -->
      <div class="upload-section" v-if="!isGenerating && !showResults">
        <div class="upload-card">
          <h2>📄 上传需求文档</h2>
          <div class="upload-area" 
               @dragover.prevent 
               @drop="handleDrop"
               :class="{ 'drag-over': isDragOver }"
               @dragenter="isDragOver = true"
               @dragleave="isDragOver = false">
            <div v-if="!selectedFile" class="upload-placeholder">
              <i class="upload-icon">📁</i>
              <p>拖拽文件到此处或点击选择文件</p>
              <p class="upload-hint">支持 PDF、Word、TXT、Markdown 格式</p>
              <input 
                type="file" 
                ref="fileInput" 
                @change="handleFileSelect"
                accept=".pdf,.doc,.docx,.txt,.md"
                style="display: none;">
              <button class="select-file-btn" @click="$refs.fileInput.click()">
                选择文件
              </button>
            </div>
            
            <div v-else class="file-selected">
              <div class="file-info">
                <i class="file-icon">📄</i>
                <div class="file-details">
                  <p class="file-name">{{ selectedFile.name }}</p>
                  <p class="file-size">{{ formatFileSize(selectedFile.size) }}</p>
                </div>
                <button class="remove-file" @click="removeFile">❌</button>
              </div>
            </div>
          </div>

          <div v-if="selectedFile" class="document-info">
            <div class="form-group">
              <label>文档标题</label>
              <input 
                v-model="documentTitle" 
                type="text" 
                class="form-input"
                placeholder="请输入文档标题">
            </div>
            
            <div class="form-group">
              <label>关联项目（可选）</label>
              <select v-model="selectedProject" class="form-select">
                <option value="">请选择项目</option>
                <option v-for="project in projects" :key="project.id" :value="project.id">
                  {{ project.name }}
                </option>
              </select>
            </div>

            <div class="form-group">
              <label>关联版本（可选）</label>
              <div class="version-select-row">
                <select v-model="selectedVersion" class="form-select version-select">
                  <option value="">不关联版本</option>
                  <option v-for="ver in availableVersions" :key="ver.id" :value="ver.id">
                    {{ ver.name }}{{ ver.is_baseline ? ' (基线)' : '' }}
                  </option>
                </select>
                <button class="quick-create-ver-btn" @click="openQuickCreateVersion(selectedProject)" title="快速新建版本">+</button>
              </div>
            </div>

            <button
              class="generate-btn"
              @click="generateFromDocument"
              :disabled="!documentTitle || isGenerating || (currentResultId && hasUnconfirmedItems)"
              :title="(currentResultId && hasUnconfirmedItems) ? '请先在拆解结果中逐项确认所有待确认项' : ''">
              <span v-if="isGenerating">🔄 生成中...</span>
              <span v-else>🚀 生成测试用例</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 分隔线2 -->
      <div class="divider" v-if="!isGenerating && !showResults">
        <span>或</span>
      </div>

      <!-- 需求文档生成区域（后门流程） -->
      <div class="req-doc-section" v-if="!isGenerating && !showResults">
        <div class="req-doc-card">
          <div class="req-doc-header">
            <h2>📋 需求文档生成</h2>
            <p class="req-doc-desc">将原始需求文案整理成结构化 Markdown 文档，再直接喂入 AI 生成测试用例</p>
          </div>

          <!-- 输入方式 Tab 切换 -->
          <div class="rd-tabs" v-if="!reqDoc.markdown">
            <button
              :class="['rd-tab', { active: reqDoc.inputMode === 'text' }]"
              @click="reqDoc.inputMode = 'text'">
              ✏️ 粘贴文字
            </button>
            <button
              :class="['rd-tab', { active: reqDoc.inputMode === 'file' }]"
              @click="reqDoc.inputMode = 'file'">
              📁 上传文件
            </button>
          </div>

          <!-- 文字输入模式 -->
          <div class="form-group rd-text-input" v-if="!reqDoc.markdown && reqDoc.inputMode === 'text'">
            <textarea
              v-model="reqDoc.rawText"
              class="form-textarea"
              rows="7"
              placeholder="粘贴需求文案、产品说明、功能描述等原始文字，AI 将帮你整理成标准格式的需求文档…"></textarea>
          </div>

          <!-- 文件上传模式 -->
          <div class="rd-upload-zone" v-if="!reqDoc.markdown && reqDoc.inputMode === 'file'">
            <!-- 隐藏的文件选择 input（多文件） -->
            <input
              type="file"
              ref="reqDocFileInput"
              @change="handleReqDocFileSelect"
              accept=".pdf,.doc,.docx,.txt,.md"
              multiple
              style="display: none">
            <!-- 隐藏的文件夹选择 input（webkitdirectory） -->
            <input
              type="file"
              ref="reqDocFolderInput"
              @change="handleReqDocFolderSelect"
              accept=".pdf,.doc,.docx,.txt,.md"
              webkitdirectory
              directory
              multiple
              style="display: none">

            <!-- 上传入口（两个入口：文件 / 文件夹） -->
            <div class="rd-upload-entries">
              <div class="rd-drop-zone" @click.stop.prevent="$refs.reqDocFileInput.click()">
                <div class="rd-drop-icon">📄</div>
                <p class="rd-drop-title">选择文件</p>
                <p class="rd-drop-hint">支持 PDF / Word / TXT / MD</p>
              </div>
              <div class="rd-drop-zone rd-folder-zone" @click.stop.prevent="$refs.reqDocFolderInput.click()">
                <div class="rd-drop-icon">📁</div>
                <p class="rd-drop-title">选择文件夹</p>
                <p class="rd-drop-hint">读取文件夹内所有文档合并</p>
              </div>
            </div>

            <!-- 已选文件列表（按文件夹分组） -->
            <div v-if="reqDoc.files.length" class="rd-file-list">
              <template v-for="(group, gIdx) in fileGroups" :key="'g'+gIdx">
                <!-- 文件夹标题行 -->
                <div v-if="group.isFolder" class="rd-folder-header">
                  <span class="rd-folder-icon">📁</span>
                  <span class="rd-folder-name">{{ group.name }}</span>
                  <span class="rd-folder-count">{{ group.items.length }} 个文件</span>
                  <button class="rd-folder-clear" @click="removeFolder(gIdx)" :disabled="group.items.some(f => f.extracting)">✕</button>
                </div>
                <!-- 文件条目 -->
                <div
                  v-for="(f, i) in group.items"
                  :key="'gf'+gIdx+'f'+i"
                  :class="['rd-file-item', { 'rd-file-sub': group.isFolder }]">
                  <span class="rd-file-icon">📄</span>
                  <span class="rd-file-name" :title="f.file.webkitRelativePath || f.file.name">{{ f.file.name }}</span>
                  <span v-if="f.extracting" class="rd-extract-status extracting">⏳ 提取中…</span>
                  <span v-else-if="f.error" class="rd-extract-status error" :title="f.error">❌ 失败</span>
                  <span v-else-if="f.isImagePdf" class="rd-extract-status image-pdf">📷 图片型PDF · AI视觉识别</span>
                  <span v-else-if="f.extracted" class="rd-extract-status done">✅ 文字已提取</span>
                  <button class="rd-file-clear" @click="removeReqDocFile(gIdx, i)" :disabled="f.extracting">✕</button>
                </div>
              </template>

              <!-- 无文件夹归属的单独文件 -->
              <template v-if="flatFiles.length && fileGroups.some(g => g.isFolder)">
                <div class="rd-folder-header">
                  <span class="rd-folder-icon">📄</span>
                  <span class="rd-folder-name">单独文件</span>
                  <span class="rd-folder-count">{{ flatFiles.length }} 个</span>
                </div>
              </template>
              <div
                v-for="(f, i) in flatFiles"
                :key="'f'+i"
                :class="['rd-file-item', { 'rd-file-sub': fileGroups.some(g => g.isFolder) }]">
                <span class="rd-file-icon">📄</span>
                <span class="rd-file-name">{{ f.file.name }}</span>
                <span v-if="f.extracting" class="rd-extract-status extracting">⏳ 提取中…</span>
                <span v-else-if="f.error" class="rd-extract-status error" :title="f.error">❌ 失败</span>
                <span v-else-if="f.isImagePdf" class="rd-extract-status image-pdf">📷 图片型PDF · AI视觉识别</span>
                <span v-else-if="f.extracted" class="rd-extract-status done">✅ 文字已提取</span>
                <button class="rd-file-clear" @click="removeFlatFile(i)" :disabled="f.extracting">✕</button>
              </div>
            </div>
          </div>

          <!-- 操作按钮（未生成时显示） -->
          <div class="req-doc-actions" v-if="!reqDoc.markdown">
            <!-- 项目选择（上传文件/粘贴文字阶段就选好项目，用于读取知识库+后续回填） -->
            <div class="req-doc-project-row">
              <div class="form-group project-select-inline">
                <label>关联项目</label>
                <select v-model="reqDoc.selectedProject" class="form-select">
                  <option value="">请选择项目（可选）</option>
                  <option v-for="project in projects" :key="project.id" :value="project.id">
                    {{ project.name }}
                  </option>
                </select>
              </div>
              <span class="req-doc-project-hint" v-if="reqDoc.selectedProject">
                将读取该项目知识库辅助生成，确认后的问答可回填知识库
              </span>
            </div>
            <button
              class="req-doc-btn primary"
              @click="generateReqDoc"
              :disabled="!canGenerateReqDoc || reqDoc.isGenerating || reqDoc.isExtracting">
              <span v-if="reqDoc.isExtracting">⏳ 文件提取中…</span>
              <span v-else-if="reqDoc.isGenerating && hasImagePdfFiles">👁️ AI 视觉识别中…</span>
              <span v-else-if="reqDoc.isGenerating">⏳ AI 生成中…</span>
              <span v-else-if="hasImagePdfFiles">👁️ AI 视觉识别并生成文档</span>
              <span v-else>✨ AI 自动生成文档</span>
            </button>
            <button
              class="req-doc-btn analyze-doc-btn"
              @click="analyzeFromReqDocInput"
              :disabled="analyzeLoading || (!reqDoc.rawText.trim() && !reqDoc.markdown.trim() && !hasUploadedFiles())">
              <span v-if="analyzeLoading">🔄 拆解中...</span>
              <span v-else>🧩 先拆解需求</span>
            </button>
            <button
              class="req-doc-btn secondary"
              @click="getReqDocTemplate"
              :disabled="reqDoc.isGenerating || reqDoc.isExtracting">
              📄 使用空白模板
            </button>
          </div>

          <!-- 生成后的编辑区 -->
          <div v-if="reqDoc.markdown" class="req-doc-editor">
            <div class="editor-toolbar">
              <span class="editor-label">📝 需求文档（可直接编辑）</span>
              <div class="editor-toolbar-actions">
                <button class="toolbar-btn" @click="toggleReqDocPreview">
                  {{ reqDoc.showPreview ? '✏️ 编辑' : '👁️ 预览' }}
                </button>
                <button class="toolbar-btn danger" @click="resetReqDoc">
                  🔄 重新生成
                </button>
              </div>
            </div>

            <!-- 编辑模式 -->
            <textarea
              v-if="!reqDoc.showPreview"
              v-model="reqDoc.markdown"
              class="req-doc-textarea"
              rows="18"
              spellcheck="false"></textarea>

            <!-- 预览模式 -->
            <div
              v-else
              class="req-doc-preview markdown-body"
              v-html="formatMarkdown(reqDoc.markdown)"></div>

            <!-- 项目选择 + 版本选择 + 生成按钮 -->
            <div class="req-doc-generate-row">
              <div class="form-group project-select-inline">
                <label>关联项目（可选）</label>
                <select v-model="reqDoc.selectedProject" class="form-select">
                  <option value="">请选择项目</option>
                  <option v-for="project in projects" :key="project.id" :value="project.id">
                    {{ project.name }}
                  </option>
                </select>
              </div>
              <div class="form-group project-select-inline">
                <label>关联版本（可选）</label>
                <div class="version-select-row">
                  <select v-model="selectedVersion" class="form-select version-select">
                    <option value="">不关联版本</option>
                    <option v-for="ver in availableVersions" :key="ver.id" :value="ver.id">
                      {{ ver.name }}{{ ver.is_baseline ? ' (基线)' : '' }}
                    </option>
                  </select>
                  <button class="quick-create-ver-btn" @click="openQuickCreateVersion(reqDoc.selectedProject)" title="快速新建版本">+</button>
                </div>
              </div>
              <button
                class="analyze-btn doc-analyze-btn"
                @click="analyzeFromReqDocMarkdown"
                :disabled="analyzeLoading || !reqDoc.markdown.trim()">
                <span v-if="analyzeLoading">🔄 拆解中...</span>
                <span v-else>🧩 拆解此文档</span>
              </button>
              <button
                class="generate-manual-btn use-req-doc-btn"
                @click="useReqDocForGeneration"
                :disabled="!reqDoc.markdown.trim() || isGenerating || (currentResultId && hasUnconfirmedItems)"
                :title="(currentResultId && hasUnconfirmedItems) ? '请先在拆解结果中逐项确认所有待确认项' : ''">
                🚀 用此文档生成测试用例
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 历史需求文档 面板 -->
      <div class="history-section" v-if="!isGenerating && !showResults">
        <div class="history-card">
          <div class="history-header">
            <div class="history-tabs">
              <button :class="['history-tab', { active: true }]" style="cursor:default">
                📚 历史需求文档
              </button>
            </div>
          </div>

          <!-- 历史需求文档 -->
          <div class="history-version-row">
            <span class="history-count" v-if="reqDocHistoryLoaded" style="margin-right:12px">{{ reqDocHistory.length }} 条记录</span>
            <label style="font-size:0.8rem;color:#64748b;margin-right:6px;white-space:nowrap">关联版本：</label>
            <select v-model="selectedVersion" class="form-select version-select" style="width:160px;font-size:0.8rem;padding:4px 8px">
              <option value="">不关联版本</option>
              <option v-for="ver in availableVersions" :key="ver.id" :value="ver.id">
                {{ ver.name }}{{ ver.is_baseline ? ' (基线)' : '' }}
              </option>
            </select>
            <button class="quick-create-ver-btn" @click="openQuickCreateVersion(null)" title="快速新建版本" style="margin-left:4px">+</button>
          </div>
          <!-- 加载中 -->
          <div v-if="!reqDocHistoryLoaded" class="history-loading">
            <span class="loading-spinner"></span> 加载中...
          </div>
          <!-- 加载失败 -->
          <div v-else-if="reqDocHistoryError" class="history-error">
            ⚠️ 加载失败，<a href="javascript:void(0)" @click="loadReqDocHistory">点击重试</a>
          </div>
          <!-- 空列表 -->
          <div v-else-if="reqDocHistory.length === 0" class="history-empty">
            📭 暂无历史需求文档，<br>在下方生成需求文档后自动保存到此处
          </div>
          <!-- 有数据 -->
          <div v-else class="history-list">
            <div
              v-for="doc in reqDocHistory"
              :key="doc.id"
              class="history-item">
              <div class="history-item-main">
                <div class="history-item-title">{{ doc.title || '未命名文档' }}</div>
                <div class="history-item-meta">
                  <span class="history-source">
                    <span v-if="doc.source_type === 'file'">📁</span>
                    <span v-else-if="doc.source_type === 'text'">✏️</span>
                    <span v-else>📄</span>
                    {{ doc.source_type_display }}
                  </span>
                  <span class="history-time">{{ formatDateTime(doc.created_at) }}</span>
                </div>
              </div>
              <div class="history-item-actions">
                <button class="history-btn view" @click="viewHistoryDoc(doc)" title="查看文档">
                  👁️ 查看
                </button>
                <button class="history-btn edit" @click="editHistoryDoc(doc)" title="编辑文档">
                  ✏️ 编辑
                </button>
                <!-- 有拆解结果 → 查看拆解；无 → 执行拆解 -->
                <button
                  v-if="docAnalysisMap[doc.id]"
                  class="history-btn analyze"
                  @click="viewDocAnalysis(doc)"
                  title="查看拆解结果">
                  📋 查看拆解
                </button>
                <button
                  v-else
                  class="history-btn analyze"
                  @click="analyzeFromHistoryDoc(doc)"
                  :disabled="analyzeLoading"
                  title="需求拆解">
                  🧩 拆解
                </button>
                <button class="history-btn generate" @click="generateFromHistoryDoc(doc)"
                  :disabled="docAnalysisMap[doc.id] && hasUnconfirmedItems"
                  :title="(docAnalysisMap[doc.id] && hasUnconfirmedItems) ? '请先在拆解结果中逐项确认所有待确认项' : '一键提交生成测试用例'">
                  🚀 生成用例
                </button>
                <button class="history-btn del" @click="deleteReqDocHistory(doc)" title="删除此文档">
                  🗑️ 删除
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 历史文档查看/编辑弹窗 -->
      <div v-if="showHistoryPreview" class="modal-overlay" @click.self="closePreview">
        <div class="history-preview-modal">
          <div class="preview-header">
            <h3 v-if="!isEditingDoc">{{ viewingDoc?.title || '文档详情' }}</h3>
            <input v-else v-model="editingTitle" class="edit-title-input" placeholder="文档标题" />
            <button class="preview-close" @click="closePreview">✕</button>
          </div>
          <!-- 预览模式 -->
          <div v-if="!isEditingDoc" class="preview-body markdown-body" v-html="formatMarkdown(viewingDoc?.markdown_content || '')"></div>
          <!-- 编辑模式 -->
          <div v-else class="edit-body">
            <textarea v-model="editingMarkdown" class="edit-textarea" placeholder="在此编辑 Markdown 需求文档..."></textarea>
          </div>
          <div class="preview-actions">
            <template v-if="!isEditingDoc">
              <button
                v-if="viewingDoc && docAnalysisMap[viewingDoc.id]"
                class="history-btn analyze"
                @click="viewDocAnalysis(viewingDoc)"
                title="查看拆解结果">
                📋 查看拆解
              </button>
              <button
                v-else
                class="history-btn analyze"
                @click="analyzeFromPreviewDoc"
                :disabled="analyzeLoading">
                🧩 需求拆解
              </button>
              <button class="history-btn edit" @click="enterEditMode">✏️ 编辑修改</button>
              <button class="generate-manual-btn" @click="generateFromPreviewDoc" :disabled="(currentResultId && hasUnconfirmedItems)" :title="(currentResultId && hasUnconfirmedItems) ? '请先在拆解结果中逐项确认所有待确认项' : ''" style="width:auto;padding:10px 28px;">
                🚀 用此文档生成测试用例
              </button>
            </template>
            <template v-else>
              <button class="toolbar-btn" @click="cancelEdit">❌ 取消编辑</button>
              <button class="generate-manual-btn" @click="saveDocEdit" :disabled="editingSaving || !editingMarkdown.trim()" style="width:auto;padding:10px 28px;">
                {{ editingSaving ? '保存中...' : '✅ 保存修改' }}
              </button>
            </template>
          </div>
        </div>
      </div>

      <!-- 生成用例确认弹窗 -->
      <div v-if="showGenerateConfirm" class="modal-overlay" @click.self="showGenerateConfirm = false">
        <div class="generate-confirm-modal">
          <div class="quick-version-header">
            <h3>🚀 生成测试用例</h3>
            <button class="preview-close" @click="showGenerateConfirm = false">✕</button>
          </div>
          <div class="quick-version-body">
            <p style="color:#666;margin-bottom:16px;font-size:0.9rem">
              请确认关联的项目和版本号，生成的测试用例将绑定到所选版本。
            </p>
            <div class="form-group">
              <label>生成模式 <span class="required">*</span></label>
              <div class="generation-mode-selector">
                <label 
                  v-for="mode in generationModes" 
                  :key="mode.value"
                  class="mode-option"
                  :class="{ active: generateConfirmForm.generation_mode === mode.value }"
                >
                  <input type="radio" v-model="generateConfirmForm.generation_mode" :value="mode.value" class="mode-radio" />
                  <span class="mode-icon">{{ mode.icon }}</span>
                  <span class="mode-name">{{ mode.label }}</span>
                  <span class="mode-desc">{{ mode.desc }}</span>
                </label>
              </div>
            </div>
            <div class="form-group">
              <label>归属项目 <span class="required">*</span></label>
              <select v-model="generateConfirmForm.project_id" class="form-select" @change="onConfirmProjectChange">
                <option :value="null">请选择项目</option>
                <option v-for="project in projects" :key="project.id" :value="project.id">
                  {{ project.name }}
                </option>
              </select>
            </div>
            <div class="form-group">
              <label>关联版本 <span class="required">*</span></label>
              <select v-model="generateConfirmForm.version_id" class="form-select">
                <option :value="null">请选择版本</option>
                <option v-for="ver in generateConfirmVersions" :key="ver.id" :value="ver.id">
                  {{ ver.name }}{{ ver.is_baseline ? ' (基线)' : '' }}
                </option>
              </select>
              <button class="quick-create-ver-btn" style="margin-left:8px;vertical-align:middle" @click="openQuickCreateVersion(generateConfirmForm.project_id)" title="快速新建版本">+</button>
            </div>
            <div class="form-group">
              <label>功能模块</label>
              <select v-model="generateConfirmForm.feature_module_id" class="form-select" @change="onConfirmFeatureModuleChange">
                <option :value="null">请选择功能模块</option>
                <optgroup v-if="generateConfirmFeatureModuleGroups.version.length" :label="`已关联 ${generateConfirmVersionName}`">
                  <option v-for="fm in generateConfirmFeatureModuleGroups.version" :key="fm.id" :value="fm.id">{{ fm.name }}</option>
                </optgroup>
                <optgroup v-if="generateConfirmFeatureModuleGroups.unassociated.length" label="未关联版本">
                  <option v-for="fm in generateConfirmFeatureModuleGroups.unassociated" :key="fm.id" :value="fm.id">{{ fm.name }}</option>
                </optgroup>
                <option v-for="fm in generateConfirmFeatureModuleGroups.all" :key="fm.id" :value="fm.id">{{ fm.name }}</option>
              </select>
              <button class="quick-create-ver-btn" style="margin-left:8px;vertical-align:middle" @click="openQuickCreateFeatureModule(generateConfirmForm.project_id)" title="快速新建功能模块">+</button>
            </div>
            <div class="form-group">
              <label>测试点</label>
              <select v-model="generateConfirmForm.test_point_id" class="form-select">
                <option :value="null">请选择测试点</option>
                <option v-for="tp in generateConfirmTestPoints" :key="tp.id" :value="tp.id">
                  {{ tp.name }}
                </option>
              </select>
              <button class="quick-create-ver-btn" style="margin-left:8px;vertical-align:middle" @click="openQuickCreateTestPoint(generateConfirmForm.feature_module_id)" :disabled="!generateConfirmForm.feature_module_id" title="快速新建测试点">+</button>
            </div>
          </div>
          <div class="quick-version-actions">
            <button class="toolbar-btn" @click="showGenerateConfirm = false">取消</button>
            <button class="generate-manual-btn" @click="confirmStartGeneration" :disabled="!canConfirmGenerate || isGenerating" style="width:auto;padding:8px 24px;">
              {{ isGenerating ? '生成中...' : '✅ 确认并开始生成' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 快速创建版本弹窗 -->
      <div v-if="showQuickCreateVersion" class="modal-overlay" @click.self="showQuickCreateVersion = false">
        <div class="quick-version-modal">
          <div class="quick-version-header">
            <h3>⚡ 快速新建版本</h3>
            <button class="preview-close" @click="showQuickCreateVersion = false">✕</button>
          </div>
          <div class="quick-version-body">
            <div class="form-group">
              <label>版本名称 <span class="required">*</span></label>
              <input v-model="quickVersionForm.name" class="form-input" placeholder="例如：v2.1.0、2026-Q3" @keyup.enter="saveQuickVersion" />
            </div>
            <div class="form-group">
              <label>关联项目</label>
              <select v-model="quickVersionForm.project_id" class="form-select">
                <option :value="null">请选择项目</option>
                <option v-for="project in projects" :key="project.id" :value="project.id">
                  {{ project.name }}
                </option>
              </select>
            </div>
            <div class="form-group">
              <label>版本描述</label>
              <input v-model="quickVersionForm.description" class="form-input" placeholder="可选填版本说明" />
            </div>
            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" v-model="quickVersionForm.is_baseline" />
                设为基线版本
              </label>
            </div>
          </div>
          <div class="quick-version-actions">
            <button class="toolbar-btn" @click="showQuickCreateVersion = false">取消</button>
            <button class="generate-manual-btn" @click="saveQuickVersion" :disabled="!quickVersionForm.name.trim() || quickVersionSaving" style="width:auto;padding:8px 24px;">
              {{ quickVersionSaving ? '保存中...' : '✅ 创建' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 快速创建功能模块弹窗 -->
      <div v-if="showQuickCreateFeatureModule" class="modal-overlay" @click.self="showQuickCreateFeatureModule = false">
        <div class="quick-version-modal">
          <div class="quick-version-header">
            <h3>⚡ 快速新建功能模块</h3>
            <button class="preview-close" @click="showQuickCreateFeatureModule = false">✕</button>
          </div>
          <div class="quick-version-body">
            <div class="form-group">
              <label>模块名称 <span class="required">*</span></label>
              <input v-model="quickFeatureModuleForm.name" class="form-input" placeholder="例如：用户登录、搜索功能" maxlength="100" @keyup.enter="saveQuickFeatureModule" />
            </div>
            <div class="form-group">
              <label>关联项目 <span class="required">*</span></label>
              <select v-model="quickFeatureModuleForm.project_id" class="form-select">
                <option :value="null">请选择项目</option>
                <option v-for="project in projects" :key="project.id" :value="project.id">
                  {{ project.name }}
                </option>
              </select>
            </div>
            <div class="form-group">
              <label>模块描述</label>
              <input v-model="quickFeatureModuleForm.description" class="form-input" placeholder="可选填模块描述" />
            </div>
          </div>
          <div class="quick-version-actions">
            <button class="toolbar-btn" @click="showQuickCreateFeatureModule = false">取消</button>
            <button class="generate-manual-btn" @click="saveQuickFeatureModule" :disabled="!quickFeatureModuleForm.name.trim() || !quickFeatureModuleForm.project_id || quickFeatureModuleSaving" style="width:auto;padding:8px 24px;">
              {{ quickFeatureModuleSaving ? '保存中...' : '✅ 创建' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 快速创建测试点弹窗 -->
      <div v-if="showQuickCreateTestPoint" class="modal-overlay" @click.self="showQuickCreateTestPoint = false">
        <div class="quick-version-modal">
          <div class="quick-version-header">
            <h3>🎯 快速新建测试点</h3>
            <button class="preview-close" @click="showQuickCreateTestPoint = false">✕</button>
          </div>
          <div class="quick-version-body">
            <div class="form-group">
              <label>所属功能模块</label>
              <input :value="generateConfirmFeatureModules.find(fm => fm.id === generateConfirmForm.feature_module_id)?.name || ''" class="form-input" disabled />
            </div>
            <div class="form-group">
              <label>测试点名称 <span class="required">*</span></label>
              <input v-model="quickTestPointForm.name" class="form-input" placeholder="例如：登录按钮点击、密码输入校验" maxlength="200" @keyup.enter="saveQuickTestPoint" />
            </div>
            <div class="form-group">
              <label>测试点描述</label>
              <input v-model="quickTestPointForm.description" class="form-input" placeholder="可选填测试点描述" />
            </div>
          </div>
          <div class="quick-version-actions">
            <button class="toolbar-btn" @click="showQuickCreateTestPoint = false">取消</button>
            <button class="generate-manual-btn" @click="saveQuickTestPoint" :disabled="!quickTestPointForm.name.trim() || quickTestPointSaving" style="width:auto;padding:8px 24px;">
              {{ quickTestPointSaving ? '保存中...' : '✅ 创建' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 生成进度和结果 -->
      <div v-if="isGenerating || showResults" class="generation-progress">
        <div class="progress-card">
          <h3>
            🤖 AI正在为您生成测试用例
            <span class="current-mode-badge">
              (当前模式: {{ globalOutputMode === 'stream' ? '⚡实时流式输出' : '📄完整输出' }})
            </span>
          </h3>
          <div class="progress-info">
            <div class="progress-item">
              <span class="label">任务ID:</span>
              <span class="value">{{ currentTaskId || '准备中...' }}</span>
            </div>
            <div class="progress-item">
              <span class="label">当前状态:</span>
              <span class="value">{{ showResults ? '生成完成' : progressText }}</span>
            </div>
          </div>

          <!-- 流式内容实时显示区域 -->
          <div v-if="streamedContent" class="stream-content-display">
            <div class="stream-header">
              <span class="stream-title">✍️ 实时生成内容</span>
              <span class="stream-status">{{ streamedContent.length }} 字符</span>
            </div>
            <div class="stream-content" v-html="formatMarkdown(streamedContent)"></div>
          </div>

          <!-- 评审内容显示区域 -->
          <div v-if="streamedReviewContent" class="stream-content-display" style="margin-top: 15px;">
            <div class="stream-header">
              <span class="stream-title">📝 AI评审意见</span>
              <span class="stream-status">{{ streamedReviewContent.length }} 字符</span>
            </div>
            <div class="stream-content" v-html="formatMarkdown(streamedReviewContent)"></div>
          </div>

          <!-- 最终版用例显示区域 -->
          <div v-if="finalTestCases" class="stream-content-display" style="margin-top: 15px;">
            <div class="stream-header">
              <span class="stream-title">
                🎯 最终版用例
                <span v-if="isGenerating" class="streaming-indicator">🔄 正在生成...</span>
              </span>
              <span class="stream-status">{{ finalTestCases.length }} 字符</span>
            </div>
            <div class="stream-content final-testcases" v-html="formatMarkdown(finalTestCases)"></div>
          </div>

          <div class="progress-steps">
            <div class="step" :class="{ active: currentStep >= 1 }">
              <span class="step-number">1</span>
              <span class="step-text">需求分析</span>
            </div>
            <div class="step" :class="{ active: currentStep >= 2 }">
              <span class="step-number">2</span>
              <span class="step-text">用例编写</span>
            </div>
            <div v-if="showReviewStep" class="step" :class="{ active: currentStep >= 3 }">
              <span class="step-number">3</span>
              <span class="step-text">用例评审</span>
            </div>
            <div class="step" :class="{ active: currentStep >= (showReviewStep ? 4 : 3) }">
              <span class="step-number">{{ showReviewStep ? 4 : 3 }}</span>
              <span class="step-text">完成</span>
            </div>
          </div>

          <!-- 任务完成后的操作按钮 -->
          <div v-if="showResults && generationResult" class="completion-actions">
            <button class="download-btn" @click="downloadTestCases">
              <span>📥 下载测试用例</span>
            </button>
            <button class="save-btn" @click="saveToTestCaseRecords">
              <span>💾 保存到用例库</span>
            </button>
            <button class="new-generation-btn" @click="resetGeneration">
              <span>📝 生成新用例</span>
            </button>
          </div>
          <div v-else-if="showResults" class="completion-actions">
            <button class="new-generation-btn" @click="resetGeneration">
              <span>📝 生成新用例</span>
            </button>
          </div>
          <button v-else class="cancel-generation-btn" @click="cancelGeneration">
            取消生成
          </button>
        </div>
      </div>

      <!-- 旧的生成结果区域已废弃，保留用于兼容 -->
      <!-- 现在使用流式显示区域 + 最终版用例区域 -->
      <div v-if="false && showResults && generationResult" class="generation-result">
        <div class="result-header">
          <h2>✅ 测试用例生成完成</h2>
          <div class="result-summary">
            <span class="summary-item">
              📊 任务ID: {{ generationResult.task_id }}
            </span>
            <span class="summary-item">
              ⏱️ 生成时间: {{ formatDateTime(generationResult.completed_at) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 插接矩阵弹窗 -->
    <div v-if="showMatrixModal" class="matrix-modal-overlay" @click.self="showMatrixModal = false">
      <div class="matrix-modal">
        <div class="matrix-modal-header">
          <h2>📊 深度业务逻辑拆解与插接矩阵</h2>
          <button class="matrix-close-btn" @click="showMatrixModal = false">✕</button>
        </div>
        <div class="matrix-modal-body">
          <div v-if="!analyzeResult" class="matrix-empty">
            暂无拆解结果，请先进行需求拆解
          </div>
          <div v-else class="matrix-sections">
            <!-- 需求概述 -->
            <template v-for="(sec, idx) in matrixSections" :key="idx">
              <div class="matrix-section" v-if="sec.html.trim()">
                <h3 v-if="sec.title" class="matrix-section-title">{{ sec.title }}</h3>
                <div class="matrix-section-body" v-html="sec.html"></div>
              </div>
            </template>
          </div>
        </div>
        <div class="matrix-modal-footer">
          <button class="matrix-btn copy-btn" @click="copyMatrixToClipboard">📋 复制全部</button>
          <button class="matrix-btn close-btn" @click="showMatrixModal = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import api from '@/utils/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as XLSX from 'xlsx'
import { useUserStore } from '@/stores/user'
import {
  getAnalysisResults,
  getAnalysisResultDetail,
  createAnalysisResult,
  deleteAnalysisResult as apiDeleteAnalysisResult,
  getClarifications,
  saveAllClarifications,
  refineAnalysis,
  getAnalysisResultsByDocs,
  autoFillKnowledgeFromConfirmations
} from '@/api/requirement-analysis'

export default {
  name: 'RequirementAnalysisView',
  data() {
    return {
      // 全局输出模式设置
      globalOutputMode: 'stream',  // 默认使用流式输出

      // 手动输入需求
      manualInput: {
        title: '',
        description: '',
        selectedProject: ''
      },

      // 文件上传
      selectedFile: null,
      documentTitle: '',
      selectedProject: '',
      selectedVersion: '',
      selectedFeatureModule: '',
      projects: [],
      allVersions: [],
      allFeatureModules: [],
      // 快速创建版本
      showQuickCreateVersion: false,
      quickVersionSaving: false,
      quickVersionForm: {
        name: '',
        project_id: null,
        description: '',
        is_baseline: false
      },
      // 快速创建功能模块
      showQuickCreateFeatureModule: false,
      quickFeatureModuleSaving: false,
      quickFeatureModuleForm: {
        name: '',
        project_id: null,
        description: ''
      },
      // 快速创建测试点
      showQuickCreateTestPoint: false,
      quickTestPointSaving: false,
      quickTestPointForm: {
        name: '',
        feature_module_id: null,
        description: ''
      },
      // 测试点相关
      moduleTestPoints: [],
      // 生成确认弹窗
      showGenerateConfirm: false,
      generateConfirmForm: {
        project_id: null,
        version_id: null,
        feature_module_id: null,
        test_point_id: null,
        generation_mode: 'smart'
      },
      generationModes: [
        { value: 'smart', label: '智能', icon: '🤖', desc: 'AI评估' },
        { value: 'quick', label: '快速', icon: '⚡', desc: '10~20条' },
        { value: 'standard', label: '标准', icon: '📋', desc: '20~40条' },
        { value: 'comprehensive', label: '全面', icon: '🔬', desc: '全量覆盖' }
      ],
      pendingGeneratePayload: null,
      isDragOver: false,

      // 需求拆解（需求分析与拆解专家）
      analyzeLoading: false,
      analyzeResult: '',
      analyzeImages: [],

      // 拆解结果编辑/追问
      isEditingResult: false,
      showDeepQuestion: false,
      deepChatMessages: [],        // { role: 'user'|'assistant', content: string }
      deepChatLoading: false,
      deepStreamingContent: '',    // 流式输出中的内容
      deepQuestionInput: '',

      // 结构化追问 Q&A（表格模式）
      qaMode: 'table',            // 'table' | 'chat'
      clarificationItems: [],      // { id, question, answer, status: 'pending'|'answered'|'confirmed', category }
      qaGenerating: false,         // 生成追问中
      qaSaving: false,             // 保存回答中
      currentResultId: null,       // 当前追问清单关联的拆解结果历史记录 ID
      currentRequirementText: '',  // 当前拆解使用的需求文本（用于自动落库）
      currentProjectId: null,      // 当前拆解关联的项目 ID
      showMatrixModal: false,       // 插接矩阵弹窗
      uncertainItems: [],           // 拆解结果中的待确认项（逐项人工确认，对齐 AI 用例评审）
      refining: false,              // 精炼中
      showUncertainDialog: false,   // 待确认弹窗
      docAnalysisMap: {},           // 每条文档的最新拆解结果 { docId: { id, title, ... } }
      currentAnalyzedDocId: null,   // 当前正在拆解的文档 ID（用于关联）

      // 生成状态
      isGenerating: false,
      currentTaskId: null,
      progressText: '准备开始生成...',
      currentStep: 0,
      pollInterval: null,
      eventSource: null,  // SSE连接
      streamedContent: '',  // 流式接收的内容
      streamedReviewContent: '',  // 流式接收的评审内容
      finalTestCases: '',  // 最终版用例
      hasShownCompletionMessage: false,  // 是否已经显示过完成消息
      showReviewStep: true,  // 是否显示评审步骤（根据生成配置决定）

      // 生成结果
      showResults: false,
      generationResult: null,

      // AI配置状态
      configStatus: {
        overall_status: 'unknown',
        message: '',
        writer_model: {
          configured: false,
          enabled: false,
          name: null,
          provider: null,
          id: null,
          required: true
        },
        writer_prompt: {
          configured: false,
          enabled: false,
          name: null,
          id: null,
          required: true
        },
        reviewer_model: {
          configured: false,
          enabled: false,
          name: null,
          id: null,
          required: true
        },
        reviewer_prompt: {
          configured: false,
          enabled: false,
          name: null,
          id: null,
          required: true
        },
        generation_config: {
          configured: false,
          enabled: false,
          name: null,
          id: null,
          required: true,
          default_output_mode: null
        }
      },
      showConfigGuide: false,
      checkingConfig: true,
      modalKey: 0,  // 用于强制重新渲染弹窗

      // 历史需求文档
      reqDocHistory: [],
      reqDocHistoryLoaded: false,
      reqDocHistoryError: false,
      showHistoryPreview: false,
      viewingDoc: null,
      // 编辑模式
      isEditingDoc: false,

      // 历史拆解结果
      analysisResults: [],
      analysisResultsLoaded: false,
      analysisResultsError: false,
      viewingResult: null,
      showResultPreview: false,
      historyTab: 'docs',  // 'docs' | 'results'
      editingMarkdown: '',
      editingTitle: '',
      editingSaving: false,

      // 需求文档生成（后门流程）
      reqDoc: {
        inputMode: 'text',      // 'text' | 'file'
        rawText: '',
        files: [],              // [{ file, documentId, isImagePdf, extracting, extracted, folder?, relativePath? }]
        isExtracting: false,    // 是否有文件仍在提取中（汇总）
        markdown: '',
        isGenerating: false,
        showPreview: false,
        selectedProject: ''
      }
    }
  },
  
  computed: {
    canGenerateManual() {
      return this.manualInput.title.trim() && 
             this.manualInput.description.trim() && 
             this.manualInput.description.length <= 2000
    },
    canGenerateReqDoc() {
      if (this.reqDoc.inputMode === 'text') return !!this.reqDoc.rawText.trim()
      if (!this.reqDoc.files.length) return false
      return this.reqDoc.files.every(f => f.extracted || f.isImagePdf)
    },
    hasImagePdfFiles() {
      return this.reqDoc.files.some(f => f.isImagePdf)
    },
    // 按文件夹分组
    fileGroups() {
      const groups = []
      const seen = new Set()
      for (const f of this.reqDoc.files) {
        if (!f.folder) continue
        if (seen.has(f.folder)) continue
        seen.add(f.folder)
        groups.push({
          isFolder: true,
          name: f.folder,
          items: this.reqDoc.files.filter(x => x.folder === f.folder)
        })
      }
      return groups
    },
    // 无文件夹归属的单独文件
    flatFiles() {
      return this.reqDoc.files.filter(f => !f.folder)
    },
    // 是否还有未确认的待确认项（用于拦截「生成测试用例」下一步）
    hasUnconfirmedItems() {
      return this.uncertainItems.some(i => !i.confirmed)
    },
    // 解析插接矩阵：将 markdown 文本拆成结构化 section（表格转为 HTML table）
    matrixSections() {
      if (!this.analyzeResult) return []
      const text = this.analyzeResult
      const sections = []
      // 按 ### 拆分 section
      const parts = text.split(/(?=^#{1,3}\s)/m)
      for (const part of parts) {
        const trimmed = part.trim()
        if (!trimmed) continue
        // 提取标题行
        const titleMatch = trimmed.match(/^(#{1,3})\s+(.+)/m)
        const title = titleMatch ? titleMatch[2].trim() : ''
        let body = titleMatch ? trimmed.substring(titleMatch[0].length).trim() : trimmed
        // 检查 body 中是否包含 markdown 表格，如果有则转为 HTML table
        if (/\|.*\|/.test(body) && body.includes('---')) {
          body = this.convertMarkdownTablesToHtml(body)
        } else {
          body = this.formatMarkdown(body)
        }
        sections.push({ title, html: body })
      }
      return sections
    },
    availableVersions() {
      return this.allVersions
    },
    // 生成确认弹窗的版本列表（根据选择的项目过滤）
    generateConfirmVersions() {
      if (!this.generateConfirmForm.project_id) {
        return this.allVersions
      }
      return this.allVersions.filter(v =>
        !v.projects || v.projects.length === 0 || v.projects.some(p => p.id === this.generateConfirmForm.project_id)
      )
    },
    generateConfirmFeatureModules() {
      if (!this.generateConfirmForm.project_id) {
        return this.allFeatureModules || []
      }
      if (!this.allFeatureModules) return []
      return this.allFeatureModules.filter(fm => fm.project?.id === this.generateConfirmForm.project_id)
    },
    generateConfirmVersionName() {
      if (!this.generateConfirmForm.version_id) return ''
      const v = this.generateConfirmVersions.find(v => v.id === Number(this.generateConfirmForm.version_id))
      return v ? v.name : ''
    },
    // 生成确认弹窗功能模块下拉分组：已关联选中版本 + 未关联版本
    generateConfirmFeatureModuleGroups() {
      if (!this.generateConfirmForm.project_id) {
        return { version: [], unassociated: [], all: this.allFeatureModules || [] }
      }
      if (!this.allFeatureModules) return { version: [], unassociated: [], all: [] }
      const base = this.allFeatureModules.filter(fm => fm.project?.id === this.generateConfirmForm.project_id)
      if (this.generateConfirmForm.version_id) {
        const vid = Number(this.generateConfirmForm.version_id)
        const versionMods = []
        const unassociated = []
        for (const fm of base) {
          const versions = fm.versions || []
          if (versions.some(v => v.id === vid)) versionMods.push(fm)
          else if (versions.length === 0) unassociated.push(fm)
        }
        return { version: versionMods, unassociated, all: [] }
      }
      return { version: [], unassociated: [], all: base }
    },
    generateConfirmTestPoints() {
      if (!this.generateConfirmForm.feature_module_id) return []
      return this.moduleTestPoints || []
    },
    // 是否可以确认生成
    canConfirmGenerate() {
      return this.generateConfirmForm.project_id && this.generateConfirmForm.version_id && this.pendingGeneratePayload
    }
  },
  
  mounted() {
    this.loadProjects()
    this.loadVersions()
    this.loadFeatureModules()
    this.checkConfigStatus()
    this.loadReqDocHistory()
    this.loadAnalysisResults()
  },

  activated() {
    // 当从其他页面返回时，重新检查配置状态
    // 立即隐藏弹窗和遮罩层，强制重新渲染
    this.showConfigGuide = false
    this.checkingConfig = true
    this.modalKey += 1  // 改变key值，强制重新渲染弹窗

    // 延迟检查配置，确保页面完全加载后再显示弹窗
    setTimeout(async () => {
      await this.checkConfigStatus()
    }, 200)

    // 刷新历史文档列表
    this.loadReqDocHistory()
  },

  beforeUnmount() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval)
    }
    // 停止token自动刷新定时器
    const userStore = useUserStore()
    userStore.stopAutoRefresh()
  },

  // 解析 AI 返回的 markdown 拆解结果为结构化表格数据
  parsedAnalyzeSections() {
    if (!this.analyzeResult) return []
    try {
      const result = this.parseAnalyzeMarkdown(this.analyzeResult)
      // 确保每个 section 都有 rows/headers 默认数组，避免模板访问 .length 崩溃
      return (result || []).map(s => ({
        title: s.title || '',
        type: s.type || 'text',
        rows: Array.isArray(s.rows) ? s.rows : [],
        headers: Array.isArray(s.headers) ? s.headers : [],
        text: s.text || ''
      }))
    } catch (e) {
      console.error('需求拆解结果解析失败:', e)
      return []  // 降级为原始 markdown 渲染
    }
  },

  methods: {
    async loadProjects() {
      try {
        const response = await api.get('/projects/')
        this.projects = response.data.results || response.data
      } catch (error) {
        console.error('加载项目失败:', error)
      }
    },

    async loadVersions() {
      try {
        const response = await api.get('/versions/')
        this.allVersions = response.data.results || response.data || []
      } catch (error) {
        console.error('加载版本失败:', error)
        this.allVersions = []
      }
    },

    async loadFeatureModules() {
      try {
        const response = await api.get('/feature-modules/')
        this.allFeatureModules = response.data.results || response.data || []
      } catch (error) {
        console.error('加载功能模块失败:', error)
        this.allFeatureModules = []
      }
    },

    async loadModuleTestPoints(moduleId) {
      if (!moduleId) {
        this.moduleTestPoints = []
        return
      }
      try {
        const response = await api.get(`/feature-modules/modules/${moduleId}/test-points/`)
        this.moduleTestPoints = response.data || []
      } catch (error) {
        console.error('加载测试点失败:', error)
        this.moduleTestPoints = []
      }
    },

    openQuickCreateVersion(projectId) {
      this.showQuickCreateVersion = true
      this.quickVersionForm = {
        name: '',
        project_id: projectId || null,
        description: '',
        is_baseline: false
      }
      // 聚焦到名称输入框
      this.$nextTick(() => {
        const input = document.querySelector('.quick-version-body .form-input')
        if (input) input.focus()
      })
    },

    async saveQuickVersion() {
      const name = this.quickVersionForm.name.trim()
      if (!name) {
        ElMessage.warning('请输入版本名称')
        return
      }
      if (!this.quickVersionForm.project_id) {
        ElMessage.warning('请选择关联项目')
        return
      }
      this.quickVersionSaving = true
      try {
        const payload = {
          name: name,
          description: this.quickVersionForm.description.trim(),
          is_baseline: this.quickVersionForm.is_baseline,
          project_ids: [this.quickVersionForm.project_id]
        }
        const response = await api.post('/versions/', payload)
        // 刷新版本列表
        await this.loadVersions()
        // 自动选中新创建的版本
        this.selectedVersion = response.data.id
        ElMessage.success(`版本「${name}」创建成功`)
        this.showQuickCreateVersion = false
      } catch (error) {
        if (error.response?.data) {
          const errors = Object.values(error.response.data).flat()
          ElMessage.error(errors[0] || '创建版本失败')
        } else {
          ElMessage.error('创建版本失败')
        }
      } finally {
        this.quickVersionSaving = false
      }
    },

    openQuickCreateFeatureModule(projectId) {
      this.showQuickCreateFeatureModule = true
      this.quickFeatureModuleForm = {
        name: '',
        project_id: projectId || null,
        description: ''
      }
      this.$nextTick(() => {
        const input = document.querySelector('.quick-version-body .form-input')
        if (input) input.focus()
      })
    },

    async saveQuickFeatureModule() {
      const name = this.quickFeatureModuleForm.name.trim()
      if (!name) {
        ElMessage.warning('请输入模块名称')
        return
      }
      if (!this.quickFeatureModuleForm.project_id) {
        ElMessage.warning('请选择关联项目')
        return
      }
      this.quickFeatureModuleSaving = true
      try {
        const response = await api.post('/feature-modules/', {
          name: name,
          description: this.quickFeatureModuleForm.description.trim(),
          project_id: this.quickFeatureModuleForm.project_id
        })
        // 刷新功能模块列表
        await this.loadFeatureModules()
        // 自动选中新创建的功能模块
        this.generateConfirmForm.feature_module_id = response.data.id
        ElMessage.success(`功能模块「${name}」创建成功`)
        this.showQuickCreateFeatureModule = false
      } catch (error) {
        if (error.response?.data) {
          const detail = error.response.data.detail || error.response.data.name || '创建功能模块失败'
          ElMessage.error(Array.isArray(detail) ? detail[0] : detail)
        } else {
          ElMessage.error('创建功能模块失败')
        }
      } finally {
        this.quickFeatureModuleSaving = false
      }
    },

    openQuickCreateTestPoint(moduleId) {
      this.showQuickCreateTestPoint = true
      this.quickTestPointForm = {
        name: '',
        feature_module_id: moduleId || null,
        description: ''
      }
      this.$nextTick(() => {
        const input = document.querySelectorAll('.quick-version-body .form-input')[1]
        if (input) input.focus()
      })
    },

    async saveQuickTestPoint() {
      const name = this.quickTestPointForm.name.trim()
      if (!name) {
        ElMessage.warning('请输入测试点名称')
        return
      }
      if (!this.quickTestPointForm.feature_module_id) {
        ElMessage.warning('请先选择功能模块')
        return
      }
      this.quickTestPointSaving = true
      try {
        const response = await api.post('/feature-modules/test-points/', {
          name: name,
          description: this.quickTestPointForm.description.trim(),
          feature_module_id: this.quickTestPointForm.feature_module_id
        })
        // 刷新当前模块的测试点列表
        await this.loadModuleTestPoints(this.quickTestPointForm.feature_module_id)
        // 自动选中新创建的测试点
        this.generateConfirmForm.test_point_id = response.data.id
        ElMessage.success(`测试点「${name}」创建成功`)
        this.showQuickCreateTestPoint = false
      } catch (error) {
        if (error.response?.data) {
          const detail = error.response.data.detail || error.response.data.name || '创建测试点失败'
          ElMessage.error(Array.isArray(detail) ? detail[0] : detail)
        } else {
          ElMessage.error('创建测试点失败')
        }
      } finally {
        this.quickTestPointSaving = false
      }
    },

    async checkConfigStatus() {
      try {
        this.checkingConfig = true
        const response = await api.get('/requirement-analysis/api/config/check/')
        this.configStatus = response.data

        // 判断逻辑：只有当"用例编写模型"、"用例评审模型"、"用例编写提示词"和"用例评审提示词"都配置且启用时，才不显示弹框
        const writerModelReady = response.data.writer_model &&
                                response.data.writer_model.configured &&
                                response.data.writer_model.enabled

        const reviewerModelReady = response.data.reviewer_model &&
                                  response.data.reviewer_model.configured &&
                                  response.data.reviewer_model.enabled

        const writerPromptReady = response.data.writer_prompt &&
                                 response.data.writer_prompt.configured &&
                                 response.data.writer_prompt.enabled

        const reviewerPromptReady = response.data.reviewer_prompt &&
                                   response.data.reviewer_prompt.configured &&
                                   response.data.reviewer_prompt.enabled

        // 检查生成行为配置
        const generationConfigReady = response.data.generation_config &&
                                      response.data.generation_config.configured

        // 根据生成配置的enable_auto_review决定是否显示评审步骤（无论其他配置状态，始终读取）
        if (response.data.generation_config && response.data.generation_config.enable_auto_review !== null) {
          this.showReviewStep = response.data.generation_config.enable_auto_review
        } else {
          this.showReviewStep = true  // 默认显示
        }

        // 只有五项都准备好时才不显示引导弹框
        if (writerModelReady && reviewerModelReady && writerPromptReady && reviewerPromptReady && generationConfigReady) {
          this.showConfigGuide = false

          // 如果生成配置允许用户修改，则使用配置的默认输出模式
          if (response.data.generation_config && response.data.generation_config.default_output_mode) {
            this.globalOutputMode = response.data.generation_config.default_output_mode
          }
        } else {
          this.showConfigGuide = true
        }
      } catch (error) {
        console.error('检查配置状态失败:', error)
        // 如果检查失败，默认不显示引导，避免影响正常使用
        this.showConfigGuide = false
        this.checkingConfig = false
      } finally {
        this.checkingConfig = false
      }
    },

    goToConfig() {
      // 智能判断跳转目标：优先跳转到未配置/未启用的页面
      // 优先级：必需配置 > 可选配置，提示词 > 模型

      // 0. 首先检查生成行为配置（generation_config）
      if (!this.configStatus.generation_config || !this.configStatus.generation_config.configured) {
        this.$router.push('/configuration/generation-config')
        return
      }

      // 1. 优先检查必需的提示词配置（writer_prompt）
      if (!this.configStatus.writer_prompt.configured || !this.configStatus.writer_prompt.enabled) {
        this.$router.push('/configuration/prompt-config')
        return
      }

      // 2. 检查必需的模型配置（writer_model）
      if (!this.configStatus.writer_model.configured || !this.configStatus.writer_model.enabled) {
        this.$router.push('/configuration/ai-model')
        return
      }

      // 3. 检查可选的评审提示词（reviewer_prompt）
      if (!this.configStatus.reviewer_prompt.configured || !this.configStatus.reviewer_prompt.enabled) {
        this.$router.push('/configuration/prompt-config')
        return
      }

      // 4. 检查可选的评审模型（reviewer_model）
      if (!this.configStatus.reviewer_model.configured || !this.configStatus.reviewer_model.enabled) {
        this.$router.push('/configuration/ai-model')
        return
      }

      // 默认跳转到生成行为配置
      this.$router.push('/configuration/generation-config')
    },

    goToPromptConfig() {
      this.$router.push('/configuration/prompt-config')
    },

    getConfigItemClass(configKey) {
      const config = this.configStatus[configKey]
      if (config.enabled) {
        return 'status-enabled'
      } else if (config.configured) {
        return 'status-disabled'
      } else {
        return 'status-unconfigured'
      }
    },

    getStatusIcon(configKey) {
      const config = this.configStatus[configKey]
      if (config.enabled) {
        // 绿色对号
        return '<path d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm193.5 301.7l-210.6 292c-12.7 17.7-39 17.7-51.7 0L318.5 484.9c-3.8-5.3 0-12.7 6.5-12.7h46.9c10.2 0 19.9 4.9 25.9 13.3l71.2 98.8 157.2-218c6-8.3 15.6-13.3 25.9-13.3H699c6.5 0 10.3 7.4 6.5 12.7z" fill="#27ae60"/>'
      } else if (config.configured) {
        // 禁用图标（灰色圆圈和斜线）
        return '<path d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm0 820c-205.4 0-372-166.6-372-372s166.6-372 372-372 372 166.6 372 372-166.6 372-372 372zm128-412c0 4.4-3.6 8-8 8H392c-4.4 0-8-3.6-8-8v-48c0-4.4 3.6-8 8-8h240c4.4 0 8 3.6 8 8v48z" fill="#95a5a6"/>'
      } else {
        // 红色叉号
        return '<path d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm165.4 618.2l-66-70.7c-10.6-10.1-28.1-10.1-38.8 0l-66.7 71.5-66.7-71.5c-10.6-10.1-28.1-10.1-38.8 0l-66 70.7c-9.9 10.6-9.9 27.4 0 38l66 70.7c10.6 10.1 28.1 10.1 38.8 0l66.7-71.5 66.7 71.5c10.6 10.1 28.1 10.1 38.8 0l66-70.7c9.9-10.6 9.9-27.4 0-38z" fill="#e74c3c"/>'
      }
    },

    getStatusSymbol(configKey) {
      const config = this.configStatus[configKey]
      if (config.enabled) {
        // 绿色对勾
        return '<span style="color: #27ae60; font-size: 18px;">✓</span>'
      } else if (config.configured) {
        // 禁用图标
        return '<span style="color: #95a5a6; font-size: 18px;">○</span>'
      } else {
        // 红色叉号
        return '<span style="color: #e74c3c; font-size: 18px;">✗</span>'
      }
    },

    handleDrop(event) {
      event.preventDefault()
      this.isDragOver = false
      const files = event.dataTransfer.files
      if (files.length > 0) {
        this.handleFileSelect({ target: { files } })
      }
    },

    handleFileSelect(event) {
      const file = event.target.files[0]
      if (file) {
        const allowedTypes = [
          'application/pdf',
          'application/msword',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          'text/plain',
          'text/markdown',
          'text/x-markdown'
        ]
        
        if (allowedTypes.includes(file.type) || 
            file.name.match(/\.(pdf|doc|docx|txt|md)$/i)) {
          this.selectedFile = file
          this.documentTitle = file.name.replace(/\.[^/.]+$/, "")
        } else {
          ElMessage.error('请选择 PDF、Word、TXT 或 Markdown 格式的文件')
        }
      }
    },

    removeFile() {
      this.selectedFile = null
      this.documentTitle = ''
      this.$refs.fileInput.value = ''
    },

    formatFileSize(bytes) {
      if (bytes === 0) return '0 Bytes'
      const k = 1024
      const sizes = ['Bytes', 'KB', 'MB', 'GB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
    },

    // ────── 历史文档面板 ──────
    async loadReqDocHistory() {
      this.reqDocHistoryError = false
      try {
        const response = await api.get('/requirement-analysis/api/req-docs/')
        this.reqDocHistory = response.data.results || response.data || []
        this.reqDocHistoryLoaded = true
        // 重建 docAnalysisMap（从后端持久化的 req_doc 关联恢复，刷新后不丢失）
        await this.rebuildDocAnalysisMap()
      } catch (error) {
        console.error('加载历史文档失败:', error)
        this.reqDocHistoryError = true
        this.reqDocHistoryLoaded = true
        this.reqDocHistory = []
      }
    },

    /** 根据历史需求文档列表，从后端批量查询每条文档的最新拆解结果，重建 docAnalysisMap */
    async rebuildDocAnalysisMap() {
      const ids = (this.reqDocHistory || []).map(d => d.id).filter(Boolean)
      if (!ids.length) {
        this.docAnalysisMap = {}
        return
      }
      try {
        const res = await getAnalysisResultsByDocs(ids)
        this.docAnalysisMap = (res.data && res.data.map) || {}
      } catch (e) {
        console.error('重建拆解关联失败:', e)
        this.docAnalysisMap = {}
      }
    },

    async viewHistoryDoc(doc) {
      // 加载完整内容，预览模式打开
      try {
        const response = await api.get(`/requirement-analysis/api/req-docs/${doc.id}/`)
        this.viewingDoc = response.data
        this.isEditingDoc = false
        this.showHistoryPreview = true
      } catch (error) {
        ElMessage.error('加载文档详情失败')
      }
    },

    async editHistoryDoc(doc) {
      // 加载完整内容，直接进入编辑模式
      try {
        const response = await api.get(`/requirement-analysis/api/req-docs/${doc.id}/`)
        this.viewingDoc = response.data
        this.editingMarkdown = response.data.markdown_content || ''
        this.editingTitle = response.data.title || ''
        this.isEditingDoc = true
        this.showHistoryPreview = true
      } catch (error) {
        ElMessage.error('加载文档详情失败')
      }
    },

    enterEditMode() {
      // 从预览模式切换到编辑模式
      if (!this.viewingDoc) return
      this.editingMarkdown = this.viewingDoc.markdown_content || ''
      this.editingTitle = this.viewingDoc.title || ''
      this.isEditingDoc = true
    },

    cancelEdit() {
      this.isEditingDoc = false
      this.editingMarkdown = ''
      this.editingTitle = ''
    },

    async saveDocEdit() {
      if (!this.viewingDoc || !this.editingMarkdown.trim()) return
      this.editingSaving = true
      try {
        const response = await api.patch(
          `/requirement-analysis/api/req-docs/${this.viewingDoc.id}/`,
          { title: this.editingTitle.trim(), markdown_content: this.editingMarkdown }
        )
        const updated = response.data
        // 更新 viewingDoc（包含后端返回的 updated_at 等）
        if (updated.markdown_content) {
          this.viewingDoc.markdown_content = updated.markdown_content
        }
        if (updated.title) {
          this.viewingDoc.title = updated.title
        }
        // 同步本地列表中的标题
        const idx = this.reqDocHistory.findIndex(d => d.id === this.viewingDoc.id)
        if (idx !== -1 && updated.title) {
          this.reqDocHistory[idx].title = updated.title
        }
        this.isEditingDoc = false
        ElMessage.success('文档已保存')
      } catch (error) {
        ElMessage.error('保存失败：' + (error.response?.data?.error || error.message))
      } finally {
        this.editingSaving = false
      }
    },

    closePreview() {
      this.showHistoryPreview = false
      this.isEditingDoc = false
      this.editingMarkdown = ''
      this.editingTitle = ''
    },

    async deleteReqDocHistory(doc) {
      try {
        await ElMessageBox.confirm(
          `确定删除「${doc.title || '未命名文档'}」？此操作不可恢复。`,
          '确认删除',
          { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
        )
      } catch {
        return
      }
      try {
        await api.delete(`/requirement-analysis/api/req-docs/${doc.id}/`)
        this.reqDocHistory = this.reqDocHistory.filter(d => d.id !== doc.id)
        ElMessage.success('已删除')
      } catch (error) {
        ElMessage.error('删除失败')
        console.error('删除历史文档失败:', error)
      }
    },

    async generateFromHistoryDoc(doc) {
      // 先加载文档，然后弹出确认弹窗
      try {
        const response = await api.get(`/requirement-analysis/api/req-docs/${doc.id}/`)
        const fullDoc = response.data
        const firstLine = (fullDoc.markdown_content || '').split('\n')[0].replace(/^#+\s*/, '').trim()
        const title = firstLine || fullDoc.title || '需求文档'
        
        // 打开确认弹窗，保存待生成的 payload
        this.pendingGeneratePayload = { title, content: fullDoc.markdown_content, source: 'history' }
        // 预填项目（如果历史文档有关联项目）
        const defaultProjectId = fullDoc.project?.id || null
        this.generateConfirmForm = {
          project_id: defaultProjectId,
          version_id: this.selectedVersion || null,
          feature_module_id: null,
          test_point_id: null,
          generation_mode: 'smart'
        }
        this.showGenerateConfirm = true
      } catch (error) {
        ElMessage.error('加载文档失败：' + (error.response?.data?.error || error.message))
      }
    },

    async generateFromPreviewDoc() {
      if (!this.viewingDoc) return
      const firstLine = (this.viewingDoc.markdown_content || '').split('\n')[0].replace(/^#+\s*/, '').trim()
      const title = firstLine || this.viewingDoc.title || '需求文档'
      
      // 打开确认弹窗
      this.pendingGeneratePayload = { title, content: this.viewingDoc.markdown_content, source: 'preview' }
      const defaultProjectId = this.viewingDoc.project?.id || null
      this.generateConfirmForm = {
        project_id: defaultProjectId,
        version_id: this.selectedVersion || null,
        feature_module_id: null,
        test_point_id: null,
        generation_mode: 'smart'
      }
      this.showGenerateConfirm = true
    },

    // 生成确认弹窗：项目切换时清空版本
    onConfirmProjectChange() {
      this.generateConfirmForm.version_id = null
      this.generateConfirmForm.feature_module_id = null
      this.generateConfirmForm.test_point_id = null
      this.moduleTestPoints = []
    },

    // 生成确认弹窗：功能模块切换时加载测试点
    async onConfirmFeatureModuleChange() {
      this.generateConfirmForm.test_point_id = null
      if (this.generateConfirmForm.feature_module_id) {
        await this.loadModuleTestPoints(this.generateConfirmForm.feature_module_id)
      } else {
        this.moduleTestPoints = []
      }
    },

    // 确认后开始生成
    async confirmStartGeneration() {
      if (!this.canConfirmGenerate) return

      // 拦截：仅当有拆解结果且存在未确认待确认项时才拦截
      // 没做拆解的用户可以直接走后续用例评审流程
      if (this.currentResultId && this.hasUnconfirmedItems) {
        ElMessage.warning(`请先在拆解结果中逐项确认所有待确认项（还剩 ${this.uncertainItems.filter(i => !i.confirmed).length} 条未确认）`)
        return
      }

      const payload = this.pendingGeneratePayload
      if (!payload) return
      
      const confirmedProjectId = this.generateConfirmForm.project_id
      const confirmedVersionId = this.generateConfirmForm.version_id
      const confirmedFeatureModuleId = this.generateConfirmForm.feature_module_id
      const confirmedTestPointId = this.generateConfirmForm.test_point_id
      const confirmedGenerationMode = this.generateConfirmForm.generation_mode || 'smart'
      
      // 同步到全局变量（供其他入口使用）
      this.selectedVersion = confirmedVersionId
      this.selectedProject = confirmedProjectId ? String(confirmedProjectId) : ''
      this.selectedFeatureModule = confirmedFeatureModuleId || null
      
      this.showGenerateConfirm = false
      try {
        await this.startGeneration(
          payload.title,
          payload.content,
          confirmedProjectId,
          this.globalOutputMode,
          confirmedVersionId,
          confirmedFeatureModuleId,
          confirmedTestPointId,
          confirmedGenerationMode
        )
        this.showHistoryPreview = false
      } catch (error) {
        console.error('生成失败:', error)
      } finally {
        this.pendingGeneratePayload = null
      }
    },
    // ────── END 历史文档面板 ──────

    // ────── 历史拆解结果面板 ──────
    async loadAnalysisResults() {
      this.analysisResultsError = false
      try {
        const response = await getAnalysisResults()
        this.analysisResults = response.data.results || response.data || []
        this.analysisResultsLoaded = true
      } catch (error) {
        console.error('加载拆解结果历史失败:', error)
        this.analysisResultsError = true
        this.analysisResultsLoaded = true
        this.analysisResults = []
      }
    },

    async saveAnalysisResult(resultContent, requirementText, projectId) {
      try {
        // 用需求文本首行作为标题
        const firstLine = (requirementText || '').split('\n')[0].trim()
        const title = firstLine ? firstLine.slice(0, 100) : '需求拆解结果'
        const preview = resultContent.slice(0, 200)
        // 解析关联的需求文档 ID：优先取当前正在拆解的文档；
        // 精炼场景下 currentAnalyzedDocId 已被清空，则从 docAnalysisMap 反查当前结果对应的文档
        let reqDocId = this.currentAnalyzedDocId || null
        if (!reqDocId && this.currentResultId) {
          const found = Object.entries(this.docAnalysisMap).find(
            ([, v]) => v && v.id === this.currentResultId
          )
          if (found) reqDocId = Number(found[0])
        }
        const response = await createAnalysisResult({
          title,
          requirement_text: requirementText || '',
          result_content: resultContent,
          content_preview: preview,
          project: projectId || null,
          req_doc: reqDocId
        })
        // 记录当前拆解结果 ID，供追问清单持久化关联
        if (response.data && response.data.id) {
          this.currentResultId = response.data.id
          // 关联到当前文档（每条文档只保留最新拆解）
          if (reqDocId) {
            this.docAnalysisMap[reqDocId] = {
              id: response.data.id,
              title: response.data.title || title
            }
          }
        }
        this.currentAnalyzedDocId = null
        // 静默刷新历史列表（不阻塞用户）
        this.loadAnalysisResults()
      } catch (error) {
        console.error('保存拆解结果历史失败:', error)
        this.currentAnalyzedDocId = null
      }
    },

    async viewAnalysisResult(result) {
      try {
        const response = await getAnalysisResultDetail(result.id)
        this.analyzeResult = response.data.result_content || ''
        this.extractAllUncertainItems()
        if (this.uncertainItems.length > 0) {
          this.$nextTick(() => { this.showUncertainDialog = true })
        }
        this.currentResultId = result.id
        this.currentRequirementText = response.data.requirement_text || ''
        this.currentProjectId = response.data.project || null
        this.clarificationItems = []
        this.showResultPreview = false
        ElMessage.success('已加载历史拆解结果')
        // 滚动到结果区域
        this.$nextTick(() => {
          const el = this.$el.querySelector('.analyze-result-card')
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        })
        // 加载该拆解结果下已保存的追问清单
        await this.loadClarifications()
      } catch (error) {
        ElMessage.error('加载拆解结果详情失败')
      }
    },

    async deleteAnalysisResult(result) {
      try {
        await ElMessageBox.confirm('确定删除这条拆解结果记录吗？', '删除确认', {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'warning'
        })
      } catch (e) {
        return  // 用户取消
      }
      try {
        await apiDeleteAnalysisResult(result.id)
        this.analysisResults = this.analysisResults.filter(r => r.id !== result.id)
        ElMessage.success('已删除')
      } catch (error) {
        ElMessage.error('删除失败: ' + (error.response?.data?.error || error.message))
      }
    },
    // ────── END 历史拆解结果面板 ──────

    // ────── 需求文档生成（后门流程）──────
    async generateReqDoc() {
      if (!this.canGenerateReqDoc) return
      this.reqDoc.isGenerating = true
      try {
        let payload
        if (this.reqDoc.inputMode === 'text') {
          payload = { raw_text: this.reqDoc.rawText }
        } else {
          // 文件模式：分离 vision 和 text 两类文档
          const textIds = []
          const visionIds = []
          for (const f of this.reqDoc.files) {
            if (f.isImagePdf && f.documentId) {
              visionIds.push(f.documentId)
            } else if (f.extracted && f.documentId) {
              textIds.push(f.documentId)
            }
          }
          if (visionIds.length) {
            // 有图片型 PDF → 走 vision 模式，文字型作为补充
            payload = {
              document_ids: visionIds,
              text_document_ids: textIds,
              raw_text: this.reqDoc.rawText || undefined
            }
          } else if (textIds.length) {
            // 纯文字型文档 → 走文字模式
            payload = {
              text_document_ids: textIds,
              raw_text: this.reqDoc.rawText || undefined
            }
          } else {
            // 兜底
            payload = { raw_text: this.reqDoc.rawText }
          }
        }
        // 附加项目 ID（用于后端读取该项目知识库辅助生成）
        if (this.reqDoc.selectedProject) {
          payload.project_id = Number(this.reqDoc.selectedProject)
        }
        const response = await api.post('/requirement-analysis/api/generate-req-doc/', payload, { timeout: 300000 })
        this.reqDoc.markdown = response.data.markdown
        // 记录刚生成的需求文档 ID，供后续「拆解此文档」时关联到该文档（否则历史列表按钮不会变「查看拆解」）
        this.currentAnalyzedDocId = response.data.doc_id || null
        ElMessage.success('需求文档生成成功，请检查并编辑后使用')
        // 刷新历史文档列表
        this.loadReqDocHistory()
      } catch (error) {
        console.error('生成需求文档失败:', error)
        ElMessage.error('生成失败：' + (error.response?.data?.error || error.message))
      } finally {
        this.reqDoc.isGenerating = false
      }
    },

    async getReqDocTemplate() {
      try {
        const response = await api.get('/requirement-analysis/api/req-doc-template/')
        this.reqDoc.markdown = response.data.template
        ElMessage.success('已加载空白模板，请填写内容')
      } catch (error) {
        ElMessage.error('获取模板失败')
      }
    },

    toggleReqDocPreview() {
      this.reqDoc.showPreview = !this.reqDoc.showPreview
    },

    resetReqDoc() {
      this.reqDoc.markdown = ''
      this.reqDoc.showPreview = false
      this.reqDoc.rawText = ''
      this.reqDoc.files = []
      this.reqDoc.isExtracting = false
      this.currentAnalyzedDocId = null  // 重置关联文档
      if (this.$refs.reqDocFileInput) this.$refs.reqDocFileInput.value = ''
      if (this.$refs.reqDocFolderInput) this.$refs.reqDocFolderInput.value = ''
    },

    // ── 共享：上传单个文件并提取文字 ──
    async _uploadOneFile(file, extraMeta = {}) {
      const entry = { file, documentId: null, isImagePdf: false, extracting: true, extracted: false, error: null, ...extraMeta }
      this.reqDoc.files.push(entry)
      const idx = this.reqDoc.files.length - 1
      try {
        const formData = new FormData()
        formData.append('title', file.name)
        formData.append('file', file)
        const uploadResp = await api.post('/requirement-analysis/api/documents/', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
        const docId = uploadResp.data.id
        this.reqDoc.files[idx].documentId = docId

        const extractResp = await api.get(`/requirement-analysis/api/documents/${docId}/extract_text/`)
        const text = extractResp.data.extracted_text

        if (text && text.trim().length >= 50) {
          this.reqDoc.files[idx].extracted = true
          this.reqDoc.files[idx].isImagePdf = false
          // 不累积到 rawText，generateReqDoc 走 document_ids 模式
        } else {
          this.reqDoc.files[idx].isImagePdf = true
          this.reqDoc.files[idx].extracted = false
        }
      } catch (error) {
        this.reqDoc.files[idx].error = error.response?.data?.error || error.message
      } finally {
        this.reqDoc.files[idx].extracting = false
      }
    },

    // ── 汇总+提示 ──
    _finishFileUpload(refName) {
      this.reqDoc.isExtracting = this.reqDoc.files.some(f => f.extracting)
      if (this.$refs[refName]) this.$refs[refName].value = ''

      const allDone = this.reqDoc.files.filter(f => !f.error)
      const textCount = allDone.filter(f => f.extracted).length
      const imgCount = allDone.filter(f => f.isImagePdf).length
      const errCount = this.reqDoc.files.filter(f => f.error).length

      if (allDone.length === textCount + imgCount && !errCount && this.reqDoc.files.length > 0) {
        const parts = []
        if (textCount) parts.push(`${textCount} 个文字提取成功`)
        if (imgCount) parts.push(`${imgCount} 个图片型PDF将由AI视觉识别`)
        ElMessage.success(parts.join('，') + '，可点击生成文档')
      } else if (errCount) {
        ElMessage.warning(`${errCount} 个文件处理失败，请检查`)
      }
    },

    // ── 多文件选择 → 逐文件上传提取 ──
    async handleReqDocFileSelect(event) {
      const newFiles = Array.from(event.target.files)
      if (!newFiles.length) return
      for (const file of newFiles) {
        await this._uploadOneFile(file)
      }
      this._finishFileUpload('reqDocFileInput')
    },

    // ── 文件夹选择 → 遍历文件夹内所有文件 ──
    async handleReqDocFolderSelect(event) {
      const rawFiles = Array.from(event.target.files)
      if (!rawFiles.length) return

      // 提取文件夹名（从第一个文件的 webkitRelativePath 取第一段）
      const firstPath = rawFiles[0].webkitRelativePath || rawFiles[0].name
      const folderName = firstPath.split('/')[0]

      // 过滤支持的文件类型
      const supportedExts = ['pdf', 'doc', 'docx', 'txt', 'md']
      const validFiles = rawFiles.filter(f => {
        const ext = f.name.split('.').pop().toLowerCase()
        return supportedExts.includes(ext)
      })

      if (!validFiles.length) {
        ElMessage.warning('该文件夹内没有支持的文档文件')
        if (this.$refs.reqDocFolderInput) this.$refs.reqDocFolderInput.value = ''
        return
      }

      ElMessage.info(`正在读取文件夹「${folderName}」内 ${validFiles.length} 个文件…`)

      for (const file of validFiles) {
        await this._uploadOneFile(file, {
          folder: folderName,
          relativePath: file.webkitRelativePath || file.name
        })
      }
      this._finishFileUpload('reqDocFolderInput')
    },

    // ── 删除操作（适配分组索引） ──
    removeReqDocFile(groupIdx, fileIdx) {
      // 找到该分组在 files 数组中的实际索引
      let cursor = 0
      for (let g = 0; g < this.fileGroups.length; g++) {
        if (g === groupIdx) {
          const targetIdx = cursor + fileIdx
          this.reqDoc.files.splice(targetIdx, 1)
          break
        }
        cursor += this.fileGroups[g].items.length
      }
      this.reqDoc.rawText = ''  // 清空 rawText，generateReqDoc 从 document_ids 取
      this.reqDoc.isExtracting = this.reqDoc.files.some(f => f.extracting)
    },

    removeFolder(groupIdx) {
      let cursor = 0
      for (let g = 0; g < this.fileGroups.length; g++) {
        if (g === groupIdx) {
          this.reqDoc.files.splice(cursor, this.fileGroups[g].items.length)
          break
        }
        cursor += this.fileGroups[g].items.length
      }
      this.reqDoc.rawText = ''
      this.reqDoc.isExtracting = this.reqDoc.files.some(f => f.extracting)
    },

    removeFlatFile(flatIdx) {
      // flatFiles 对应的是 files 中 folder 为空的条目
      const target = this.flatFiles[flatIdx]
      if (!target) return
      const realIdx = this.reqDoc.files.indexOf(target)
      if (realIdx !== -1) {
        this.reqDoc.files.splice(realIdx, 1)
      }
      this.reqDoc.rawText = ''
      this.reqDoc.isExtracting = this.reqDoc.files.some(f => f.extracting)
    },

    clearReqDocFiles() {
      this.reqDoc.files = []
      this.reqDoc.rawText = ''
      this.reqDoc.isExtracting = false
      if (this.$refs.reqDocFileInput) this.$refs.reqDocFileInput.value = ''
      if (this.$refs.reqDocFolderInput) this.$refs.reqDocFolderInput.value = ''
    },

    async useReqDocForGeneration() {
      if (!this.reqDoc.markdown.trim()) return
      const firstLine = this.reqDoc.markdown.split('\n')[0].replace(/^#+\s*/, '').trim()
      const title = firstLine || '需求文档'
      // 弹出确认弹窗
      this.pendingGeneratePayload = { title, content: this.reqDoc.markdown, source: 'reqDoc' }
      this.generateConfirmForm = {
        project_id: this.reqDoc.selectedProject ? Number(this.reqDoc.selectedProject) : null,
        version_id: this.selectedVersion || null,
        feature_module_id: null,
        test_point_id: null,
        generation_mode: 'smart'
      }
      this.showGenerateConfirm = true
    },
    // ────── END 需求文档生成 ──────

    async generateFromManualInput() {
      if (!this.canGenerateManual) {
        ElMessage.error('请填写完整的需求信息')
        return
      }

      const requirementText = `需求标题: ${this.manualInput.title}\n\n需求描述:\n${this.manualInput.description}`
      // 弹出确认弹窗
      this.pendingGeneratePayload = { title: this.manualInput.title, content: requirementText, source: 'manual' }
      this.generateConfirmForm = {
        project_id: this.manualInput.selectedProject ? Number(this.manualInput.selectedProject) : null,
        version_id: this.selectedVersion || null,
        feature_module_id: null,
        test_point_id: null,
        generation_mode: 'smart'
      }
      this.showGenerateConfirm = true
    },

    // 通用拆解核心：接受任意文本+图片，结果写入 this.analyzeResult
    async callAnalyzeAPI(requirement_text, project_id = null, images = []) {
      if (!requirement_text.trim() && images.length === 0) {
        ElMessage.error('请提供需求内容（文本或截图）')
        return false
      }
      this.analyzeLoading = true
      this.analyzeResult = ''
      this.clarificationItems = []
      this.currentResultId = null
      this.showDeepQuestion = false
      this.currentRequirementText = requirement_text || ''
      this.currentProjectId = project_id || null
      try {
        const response = await api.post('/requirement-analysis/api/testcase-generation/analyze/', {
          requirement_text,
          project_id,
          images
        })
        // 兼容多种返回结构：{result: '...'} / 直接字符串 / 其他
        let result = response.data && response.data.result
        if (result === undefined || result === null) {
          result = (typeof response.data === 'string') ? response.data : JSON.stringify(response.data)
        }
        if (!result || !String(result).trim()) {
          ElMessage.error('需求拆解返回为空，请检查提示词配置或重试')
          return false
        }
        this.analyzeResult = String(result)
        ElMessage.success('需求拆解完成')
        // 拆解成功后自动保存到历史记录
        this.saveAnalysisResult(String(result), requirement_text, project_id)
        // 提取待确认项，供人工逐项确认（对齐 AI 用例评审闭环）
        this.extractAllUncertainItems()
        // 自动弹出确认对话框
        if (this.uncertainItems.length > 0) {
          this.$nextTick(() => { this.showUncertainDialog = true })
        }
        return true
      } catch (error) {
        console.error('需求拆解失败:', error)
        ElMessage.error('需求拆解失败: ' + (error.response?.data?.error || error.message))
        return false
      } finally {
        this.analyzeLoading = false
      }
    },

    async analyzeRequirement() {
      const requirement_text = `需求标题: ${this.manualInput.title}\n\n需求描述:\n${this.manualInput.description}`
      await this.callAnalyzeAPI(
        requirement_text,
        this.manualInput.selectedProject ? Number(this.manualInput.selectedProject) : null,
        this.analyzeImages
      )
    },

    hasUploadedFiles() {
      return this.reqDoc.files && this.reqDoc.files.length > 0
    },

    async analyzeFromReqDocInput() {
      // 优先取手动输入文本，其次取 AI 已生成的 markdown（上传文件→生成文档后 rawText 会被清空）
      const text = (this.reqDoc.rawText || this.reqDoc.markdown || '').trim()
      let images = []
      if (!text && !this.hasUploadedFiles()) {
        ElMessage.error('请先粘贴文字、上传文件或生成需求文档')
        return
      }
      await this.callAnalyzeAPI(
        text,
        this.reqDoc.selectedProject ? Number(this.reqDoc.selectedProject) : null,
        images
      )
    },

    async analyzeFromReqDocMarkdown() {
      const text = (this.reqDoc.markdown || '').trim()
      if (!text) { ElMessage.error('文档内容为空'); return }
      await this.callAnalyzeAPI(
        text,
        this.reqDoc.selectedProject ? Number(this.reqDoc.selectedProject) : null
      )
    },

    async analyzeFromHistoryDoc(doc) {
      // 列表接口只返回 content_preview（前200字），不含完整 markdown_content，
      // 若列表项无完整内容，先拉详情接口获取完整文档
      let text = (doc.markdown_content || doc.content || '').trim()
      if (!text) {
        try {
          const res = await api.get(`/requirement-analysis/api/req-docs/${doc.id}/`)
          text = (res.data.markdown_content || res.data.content || '').trim()
        } catch (e) {
          // 拉取失败则用 preview 兜底
          text = (doc.content_preview || '').trim()
        }
      }
      if (!text) { ElMessage.error('文档内容为空，请先查看并保存该文档'); return }
      this.currentAnalyzedDocId = doc.id
      await this.callAnalyzeAPI(text, doc.project_id ? Number(doc.project_id) : null)
    },

    async analyzeFromPreviewDoc() {
      if (!this.viewingDoc) return
      const text = (this.viewingDoc.markdown_content || this.editingMarkdown || '').trim()
      if (!text) { ElMessage.error('文档内容为空'); return }
      this.currentAnalyzedDocId = this.viewingDoc.id
      await this.callAnalyzeAPI(text)
    },

    /** 查看某文档的拆解结果（回填到主结果区） */
    async viewDocAnalysis(doc) {
      const cached = this.docAnalysisMap[doc.id]
      if (!cached || !cached.id) return
      try {
        const response = await getAnalysisResultDetail(cached.id)
        this.analyzeResult = response.data.result_content || ''
        this.currentResultId = cached.id
        this.currentRequirementText = response.data.requirement_text || ''
        this.extractAllUncertainItems()
        // 滚动到结果区并显示
        this.showResults = true
        this.isGenerating = false
        if (this.uncertainItems.length > 0) {
          this.$nextTick(() => { this.showUncertainDialog = true })
        }
      } catch (e) {
        ElMessage.error('加载拆解结果失败')
      }
    },

    onAnalyzeImageChange(e) {
      const files = e.target.files
      if (!files || !files.length) return
      Array.from(files).forEach(file => {
        const reader = new FileReader()
        reader.onload = () => {
          this.analyzeImages.push(reader.result)
        }
        reader.readAsDataURL(file)
      })
      e.target.value = ''
    },

    removeAnalyzeImage(idx) {
      this.analyzeImages.splice(idx, 1)
    },

    copyAnalyzeResult() {
      const text = this.analyzeResult
      if (navigator.clipboard && text) {
        navigator.clipboard.writeText(text).then(
          () => ElMessage.success('已复制到剪贴板'),
          () => ElMessage.error('复制失败')
        )
      }
    },

    copyMatrixToClipboard() {
      if (navigator.clipboard && this.analyzeResult) {
        navigator.clipboard.writeText(this.analyzeResult).then(
          () => ElMessage.success('插接矩阵已复制到剪贴板'),
          () => ElMessage.error('复制失败')
        )
      }
    },

    // ── 深度追问（流式 SSE） ──
    async sendDeepQuestion() {
      const question = this.deepQuestionInput.trim()
      if (!question) return
      // 注意：先不立即清空输入框，等发送成功后再清空；失败则保留内容以便重试
      // 加入用户消息（用于上下文历史）
      this.deepChatMessages.push({ role: 'user', content: question })
      this.deepChatLoading = true
      this.deepStreamingContent = ''
      this.$nextTick(() => this.scrollToDeepBottom())

      try {
        const token = localStorage.getItem('access_token') || ''
        const baseUrl = (api.defaults.baseURL || '/api').replace(/\/$/, '')
        const resp = await fetch(`${baseUrl}/requirement-analysis/api/deep-question/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({
            question,
            context: this.analyzeResult,
            history: this.deepChatMessages.slice(0, -1).map(m => ({ role: m.role, content: m.content }))
          })
        })
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          // 处理 SSE 行
          const lines = buf.split('\n')
          buf = lines.pop() || ''
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6).trim()
              if (data === '[DONE]') continue
              try {
                const j = JSON.parse(data)
                if (j.content !== undefined) {
                  this.deepStreamingContent += j.content
                  this.$nextTick(() => this.scrollToDeepBottom())
                }
                if (j.error) throw new Error(j.error)
              } catch (e) {
                if (e.message !== 'Unexpected end of JSON input') console.warn('SSE parse:', e)
              }
            }
          }
        }
        // 完成
        this.deepChatMessages.push({ role: 'assistant', content: this.deepStreamingContent })
        this.deepStreamingContent = ''
        this.deepQuestionInput = ''  // 仅发送成功后才清空输入框
      } catch (err) {
        console.error('深度追问失败:', err)
        const errMsg = err.message || '追问失败，请重试'
        this.deepChatMessages.push({ role: 'assistant', content: `⚠️ ${errMsg}` })
        // 回滚：移除本次失败临时加入的用户消息，并保留输入框内容以便重试
        if (this.deepChatMessages[this.deepChatMessages.length - 2]?.role === 'user') {
          this.deepChatMessages.splice(this.deepChatMessages.length - 2, 1)
        }
        this.deepQuestionInput = question
      } finally {
        this.deepChatLoading = false
        this.$nextTick(() => this.scrollToDeepBottom())
      }
    },

    scrollToDeepBottom() {
      const el = this.$refs.deepQuestionScroll
      if (el) el.scrollTop = el.scrollHeight
    },

    // ── 结构化追问 Q&A（表格模式） ──

    /** 从服务端加载当前拆解结果关联的追问清单，成功返回 true */
    async loadClarifications() {
      if (!this.currentResultId) return false
      try {
        const response = await getClarifications({ analysis_result: this.currentResultId })
        const items = response.data.results || response.data || []
        if (Array.isArray(items) && items.length > 0) {
          this.clarificationItems = items.map((it, i) => ({
            id: Date.now() + i,
            question: it.question,
            answer: it.answer || '',
            status: it.status || 'pending',
            category: it.category || '其他'
          }))
          this.qaMode = 'table'
          return true
        }
      } catch (e) {
        console.error('加载追问清单失败:', e)
      }
      return false
    },

    /** 将当前追问清单整体持久化到服务端（关联 currentResultId） */
    async saveClarifications() {
      // 若尚未有关联的拆解结果历史，先自动落库
      if (!this.currentResultId && this.analyzeResult) {
        await this.saveAnalysisResult(
          this.analyzeResult,
          this.currentRequirementText || '',
          this.currentProjectId || null
        )
      }
      if (!this.currentResultId) return
      try {
        const items = this.clarificationItems.map(it => ({
          question: it.question,
          answer: it.answer || '',
          category: it.category || '其他',
          status: it.status || 'pending'
        }))
        await saveAllClarifications({ analysis_result: this.currentResultId, items })
      } catch (e) {
        console.error('保存追问清单失败:', e)
      }
    },

    /** 切换追问面板时，优先加载已保存的追问，否则自动生成 */
    async toggleDeepQuestion() {
      this.showDeepQuestion = !this.showDeepQuestion
      if (this.showDeepQuestion) {
        const loaded = await this.loadClarifications()
        if (!loaded && this.clarificationItems.length === 0) {
          await this.generateClarificationQuestions()
        }
      }
    },

    /** AI 生成结构化追问清单 */
    async generateClarificationQuestions() {
      if (!this.analyzeResult || this.qaGenerating) return
      this.qaGenerating = true
      try {
        const token = localStorage.getItem('access_token') || ''
        const baseUrl = (api.defaults.baseURL || '/api').replace(/\/$/, '')
        const resp = await fetch(`${baseUrl}/requirement-analysis/api/deep-question/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({
            question: '请基于上述需求拆解结果，重点提取其中的「待确认事项」表格（Q-01、Q-02…每一行）以及所有「⚠️ 待确认」「待确认风险」标记的内容，把它们【逐条】作为需要人工确认的追问项，原样保留问题描述。然后再补充其他边界条件、异常场景、数据依赖或业务规则的不明确点。\n\n以 JSON 数组格式返回，每项包含：\n- question（问题文本，若是待确认事项请保留原描述，如「Q-01: xxx」）\n- category（分类：待确认项/边界条件/异常场景/数据依赖/业务规则/其他）\n返回 5-10 个高质量追问，待确认事项必须排在前面。',
            context: this.analyzeResult,
            history: []
          })
        })
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        // 读完整响应
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let fullText = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          fullText += decoder.decode(value, { stream: true })
        }
        this.parseClarificationQuestions(fullText)
      } catch (err) {
        console.error('生成追问失败:', err)
        // fallback: 从拆解结果中用正则提取编号问题
        this.extractQuestionsFromResult()
      } finally {
        this.qaGenerating = false
      }
      // 生成后持久化
      if (this.clarificationItems.length > 0) {
        this.qaMode = 'table'
        this.saveClarifications()
      }
    },

    /** 解析 AI 返回的追问为结构化数组 */
    parseClarificationQuestions(text) {
      // 尝试提取 JSON 数组
      const jsonMatch = text.match(/\[[\s\S]*?\]/)
      if (jsonMatch) {
        try {
          const items = JSON.parse(jsonMatch[0])
          if (Array.isArray(items) && items.length > 0) {
            this.clarificationItems = items.map((item, i) => ({
              id: Date.now() + i,
              question: item.question || String(item),
              answer: '',
              status: 'pending',
              category: item.category || '其他'
            }))
            return
          }
        } catch (e) { /* 不是有效 JSON，走 fallback */ }
      }
      // fallback: 按编号列表解析
      this.extractQuestionsFromText(text)
    },

    /** 从文本中提取编号问题（fallback） */
    extractQuestionsFromText(text) {
      const lines = text.split('\n')
      const questions = []
      const re = /^\s*(\d+)[\.、．]\s*(.+)/
      for (const line of lines) {
        const m = line.match(re)
        if (m) {
          questions.push({
            id: Date.now() + questions.length,
            question: m[2].trim(),
            answer: '',
            status: 'pending',
            category: '待分类'
          })
        }
      }
      if (questions.length > 0) {
        this.clarificationItems = questions
        this.qaMode = 'table'  // 提取成功后切到表格模式
      } else {
        // 最后的 fallback: 从拆解结果中提取
        this.extractQuestionsFromResult()
      }
    },

    /** 从拆解结果 markdown 中提取可能的追问点 */
    extractQuestionsFromResult() {
      const text = this.analyzeResult || ''
      const questions = []

      // ① 优先提取「待确认事项」表格（Q-01 / Q-02 ... 行）
      const secMatch = text.split(/(?=^#{1,6}\s*.*待确认)/m)
      for (const sec of secMatch) {
        if (!/待确认/.test(sec)) continue
        const rows = sec.split('\n')
        for (const line of rows) {
          const cells = line.split('|').map(c => c.trim()).filter(c => c !== '')
          // 形如 Q-01 | 问题 | 建议 | 阻塞风险
          if (cells.length >= 2 && /^Q-?\d+/i.test(cells[0])) {
            questions.push({
              id: Date.now() + questions.length,
              question: `${cells[0]}: ${cells[1]}`,
              answer: '',
              status: 'pending',
              category: '待确认项'
            })
          }
        }
      }

      // ② 没提取到则退化为全文疑问特征扫描
      if (questions.length === 0) {
        const qRe = /(?:是否|如何|什么|哪个|多少|能否|会不会|\?|？|边界|限制|条件|规则|异常).{5,100}/
        for (const line of text.split('\n')) {
          const trimmed = line.replace(/^#{1,6}\s*/, '').trim()
          if (trimmed.length > 15 && trimmed.length < 200 && qRe.test(trimmed)) {
            questions.push({
              id: Date.now() + questions.length,
              question: trimmed,
              answer: '',
              status: 'pending',
              category: '自动提取'
            })
          }
        }
      }

      // 去重并限制数量
      const seen = new Set()
      this.clarificationItems = questions.filter(q => {
        if (seen.has(q.question)) return false
        seen.add(q.question)
        return true
      }).slice(0, 10)
      // 提取到追问后自动切换到表格模式
      if (this.clarificationItems.length > 0) {
        this.qaMode = 'table'
      }
    },

    /** 从拆解结果中【全面】提取所有待确认项（对齐 AI 用例评审 uncertain_items） */
    extractAllUncertainItems(excludeList) {
      const text = this.analyzeResult || ''
      const items = []
      const seen = new Set()
      const exclude = new Set((excludeList || []).map(s => String(s).trim()).filter(Boolean))
      const push = (question, context) => {
        const key = String(question).trim()
        if (!key || seen.has(key) || exclude.has(key)) return
        seen.add(key)
        items.push({
          id: Date.now() + items.length,
          question: question.trim(),
          context: context || '',
          answer: '',
          confirmed: false
        })
      }

      // ① 待确认事项表格（Q-01 / Q-02 ... 每一行）
      const secParts = text.split(/(?=^#{1,6}\s*.*待确认)/m)
      for (const sec of secParts) {
        if (!/待确认/.test(sec)) continue
        for (const line of sec.split('\n')) {
          const cells = line.split('|').map(c => c.trim()).filter(c => c !== '')
          if (cells.length >= 2 && /^Q-?\d+/i.test(cells[0])) {
            push(`${cells[0]}: ${cells[1]}`, cells.slice(2).join(' | '))
          }
        }
      }

      // ② 行内 ⚠️ 待确认 标记（⚠️ 待确认：xxx），排除方括号形式避免重复
      const warnRe = /(?<!\[)⚠️\s*待确认[：:]\s*(.+?)(?=\n|$)/g
      let m
      while ((m = warnRe.exec(text)) !== null) {
        push(`⚠️ 待确认：${m[1].trim()}`, '')
      }
      // ③ 方括号形式 [⚠️ 待确认: xxx]
      const bracketRe = /\[\s*⚠️\s*待确认[：:]\s*(.+?)\s*\]/g
      while ((m = bracketRe.exec(text)) !== null) {
        push(`⚠️ 待确认：${m[1].trim()}`, '')
      }

      // ④ ★ 深度追问清单 / 追问清单（编号列表：1. **关于xxx**：问题描述...）
      const dqSections = text.split(/(?=^#{1,6}\s*.*(?:深度)?追问)/m)
      for (const sec of dqSections) {
        if (!/(深度)?追问/.test(sec)) continue
        // 匹配编号行：1. **关于"xxx"**：描述内容   或   1. **主题**：描述
        const numRe = /^\s*(\d+)[\.、．)\]]\s*\*\*(.+?)\*\*[：:：]\s*(.+)/
        for (const line of sec.split('\n')) {
          const nm = line.match(numRe)
          if (nm) {
            push(`${nm[1]}. ${nm[2].trim()}`, nm[3].trim())
          }
        }
      }

      this.uncertainItems = items
    },

    /** 基于已确认项精炼拆解结果（对齐 AI 用例评审 resolve_replies 闭环） */
    async refineAndContinue() {
      const confirmedItems = this.uncertainItems.filter(i => i.confirmed)
      if (confirmedItems.length === 0) {
        ElMessage.warning('请先逐项确认（可留空表示采纳 AI 推测）')
        return
      }
      const replies = confirmedItems.map(i => ({
        question: i.question,
        answer: i.answer || i.context || '',
        context: i.context || ''
      }))
      // 已确认的问题文本，精炼后重新提取时跳过，避免重复弹出造成死循环
      const confirmedTexts = confirmedItems.map(i => i.question.trim())
      this.refining = true
      try {
        const res = await refineAnalysis({
          original_report: this.analyzeResult,
          resolve_replies: replies
        })
        if (res.data && res.data.report) {
          this.analyzeResult = res.data.report
          this.saveAnalysisResult(this.analyzeResult, this.currentRequirementText, this.currentProjectId)
          // 精炼成功后，自动将确认的问答回填到项目知识库（非阻塞，避免影响用户体验）
          if (this.selectedProject && confirmedItems.length > 0) {
            autoFillKnowledgeFromConfirmations(
              Number(this.selectedProject),
              confirmedItems.map(i => ({ question: i.question, answer: i.answer || i.context || '' }))
            ).then(res => {
              if (res.data && res.data.created_count > 0) {
                ElMessage.success(`已自动补充 ${res.data.created_count} 条知识到项目知识库`)
              }
            }).catch(() => {})  // 静默失败，不影响主流程
          }
          this.extractAllUncertainItems(confirmedTexts)
          if (this.uncertainItems.length === 0) {
            ElMessage.success('所有待确认项已消除，可继续生成测试用例')
          } else {
            ElMessage.success('已根据确认精炼拆解结果，仍有待确认项请继续确认')
          }
        } else if (res.data && res.data.error) {
          ElMessage.error(res.data.error)
        }
      } catch (e) {
        ElMessage.error(e.response?.data?.error || '精炼失败')
      } finally {
        this.refining = false
      }
    },

    /** 确认并精炼后关闭弹窗 */
    async refineAndClose() {
      await this.refineAndContinue()
      if (this.uncertainItems.length === 0) {
        this.showUncertainDialog = false
      }
    },

    /** 回答某条追问 */
    answerQuestion(id, answer) {
      const item = this.clarificationItems.find(i => i.id === id)
      if (item) {
        item.answer = answer
        item.status = 'answered'
      }
    },

    /** 确认某条回答（标记已确认） */
    confirmAnswer(id) {
      const item = this.clarificationItems.find(i => i.id === id)
      if (item) {
        item.status = 'confirmed'
        this.saveClarifications()
      }
    },

    /** 追加手动提问 */
    addManualQuestion() {
      const q = prompt('输入新的追问问题:')
      if (q && q.trim()) {
        this.clarificationItems.push({
          id: Date.now(),
          question: q.trim(),
          answer: '',
          status: 'pending',
          category: '手动'
        })
        this.saveClarifications()
      }
    },

    /** 切换表格/聊天模式 */
    switchQAMode(mode) {
      this.qaMode = mode
    },

    statusText(status) {
      return { pending: '待回复', answered: '已回复', confirmed: '已确认' }[status] || status
    },

    removeQAItem(id) {
      this.clarificationItems = this.clarificationItems.filter(i => i.id !== id)
      this.saveClarifications()
    },

    escapeHtml(text) {
      if (!text) return ''
      return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    },

    // ── Markdown 表格解析器：将 AI 返回的 markdown 拆解为结构化 section 数组 ──
    parseAnalyzeMarkdown(md) {
      const sections = []
      const lines = md.split('\n')
      let i = 0

      while (i < lines.length) {
        const line = lines[i].trim()

        // 跳过空行
        if (!line) { i++; continue }

        // 匹配标题 ### 1. xxx 或 ## xxx
        const headingMatch = line.match(/^(#{1,4})\s+(.+)/)
        if (headingMatch) {
          const title = headingMatch[2].replace(/^\d+\.\s*/, '').trim()
          i++

          // 收集后续非空行直到下一个同级或更高级标题
          const contentLines = []
          while (i < lines.length) {
            const cl = lines[i].trim()
            // 遇到同级别或更高级标题就停止
            if (cl.match(/^#{1,4}\s+/)) break
            contentLines.push(lines[i])
            i++
          }

          // 解析内容区域中的表格和文本
          const parsed = this.parseContentBlock(contentLines)
          sections.push({ title, ...parsed })
          continue
        }

        // 无标题的普通段落
        const paraLines = []
        while (i < lines.length && lines[i].trim() && !lines[i].trim().match(/^#{1,4}\s+/)) {
          paraLines.push(lines[i])
          i++
        }
        if (paraLines.length) {
          sections.push({ type: 'text', text: paraLines.join('\n').trim() })
        }
      }

      return sections
    },

    parseContentBlock(lines) {
      // 找出所有表格行（以 | 开头和结尾的行）
      const tableRanges = []
      let tableStart = -1

      for (let j = 0; j < lines.length; j++) {
        const l = lines[j].trim()
        if (l.startsWith('|') && l.endsWith('|')) {
          if (tableStart === -1) tableStart = j
        } else if (l.match(/^\|[-:|]+\|$/)) {
          // 分隔行，跳过，继续收集
        } else {
          if (tableStart !== -1) {
            tableRanges.push({ start: tableStart, end: j })
            tableStart = -1
          }
        }
      }
      if (tableStart !== -1) tableRanges.push({ start: tableStart, end: lines.length })

      // 如果有表格且表格占内容主体 → 当作表格解析；否则当作 KV 对
      let totalTableRows = 0
      for (const range of tableRanges) {
        for (let k = range.start; k < range.end; k++) {
          if (!lines[k].trim().match(/^\|[-:|]+\|$/)) totalTableRows++
        }
      }

      // 判断是 KV 表（2列）还是多列表格
      if (totalTableRows >= 2) {
        // 尝试解析为多列表格
        const allRows = []
        for (const range of tableRanges) {
          for (let k = range.start; k < range.end; k++) {
            const l = lines[k].trim()
            if (!l || l.match(/^\|[-:|]+\|$/)) continue
            allRows.push(this.splitTableRow(l))
          }
        }
        if (allRows.length >= 2) {
          const headers = allRows[0]
          const dataRows = allRows.slice(1)
          // 如果只有2列且第一列都是短标签名 → 也当 KV 处理
          if (headers.length === 2 && dataRows.every(r => r[0] && r[0].length <= 15)) {
            return { type: 'kv', rows: dataRows }
          }
          return { type: 'table', headers, rows: dataRows }
        }
      }

      // KV 解析：找 |字段|内容| 格式的行
      const kvRows = []
      for (const range of tableRanges) {
        for (let k = range.start; k < range.end; k++) {
          const l = lines[k].trim()
          if (!l || l.match(/^\|[-:|]+\|$/)) continue
          const cells = this.splitTableRow(l)
          if (cells.length === 2) kvRows.push(cells)
        }
      }
      if (kvRows.length > 0) return { type: 'kv', rows: kvRows }

      // 纯文本兜底
      const text = lines.map(l => l.trim()).filter(Boolean).join('\n')
      return { type: 'text', text }
    },

    splitTableRow(line) {
      // 去掉首尾 | 再按 | 分割
      return line.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
    },

    onCellEdit(sectionIdx, rowIdx, colIdx, event) {
      const newVal = event.target.textContent.trim()
      const section = this.parsedAnalyzeSections[sectionIdx]
      if (!section || !section.rows) return
      // 直接修改 rows 引用（Vue 响应式会追踪）
      if (section.rows[rowIdx]) {
        section.rows[rowIdx][colIdx] = newVal
      }
    },

    exportAnalyzeToMarkdown() {
      const sections = this.parsedAnalyzeSections
      if (!sections.length) return this.analyzeResult

      let md = ''
      for (const s of sections) {
        md += `\n### ${s.title}\n\n`
        if (s.type === 'kv' && s.rows && s.rows.length) {
          md += '| 字段 | 内容 |\n|------|------|\n'
          for (const r of s.rows) {
            md += `| ${r[0] || ''} | ${r[1] || ''} |\n`
          }
        } else if (s.type === 'table' && s.headers && s.headers.length) {
          md += '| ' + s.headers.join(' | ') + ' |\n'
          md += '|' + s.headers.map(() => '------').join('|') + '|\n'
          for (const r of s.rows) {
            md += '| ' + r.map(c => c || '').join(' | ') + ' |\n'
          }
        } else if (s.type === 'text') {
          md += s.text + '\n'
        }
      }
      return md.trim()
    },

    async generateFromDocument() {
      if (!this.selectedFile || !this.documentTitle) {
        ElMessage.error('请选择文件并输入文档标题')
        return
      }

      try {
        // 首先上传并提取文档内容
        const formData = new FormData()
        formData.append('title', this.documentTitle)
        formData.append('file', this.selectedFile)
        if (this.selectedProject) {
          formData.append('project', this.selectedProject)
        }

        ElMessage.info('正在提取文档内容...')
        const uploadResponse = await api.post('/requirement-analysis/api/documents/', formData, {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        })

        // 提取文档内容
        const extractResponse = await api.get(`/requirement-analysis/api/documents/${uploadResponse.data.id}/extract_text/`)
        const extractedText = extractResponse.data.extracted_text

        if (!extractedText || extractedText.trim().length === 0) {
          ElMessage.error('无法从文档中提取到有效内容，请检查文档格式')
          return
        }

        const requirementText = `文档标题: ${this.documentTitle}\n\n文档内容:\n${extractedText}`

        // 弹出确认弹窗
        this.pendingGeneratePayload = { title: this.documentTitle, content: requirementText, source: 'document' }
        this.generateConfirmForm = {
          project_id: this.selectedProject ? Number(this.selectedProject) : null,
          version_id: this.selectedVersion || null,
          feature_module_id: null,
          test_point_id: null,
          generation_mode: 'smart'
        }
        this.showGenerateConfirm = true

      } catch (error) {
        console.error('文档处理失败:', error)
        ElMessage.error('文档处理失败: ' + (error.response?.data?.error || error.message))
      }
    },

    async startGeneration(title, requirementText, projectId, outputMode = 'stream', versionId = '', featureModuleId = null, testPointId = null, generationMode = 'smart') {
      // 在开始生成前，主动刷新token确保生成过程中不会过期
      try {
        const userStore = useUserStore()
        if (userStore.isTokenExpiringSoon && userStore.refreshToken) {
          console.log('生成前主动刷新token...')
          await userStore.refreshAccessToken()
          console.log('Token刷新成功，可以安全开始生成')
        } else if (userStore.accessToken) {
          console.log('Token状态良好，无需刷新')
        }
      } catch (error) {
        console.error('Token刷新失败:', error)
        ElMessage.error('Token刷新失败，请重新登录')
        return
      }

      this.isGenerating = true
      this.currentStep = 1
      this.progressText = '正在创建生成任务...'
      this.streamedContent = ''  // 清空流式内容
      this.finalTestCases = ''  // 清空最终版用例
      this.streamedReviewContent = ''  // 清空评审内容
      this.hasShownCompletionMessage = false  // 重置完成消息标志位
      this.showResults = false  // 隐藏上一次的结果

      try {
        // 调用新的生成API
        const requestData = {
          title: title,
          requirement_text: requirementText,
          use_writer_model: true,
          use_reviewer_model: this.showReviewStep,
          output_mode: outputMode,  // 添加输出模式参数
          generation_mode: generationMode  // 生成模式
        }

        // 将需求拆解阶段确认的问答对传入，供用例生成时作为上下文注入（让AI基于确认结论精准出例）
        const confirmedItems = (this.uncertainItems || []).filter(i => i.confirmed)
        if (confirmedItems.length > 0) {
          requestData.confirmed_answers = JSON.stringify(
            confirmedItems.map(i => ({
              question: i.question || '',
              answer: i.answer || i.context || ''
            }))
          )
        }

        // 如果选择了项目，添加到请求中
        if (projectId) {
          requestData.project = projectId
        }
        // 如果选择了版本，添加到请求中
        if (versionId) {
          requestData.version = versionId
        }
        // 如果选择了功能模块，添加到请求中
        if (featureModuleId) {
          requestData.feature_module = featureModuleId
        }
        // 如果选择了测试点，添加到请求中
        if (testPointId) {
          requestData.test_point = testPointId
        }

        const response = await api.post('/requirement-analysis/api/testcase-generation/generate/', requestData)

        this.currentTaskId = response.data.task_id
        this.progressText = '任务已创建，正在处理中...'

        ElMessage.success('测试用例生成任务已启动')

        // 根据输出模式选择不同的进度获取方式
        if (outputMode === 'stream') {
          this.startStreamingProgress()
        } else {
          this.startPolling()
        }

      } catch (error) {
        console.error('创建生成任务失败:', error)
        ElMessage.error('创建任务失败: ' + (error.response?.data?.error || error.message))
        this.isGenerating = false
      }
    },

    startStreamingProgress() {
      // 使用SSE进行流式进度获取
      // 注意：EventSource不使用axios代理，需要直接指向后端服务器
      // 完整的URL路径: /api/requirement-analysis/api/testcase-generation/{task_id}/stream_progress/
      const isDev = import.meta.env.DEV
      const baseUrl = isDev ? 'http://127.0.0.1:8000' : ''
      const apiUrl = `${baseUrl}/api/requirement-analysis/api/testcase-generation/${this.currentTaskId}/stream_progress/`

      console.log('SSE连接URL:', apiUrl)

      // 创建EventSource（不支持自定义headers，使用withCredentials发送cookie）
      this.eventSource = new EventSource(apiUrl, { withCredentials: true })

      // 监听连接打开事件
      this.eventSource.onopen = (event) => {
        console.log('✅ SSE连接已打开', event)
      }

      this.eventSource.onmessage = (event) => {
        console.log('📨 收到SSE消息:', event.data)

        try {
          const data = JSON.parse(event.data)
          console.log('📦 解析后的数据:', data)

          if (data.type === 'progress') {
            // 更新进度状态
            if (data.status === 'generating') {
              this.currentStep = 2
              this.progressText = `正在编写测试用例... ${data.progress}%`
            } else if (data.status === 'reviewing') {
              this.currentStep = 3
              this.progressText = `正在评审测试用例... ${data.progress}%`
            } else if (data.status === 'revising') {
              this.currentStep = 3
              this.progressText = `正在生成最终版用例... ${data.progress}%`
            }
          } else if (data.type === 'content') {
            // 实时接收流式内容（用例生成）
            console.log('✍️ 收到流式内容:', data.content.length, '个字符')
            this.streamedContent += data.content
            this.currentStep = 2
            this.progressText = '正在生成测试用例...'
          } else if (data.type === 'review_content') {
            // 实时接收评审内容
            console.log('📝 收到评审内容:', data.content.length, '个字符', '当前总长度:', this.streamedReviewContent.length + data.content.length)
            this.streamedReviewContent += data.content
            this.currentStep = 3
            this.progressText = '正在评审测试用例...'
          } else if (data.type === 'final_content') {
            // 实时接收最终版用例内容
            console.log('🎯 收到最终用例内容:', data.content.length, '个字符', '当前总长度:', this.finalTestCases.length + data.content.length)
            this.finalTestCases += data.content
            this.currentStep = 3
            this.progressText = '🎯 正在流式生成最终版用例...'
          } else if (data.type === 'status') {
            // 最终状态
            console.log('📊 收到状态更新:', data.status)
            if (data.status === 'completed') {
              this.progressText = '生成完成！'
              // 获取最终结果
              this.fetchFinalResult()
            } else if (data.status === 'failed') {
              this.progressText = '生成失败'
              this.handleGenerationError()
            }
          } else if (data.type === 'done') {
            // 流式结束，立即关闭EventSource，获取最终结果
            console.log('✅ 流式传输完成')
            if (this.eventSource) {
              console.log('🔒 关闭SSE连接')
              this.eventSource.close()
              this.eventSource = null
            }
            this.fetchFinalResult()
          }
        } catch (e) {
          console.error('❌ 解析SSE数据失败:', e, '原始数据:', event.data)
        }
      }

      this.eventSource.onerror = (error) => {
        console.log('⚠️ SSE连接事件:', error)

        // 如果EventSource已经被关闭（在onmessage中关闭的），不做任何处理
        if (!this.eventSource) {
          console.log('ℹ️ EventSource已关闭，忽略错误事件')
          return
        }

        console.log('EventSource状态:', {
          readyState: this.eventSource.readyState,
          url: this.eventSource.url
        })

        // 如果任务已经完成或不在生成中，不要降级
        if (this.showResults || !this.isGenerating) {
          console.log('ℹ️ 任务已完成或不在生成中，不降级到轮询')
          // 清理EventSource
          if (this.eventSource) {
            this.eventSource.close()
            this.eventSource = null
          }
          return
        }

        // readyState=0表示连接中断，可能需要降级到轮询模式
        // 但由于我们在done消息中主动关闭了连接，这里再次检查状态
        if (this.eventSource.readyState === 0) {
          console.error('❌ SSE连接中断，降级到轮询模式')
          this.eventSource.close()
          this.eventSource = null
          ElMessage.warning('流式连接中断，切换到轮询模式')
          this.startPolling()
        }
      }
    },

    async fetchFinalResult() {
      try {
        // 修复URL：去掉多余的/api/前缀（axios baseURL已经包含/api）
        const response = await api.get(`/requirement-analysis/api/testcase-generation/${this.currentTaskId}/progress/`)
        const task = response.data

        this.generationResult = task
        this.showResults = true
        this.isGenerating = false

        // 设置第4步为完成状态
        this.currentStep = 4

        // 设置最终版用例（如果还没有通过流式接收完整）
        if (task.final_test_cases) {
          console.log('📝 从task对象获取最终用例')
          // 无论this.finalTestCases是否已有值，都用最新的final_test_cases覆盖
          // 这样确保完整输出模式下也能正确显示最终版用例
          this.finalTestCases = task.final_test_cases
        }

        // 如果评审内容为空，从task对象中获取
        if (!this.streamedReviewContent && task.review_feedback) {
          console.log('📝 从task对象获取评审内容')
          this.streamedReviewContent = task.review_feedback
        }

        // 如果生成内容为空，从task对象中获取
        if (!this.streamedContent && task.generated_test_cases) {
          console.log('✍️ 从task对象获取生成内容')
          this.streamedContent = task.generated_test_cases
        }

        if (this.eventSource) {
          this.eventSource.close()
          this.eventSource = null
        }

        // 只显示一次完成消息
        if (!this.hasShownCompletionMessage) {
          ElMessage.success('测试用例生成完成！')
          this.hasShownCompletionMessage = true
        }
      } catch (error) {
        console.error('获取最终结果失败:', error)
        ElMessage.error('获取结果失败')
        this.isGenerating = false
      }
    },

    handleGenerationError() {
      this.isGenerating = false
      if (this.eventSource) {
        this.eventSource.close()
        this.eventSource = null
      }
      if (this.pollInterval) {
        clearInterval(this.pollInterval)
        this.pollInterval = null
      }
    },

    startPolling() {
      this.pollInterval = setInterval(async () => {
        try {
          // 修复URL：去掉多余的/api/前缀（axios baseURL已经包含/api）
          const response = await api.get(`/requirement-analysis/api/testcase-generation/${this.currentTaskId}/progress/`)
          const task = response.data

          console.log(`轮询 - 任务状态: ${task.status}, 进度: ${task.progress}%`)

          // 更新进度显示
          if (task.status === 'generating') {
            this.currentStep = 2
            this.progressText = '正在编写测试用例...'
          } else if (task.status === 'reviewing') {
            this.currentStep = 3
            this.progressText = '正在评审测试用例...'
          } else if (task.status === 'completed') {
            this.currentStep = 4
            this.progressText = '生成完成！'

            // 任务完成，显示结果
            this.generationResult = task
            this.showResults = true
            this.isGenerating = false

            // 设置显示内容（完整输出模式下需要）
            if (task.generated_test_cases) {
              console.log('✍️ 轮询模式 - 设置生成内容')
              this.streamedContent = task.generated_test_cases
            }
            if (task.review_feedback) {
              console.log('📝 轮询模式 - 设置评审内容')
              this.streamedReviewContent = task.review_feedback
            }
            if (task.final_test_cases) {
              console.log('🎯 轮询模式 - 设置最终版用例')
              this.finalTestCases = task.final_test_cases
            }

            clearInterval(this.pollInterval)
            this.pollInterval = null

            // 只显示一次完成消息
            if (!this.hasShownCompletionMessage) {
              ElMessage.success('测试用例生成完成！')
              this.hasShownCompletionMessage = true
            }
            return
          } else if (task.status === 'failed') {
            this.progressText = '生成失败'
            this.isGenerating = false

            clearInterval(this.pollInterval)
            this.pollInterval = null

            ElMessage.error('测试用例生成失败: ' + (task.error_message || '未知错误'))
            return
          }

        } catch (error) {
          console.error('轮询 - 检查任务进度失败:', error)
          // 继续轮询，不中断
        }
      }, 3000) // 每3秒检查一次
    },

    cancelGeneration() {
      if (this.pollInterval) {
        clearInterval(this.pollInterval)
        this.pollInterval = null
      }
      this.isGenerating = false
      this.currentTaskId = null
      ElMessage.info('已取消生成任务')
    },

    // 下载测试用例为xlsx文件
    async downloadTestCases() {
      try {
        if (!this.generationResult || !this.generationResult.task_id) {
          ElMessage.warning('没有可下载的生成结果，请先完成用例生成')
          return
        }
        // 解析最终测试用例内容
        const finalTestCases = this.generationResult.final_test_cases;
        const taskId = this.generationResult.task_id;

        // 创建工作簿
        const workbook = XLSX.utils.book_new();

        // 过滤掉总结和建议部分，只保留测试用例内容
        const filteredContent = this.filterTestCasesOnly(finalTestCases);

        // 尝试解析表格格式的测试用例（参考AutoGenTestCase的做法）
        const tableFormat = this.parseTableFormat(filteredContent);

        let worksheetData = [];

        if (tableFormat.length > 0) {
          // 如果解析到表格格式，直接使用，但要确保表头正确
          worksheetData = tableFormat;
          
          // 检查并修正表头
          if (worksheetData.length > 0) {
            const header = worksheetData[0];
            for (let i = 0; i < header.length; i++) {
              if (header[i] && header[i].includes('测试步骤')) {
                header[i] = header[i].replace('测试步骤', '操作步骤');
              }
              if (header[i] && header[i].includes('Test Steps')) {
                header[i] = header[i].replace('Test Steps', '操作步骤');
              }
            }
          }
        } else {
          // 否则尝试解析结构化格式
          worksheetData = this.parseStructuredFormat(filteredContent);
        }

        // 将所有单元格中的<br>标签转换为换行符
        worksheetData = worksheetData.map(row =>
          row.map(cell => this.convertBrToNewline(cell))
        );

        // 创建工作表
        const worksheet = XLSX.utils.aoa_to_sheet(worksheetData);

        // 设置列宽
        const colWidths = [
          { wch: 15 }, // 测试用例编号
          { wch: 30 }, // 测试场景
          { wch: 25 }, // 前置条件
          { wch: 40 }, // 操作步骤
          { wch: 30 }, // 预期结果
          { wch: 10 }  // 优先级
        ];
        worksheet['!cols'] = colWidths;

        // 设置表头样式（加粗）
        if (worksheetData.length > 1) {
          for (let col = 0; col < Math.min(6, worksheetData[0].length); col++) {
            const cellAddress = XLSX.utils.encode_cell({ r: 0, c: col });
            if (!worksheet[cellAddress]) continue;
            worksheet[cellAddress].s = {
              font: { bold: true },
              alignment: { horizontal: 'center', vertical: 'center', wrapText: true }
            };
          }
          
          // 设置自动换行
          for (let row = 1; row < worksheetData.length; row++) {
            for (let col = 0; col < Math.min(6, worksheetData[row].length); col++) {
              const cellAddress = XLSX.utils.encode_cell({ r: row, c: col });
              if (worksheet[cellAddress]) {
                worksheet[cellAddress].s = {
                  alignment: { vertical: 'top', wrapText: true }
                };
              }
            }
          }
        }

        // 将工作表添加到工作簿
        XLSX.utils.book_append_sheet(workbook, worksheet, '测试用例');

        // 生成文件名（包含任务ID和日期）
        const fileName = `测试用例_${taskId}_${new Date().toISOString().slice(0, 10)}.xlsx`;

        // 导出文件
        XLSX.writeFile(workbook, fileName);

        ElMessage.success('测试用例下载成功');
      } catch (error) {
        console.error('下载测试用例失败:', error);
        ElMessage.error('下载测试用例失败: ' + (error.message || '未知错误'));
      }
    },

    // 保存到用例记录
    async saveToTestCaseRecords() {
      try {
        if (!this.generationResult || !this.generationResult.task_id) {
          ElMessage.warning('没有可保存的生成结果，请先完成用例生成')
          return
        }
        // 调用后端API保存到记录
        const response = await api.post(`/requirement-analysis/api/testcase-generation/${this.generationResult.task_id}/save_to_records/`)

        if (response.data.already_saved) {
          ElMessage.info('测试用例已经保存过了')
        } else {
          const importedCount = response.data.imported_count || 0
          ElMessage.success(`测试用例已保存！已导入 ${importedCount} 条测试用例到测试用例管理系统`)
        }

        // 不跳转，留在当前页面
        // this.$router.push('/generated-testcases')
      } catch (error) {
        console.error('保存测试用例失败:', error)
        ElMessage.error('保存测试用例失败: ' + (error.response?.data?.error || error.message))
      }
    },

    resetGeneration() {
      // 重置生成状态
      this.isGenerating = false;
      this.currentTaskId = null;
      this.progressText = '准备开始生成...';
      this.currentStep = 0;
      this.showResults = false;
      this.generationResult = null;

      // 清空流式内容和最终版用例
      this.streamedContent = '';
      this.streamedReviewContent = '';
      this.finalTestCases = '';

      if (this.pollInterval) {
        clearInterval(this.pollInterval);
        this.pollInterval = null;
      }

      // 刷新页面以获取最新的配置
      window.location.reload();
    },

    // 格式化日期时间
    formatDateTime(dateTimeString) {
      if (!dateTimeString) return '';
      const date = new Date(dateTimeString);
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      const hours = String(date.getHours()).padStart(2, '0');
      const minutes = String(date.getMinutes()).padStart(2, '0');
      return `${year}-${month}-${day} ${hours}:${minutes}`;
    },

    // 格式化Markdown为HTML（简化版）
    formatMarkdown(content) {
      if (!content) return '';

      // 先去除"新增"标记，在markdown转换之前处理
      // 这样可以避免markdown转换后无法匹配的问题
      let html = content
        .replace(/\*\*新增\*\*-/g, '')  // **新增**-xxx -> xxx (保留xxx的原有格式)
        .replace(/新增-/g, '');  // 新增-xxx -> xxx (保留xxx的原有格式)

      // 转义HTML特殊字符
      html = html
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

      // 转换Markdown语法
      // 标题 #
      html = html.replace(/^#{6}\s+(.+)$/gm, '<h6>$1</h6>');
      html = html.replace(/^#{5}\s+(.+)$/gm, '<h5>$1</h5>');
      html = html.replace(/^#{4}\s+(.+)$/gm, '<h4>$1</h4>');
      html = html.replace(/^#{3}\s+(.+)$/gm, '<h3>$1</h3>');
      html = html.replace(/^#{2}\s+(.+)$/gm, '<h2>$1</h2>');
      html = html.replace(/^#{1}\s+(.+)$/gm, '<h1>$1</h1>');

      // 粗体 **text** 或 __text__
      html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

      // 斜体 *text* 或 _text_
      html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
      html = html.replace(/_(.+?)_/g, '<em>$1</em>');

      // 代码块 ```code```
      html = html.replace(/```([\s\S]+?)```/g, '<pre><code>$1</code></pre>');

      // 行内代码 `code`
      html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

      // 换行符转换为<br>
      html = html.replace(/\n/g, '<br>');

      return html;
    },

    // 将 markdown 中的表格转为 HTML <table>（用于插接矩阵弹窗）
    convertMarkdownTablesToHtml(text) {
      if (!text) return ''
      let html = text
      // 匹配连续的表格行（|...| 开头的行）
      const tableRegex = /^((?:\|.+\|\n?)+)/gm
      html = html.replace(tableRegex, (tableBlock) => {
        const lines = tableBlock.trim().split('\n').filter(l => l.trim())
        if (lines.length < 2) return tableBlock // 至少需要表头+分隔行
        // 解析表头（第一行）
        const headers = this.parseTableRow(lines[0])
        // 跳过分隔行（第二行，---|---）
        const dataLines = lines.slice(2)
        if (dataLines.length === 0 && lines.length === 2) return '' // 只有表头无数据则跳过
        // 构建 HTML table
        let tableHtml = '<div class="matrix-table-wrapper"><table class="matrix-table"><thead><tr>'
        for (const h of headers) {
          tableHtml += `<th>${this.escapeCell(h)}</th>`
        }
        tableHtml += '</tr></thead><tbody>'
        for (let i = 0; i < dataLines.length; i++) {
          const cells = this.parseTableRow(dataLines[i])
          // 如果单元格数少于表头数，补空
          while (cells.length < headers.length) cells.push('')
          tableHtml += '<tr'
          if (i % 2 === 1) tableHtml += ' class="alt-row"'
          tableHtml += '>'
          for (const c of cells) {
            tableHtml += `<td>${this.formatCellContent(c)}</td>`
          }
          tableHtml += '</tr>'
        }
        tableHtml += '</tbody></table></div>'
        return tableHtml
      })
      // 处理剩余非表格文本：标题 + 粗体 + 换行
      html = html.replace(/^#{1,3}\s+(.+)$/gm, '<h4>$1</h4>')
      html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      html = html.replace(/\n{2,}/g, '</p><p>')
      html = html.replace(/\n/g, '<br>')
      if (html && !html.startsWith('<')) html = '<p>' + html + '</p>'
      return html
    },
    parseTableRow(line) {
      return line.split('|').map(c => c.trim()).filter((c, i, arr) => {
        // 过滤首尾空元素，但保留中间空单元格
        if (i === 0 || i === arr.length - 1) return c !== ''
        return true
      })
    },
    escapeCell(text) {
      if (!text) return ''
      return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    },
    formatCellContent(text) {
      if (!text) return ''
      let cell = this.escapeCell(text)
      // 处理编号列表: **1. xxx** → 编号加粗
      cell = cell.replace(/\*\*(\d+[.、．]\s*.+?)\*\*/g, '<span class="matrix-item-num">$1</span>')
      // 处理剩余粗体
      cell = cell.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // 处理 <br> 标签（AI 输出中可能含有的）
      cell = cell.replace(/<br\s*\/?>/gi, '<br>')
      return cell
    },

    // 将HTML的<br>标签转换为换行符（用于Excel导出）
    convertBrToNewline(text) {
      if (!text) return '';
      return text.replace(/<br\s*\/?>/gi, '\n');
    },

    // 过滤掉总结和建议部分，只保留测试用例内容
    filterTestCasesOnly(content) {
      if (!content) return '';

      const lines = content.split('\n');
      const filteredLines = [];
      let inTestCaseSection = true;
      
      for (let line of lines) {
        const trimmedLine = line.trim();
        
        // 检查是否到了总结或建议部分
        if (trimmedLine.includes('总结') || 
            trimmedLine.includes('建议') || 
            trimmedLine.includes('Summary') || 
            trimmedLine.includes('Recommendation') ||
            trimmedLine.includes('最后') ||
            trimmedLine.includes('补充说明')) {
          inTestCaseSection = false;
          break;
        }
        
        if (inTestCaseSection) {
          filteredLines.push(line);
        }
      }
      
      return filteredLines.join('\n');
    },

    // 解析表格格式的测试用例（参考AutoGenTestCase的做法）
    parseTableFormat(content) {
      if (!content) return [];
      
      const lines = content.split('\n').filter(line => line.trim());
      const worksheetData = [];
      
      for (let line of lines) {
        const trimmedLine = line.trim();
        
        // 检查是否是表格行（包含|分隔符，且不是分隔线）
        if (trimmedLine.includes('|') && !trimmedLine.includes('--------')) {
          let cells = trimmedLine.split('|').map(cell => cell.trim())
          // 移除首尾空字符串（split('|') 在首尾会产生空字符串）
          while (cells.length > 0 && cells[0] === '') cells.shift()
          while (cells.length > 0 && cells[cells.length - 1] === '') cells.pop()
          if (cells.length > 1) {
            worksheetData.push(cells);
          }
        }
      }
      
      return worksheetData;
    },

    // 解析结构化格式的测试用例
    parseStructuredFormat(content) {
      if (!content) return [];
      
      const lines = content.split('\n').filter(line => line.trim());
      const worksheetData = [];
      
      // 添加表头
      worksheetData.push(['测试用例编号', '测试场景', '前置条件', '操作步骤', '预期结果', '优先级']);
      
      let currentTestCase = {};
      let testCaseNumber = 1;
      let i = 0;
      
      while (i < lines.length) {
        const line = lines[i].trim();
        
        // 识别测试用例开始标志
        if (line.includes('测试用例') || line.includes('Test Case') || 
            line.match(/^(\d+\.|\*|\-|\d+、)/)) {
          
          // 如果之前有测试用例数据，先保存
          if (Object.keys(currentTestCase).length > 0) {
            worksheetData.push([
              currentTestCase.number || `TC${testCaseNumber}`,
              currentTestCase.scenario || '',
              currentTestCase.precondition || '',
              currentTestCase.steps || '',
              currentTestCase.expected || '',
              currentTestCase.priority || '中'
            ]);
            testCaseNumber++;
          }
          
          // 开始新的测试用例
          currentTestCase = {
            number: `TC${testCaseNumber}`,
            scenario: line.replace(/^(\d+\.|\*|\-|\d+、)\s*/, '').replace(/测试用例\d*[:：]?\s*/, ''),
            precondition: '',
            steps: '',
            expected: '',
            priority: '中'
          };
          i++;
        }
        // 识别前置条件
        else if (line.includes('前置条件') || line.includes('前提') || 
                 line.includes('Precondition')) {
          let precondition = line.replace(/.*?[:：]\s*/, '');
          // 收集后续的前置条件行
          i++;
          while (i < lines.length) {
            const nextLine = lines[i].trim();
            if (nextLine.includes('测试步骤') || nextLine.includes('操作步骤') || 
                nextLine.includes('Test Steps') || nextLine.includes('步骤') ||
                nextLine.includes('预期结果') || nextLine.includes('Expected') ||
                nextLine.includes('优先级') || nextLine.includes('Priority') ||
                nextLine.includes('测试用例') || nextLine.includes('Test Case') ||
                nextLine.match(/^(\d+\.|\*|\-|\d+、)/)) {
              break;
            }
            if (nextLine) {
              precondition += '\n' + nextLine;
            }
            i++;
          }
          currentTestCase.precondition = precondition;
        }
        // 识别测试步骤
        else if (line.includes('测试步骤') || line.includes('操作步骤') || 
                 line.includes('Test Steps') || line.includes('步骤')) {
          let steps = line.replace(/.*?[:：]\s*/, '');
          // 收集后续的步骤行
          i++;
          while (i < lines.length) {
            const nextLine = lines[i].trim();
            if (nextLine.includes('预期结果') || nextLine.includes('Expected') ||
                nextLine.includes('优先级') || nextLine.includes('Priority') ||
                nextLine.includes('测试用例') || nextLine.includes('Test Case') ||
                nextLine.match(/^(\d+\.|\*|\-|\d+、)/)) {
              break;
            }
            if (nextLine) {
              steps += '\n' + nextLine;
            }
            i++;
          }
          currentTestCase.steps = steps;
        }
        // 识别预期结果
        else if (line.includes('预期结果') || line.includes('Expected') || 
                 line.includes('期望')) {
          let expected = line.replace(/.*?[:：]\s*/, '');
          // 收集后续的结果行
          i++;
          while (i < lines.length) {
            const nextLine = lines[i].trim();
            if (nextLine.includes('优先级') || nextLine.includes('Priority') ||
                nextLine.includes('测试用例') || nextLine.includes('Test Case') ||
                nextLine.match(/^(\d+\.|\*|\-|\d+、)/)) {
              break;
            }
            if (nextLine) {
              expected += '\n' + nextLine;
            }
            i++;
          }
          currentTestCase.expected = expected;
        }
        // 识别优先级
        else if (line.includes('优先级') || line.includes('Priority')) {
          currentTestCase.priority = line.replace(/.*?[:：]\s*/, '');
          i++;
        }
        // 如果是没有明确标识的行，可能是场景描述的延续
        else if (Object.keys(currentTestCase).length > 0 && 
                 !currentTestCase.steps && !currentTestCase.expected && 
                 !currentTestCase.precondition) {
          if (currentTestCase.scenario && line.length > 5) {
            currentTestCase.scenario += '\n' + line;
          }
          i++;
        } else {
          i++;
        }
      }
      
      // 保存最后一个测试用例
      if (Object.keys(currentTestCase).length > 0) {
        worksheetData.push([
          currentTestCase.number || `TC${testCaseNumber}`,
          currentTestCase.scenario || '',
          currentTestCase.precondition || '',
          currentTestCase.steps || '',
          currentTestCase.expected || '',
          currentTestCase.priority || '中'
        ]);
      }
      
      // 如果没有解析到结构化数据，则按原格式输出
      if (worksheetData.length <= 1) {
        worksheetData.length = 0; // 清空
        worksheetData.push(['测试用例内容']);
        content.split('\n').forEach((line, index) => {
          if (line.trim()) {
            worksheetData.push([line.trim()]);
          }
        });
      }
      
      return worksheetData;
    }
  }
}
</script>

<style scoped>
.requirement-analysis {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
  position: relative;
}

.page-header {
  text-align: center;
  margin-bottom: 40px;
}

.page-header h1 {
  font-size: 2.5rem;
  color: #2c3e50;
  margin-bottom: 10px;
}

.page-header p {
  color: #666;
  font-size: 1.1rem;
}

/* 输出模式设置区域 - 全局 */
.output-mode-section {
  margin-bottom: 30px;
}

.output-mode-card {
  background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border: 1px solid rgba(226, 232, 240, 0.8);
  transition: all 0.3s ease;
}

.output-mode-card:hover {
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
}

.output-mode-card h3 {
  font-size: 1.3rem;
  color: #1a202c;
  margin: 0 0 8px 0;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.mode-section-desc {
  color: #64748b;
  font-size: 0.9rem;
  margin: 0 0 16px 0;
  line-height: 1.5;
}

/* 配置引导弹出窗口 */
.modal-overlay {
  position: fixed !important;
  top: 0 !important;
  left: 0 !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  background: rgba(15, 23, 42, 0.6) !important;
  backdrop-filter: blur(4px);
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  z-index: 9999 !important;
  padding: 20px;
  margin: 0 !important;
  opacity: 1 !important;
}

.guide-config-modal {
  background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%) !important;
  border-radius: 24px;
  padding: 36px;
  max-width: 850px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(226, 232, 240, 0.8);
  position: relative;
  flex-shrink: 0;
  margin: auto;
  opacity: 1 !important;
}

.guide-config-modal::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 5px;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  border-radius: 24px 24px 0 0;
}

.guide-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 28px;
}

.guide-icon {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  filter: drop-shadow(0 4px 8px rgba(245, 158, 11, 0.2));
}

.guide-title h2 {
  font-size: 1.6rem;
  color: #1a202c;
  margin: 0 0 6px 0;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.guide-title p {
  color: #64748b;
  font-size: 0.95rem;
  margin: 0;
  font-weight: 400;
}

.config-groups {
  margin-bottom: 24px;
}

.config-group {
  margin-bottom: 20px;
}

.group-label {
  font-size: 0.85rem;
  color: #94a3b8;
  margin-bottom: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.config-items-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}

.config-item-inline {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-radius: 12px;
  border: 2px solid transparent;
  position: relative;
  overflow: hidden;
  font-weight: 500;
}

.config-item-inline::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: 12px 0 0 12px;
}

.config-item-inline.optional {
  opacity: 0.75;
}

/* 根据状态设置背景色和样式 */
.config-item-inline.status-enabled {
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.9) 0%, rgba(220, 252, 231, 0.6) 100%);
  border-color: rgba(34, 197, 94, 0.2);
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.1);
}

.config-item-inline.status-enabled::before {
  background: linear-gradient(180deg, #22c55e 0%, #16a34a 100%);
}

.config-item-inline.status-disabled {
  background: linear-gradient(135deg, rgba(254, 249, 195, 0.9) 0%, rgba(254, 240, 138, 0.6) 100%);
  border-color: rgba(234, 179, 8, 0.2);
  box-shadow: 0 4px 12px rgba(234, 179, 8, 0.1);
}

.config-item-inline.status-disabled::before {
  background: linear-gradient(180deg, #eab308 0%, #ca8a04 100%);
}

.config-item-inline.status-unconfigured {
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.9) 0%, rgba(254, 226, 226, 0.6) 100%);
  border-color: rgba(239, 68, 68, 0.2);
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.1);
}

.config-item-inline.status-unconfigured::before {
  background: linear-gradient(180deg, #ef4444 0%, #dc2626 100%);
}

.status-symbol {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  font-size: 20px;
}

.config-label {
  font-size: 0.95rem;
  color: #334155;
  font-weight: 600;
  flex-shrink: 0;
}

.config-name {
  font-size: 0.85rem;
  color: #64748b;
  margin-left: 4px;
  font-weight: 500;
}

.status-text {
  margin-left: auto;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 700;
  background: #ef4444;
  color: white;
  white-space: nowrap;
  box-shadow: 0 2px 6px rgba(239, 68, 68, 0.2);
}

.status-text.warning {
  background: #eab308;
  box-shadow: 0 2px 6px rgba(234, 179, 8, 0.2);
}

.guide-actions {
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
  gap: 12px;
  margin-top: 30px;
  width: 100%;
}

.guide-actions button {
  flex: none !important;
  width: 240px !important;
  height: 50px !important;
  padding: 0 24px !important;
  border-radius: 12px;
  font-size: 0.95rem;
  font-weight: 600;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  text-align: center;
  white-space: nowrap;
  opacity: 1 !important;
  cursor: pointer;
  box-sizing: border-box !important;
}

.guide-actions .generate-manual-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
  color: white !important;
  border: 2px solid transparent !important;
  box-shadow: 0 2px 10px rgba(102, 126, 234, 0.3);
}

.guide-actions .skip-action {
  font-size: 0.85rem;
  color: #94a3b8;
  cursor: pointer;
  text-decoration: none;
  padding: 4px 8px;
  transition: color 0.3s;
}

.guide-actions .skip-action:hover {
  color: #64748b;
  text-decoration: underline;
}


.manual-input-card, .upload-card {
  background: white;
  border-radius: 12px;
  padding: 30px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  border: 1px solid #e1e8ed;
  margin-bottom: 30px;
}

.manual-input-card h2, .upload-card h2 {
  color: #2c3e50;
  margin-bottom: 20px;
  font-size: 1.5rem;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #2c3e50;
}

/* 输出模式选择器 */
.output-mode-selector {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.mode-option {
  position: relative;
  cursor: pointer;
}

.mode-option input[type="radio"] {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.mode-content {
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  transition: all 0.3s ease;
  background: white;
}

.mode-option:hover .mode-content {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
}

.mode-option.active .mode-content {
  border-color: #3b82f6;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  box-shadow: 0 4px 16px rgba(59, 130, 246, 0.2);
}

.mode-title {
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 6px;
}

.mode-desc {
  font-size: 0.85rem;
  color: #64748b;
  line-height: 1.4;
}

.mode-option.active .mode-title {
  color: #2563eb;
}

.mode-option.active .mode-desc {
  color: #475569;
}

.form-input, .form-select, .form-textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 1rem;
  transition: border-color 0.3s ease;
}

.form-input:focus, .form-select:focus, .form-textarea:focus {
  outline: none;
  border-color: #3498db;
  box-shadow: 0 0 0 2px rgba(52, 152, 219, 0.2);
}

.form-textarea {
  resize: vertical;
  font-family: inherit;
}

.char-count {
  text-align: right;
  font-size: 0.85rem;
  color: #666;
  margin-top: 5px;
}

.required {
  color: #e74c3c;
}

.generate-manual-btn, .generate-btn {
  background: #27ae60;
  color: white;
  border: none;
  padding: 15px 30px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1.1rem;
  transition: background 0.3s ease;
  width: 100%;
  margin-top: 10px;
}

.generate-manual-btn:hover:not(:disabled), .generate-btn:hover:not(:disabled) {
  background: #219a52;
}

.generate-manual-btn:disabled, .generate-btn:disabled {
  background: #bdc3c7;
  cursor: not-allowed;
}

/* 需求拆解按钮 */
.analyze-btn {
  background: #6366f1;
  color: white;
  border: none;
  padding: 15px 30px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1.1rem;
  transition: background 0.3s ease;
  width: 100%;
  margin-top: 10px;
}

.analyze-btn:hover:not(:disabled) {
  background: #4f46e5;
}

.analyze-btn:disabled {
  background: #c7c9f0;
  cursor: not-allowed;
}

/* 需求截图上传 */
.analyze-image-group {
  margin-top: 14px;
}

.analyze-image-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}

.analyze-image-item {
  position: relative;
  width: 90px;
  height: 90px;
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: hidden;
}

.analyze-image-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.analyze-image-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  cursor: pointer;
  line-height: 18px;
  font-size: 14px;
}

/* 拆解结果卡片 */
.analyze-result-card {
  margin-top: 18px;
  border: 1px solid #e0e0ff;
  border-radius: 10px;
  background: #fafaff;
  overflow: hidden;
}

.analyze-result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #eef0ff;
  border-bottom: 1px solid #e0e0ff;
}

.analyze-result-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #4f46e5;
}

.analyze-result-actions button {
  border: 1px solid #c7c9f0;
  background: #fff;
  color: #4f46e5;
  border-radius: 6px;
  padding: 4px 12px;
  margin-left: 8px;
  cursor: pointer;
  font-size: 0.85rem;
}

.analyze-result-actions button:hover {
  background: #4f46e5;
  color: #fff;
}

.analyze-result-body {
  padding: 16px;
  max-height: 520px;
  overflow-y: auto;
}

/* 拆解结果操作按钮（新版） */
.analyze-action-btn {
  border: 1px solid #c7c9f0;
  background: #fff;
  color: #4f46e5;
  border-radius: 6px;
  padding: 4px 12px;
  margin-left: 6px;
  cursor: pointer;
  font-size: 0.82rem;
  transition: all .2s;
}
.analyze-action-btn:hover { background: #eef0ff; }
.analyze-action-btn.active { background: #4f46e5; color: #fff; }
.analyze-action-btn.primary { background: #4f46e5; color: #fff; }
.analyze-action-btn.primary:hover { background: #4338ca; }
.analyze-action-btn.close { color: #94a3b8; border-color: #e2e8f0; }
.analyze-action-btn.close:hover { background: #fee2e2; color: #dc2626; border-color: #fecaca; }

/* 编辑模式文本框 */
.result-edit-textarea {
  width: 100%;
  min-height: 400px;
  max-height: 520px;
  padding: 14px 16px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.88rem;
  line-height: 1.7;
  color: #334155;
  resize: vertical;
  outline: none;
  box-sizing: border-box;
  background: #fefefe;
}
.result-edit-textarea:focus { border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79,70,229,.12); }

/* ── Markdown 渲染样式（美化版） ── */
.markdown-body {
  font-size: 0.9rem;
  line-height: 1.85;
  color: #334155;
  word-wrap: break-word;
}
.markdown-body h1, .markdown-body h2, .markdown-body h3,
.markdown-body h4, .markdown-body h5, .markdown-body h6 {
  margin: 16px 0 8px;
  font-weight: 600;
  color: #1e293b;
  line-height: 1.35;
}
.markdown-body h1 { font-size: 1.45rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }
.markdown-body h2 { font-size: 1.22rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 5px; }
.markdown-body h3 { font-size: 1.08rem; color: #4f46e5; }
.markdown-body strong { color: #111827; font-weight: 600; }
.markdown-body em { color: #6b7280; }
.markdown-body code {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.84rem;
  color: #e11d48;
  font-family: Consolas, Monaco, monospace;
}
.markdown-body pre {
  background: #1e293b;
  color: #e2e8f0;
  padding: 14px 18px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
  font-size: 0.84rem;
  line-height: 1.6;
}
.markdown-body pre code { background: none; color: inherit; padding: 0; font-size: inherit; }
.markdown-body p { margin: 6px 0; }
.markdown-body br + br { display: block; content: ''; margin-top: 8px; }

/* ── 深度追问 Q&A 面板 ── */
.deep-question-panel {
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

/* 工具栏 */
.qa-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px; border-bottom: 1px solid #e2e8f0; background: #fff;
}
.qa-mode-tabs { display: flex; gap: 4px; }
.qa-tab {
  padding: 5px 14px; border: 1px solid #e2e8f0; border-radius: 6px;
  background: #fff; font-size: 12.5px; color: #64748b; cursor: pointer;
  transition: all .15s;
  &:hover { border-color: #94a3b8; color: #334155; }
  &.active { background: #4f46e5; color: #fff; border-color: #4f46e5; }
}
.qa-actions { display: flex; gap: 6px; }
.qa-action-btn {
  padding: 4px 12px; border: 1px solid #e2e8f0; border-radius: 6px;
  background: #fff; font-size: 12px; cursor: pointer; transition: all .15s;
  &:hover:not(:disabled) { border-color: #4f46e5; color: #4f46e5; }
  &:disabled { opacity: .5; cursor: not-allowed; }
  &.primary { background: #4f46e5; color: #fff; border-color: #4f46e5; &:hover:not(:disabled) { background: #4338ca; } }
}

/* Q&A 表格 */
.qa-table-wrapper { padding: 12px 16px; }
.qa-loading, .qa-empty {
  padding: 30px; text-align: center; color: #94a3b8; font-size: 13px;
}
.qa-table { display: flex; flex-direction: column; gap: 0; }

/* 表头 */
.qa-table-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: #f1f5f9; border-radius: 6px 6px 0 0;
  font-size: 11.5px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: .3px;
}

/* 行 */
.qa-row {
  display: flex; align-items: stretch; gap: 8px;
  padding: 10px 12px; border-bottom: 1px solid #f1f5f9;
  background: #fff; transition: background .15s;
  &:nth-child(even) { background: #fafbfc; }
  &:hover { background: #f8fafc; }
  &.confirmed { background: #f0fdf4; border-left: 3px solid #22c55e; }
}

/* 列宽 */
.col-q      { flex: 2.5; min-width: 200px; display: flex; gap: 8px; align-items: flex-start; }
.col-cat    { width: 80px; flex-shrink: 0; display: flex; align-items: flex-start; padding-top: 2px; }
.col-ans    { flex: 2; min-width: 180px; }
.col-status { width: 72px; flex-shrink: 0; display: flex; align-items: center; gap: 4px; }
.col-action { width: 90px; flex-shrink: 0; display: flex; align-items: center; gap: 4px; }

/* 问题列 */
.q-index {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  background: #e0e7ff; color: #4f46e5; font-size: 11px; font-weight: 700;
  flex-shrink: 0; margin-top: 2px;
}
.q-text {
  font-size: 13px; color: #334155; line-height: 1.55; word-break: break-word;
}

/* 分类标签 */
.cat-tag {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 11px; white-space: nowrap;
  &.cat-边界条件 { background: #fef3c7; color: #92400e; }
  &.cat-异常场景 { background: #fee2e2; color: #991b1b; }
  &.cat-数据依赖 { background: #dbeafe; color: #1e40af; }
  &.cat-业务规则 { background: #dcfce7; color: #166534; }
  &.cat-其他, &.cat-待分类, &.cat-自动提取, &.cat-手动 { background: #f1f5f9; color: #475569; }
}

/* 回复输入框 */
.qa-answer-input {
  width: 100%; min-height: 44px; max-height: 90px;
  padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 6px;
  font-size: 12.5px; line-height: 1.5; resize: vertical;
  outline: none; transition: border-color .15s;
  background: #fafbfc;
  &:focus { border-color: #4f46e5; box-shadow: 0 0 0 2px rgba(79,70,229,.08); background: #fff; }
  &::placeholder { color: #cbd5e1; }
}

/* 状态 */
.status-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
  &.pending   { background: #d1d5db; }
  &.answered  { background: #f59e0b; }
  &.confirmed { background: #22c55e; }
}
.status-label { font-size: 11px; color: #94a3b8; }

/* 操作按钮 */
.qa-confirm-btn {
  padding: 3px 10px; border: 1px solid #22c55e; border-radius: 5px;
  background: transparent; color: #22c55e; font-size: 11.5px; cursor: pointer;
  transition: all .15s; white-space: nowrap;
  &:hover:not(:disabled) { background: #22c55e; color: #fff; }
  &:disabled { opacity: .35; cursor: not-allowed; border-color: #d1d5db; color: #9ca3af; }
}
.confirmed-badge { font-size: 11px; color: #22c55e; font-weight: 600; }
.qa-delete-btn {
  padding: 2px 6px; border: none; background: none; color: #9ca3af;
  font-size: 13px; cursor: pointer; border-radius: 4px; transition: all .15s;
  &:hover { background: #fef2f2; color: #ef4444; }
}

/* 统计栏 */
.qa-summary {
  padding: 8px 12px; margin-top: 4px;
  font-size: 11.5px; color: #94a3b8; text-align: right;
  border-top: 1px dashed #e2e8f0;
}

/* ===== 聊天模式样式（保留）===== */
.deep-question-messages {
  max-height: 320px;
  overflow-y: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chat-msg {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  animation: fadeInUp .25s ease-out;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.chat-msg-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: #e2e8f0;
  font-size: 16px;
  flex-shrink: 0;
}
.chat-msg.user .chat-msg-avatar { background: #dbeafe; }
.chat-msg.assistant .chat-msg-avatar { background: #ede9fe; }
.chat-msg-content {
  max-width: 82%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 0.87rem;
  line-height: 1.7;
  word-break: break-word;
}
.chat-msg.user .chat-msg-content {
  background: #4f46e5;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.chat-msg.assistant .chat-msg-content {
  background: #fff;
  color: #334155;
  border: 1px solid #e2e8f0;
  border-bottom-left-radius: 4px;
}
.chat-msg-content.streaming {
  min-height: 24px;
}
.typing-cursor {
  display: inline-block;
  width: 7px; height: 15px;
  background: #4f46e5;
  animation: blink .7s step-end infinite;
  vertical-align: text-bottom;
  margin-right: 2px;
  border-radius: 1px;
}
@keyframes blink { 50% { opacity: 0; } }
.deep-question-input-row {
  display: flex;
  gap: 8px;
  padding: 10px 14px 14px;
  border-top: 1px solid #e2e8f0;
  background: #fff;
}
.deep-q-input {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-radius: 20px;
  padding: 8px 16px;
  font-size: 0.87rem;
  outline: none;
  transition: border-color .2s;
}
.deep-q-input:focus { border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79,70,229,.1); }
.deep-q-send-btn {
  padding: 8px 20px;
  border: none;
  border-radius: 20px;
  background: #4f46e5;
  color: #fff;
  cursor: pointer;
  font-size: 0.85rem;
  white-space: nowrap;
  transition: background .2s;
}
.deep-q-send-btn:hover:not(:disabled) { background: #4338ca; }
.deep-q-send-btn:disabled { background: #a5b4fc; cursor: not-allowed; }

/* ── 结构化拆解表格样式 ── */
.analyze-sections {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.analyze-section {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.analyze-section-title {
  margin: 0;
  padding: 10px 16px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #4f46e5;
  background: linear-gradient(135deg, #f8f7ff 0%, #eef0ff 100%);
  border-bottom: 1px solid #e2e8f0;
}

.analyze-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}

/* KV 键值对表（2列） */
.kv-table td {
  padding: 10px 14px;
  border-bottom: 1px solid #f1f1f9;
  vertical-align: top;
}

.kv-table tr:last-child td {
  border-bottom: none;
}

.kv-key {
  width: 140px;
  font-weight: 600;
  color: #6366f1;
  background: #fafaff;
  white-space: nowrap;
  user-select: none;
}

.kv-val {
  color: #334155;
  line-height: 1.6;
  min-height: 24px;
  outline: none;
  transition: background 0.15s;
}

.kv-val:focus {
  background: #fefefe;
  box-shadow: inset 0 0 0 2px #c7d2fe;
  border-radius: 3px;
}

/* 多列数据表 */
.table-wrapper {
  overflow-x: auto;
}

.data-table th {
  padding: 10px 12px;
  text-align: left;
  font-weight: 600;
  color: #4f46e5;
  background: #f5f3ff;
  border-bottom: 2px solid #ddd6fe;
  white-space: nowrap;
  font-size: 0.85rem;
  user-select: none;
}

.data-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #f1f1f9;
  color: #334155;
  line-height: 1.55;
  vertical-align: top;
  min-height: 28px;
  outline: none;
  transition: background 0.15s;
}

.data-table td:focus {
  background: #fefefe;
  box-shadow: inset 0 0 0 2px #c7d2fe;
}

.data-table tr:hover td {
  background: #fafbff;
}

.data-table tr:last-child td {
  border-bottom: none;
}

/* 纯文本块 */
.analyze-text-block {
  margin: 0;
  padding: 12px 16px;
  color: #475569;
  line-height: 1.7;
  font-size: 0.88rem;
}

.divider {
  text-align: center;
  margin: 40px 0;
  position: relative;
}

.divider::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: #ddd;
}

.divider span {
  background: white;
  padding: 0 20px;
  color: #666;
  font-size: 1rem;
}

.upload-area {
  border: 2px dashed #ddd;
  border-radius: 8px;
  padding: 40px;
  text-align: center;
  transition: border-color 0.3s ease;
  margin-bottom: 20px;
}

.upload-area.drag-over {
  border-color: #3498db;
  background: #f8f9fa;
}

.upload-placeholder {
  color: #666;
}

.upload-icon {
  font-size: 3rem;
  margin-bottom: 15px;
  display: block;
}

.upload-hint {
  color: #999;
  font-size: 0.9rem;
  margin-top: 5px;
}

.select-file-btn {
  background: #3498db;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  margin-top: 15px;
}

.file-selected {
  padding: 20px;
  background: #f8f9fa;
  border-radius: 6px;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 15px;
}

.file-icon {
  font-size: 2rem;
}

.file-details {
  flex: 1;
}

.file-name {
  font-weight: 600;
  margin: 0;
}

.file-size {
  color: #666;
  font-size: 0.9rem;
  margin: 5px 0 0 0;
}

.remove-file {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.2rem;
}

.generation-progress {
  margin: 40px 0;
}

.progress-card {
  background: white;
  border-radius: 12px;
  padding: 30px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  border: 1px solid #e1e8ed;
  text-align: center;
}

.progress-card h3 {
  color: #2c3e50;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}

.current-mode-badge {
  display: inline-block;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: 500;
  margin-left: 8px;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
}

.progress-info {
  display: flex;
  justify-content: center;
  gap: 30px;
  margin-bottom: 30px;
  flex-wrap: wrap;
}

.progress-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.progress-item .label {
  font-size: 0.9rem;
  color: #666;
}

.progress-item .value {
  font-weight: 600;
  color: #2c3e50;
}

/* 流式内容显示区域 */
.stream-content-display {
  margin: 20px 0;
  border: 2px solid #e1e8ed;
  border-radius: 8px;
  overflow: hidden;
  background: #f8f9fa;
}

.stream-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #e9ecef;
  border-bottom: 1px solid #dee2e6;
}

.stream-title {
  font-weight: 600;
  color: #495057;
  font-size: 0.95rem;
}

.stream-status {
  font-size: 0.85rem;
  color: #6c757d;
  background: white;
  padding: 4px 10px;
  border-radius: 12px;
  border: 1px solid #dee2e6;
}

.stream-content {
  max-height: 400px;
  overflow-y: auto;
  padding: 16px;
  text-align: left;
  background: white;
  font-size: 0.9rem;
  line-height: 1.6;
  color: #2c3e50;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.stream-content::-webkit-scrollbar {
  width: 8px;
}

.stream-content::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.stream-content::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
}

.stream-content::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

/* 最终版用例特殊样式 */
.stream-content.final-testcases {
  background: #f0f7ff;
  border-left: 4px solid #2196F3;
}

.stream-content.final-testcases::before {
  content: '📋 最终版本';
  display: block;
  font-weight: 600;
  color: #2196F3;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid #e3f2fd;
}

/* 流式输出指示器 */
.streaming-indicator {
  font-size: 0.85em;
  margin-left: 8px;
  color: #4CAF50;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.stream-content h1,
.stream-content h2,
.stream-content h3,
.stream-content h4,
.stream-content h5,
.stream-content h6 {
  margin-top: 1em;
  margin-bottom: 0.5em;
  color: #2c3e50;
  font-weight: 600;
}

.stream-content code {
  background: #f1f3f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 0.85em;
}

.stream-content pre {
  background: #f1f3f5;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 10px 0;
}

.stream-content pre code {
  background: none;
  padding: 0;
}

.progress-steps {
  display: flex;
  justify-content: center;
  gap: 20px;
  margin-bottom: 30px;
  flex-wrap: wrap;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  opacity: 0.4;
  transition: opacity 0.3s ease;
}

.step.active {
  opacity: 1;
}

.step-number {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #ddd;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  color: white;
}

.step.active .step-number {
  background: #3498db;
}

.step-text {
  font-size: 0.9rem;
  color: #666;
}

.cancel-generation-btn {
  background: #e74c3c;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
}

.completion-actions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  flex-wrap: wrap;
}

.completion-actions button {
  flex: 1;
  min-width: 150px;
  padding: 12px 20px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.completion-actions .download-btn {
  background: #28a745;
  color: white;
  font-size: 1rem;
}

.completion-actions .download-btn:hover {
  background: #218838;
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(40, 167, 69, 0.3);
}

.completion-actions .save-btn {
  background: #007bff;
  color: white;
  font-size: 1rem;
}

.completion-actions .save-btn:hover {
  background: #0056b3;
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 123, 255, 0.3);
}

.completion-actions .new-generation-btn {
  background: #6c757d;
  color: white;
  font-size: 1rem;
}

.completion-actions .new-generation-btn:hover {
  background: #5a6268;
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(108, 117, 125, 0.3);
}

.generation-result {
  margin: 40px 0;
}

.result-header {
  background: white;
  border-radius: 12px;
  padding: 30px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  border: 1px solid #e1e8ed;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
}

.result-header h2 {
  color: #27ae60;
  margin: 0;
}

.result-summary {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}

.summary-item {
  color: #666;
  font-size: 0.9rem;
}

.new-generation-btn {
  background: #3498db;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
}

.generated-testcases-section, .review-feedback-section, .final-testcases-section {
  background: white;
  border-radius: 12px;
  padding: 30px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  border: 1px solid #e1e8ed;
  margin-bottom: 20px;
}

.generated-testcases-section h3, .review-feedback-section h3, .final-testcases-section h3 {
  color: #2c3e50;
  margin-bottom: 20px;
}

.testcase-content, .review-content {
  background: #f8f9fa;
  border-radius: 6px;
  padding: 20px;
  border-left: 4px solid #3498db;
}

.testcase-content pre, .review-content pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  margin: 0;
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 0.9rem;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .result-header {
    flex-direction: column;
    align-items: flex-start;
  }
  
  .progress-info, .result-summary {
    flex-direction: column;
    gap: 10px;
  }
  
  .progress-steps {
    gap: 10px;
  }
}

.actions-section {
  display: flex;
  gap: 20px;
  justify-content: center;
  margin-top: 30px;
  flex-wrap: wrap;
}

.download-btn, .save-btn {
  padding: 12px 24px;
  border: none;
  border-radius: 6px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.3s ease;
}

.download-btn {
  background-color: #1abc9c;
  color: white;
}

.download-btn:hover {
  background-color: #16a085;
}

.save-btn {
  background-color: #3498db;
  color: white;
}

.save-btn:hover {
  background-color: #2980b9;
}

@media (max-width: 768px) {
  .actions-section {
    flex-direction: column;
    align-items: center;
  }

  .download-btn, .save-btn {
    width: 100%;
    max-width: 300px;
    justify-content: center;
  }
}
</style>

<style>
/* 全局样式：确保弹窗不受任何容器限制 */
.modal-overlay {
  position: fixed !important;
  top: 0 !important;
  left: 0 !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  max-width: none !important;
  max-height: none !important;
  background: rgba(15, 23, 42, 0.6) !important;
  backdrop-filter: blur(4px);
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  z-index: 9999 !important;
  padding: 20px;
  margin: 0 !important;
  opacity: 1 !important;
  box-sizing: border-box !important;
}

.guide-config-modal {
  background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%) !important;
  border-radius: 24px;
  padding: 36px;
  max-width: 850px !important;
  width: 100% !important;
  min-width: 300px !important;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(226, 232, 240, 0.8);
  position: relative;
  flex-shrink: 0;
  margin: auto;
  opacity: 1 !important;
  box-sizing: border-box !important;
}

/* 全局按钮样式 */
.guide-actions {
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
  gap: 12px;
  margin-top: 30px;
  width: 100%;
}

.guide-actions button {
  flex: none !important;
  width: 240px !important;
  height: 50px !important;
  padding: 0 24px !important;
  border-radius: 12px;
  font-size: 0.95rem;
  font-weight: 600;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  text-align: center;
  white-space: nowrap;
  opacity: 1 !important;
  box-sizing: border-box !important;
  cursor: pointer;
}

.guide-actions .generate-manual-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
  color: white !important;
  border: 2px solid transparent !important;
  box-shadow: 0 2px 10px rgba(102, 126, 234, 0.3);
}

.guide-actions .skip-action {
  font-size: 0.85rem;
  color: #94a3b8;
  cursor: pointer;
  text-decoration: none;
  padding: 4px 8px;
  transition: color 0.3s;
}

.guide-actions .skip-action:hover {
  color: #64748b;
  text-decoration: underline;
}

/* ──────────── 需求文档生成区块 ──────────── */
.req-doc-section {
  width: 100%;
}

.req-doc-card {
  background: linear-gradient(135deg, #ffffff 0%, #f8faff 100%);
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 28px 32px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
}

.req-doc-header {
  margin-bottom: 20px;
}

.req-doc-header h2 {
  font-size: 1.3rem;
  color: #1a202c;
  margin: 0 0 6px 0;
  font-weight: 700;
}

.req-doc-desc {
  color: #64748b;
  font-size: 0.9rem;
  margin: 0;
}

.req-doc-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}

/* 上传/粘贴阶段的项目选择行 */
.req-doc-project-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  padding: 10px 14px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px dashed #cbd5e1;
}
.req-doc-project-row .form-group {
  margin-bottom: 0;
}
.req-doc-project-hint {
  font-size: 0.82rem;
  color: #64748b;
}

.req-doc-btn {
  padding: 10px 22px;
  border-radius: 10px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.req-doc-btn.primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
}

.req-doc-btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.45);
}

.req-doc-btn.secondary {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
}

.req-doc-btn.secondary:hover:not(:disabled) {
  background: #e2e8f0;
}

.req-doc-btn.analyze-doc-btn {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
}

.req-doc-btn.analyze-doc-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.45);
}

.req-doc-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none !important;
}

/* 编辑器区域 */
.req-doc-editor {
  margin-top: 16px;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding: 10px 14px;
  background: #f8faff;
  border: 1px solid #e2e8f0;
  border-radius: 10px 10px 0 0;
}

.editor-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: #374151;
}

.editor-toolbar-actions {
  display: flex;
  gap: 8px;
}

.toolbar-btn {
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #e2e8f0;
  background: white;
  color: #475569;
  transition: all 0.15s;
}

.toolbar-btn:hover {
  background: #f1f5f9;
}

.toolbar-btn.danger {
  color: #dc2626;
  border-color: #fca5a5;
}

.toolbar-btn.danger:hover {
  background: #fef2f2;
}

.req-doc-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #e2e8f0;
  border-top: none;
  border-radius: 0 0 10px 10px;
  padding: 16px;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 0.88rem;
  line-height: 1.7;
  color: #1e293b;
  background: #fafbff;
  resize: vertical;
  outline: none;
  transition: border-color 0.2s;
}

.req-doc-textarea:focus {
  border-color: #667eea;
  background: #fff;
}

.req-doc-preview {
  border: 1px solid #e2e8f0;
  border-top: none;
  border-radius: 0 0 10px 10px;
  padding: 20px 24px;
  min-height: 280px;
  background: #fff;
  overflow-y: auto;
}

/* 底部行：项目选择 + 生成按钮 */
.req-doc-generate-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.project-select-inline {
  flex: 1;
  min-width: 200px;
  margin: 0 !important;
}

.project-select-inline label {
  display: block;
  font-size: 0.85rem;
  color: #64748b;
  margin-bottom: 6px;
}

.use-req-doc-btn {
  flex-shrink: 0;
  padding: 10px 28px;
  font-size: 1rem;
}

.doc-analyze-btn {
  flex-shrink: 0;
  padding: 10px 22px;
  margin-right: 10px;
  font-size: 0.95rem;
}

/* 输入方式 Tab */
.rd-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
  border-bottom: 2px solid #e2e8f0;
  padding-bottom: 0;
}

.rd-tab {
  padding: 8px 20px;
  border: none;
  background: transparent;
  font-size: 0.9rem;
  font-weight: 600;
  color: #94a3b8;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.15s;
  border-radius: 6px 6px 0 0;
}

.rd-tab.active {
  color: #667eea;
  border-bottom-color: #667eea;
  background: #f5f7ff;
}

.rd-tab:hover:not(.active) {
  color: #475569;
  background: #f8faff;
}

.rd-text-input {
  margin-top: 0;
}

/* 文件上传区 */
.rd-upload-zone {
  margin-bottom: 4px;
}

/* 双入口布局（文件 / 文件夹） */
.rd-upload-entries {
  display: flex;
  gap: 12px;
}

.rd-upload-entries .rd-drop-zone {
  flex: 1;
  min-width: 0;
}

.rd-folder-zone {
  border-color: #bfdbfe !important;
  background: #f0f9ff !important;
}

.rd-folder-zone:hover {
  border-color: #3b82f6 !important;
  background: #e0f2fe !important;
}

.rd-drop-zone {
  border: 2px dashed #c7d2fe;
  border-radius: 12px;
  padding: 32px 20px;
  text-align: center;
  cursor: pointer;
  background: #f8faff;
  transition: all 0.2s;
}

.rd-drop-zone:hover {
  border-color: #667eea;
  background: #f0f3ff;
}

.rd-drop-icon {
  font-size: 2.2rem;
  margin-bottom: 8px;
}

.rd-drop-title {
  font-size: 1rem;
  font-weight: 600;
  color: #374151;
  margin: 0 0 4px 0;
}

.rd-drop-hint {
  font-size: 0.82rem;
  color: #94a3b8;
  margin: 0;
}

/* 文件夹分组标题 */
.rd-folder-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-top: 8px;
  background: #f0f9ff;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
}

.rd-folder-icon {
  font-size: 1.4rem;
  flex-shrink: 0;
}

.rd-folder-name {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e40af;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rd-folder-count {
  font-size: 0.8rem;
  color: #64748b;
  margin-left: auto;
  flex-shrink: 0;
}

.rd-folder-clear {
  flex-shrink: 0;
  border: none;
  background: none;
  color: #94a3b8;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.15s;
}

.rd-folder-clear:hover {
  color: #ef4444;
  background: #fee2e2;
}

/* 文件夹内子文件缩进 */
.rd-file-sub {
  margin-left: 24px;
  background: #fafbfe;
}

/* 已选文件列表 */
.rd-file-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rd-file-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #f8faff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.rd-file-icon {
  font-size: 1.4rem;
  flex-shrink: 0;
}

.rd-file-name {
  flex: 1;
  font-size: 0.9rem;
  color: #1e293b;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rd-extract-status {
  font-size: 0.82rem;
  font-weight: 600;
  flex-shrink: 0;
}

.rd-extract-status.extracting {
  color: #f59e0b;
}

.rd-extract-status.done {
  color: #10b981;
}

.rd-extract-status.image-pdf {
  color: #8b5cf6;
  font-size: 0.8rem;
}

.rd-extract-status.error {
  color: #dc2626;
  font-size: 0.8rem;
  cursor: help;
}

.rd-file-clear {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid #e2e8f0;
  background: white;
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.rd-file-clear:hover:not(:disabled) {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fca5a5;
}

.rd-file-clear:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ──────────── 历史文档面板 ──────────── */
.history-section {
  width: 100%;
  margin-bottom: 30px;
}

.history-card {
  background: linear-gradient(135deg, #ffffff 0%, #fafbfe 100%);
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 24px 28px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.history-header h2 {
  font-size: 1.2rem;
  color: #1a202c;
  margin: 0;
  font-weight: 700;
  flex-shrink: 0;
}

.history-tabs {
  display: flex;
  gap: 8px;
  width: 100%;
}

.history-tab {
  flex: 1;
  padding: 10px 16px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #64748b;
  border-radius: 10px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.history-tab:hover {
  background: #eef2ff;
  color: #4f46e5;
}

.history-tab.active {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.history-version-row {
  display: flex;
  align-items: center;
  gap: 0;
}

.history-count {
  font-size: 0.85rem;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 4px 12px;
  border-radius: 20px;
  font-weight: 600;
}

.history-loading,
.history-empty,
.history-error {
  text-align: center;
  padding: 24px 16px;
  color: #94a3b8;
  font-size: 0.9rem;
}

.history-error {
  color: #ef4444;
}

.history-error a {
  color: #667eea;
  text-decoration: underline;
  cursor: pointer;
}

.history-empty {
  color: #94a3b8;
  line-height: 1.8;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  transition: all 0.2s;
}

.history-item:hover {
  border-color: #c7d2fe;
  box-shadow: 0 2px 12px rgba(102, 126, 234, 0.08);
}

.history-item-main {
  flex: 1;
  min-width: 0;
}

.history-item-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.history-item-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.82rem;
  color: #94a3b8;
}

.history-source {
  color: #64748b;
}

.history-time {
  color: #94a3b8;
}

.history-item-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.history-btn {
  padding: 7px 16px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid;
  transition: all 0.2s;
  white-space: nowrap;
}

.history-btn.view {
  background: #f8faff;
  border-color: #e2e8f0;
  color: #475569;
}

.history-btn.view:hover {
  background: #eef2ff;
  border-color: #c7d2fe;
}

.history-btn.generate {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-color: transparent;
  color: white;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
}

.history-btn.generate:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(102, 126, 234, 0.4);
}

.history-btn.del {
  background: #fff5f5;
  border-color: #fecaca;
  color: #ef4444;
}

.history-btn.del:hover {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #dc2626;
}

.history-btn.edit {
  background: #fff7ed;
  border-color: #fed7aa;
  color: #c2410c;
}

.history-btn.edit:hover {
  background: #ffedd5;
  border-color: #fdba74;
  color: #9a3412;
}

.history-btn.analyze {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border-color: transparent;
  color: white;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.history-btn.analyze:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4);
}

/* ── 历史文档预览弹窗 ── */
.history-preview-modal {
  background: #fff;
  border-radius: 20px;
  padding: 32px;
  max-width: 820px;
  width: 100%;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
  position: relative;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.preview-header h3 {
  font-size: 1.25rem;
  color: #1a202c;
  margin: 0;
  font-weight: 700;
}

.preview-close {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid #e2e8f0;
  background: white;
  color: #94a3b8;
  font-size: 1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.preview-close:hover {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fca5a5;
}

.preview-body {
  padding: 20px;
  background: #f8faff;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  max-height: 50vh;
  overflow-y: auto;
  margin-bottom: 20px;
}

.preview-body :deep(h1),
.preview-body :deep(h2),
.preview-body :deep(h3) {
  color: #1a202c;
}

.preview-body :deep(p) {
  line-height: 1.7;
  color: #334155;
}

/* ── 编辑模式 ── */
.edit-title-input {
  flex: 1;
  padding: 8px 14px;
  margin-right: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 1.15rem;
  font-weight: 700;
  color: #1a202c;
  background: #fff;
  box-sizing: border-box;
}

.edit-title-input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.edit-body {
  margin-bottom: 20px;
}

.edit-textarea {
  width: 100%;
  min-height: 50vh;
  padding: 20px;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.9rem;
  line-height: 1.7;
  color: #1a202c;
  background: #fafbfc;
  resize: vertical;
  box-sizing: border-box;
}

.edit-textarea:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.preview-actions {
  display: flex;
  justify-content: center;
}

/* ── 快速创建版本弹窗 ── */
.quick-version-modal,
.generate-confirm-modal {
  background: #fff;
  border-radius: 16px;
  padding: 28px 32px;
  max-width: 480px;
  width: 100%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
  position: relative;
}

.generate-confirm-modal .form-group {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.generate-confirm-modal .form-group label {
  min-width: 70px;
}

/* ── 生成模式选择器 ── */
.generation-mode-selector {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.generation-mode-selector .mode-option {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 8px;
  border: 2px solid #e2e8f0;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  flex: 1;
  min-width: 70px;
  text-align: center;
}

.generation-mode-selector .mode-option:hover {
  border-color: #6366f1;
  background: #f5f3ff;
}

.generation-mode-selector .mode-option.active {
  border-color: #6366f1;
  background: #eef2ff;
  box-shadow: 0 0 0 2px rgba(99,102,241,0.15);
}

.generation-mode-selector .mode-radio {
  display: none;
}

.generation-mode-selector .mode-icon {
  font-size: 1.2rem;
  line-height: 1;
}

.generation-mode-selector .mode-name {
  font-size: 0.78rem;
  font-weight: 600;
  color: #1a202c;
  white-space: nowrap;
}

.generation-mode-selector .mode-desc {
  font-size: 0.68rem;
  color: #94a3b8;
  white-space: nowrap;
  line-height: 1.2;
}

.quick-version-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.quick-version-header h3 {
  font-size: 1.15rem;
  color: #1a202c;
  margin: 0;
  font-weight: 700;
}

.quick-version-body .form-group {
  margin-bottom: 16px;
}

.quick-version-body .form-group label {
  display: block;
  font-size: 0.85rem;
  color: #475569;
  margin-bottom: 6px;
  font-weight: 500;
}

.quick-version-body .form-group .required {
  color: #ef4444;
  margin-left: 2px;
}

.quick-version-body .form-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.9rem;
  background: #fff;
  transition: border-color 0.15s;
  box-sizing: border-box;
}

.quick-version-body .form-input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.quick-version-body .form-select {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.9rem;
  background: #fff;
  box-sizing: border-box;
}

.quick-version-body .checkbox-label {
  display: flex !important;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.85rem;
}

.quick-version-body .checkbox-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: #6366f1;
}

.quick-version-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

/* ── 版本选择器行（下拉 + 新建按钮）── */
.version-select-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.version-select-row .version-select {
  flex: 1;
}

.quick-create-ver-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  color: #6366f1;
  font-size: 1.1rem;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;
  padding: 0;
  line-height: 1;
}

.quick-create-ver-btn:hover {
  border-style: solid;
  border-color: #6366f1;
  background: #eef2ff;
  transform: scale(1.05);
}

.project-select-inline .version-select-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

/* ========== 插接矩阵弹窗 ========== */
.matrix-modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.55);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.matrix-modal {
  background: #fff;
  border-radius: 14px;
  width: 95%;
  max-width: 1400px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0,0,0,0.25);
}
.matrix-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 28px;
  border-bottom: 2px solid #e8ecf1;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 14px 14px 0 0;
}
.matrix-modal-header h2 {
  margin: 0;
  color: #fff;
  font-size: 1.3rem;
  letter-spacing: 0.5px;
}
.matrix-close-btn {
  background: rgba(255,255,255,0.2);
  color: #fff;
  border: none;
  width: 34px; height: 34px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 16px;
  transition: background 0.2s;
}
.matrix-close-btn:hover { background: rgba(255,255,255,0.4); }
.matrix-modal-body {
  padding: 24px 28px;
  overflow-y: auto;
  flex: 1;
}
.matrix-empty {
  text-align: center;
  color: #999;
  padding: 80px 0;
  font-size: 1rem;
}
.matrix-sections { display: flex; flex-direction: column; gap: 28px; }
.matrix-section-title {
  color: #2c3e50;
  font-size: 1.15rem;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid #667eea;
  display: inline-block;
}
.matrix-section-body p { line-height: 1.7; color: #444; }

/* 插接矩阵表格 */
.matrix-table-wrapper {
  overflow-x: auto;
  border-radius: 10px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  border: 1px solid #e2e8f0;
}
.matrix-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.matrix-table thead th {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  padding: 13px 14px;
  text-align: left;
  white-space: nowrap;
  font-weight: 600;
  font-size: 0.88rem;
  letter-spacing: 0.3px;
  position: sticky;
  top: 0;
  z-index: 1;
}
.matrix-table tbody td {
  padding: 11px 14px;
  border-bottom: 1px solid #edf2f7;
  vertical-align: top;
  color: #334155;
  line-height: 1.65;
}
.matrix-table tbody tr.alt-row td { background: #f8fafc; }
.matrix-table tbody tr:hover td { background: #eef2ff; }
.matrix-item-num {
  display: block;
  color: #1e40af;
  font-weight: 600;
  margin-bottom: 2px;
}
.matrix-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 28px;
  border-top: 1px solid #e8ecf1;
  background: #f8f9fb;
  border-radius: 0 0 14px 14px;
}
.matrix-btn {
  padding: 9px 22px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.92rem;
  font-weight: 500;
  transition: all 0.2s;
}
.matrix-btn.copy-btn { background: #667eea; color: #fff; }
.matrix-btn.copy-btn:hover { background: #5a6fd6; transform: translateY(-1px); }
.matrix-btn.close-btn { background: #cbd5e1; color: #475569; }
.matrix-btn.close-btn:hover { background: #94a3b8; }

/* ========== 待确认项确认弹窗（对齐 AI 用例评审） ========== */
.analyze-uncertain-trigger { margin-top: 14px; }
.au-trigger-alert { border-radius: 10px !important; }
.au-list { display: flex; flex-direction: column; gap: 14px; max-height: 50vh; overflow-y: auto; padding-right: 4px; }
.au-item {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  padding: 14px 16px;
  transition: all 0.25s;
}
.au-item.confirmed { border-color: #86efac; background: #f0fdf4; }
.au-header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.au-question { flex: 1; font-weight: 600; color: #1f2937; font-size: 0.92rem; line-height: 1.5; }
.au-context {
  margin-top: 8px;
  font-size: 0.85rem;
  color: #6b7280;
  background: #f9fafb;
  padding: 8px 12px;
  border-radius: 6px;
  line-height: 1.5;
}
.gen-gate-hint {
  margin-top: 8px;
  font-size: 0.82rem;
  color: #b45309;
  background: #fffbeb;
  border: 1px dashed #fcd34d;
  border-radius: 6px;
  padding: 6px 10px;
}
</style>