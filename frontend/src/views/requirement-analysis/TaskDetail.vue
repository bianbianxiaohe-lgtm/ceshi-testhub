<template>
  <div class="task-detail">
    <div class="page-header">
      <div class="header-left">
        <h2>任务详情 - {{ task.title }}</h2>
        <div class="task-info">
          <span class="task-id">任务ID: {{ taskId }}</span>
          <span class="task-status" :class="task.status">{{ getStatusText(task.status) }}</span>
        </div>
      </div>
      <div class="header-actions">
        <button 
          v-if="task.status === 'completed'"
          class="rerun-review-btn"
          @click="rerunReview"
          :disabled="isRerunningReview"
          :title="'使用最新评审规则重新评审，自动识别不确定项'">
          <span v-if="isRerunningReview">⏳ 评审中...</span>
          <span v-else>🔄 重新评审</span>
        </button>
        <button 
          v-if="task.status === 'completed' && task.review_feedback && testCases.length > 0" 
          class="regenerate-btn" 
          @click="openRegenerateDialog"
          :disabled="isRegenerating">
          <span v-if="isRegenerating">🔄 重新生成中...</span>
          <span v-else>🔄 基于调整重新生成</span>
        </button>
        <button 
          class="new-generate-btn"
          @click="openRegenerateNewDialog"
          title="使用当前需求从头创建新的生成任务，可修改测试点/功能模块/生成模式">
          🆕 从头重新生成
        </button>
        <button 
          v-if="testCases.length > 0" 
          class="export-btn" 
          @click="exportToExcel"
          :disabled="isExporting">
          <span v-if="isExporting">💾 导出中...</span>
          <span v-else>💾 导出Excel</span>
        </button>
      </div>
    </div>

    <!-- 重新评审进度提示横幅 -->
    <div v-if="isRerunningReview" class="rerun-progress-banner">
      <span class="progress-spinner"></span>
      <span class="progress-text">🔄 AI 正在重新评审中，预计 30-60 秒完成...</span>
      <span class="progress-count">已等待 {{ rerunElapsed }} 秒</span>
      <button class="progress-refresh-btn" @click="checkRerunStatus">🔄 手动刷新</button>
    </div>

    <!-- 需求描述折叠卡片 -->
    <div v-if="task.requirement_text" class="requirement-description-card">
      <el-collapse>
        <el-collapse-item name="requirement">
          <template #title>
            <div class="collapse-title">
              <span class="title-icon">📋</span>
              <span class="title-text">需求描述</span>
              <span class="title-hint">（点击展开查看完整内容）</span>
            </div>
          </template>
          <div class="requirement-content">
            <div class="requirement-text">
              {{ task.requirement_text }}
            </div>
            <div class="requirement-actions">
              <el-button size="small" @click="copyRequirementText">
                <el-icon><DocumentCopy /></el-icon>
                复制需求描述
              </el-button>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- AI评审报告折叠卡片 -->
    <div v-if="task.review_feedback" class="review-feedback-card">
      <el-collapse v-model="activeCollapse">
        <el-collapse-item name="review">
          <template #title>
            <div class="collapse-title">
              <span class="title-icon">🔍</span>
              <span class="title-text">AI 评审报告</span>
              <!-- 评审次数 + 时间标签 -->
              <span v-if="task.review_count > 0" class="review-meta-tag">
                第 {{ task.review_count }} 次评审
              </span>
              <span v-if="task.review_updated_at" class="review-time-tag">
                {{ formatReviewTime(task.review_updated_at) }}
              </span>
              <span v-else class="title-hint">（点击展开查看评审意见和改进建议）</span>
              <button
                class="rerun-review-btn-inline"
                @click.stop="rerunReview"
                :disabled="isRerunningReview"
                :title="'使用最新评审规则重新评审，自动识别不确定项'"
              >
                <span v-if="isRerunningReview" class="spinner"></span>
                <span v-if="isRerunningReview">评审中...</span>
                <span v-else>🔄 重新评审</span>
              </button>
            </div>
          </template>
          <div class="review-content">
            <div class="review-text" v-html="formatReviewMarkdown(task.review_feedback)"></div>

            <!-- 人工逐项确认回复区 -->
            <div class="human-feedback-section">
              <div class="human-feedback-header">
                <span class="section-icon">💬</span>
                <span class="section-title">逐项确认回复</span>
                <span v-if="hasAutoDetectedItems" class="auto-detect-badge">
                  🤖 AI已自动识别 {{ unrepliedAutoCount }} 个不确定项，请逐一回复确认
                </span>
                <span v-else class="section-hint">— 请对照评审报告，逐条确认不确定需求（每个问题单独填写，以免漏掉）</span>
              </div>

              <div v-if="feedbackItems.length === 0 && !hasAutoDetectedItems" class="feedback-empty">
                <span>暂无确认项，点击下方按钮手动添加</span>
              </div>
              <div v-else-if="feedbackItems.length === 0 && hasAutoDetectedItems" class="feedback-empty feedback-auto-empty">
                <span>🎉 AI评审未发现不确定项，所有评审点均可确定！</span>
              </div>
              <div v-else-if="pendingFeedbackItems.length === 0 && repliedFeedbackItems.length > 0" class="feedback-empty feedback-auto-empty">
                <span>✅ 所有不确定项均已回复确认！</span>
              </div>

              <!-- 待填写的确认项 -->
              <div
                v-for="item in pendingFeedbackItems"
                :key="item._origIdx"
                class="feedback-item-card"
              >
                <div class="feedback-item-header">
                  <span class="feedback-item-num">
                    <span v-if="item._autoDetected" class="auto-icon">🤖</span>
                    <span v-else>📌</span>
                    确认项
                  </span>
                  <el-button
                    size="small"
                    type="danger"
                    text
                    @click="removeFeedbackItem(item._origIdx)"
                    class="feedback-item-delete"
                  >
                    ✕ 删除
                  </el-button>
                </div>
                <div class="feedback-item-body">
                  <div class="feedback-field">
                    <label class="feedback-field-label">不确定需求：</label>
                    <el-input
                      v-model="feedbackItems[item._origIdx].question"
                      placeholder="粘贴评审报告中的不确定需求，如：截屏后是否支持编辑？"
                      maxlength="300"
                      show-word-limit
                    />
                  </div>
                  <div class="feedback-field">
                    <label class="feedback-field-label">确认回复：</label>
                    <el-input
                      v-model="feedbackItems[item._origIdx].reply"
                      type="textarea"
                      :rows="2"
                      placeholder="你的确认/补充说明，如：已确认，V1.0 暂不支持编辑，V2.0 再上"
                    />
                  </div>
                </div>
              </div>

              <!-- 已回复的确认项（折叠展示） -->
              <el-collapse v-if="repliedFeedbackItems.length > 0" class="replied-collapse">
                <el-collapse-item :title="`✅ 已确认项（${repliedFeedbackItems.length} 条）`" name="replied">
                  <div
                    v-for="item in repliedFeedbackItems"
                    :key="item._origIdx"
                    class="feedback-item-card feedback-item-replied"
                  >
                    <div class="feedback-item-header">
                      <span class="feedback-item-num replied-num">
                        ✅ 已确认
                      </span>
                      <el-button
                        size="small"
                        type="danger"
                        text
                        @click="removeFeedbackItem(item._origIdx)"
                        class="feedback-item-delete"
                      >
                        ✕ 删除
                      </el-button>
                    </div>
                    <div class="feedback-item-body">
                      <div class="feedback-field">
                        <label class="feedback-field-label">不确定需求：</label>
                        <div class="feedback-replied-text">{{ feedbackItems[item._origIdx].question }}</div>
                      </div>
                      <div class="feedback-field">
                        <label class="feedback-field-label">确认回复：</label>
                        <el-input
                          v-model="feedbackItems[item._origIdx].reply"
                          type="textarea"
                          :rows="2"
                        />
                      </div>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>



              <div class="feedback-add-row">
                <el-button size="small" @click="addFeedbackItem" type="success" plain>
                  ＋ 添加确认项
                </el-button>
              </div>

              <div class="human-feedback-actions">
                <el-button size="small" @click="saveHumanFeedback" :loading="isSavingFeedback" type="primary" plain>
                  💾 保存回复
                </el-button>
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 知识库审计建议卡片 -->
    <div v-if="task.kb_audit_result || isRunningKbAudit" class="kb-audit-card">
      <el-collapse v-model="kbAuditCollapse">
        <el-collapse-item name="kb-audit">
          <template #title>
            <div class="collapse-title">
              <span class="title-icon">📚</span>
              <span class="title-text">知识库审计建议</span>
              <span class="title-hint">（AI 基于评审和用例发现的知识库缺失与改进建议）</span>
              <button
                class="rerun-review-btn-inline"
                @click.stop="runKbAudit"
                :disabled="isRunningKbAudit"
                title="重新执行知识库智能审计"
              >
                <span v-if="isRunningKbAudit" class="spinner"></span>
                <span v-if="isRunningKbAudit">审计中...</span>
                <span v-else>🔄 重新审计</span>
              </button>
            </div>
          </template>
          <div class="kb-audit-content">
            <!-- 审计进行中 -->
            <div v-if="isRunningKbAudit" class="kb-audit-loading">
              <span class="loading-spinner"></span>
              <span>🔍 AI 正在分析知识库与测试用例的差距，预计 20-40 秒...</span>
            </div>
            <!-- 审计结果 -->
            <div v-else-if="task.kb_audit_result" class="kb-audit-result">
              <div class="kb-audit-text" v-html="formatReviewMarkdown(task.kb_audit_result)"></div>
              <div class="kb-audit-actions">
                <el-button size="small" @click="copyKbAuditResult" type="primary" plain>
                  📋 复制审计建议
                </el-button>
              </div>
            </div>
            <!-- 无审计结果 -->
            <div v-else class="kb-audit-empty">
              <span>暂无审计结果，点击上方「重新审计」按钮开始分析</span>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <div v-if="isLoading" class="loading-state">
      <p>🔄 正在加载任务详情...</p>
    </div>

    <div v-else-if="!task.task_id" class="error-state">
      <h3>任务不存在或已被删除</h3>
      <p style="color:#999;font-size:14px;margin:8px 0 16px;">1.5 秒后自动返回列表...</p>
      <router-link to="/generated-testcases">立即返回任务列表</router-link>
    </div>

    <div v-else class="task-content">
      <!-- 批量操作区域 -->
      <div class="batch-actions" v-if="testCases.length > 0">
        <div class="selection-info">
          <label class="select-all">
            <input 
              type="checkbox" 
              :checked="isAllSelected" 
              @change="toggleSelectAll">
            全选
          </label>
          <span class="selected-count" v-if="selectedCases.length > 0">
            已选择 {{ selectedCases.length }} 条用例
          </span>
        </div>
        <div class="batch-buttons">
          <button 
            class="batch-adopt-btn" 
            :disabled="selectedCases.length === 0"
            @click="batchAdopt">
            ✅ 一键采纳 ({{ selectedCases.length }})
          </button>
          <button 
            class="batch-discard-btn" 
            :disabled="selectedCases.length === 0"
            @click="batchDiscard">
            ❌ 一键弃用 ({{ selectedCases.length }})
          </button>
          <button 
            class="batch-convert-btn" 
            :disabled="selectedCases.length === 0"
            @click="convertToUiAutomation(selectedCases)"
            title="将勾选的用例转为UI自动化AI用例（可只选一条）"
            style="background:#409eff;color:#fff;border:none;border-radius:4px;padding:6px 10px;cursor:pointer;">
            🚀 转UI自动化 ({{ selectedCases.length }})
          </button>
        </div>
      </div>

      <!-- 测试用例列表 -->
      <div class="testcases-table" v-if="testCases.length > 0">
        <div class="table-header">
          <div class="header-cell checkbox-cell">选择</div>
          <div class="header-cell">测试用例编号</div>
          <div class="header-cell">测试场景</div>
          <div class="header-cell">前置条件</div>
          <div class="header-cell">操作步骤</div>
          <div class="header-cell">预期结果</div>
          <div class="header-cell">优先级</div>
          <div class="header-cell">操作</div>
        </div>
        
        <div class="table-body">
          <div 
            v-for="(testCase, index) in paginatedTestCases" 
            :key="testCase.id || index"
            class="table-row">
            <div class="body-cell checkbox-cell">
              <input 
                type="checkbox" 
                :value="testCase"
                v-model="selectedCases"
                @change="updateSelectAll">
            </div>
            <div class="body-cell">{{ testCase.caseId || `TC${String(index + 1).padStart(3, '0')}` }}</div>
            <div class="body-cell">{{ testCase.scenario }}</div>
            <div class="body-cell text-limit-2">{{ formatTextForList(testCase.precondition) }}</div>
            <div class="body-cell text-limit-2">{{ formatTextForList(testCase.steps) }}</div>
            <div class="body-cell text-limit-2">{{ formatTextForList(testCase.expected) }}</div>
            <div class="body-cell">
              <span class="priority-tag" :class="testCase.priority?.toLowerCase()">{{ testCase.priority || 'P2' }}</span>
            </div>
            <div class="body-cell">
              <div class="action-buttons">
                <button class="view-btn" @click="viewCaseDetail(testCase, index)">📖 查看详情</button>
                <button class="adopt-btn" @click="adoptSingleCase(testCase, index)">✅ 采纳</button>
                <button class="discard-btn" @click="discardSingleCase(testCase, index)">❌ 弃用</button>
                <button
                  class="convert-btn"
                  @click="convertToUiAutomation([testCase])"
                  title="仅将这一条用例转为UI自动化AI用例"
                  style="background:#409eff;color:#fff;border:none;border-radius:4px;padding:2px 6px;cursor:pointer;font-size:12px;">
                  🚀 转UI
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="empty-state">
        <h3>暂无测试用例数据</h3>
        <p>该任务还没有生成测试用例或用例已被清空</p>
      </div>

      <!-- 分页 -->
      <div v-if="testCases.length > 0" class="pagination-section">
        <div class="pagination-info">
          显示 {{ paginationStart }}-{{ paginationEnd }} 条，共 {{ testCases.length }} 条
        </div>
        <div class="pagination-controls">
          <div class="page-size-selector">
            <label>每页显示：</label>
            <select v-model="pageSize" @change="currentPage = 1">
              <option value="10">10 条</option>
              <option value="20">20 条</option>
              <option value="50">50 条</option>
            </select>
          </div>
          <div class="pagination-buttons">
            <button :disabled="currentPage <= 1" @click="currentPage--">上一页</button>
            <span class="current-page">第 {{ currentPage }} 页，共 {{ totalPages }} 页</span>
            <button :disabled="currentPage >= totalPages" @click="currentPage++">下一页</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 用例详情弹窗 -->
    <div v-if="showCaseDetail" class="case-detail-modal" @keydown.esc="closeCaseDetail">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>{{ isEditing ? '编辑测试用例' : '测试用例详情' }}</h3>
          <button class="close-btn" @click="closeCaseDetail">×</button>
        </div>

        <!-- 查看模式 -->
        <div v-if="!isEditing" class="modal-body">
          <div class="detail-item">
            <label>用例编号:</label>
            <span>{{ selectedCase.caseId || `TC${String(selectedCaseIndex + 1).padStart(3, '0')}` }}</span>
          </div>
          <div class="detail-item">
            <label>测试场景:</label>
            <p v-html="formatMarkdown(selectedCase.scenario)"></p>
          </div>
          <div class="detail-item">
            <label>前置条件:</label>
            <p v-html="formatMarkdown(selectedCase.precondition || '无')"></p>
          </div>
          <div class="detail-item">
            <label>操作步骤:</label>
            <p class="test-steps" v-html="formatMarkdown(selectedCase.steps)"></p>
          </div>
          <div class="detail-item">
            <label>预期结果:</label>
            <p v-html="formatMarkdown(selectedCase.expected)"></p>
          </div>
          <div class="detail-item">
            <label>优先级:</label>
            <span class="priority-tag" :class="selectedCase.priority?.toLowerCase()">{{ selectedCase.priority || 'P2' }}</span>
          </div>
        </div>

        <!-- 编辑模式 -->
        <div v-else class="modal-body edit-mode">
          <div class="form-item">
            <label>用例编号:</label>
            <span class="readonly-field">{{ editForm.caseId || `TC${String(selectedCaseIndex + 1).padStart(3, '0')}` }}</span>
          </div>
          <div class="form-item">
            <label>测试场景:</label>
            <el-input v-model="editForm.scenario" type="textarea" :rows="2" placeholder="请输入测试场景" />
          </div>
          <div class="form-item">
            <label>前置条件:</label>
            <el-input v-model="editForm.precondition" type="textarea" :rows="3" placeholder="请输入前置条件" />
          </div>
          <div class="form-item">
            <label>操作步骤:</label>
            <el-input v-model="editForm.steps" type="textarea" :rows="6" placeholder="请输入操作步骤" />
          </div>
          <div class="form-item">
            <label>预期结果:</label>
            <el-input v-model="editForm.expected" type="textarea" :rows="4" placeholder="请输入预期结果" />
          </div>
          <div class="form-item">
            <label>优先级:</label>
            <el-select v-model="editForm.priority" placeholder="请选择优先级">
              <el-option label="P0" value="P0"></el-option>
              <el-option label="P1" value="P1"></el-option>
              <el-option label="P2" value="P2"></el-option>
              <el-option label="P3" value="P3"></el-option>
            </el-select>
          </div>
        </div>

        <!-- 底部操作栏 -->
        <div class="modal-footer">
          <template v-if="!isEditing">
            <button class="action-btn edit-btn" @click="startEdit">
              <span>✏️ 编辑</span>
            </button>
            <button class="action-btn close-btn-footer" @click="closeCaseDetail">关闭</button>
          </template>
          <template v-else>
            <button class="action-btn save-btn" @click="saveEdit" :disabled="isSaving">
              <span v-if="isSaving">💾 保存中...</span>
              <span v-else>💾 保存</span>
            </button>
            <button class="action-btn cancel-btn" @click="cancelEdit" :disabled="isSaving">取消</button>
          </template>
        </div>
      </div>
    </div>

    <!-- 基于调整重新生成确认弹窗 -->
    <div v-if="showRegenerateDialog" class="modal-overlay" @click.self="showRegenerateDialog = false">
      <div class="regenerate-new-modal">
        <div class="quick-version-header">
          <h3>🔄 基于调整重新生成</h3>
          <button class="preview-close" @click="showRegenerateDialog = false">✕</button>
        </div>
        <div class="regenerate-new-body">
          <!-- 生成模式选择 -->
          <div class="form-group">
            <label>生成模式
              <span class="field-hint">（当前：{{ generationModeLabel(task.generation_mode) }}）</span>
            </label>
            <div class="mode-cards">
              <div
                v-for="mode in generationModes"
                :key="mode.value"
                class="mode-card"
                :class="{ active: regenerateForm.generation_mode === mode.value }"
                @click="regenerateForm.generation_mode = mode.value"
              >
                <span class="mode-icon">{{ mode.icon }}</span>
                <span class="mode-label">{{ mode.label }}</span>
                <span class="mode-desc">{{ mode.desc }}</span>
              </div>
            </div>
          </div>

          <!-- 功能模块 -->
          <div class="form-group">
            <label>功能模块
              <span class="field-hint">（当前：{{ task.feature_module_name || '未设置' }}）</span>
            </label>
            <select
              v-model="regenerateForm.feature_module_id"
              class="form-select"
              @change="onRegenerateFeatureModuleChange"
            >
              <option :value="null">不指定功能模块</option>
              <option v-for="fm in regenerateFeatureModules" :key="fm.id" :value="fm.id">
                {{ fm.name }}
              </option>
            </select>
          </div>

          <!-- 测试点 -->
          <div class="form-group">
            <label>测试点
              <span class="field-hint">（当前：{{ task.test_point_name || '未设置' }}）</span>
            </label>
            <select
              v-model="regenerateForm.test_point_id"
              class="form-select"
              :disabled="!regenerateForm.feature_module_id"
            >
              <option :value="null">不指定测试点</option>
              <option v-for="tp in regenerateTestPoints" :key="tp.id" :value="tp.id">
                {{ tp.name }}
              </option>
            </select>
            <span v-if="!regenerateForm.feature_module_id" class="field-tip">请先选择功能模块</span>
          </div>

          <!-- 说明 -->
          <div class="regen-warning-box">
            <p>⚠️ AI 将根据 <strong>评审报告的意见</strong>，结合你逐项确认的回复，重新生成改进版测试用例。</p>
            <p style="margin-top:6px;">重新生成会 <strong>覆盖当前的用例内容</strong>，原内容将无法恢复。</p>
          </div>
        </div>

        <div class="quick-version-actions">
          <button class="toolbar-btn" @click="showRegenerateDialog = false">取消</button>
          <button
            class="regenerate-btn"
            @click="doRegenerate"
            :disabled="isRegenerating"
            style="width:auto;padding:8px 28px;"
          >
            <span v-if="isRegenerating">⏳ 重新生成中...</span>
            <span v-else>✅ 确认重新生成</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 从头重新生成确认弹窗 -->
    <div v-if="showRegenerateNewDialog" class="modal-overlay" @click.self="showRegenerateNewDialog = false">
      <div class="regenerate-new-modal">
        <div class="quick-version-header">
          <h3>🆕 从头重新生成测试用例</h3>
          <button class="preview-close" @click="showRegenerateNewDialog = false">✕</button>
        </div>
        <div class="regenerate-new-body">
          <!-- 生成模式选择 -->
          <div class="form-group">
            <label>生成模式</label>
            <div class="mode-cards">
              <div
                v-for="mode in generationModes"
                :key="mode.value"
                class="mode-card"
                :class="{ active: regenerateNewForm.generation_mode === mode.value }"
                @click="regenerateNewForm.generation_mode = mode.value"
              >
                <span class="mode-icon">{{ mode.icon }}</span>
                <span class="mode-label">{{ mode.label }}</span>
                <span class="mode-desc">{{ mode.desc }}</span>
              </div>
            </div>
          </div>

          <!-- 功能模块 -->
          <div class="form-group">
            <label>功能模块
              <span class="field-hint">（当前：{{ task.feature_module_name || '未设置' }}）</span>
            </label>
            <select
              v-model="regenerateNewForm.feature_module_id"
              class="form-select"
              @change="onRegenerateNewFeatureModuleChange"
            >
              <option :value="null">不指定功能模块</option>
              <option v-for="fm in regenerateNewFeatureModules" :key="fm.id" :value="fm.id">
                {{ fm.name }}
              </option>
            </select>
          </div>

          <!-- 测试点 -->
          <div class="form-group">
            <label>测试点
              <span class="field-hint">（当前：{{ task.test_point_name || '未设置' }}）</span>
            </label>
            <select
              v-model="regenerateNewForm.test_point_id"
              class="form-select"
              :disabled="!regenerateNewForm.feature_module_id"
            >
              <option :value="null">不指定测试点</option>
              <option v-for="tp in regenerateNewTestPoints" :key="tp.id" :value="tp.id">
                {{ tp.name }}
              </option>
            </select>
            <span v-if="!regenerateNewForm.feature_module_id" class="field-tip">请先选择功能模块</span>
          </div>

          <!-- 需求描述 -->
          <div class="form-group">
            <label>需求描述
              <span class="field-hint">（可直接编辑修改后再生成）</span>
            </label>
            <textarea
              v-model="regenerateNewForm.requirement_text"
              class="requirement-textarea"
              rows="8"
              placeholder="输入需求描述..."
            ></textarea>
          </div>
        </div>

        <div class="quick-version-actions">
          <button class="toolbar-btn" @click="showRegenerateNewDialog = false">取消</button>
          <button
            class="generate-manual-btn"
            @click="confirmRegenerateNew"
            :disabled="isRegeneratingNew || !regenerateNewForm.requirement_text.trim()"
            style="width:auto;padding:8px 28px;"
          >
            <span v-if="isRegeneratingNew">⏳ 创建任务中...</span>
            <span v-else>✅ 确认并开始生成</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import api from '@/utils/api'
import { importGeneratedToAICase } from '@/api/requirement-analysis'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DocumentCopy } from '@element-plus/icons-vue'
import * as XLSX from 'xlsx'

export default {
  name: 'TaskDetail',
  data() {
    return {
      taskId: '',
      task: {},
      testCases: [],
      selectedCases: [],
      isLoading: true,
      showCaseDetail: false,
      selectedCase: {},
      selectedCaseIndex: 0,
      currentPage: 1,
      pageSize: 10,
      isExporting: false,
      isRegenerating: false,
      isRerunningReview: false,  // 重新评审loading
      rerunElapsed: 0,          // 已等待秒数
      rerunTimer: null,         // 计时器引用
      isSavingFeedback: false,
      feedbackItems: [],  // 逐项确认列表 [{question, reply}]
      activeCollapse: ['review'],  // 评审报告默认展开
      // KB审计相关
      isRunningKbAudit: false,
      kbAuditCollapse: [],  // KB审计卡片默认折叠
      // 编辑相关状态
      isEditing: false,
      isSaving: false,
      editForm: {
        caseId: '',
        scenario: '',
        precondition: '',
        steps: '',
        expected: '',
        priority: 'P2'
      },
      // 基于调整重新生成确认弹窗
      showRegenerateDialog: false,
      regenerateForm: {
        generation_mode: 'smart',
        feature_module_id: null,
        test_point_id: null,
      },
      regenerateFeatureModules: [],
      regenerateTestPoints: [],
      // 从头重新生成弹窗
      showRegenerateNewDialog: false,
      isRegeneratingNew: false,
      regenerateNewForm: {
        requirement_text: '',
        generation_mode: 'smart',
        feature_module_id: null,
        test_point_id: null,
      },
      regenerateNewFeatureModules: [],
      regenerateNewTestPoints: [],
      generationModes: [
        { value: 'smart', label: '智能', icon: '🤖', desc: 'AI评估' },
        { value: 'quick', label: '快速', icon: '⚡', desc: '10~20条' },
        { value: 'standard', label: '标准', icon: '📋', desc: '20~40条' },
        { value: 'comprehensive', label: '全面', icon: '🔬', desc: '不限' },
      ]
    }
  },

  computed: {
    isAllSelected() {
      return this.testCases.length > 0 && this.selectedCases.length === this.testCases.length
    },

    totalPages() {
      return Math.ceil(this.testCases.length / this.pageSize)
    },

    paginatedTestCases() {
      const start = (this.currentPage - 1) * this.pageSize
      const end = start + this.pageSize
      return this.testCases.slice(start, end)
    },

    paginationStart() {
      return (this.currentPage - 1) * this.pageSize + 1
    },

    paginationEnd() {
      return Math.min(this.currentPage * this.pageSize, this.testCases.length)
    },

    // 是否包含AI自动检测的不确定项
    hasAutoDetectedItems() {
      return this.feedbackItems.some(item => item._autoDetected)
    },

    // 未回复的自动检测项数量
    unrepliedAutoCount() {
      return this.feedbackItems.filter(item => item._autoDetected && item._initialPending).length
    },

    // 待填写的确认项（基于初始标记，非实时过滤，避免输入时 item 消失）
    pendingFeedbackItems() {
      return this.feedbackItems
        .map((item, idx) => ({ ...item, _origIdx: idx }))
        .filter(item => item._initialPending)
    },

    // 已回复的确认项
    repliedFeedbackItems() {
      return this.feedbackItems
        .map((item, idx) => ({ ...item, _origIdx: idx }))
        .filter(item => !item._initialPending)
    }
  },

  mounted() {
    this.taskId = this.$route.params.taskId
    this.loadTaskDetail()
  },

  methods: {
    // 复制需求描述文本
    async copyRequirementText() {
      try {
        await navigator.clipboard.writeText(this.task.requirement_text)
        ElMessage.success('需求描述已复制到剪贴板')
      } catch (error) {
        // 如果 navigator.clipboard 不可用，使用备用方法
        const textArea = document.createElement('textarea')
        textArea.value = this.task.requirement_text
        textArea.style.position = 'fixed'
        textArea.style.opacity = '0'
        document.body.appendChild(textArea)
        textArea.select()
        try {
          document.execCommand('copy')
          ElMessage.success('需求描述已复制到剪贴板')
        } catch (err) {
          ElMessage.error('复制失败，请手动复制')
        }
        document.body.removeChild(textArea)
      }
    },

    // 格式化评审时间，显示为 "MM-DD HH:mm 完成"
    formatReviewTime(isoStr) {
      if (!isoStr) return ''
      const d = new Date(isoStr)
      const mm = String(d.getMonth() + 1).padStart(2, '0')
      const dd = String(d.getDate()).padStart(2, '0')
      const hh = String(d.getHours()).padStart(2, '0')
      const mi = String(d.getMinutes()).padStart(2, '0')
      return `${mm}-${dd} ${hh}:${mi} 完成`
    },

    // 格式化评审报告 Markdown
    formatReviewMarkdown(text) {
      if (!text) return ''
      // 先转义HTML标签，防止XSS
      let formatted = text.replace(/&/g, '&amp;')
                         .replace(/</g, '&lt;')
                         .replace(/>/g, '&gt;')

      // Markdown 标题：## → <h3>, ### → <h4>
      formatted = formatted.replace(/^### (.+)$/gm, '<h4 class="review-h4">$1</h4>')
      formatted = formatted.replace(/^## (.+)$/gm, '<h3 class="review-h3">$1</h3>')
      formatted = formatted.replace(/^# (.+)$/gm, '<h2 class="review-h2">$1</h2>')

      // 加粗
      formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

      // 行内代码
      formatted = formatted.replace(/`([^`]+)`/g, '<code class="review-code">$1</code>')

      // 引用
      formatted = formatted.replace(/^&gt; (.+)$/gm, '<blockquote class="review-blockquote">$1</blockquote>')

      // 分隔线
      formatted = formatted.replace(/^---$/gm, '<hr class="review-hr">')

      // 无序列表
      formatted = formatted.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>')
      // 将连续的 <li> 包裹在 <ul> 中
      formatted = formatted.replace(/(<li>.*?<\/li>\n?)+/g, '<ul class="review-ul">$&</ul>')

      // 有序列表
      formatted = formatted.replace(/^\d+\. (.+)$/gm, '<li>$1</li>')

      // 换行
      formatted = formatted.replace(/\n/g, '<br>')


      return formatted
    },

    // 序列化逐项确认列表为存储字符串
    serializeFeedbackItems() {
      const valid = this.feedbackItems.filter(item => item.question.trim() || item.reply.trim())
      if (valid.length === 0) return ''
      return valid.map((item, i) => {
        return `【确认项 #${i + 1}】\n不确定需求：${item.question.trim() || '(未填写)'}\n确认回复：${item.reply.trim() || '(未填写)'}`
      }).join('\n\n')
    },

    // 从存储字符串反序列化为确认项列表
    deserializeFeedbackItems(str) {
      if (!str || !str.trim()) return []
      const items = []
      const blocks = str.split(/【确认项 #\d+】/).filter(b => b.trim())
      blocks.forEach(block => {
        const qMatch = block.match(/不确定需求：(.+)/)
        const rMatch = block.match(/确认回复：(.+)/)
        const reply = rMatch ? rMatch[1].trim() : ''
        const question = qMatch ? qMatch[1].trim() : ''
        const isPending = !reply || reply === '(未填写)'
        items.push({
          question: question,
          reply: reply,
          // 如果回复仍为"(未填写)"且问题非空，说明是AI自动检测的项
          _autoDetected: (reply === '(未填写)' && question !== '' && question !== '(未填写)'),
          // 初始 pending 状态（只算一次，不受后续编辑影响，避免输入时 item 消失）
          _initialPending: isPending
        })
      })
      return items
    },

    // 添加确认项
    addFeedbackItem() {
      this.feedbackItems.push({ question: '', reply: '', _initialPending: true, _autoDetected: false })
    },

    // 删除确认项
    removeFeedbackItem(idx) {
      this.feedbackItems.splice(idx, 1)
    },

    // 保存逐项确认回复到数据库
    async saveHumanFeedback() {
      const validItems = this.feedbackItems.filter(item => item.question.trim() || item.reply.trim())
      if (validItems.length === 0) {
        ElMessage.warning('请至少添加一项确认内容')
        return
      }
      this.isSavingFeedback = true
      try {
        const feedbackStr = this.serializeFeedbackItems()
        await api.patch(`/requirement-analysis/api/testcase-generation/${this.taskId}/`, {
          human_feedback: feedbackStr
        })
        ElMessage.success(`已保存 ${validItems.length} 项确认回复`)
      } catch (error) {
        console.error('保存回复失败:', error)
        const errMsg = error.response?.data?.error || error.message
        ElMessage.error('保存失败: ' + errMsg)
      } finally {
        this.isSavingFeedback = false
      }
    },

    // 单独重新评审（使用最新prompt，自动识别不确定项）
    async rerunReview() {
      try {
        await ElMessageBox.confirm(
          '将使用最新的评审规则重新评审现有用例，自动识别不确定需求点。\n\n✅ 评审完成后会保留现有用例，仅更新评审报告和确认卡片。',
          '确认重新评审',
          {
            confirmButtonText: '确定重新评审',
            cancelButtonText: '取消',
            type: 'info'
          }
        )
      } catch {
        return
      }

      this.isRerunningReview = true
      this.rerunElapsed = 0
      // 启动计时器，每秒+1
      this.rerunTimer = setInterval(() => { this.rerunElapsed++ }, 1000)

      try {
        await api.post(`/requirement-analysis/api/testcase-generation/${this.taskId}/rerun_review/`)
        ElMessage.success('重新评审已启动，正在等待AI完成评审...')

        // 轮询任务状态，直到评审完成
        let attempts = 0
        const maxAttempts = 90 // 最多等3分钟
        const poll = async () => {
          if (attempts >= maxAttempts) {
            ElMessage.warning('评审超时，请手动刷新页面查看。')
            this.stopRerunPolling()
            return
          }
          attempts++
          await new Promise(r => setTimeout(r, 2000))
          const progressRes = await api.get(`/requirement-analysis/api/testcase-generation/${this.taskId}/progress/`)
          if (progressRes.data.status === 'completed') {
            await this.loadTaskDetail()
            ElMessage.success('🎉 重新评审完成！不确定项已自动识别。')
            this.stopRerunPolling()
          } else if (progressRes.data.status === 'failed') {
            ElMessage.error('重新评审失败，请查看错误信息。')
            await this.loadTaskDetail()
            this.stopRerunPolling()
          } else {
            poll()
          }
        }
        poll()
      } catch (err) {
        const errMsg = err.response?.data?.error || err.message || '重新评审失败'
        ElMessage.error(errMsg)
        this.stopRerunPolling()
      }
    },

    // 停止重新评审轮询
    stopRerunPolling() {
      this.isRerunningReview = false
      if (this.rerunTimer) {
        clearInterval(this.rerunTimer)
        this.rerunTimer = null
      }
    },

    // 手动检查重新评审状态
    async checkRerunStatus() {
      try {
        const res = await api.get(`/requirement-analysis/api/testcase-generation/${this.taskId}/progress/`)
        if (res.data.status === 'completed') {
          await this.loadTaskDetail()
          ElMessage.success('评审已完成！')
          this.stopRerunPolling()
        } else if (res.data.status === 'failed') {
          ElMessage.error('评审失败')
          await this.loadTaskDetail()
          this.stopRerunPolling()
        } else {
          ElMessage.info(`当前状态：${res.data.status}，请继续等待...`)
        }
      } catch {
        ElMessage.error('获取状态失败，请刷新页面。')
      }
    },

    // ========== 基于调整重新生成相关方法 ==========

    // 打开「基于调整重新生成」确认弹窗，预填当前任务参数
    async openRegenerateDialog() {
      this.regenerateForm = {
        generation_mode: this.task.generation_mode || 'smart',
        feature_module_id: this.task.feature_module || null,
        test_point_id: this.task.test_point || null,
      }
      this.regenerateFeatureModules = []
      this.regenerateTestPoints = []

      // 加载当前项目的功能模块列表
      if (this.task.project) {
        try {
          const res = await api.get('/feature-modules/', { params: { project: this.task.project } })
          this.regenerateFeatureModules = res.data.results || res.data || []
        } catch (e) {
          console.error('加载功能模块失败:', e)
        }
      }

      // 加载当前功能模块的测试点列表
      if (this.regenerateForm.feature_module_id) {
        await this.loadRegenerateTestPoints(this.regenerateForm.feature_module_id)
      }

      this.showRegenerateDialog = true
    },

    // 切换功能模块时重新加载测试点
    async onRegenerateFeatureModuleChange() {
      this.regenerateForm.test_point_id = null
      await this.loadRegenerateTestPoints(this.regenerateForm.feature_module_id)
    },

    // 加载指定功能模块的测试点
    async loadRegenerateTestPoints(moduleId) {
      if (!moduleId) {
        this.regenerateTestPoints = []
        return
      }
      try {
        const res = await api.get(`/feature-modules/modules/${moduleId}/test-points/`)
        this.regenerateTestPoints = res.data || []
      } catch (e) {
        console.error('加载测试点失败:', e)
        this.regenerateTestPoints = []
      }
    },

    // 生成模式标签
    generationModeLabel(mode) {
      const map = { smart: '🤖 智能', quick: '⚡ 快速', standard: '📋 标准', comprehensive: '🔬 全面' }
      return map[mode] || mode || '未知'
    },

    // 确认执行「基于调整重新生成」
    async doRegenerate() {
      this.showRegenerateDialog = false
      this.isRegenerating = true

      try {
        const feedbackStr = this.serializeFeedbackItems()
        const postData = {
          human_feedback: feedbackStr,
          // 传递可编辑的关联参数
          generation_mode: this.regenerateForm.generation_mode,
          feature_module: this.regenerateForm.feature_module_id,
          test_point: this.regenerateForm.test_point_id,
        }
        const response = await api.post(`/requirement-analysis/api/testcase-generation/${this.taskId}/regenerate/`, postData)

        if (response.data.task) {
          this.task = response.data.task
          this.feedbackItems = this.deserializeFeedbackItems(this.task.human_feedback || '')
          if (this.task.final_test_cases) {
            this.testCases = this.parseTestCases(this.task.final_test_cases)
          }
          this.selectedCases = []
          this.currentPage = 1

          if (response.data.warning) {
            ElMessage.warning(response.data.warning)
          } else {
            ElMessage.success(response.data.message || '测试用例重新生成成功')
          }
        } else {
          ElMessage.warning('重新生成完成，但未返回有效数据')
        }
      } catch (error) {
        console.error('重新生成失败:', error)
        const errMsg = error.response?.data?.error || error.message
        ElMessage.error('重新生成失败: ' + errMsg)
      } finally {
        this.isRegenerating = false
      }
    },

    // 基于人工调整 + 评审意见，调用AI重新生成用例（保留旧方法名，内部直接打开弹窗）
    async regenerate() {
      this.openRegenerateDialog()
    },

    // ========== 从头重新生成相关方法 ==========

    // 打开"从头重新生成"弹窗，预填当前任务参数
    async openRegenerateNewDialog() {
      // 预填表单
      this.regenerateNewForm = {
        requirement_text: this.task.requirement_text || '',
        generation_mode: this.task.generation_mode || 'smart',
        feature_module_id: this.task.feature_module || null,
        test_point_id: this.task.test_point || null,
      }
      this.regenerateNewFeatureModules = []
      this.regenerateNewTestPoints = []

      // 加载当前项目的功能模块列表
      if (this.task.project) {
        try {
          const res = await api.get('/feature-modules/', { params: { project: this.task.project } })
          this.regenerateNewFeatureModules = res.data.results || res.data || []
        } catch (e) {
          console.error('加载功能模块失败:', e)
        }
      }

      // 加载当前功能模块的测试点列表
      if (this.regenerateNewForm.feature_module_id) {
        await this.loadRegenerateNewTestPoints(this.regenerateNewForm.feature_module_id)
      }

      this.showRegenerateNewDialog = true
    },

    // 切换功能模块时重新加载测试点
    async onRegenerateNewFeatureModuleChange() {
      this.regenerateNewForm.test_point_id = null
      await this.loadRegenerateNewTestPoints(this.regenerateNewForm.feature_module_id)
    },

    // 加载指定功能模块的测试点
    async loadRegenerateNewTestPoints(moduleId) {
      if (!moduleId) {
        this.regenerateNewTestPoints = []
        return
      }
      try {
        const res = await api.get(`/feature-modules/modules/${moduleId}/test-points/`)
        this.regenerateNewTestPoints = res.data || []
      } catch (e) {
        console.error('加载测试点失败:', e)
        this.regenerateNewTestPoints = []
      }
    },

    // 确认从头重新生成
    async confirmRegenerateNew() {
      if (this.isRegeneratingNew) return
      const text = this.regenerateNewForm.requirement_text.trim()
      if (!text) {
        ElMessage.warning('请填写需求描述')
        return
      }
      this.isRegeneratingNew = true
      try {
        const requestData = {
          title: this.task.title || '重新生成',
          requirement_text: text,
          use_writer_model: true,
          use_reviewer_model: true,
          output_mode: 'stream',
          generation_mode: this.regenerateNewForm.generation_mode || 'smart',
        }
        if (this.task.project) requestData.project = this.task.project
        if (this.task.version) requestData.version = this.task.version
        if (this.regenerateNewForm.feature_module_id) requestData.feature_module = this.regenerateNewForm.feature_module_id
        if (this.regenerateNewForm.test_point_id) requestData.test_point = this.regenerateNewForm.test_point_id

        const response = await api.post('/requirement-analysis/api/testcase-generation/generate/', requestData)
        const newTaskId = response.data.task_id
        this.showRegenerateNewDialog = false
        ElMessage.success('新生成任务已创建，正在跳转...')
        // 跳转到新任务详情页
        this.$router.push(`/requirement-analysis/tasks/${newTaskId}`)
      } catch (error) {
        console.error('创建任务失败:', error)
        ElMessage.error('创建任务失败: ' + (error.response?.data?.error || error.message))
      } finally {
        this.isRegeneratingNew = false
      }
    },

    // ========== 知识库审计相关方法 ==========

    // 启动知识库智能审计
    async runKbAudit() {
      if (this.isRunningKbAudit) return
      this.isRunningKbAudit = true
      try {
        await api.post(`/requirement-analysis/api/testcase-generation/${this.taskId}/audit-kb/`)
        ElMessage.success('知识库审计已启动，正在等待AI完成分析...')

        // 轮询等待审计完成（kb_audit_result 有值即完成）
        let attempts = 0
        const maxAttempts = 60 // 最多等2分钟
        const poll = async () => {
          if (attempts >= maxAttempts) {
            ElMessage.warning('知识库审计超时，请手动刷新页面查看。')
            this.isRunningKbAudit = false
            return
          }
          attempts++
          await new Promise(r => setTimeout(r, 3000))
          const taskRes = await api.get(`/requirement-analysis/api/testcase-generation/${this.taskId}/`)
          if (taskRes.data.kb_audit_result) {
            this.task.kb_audit_result = taskRes.data.kb_audit_result
            this.kbAuditCollapse = ['kb-audit']  // 展开审计卡片
            ElMessage.success('📚 知识库审计完成！请查看审计建议。')
            this.isRunningKbAudit = false
          } else {
            poll()
          }
        }
        poll()
      } catch (err) {
        const errMsg = err.response?.data?.error || err.message || '知识库审计失败'
        ElMessage.error(errMsg)
        this.isRunningKbAudit = false
      }
    },

    // 复制审计建议
    async copyKbAuditResult() {
      try {
        await navigator.clipboard.writeText(this.task.kb_audit_result || '')
        ElMessage.success('审计建议已复制到剪贴板')
      } catch {
        ElMessage.error('复制失败，请手动复制')
      }
    },


    async loadTaskDetail() {
      try {
        // 获取任务基本信息
        const taskResponse = await api.get(`/requirement-analysis/api/testcase-generation/${this.taskId}/`)
        this.task = taskResponse.data
        this.feedbackItems = this.deserializeFeedbackItems(this.task.human_feedback || '')

        // 解析最终测试用例
        if (this.task.final_test_cases) {
          this.testCases = this.parseTestCases(this.task.final_test_cases)
        }
      } catch (error) {
        console.error('加载任务详情失败:', error)
        if (error.response?.status === 404) {
          ElMessage.warning('任务不存在或已被删除，即将返回列表')
          setTimeout(() => {
            this.$router.replace('/generated-testcases')
          }, 1500)
        } else {
          ElMessage.error('加载任务详情失败')
        }
      } finally {
        this.isLoading = false
      }
    },

    parseTestCases(content) {
      // 复用RequirementAnalysisView中的解析逻辑
      if (!content) return []

      // 去除markdown加粗标记，保留纯净文本
      let cleanContent = content.replace(/\*\*([^*]+)\*\*/g, '$1')

      const lines = cleanContent.split('\n').filter(line => line.trim())
      const testCases = []

      // 尝试解析表格格式
      let isTableFormat = false
      const tableData = []

      for (let line of lines) {
        const trimmedLine = line.trim()
        if (trimmedLine.includes('|') && !trimmedLine.includes('--------')) {
          let cells = trimmedLine.split('|').map(cell => cell.trim())
          // 移除首尾空字符串（split('|') 在首尾会产生空字符串）
          while (cells.length > 0 && cells[0] === '') cells.shift()
          while (cells.length > 0 && cells[cells.length - 1] === '') cells.pop()
          if (cells.length > 1) {
            tableData.push(cells)
            isTableFormat = true
          }
        }
      }
      
      if (isTableFormat && tableData.length > 1) {
        // 表格格式解析
        const headers = tableData[0]
        for (let i = 1; i < tableData.length; i++) {
          const row = tableData[i]
          const testCase = {}

          // 清理<br>标签的辅助函数
          const cleanBrTags = (text) => {
            if (!text) return ''
            return text.replace(/<br\s*\/?>/gi, '\n')
          }

          headers.forEach((header, index) => {
            const value = cleanBrTags(row[index] || '')

            // 使用更精确的匹配逻辑，避免误判
            const cleanHeader = header.trim().toLowerCase()

            // 优先级匹配，避免误判
            if (cleanHeader === '优先级' || cleanHeader === 'priority' || cleanHeader === 'priority（优先级）' || cleanHeader === '优先级（priority）') {
              testCase.priority = value
            } else if (cleanHeader === '用例id' || cleanHeader === '编号' || cleanHeader === 'id' || cleanHeader.includes('用例id')) {
              testCase.caseId = value
            } else if (cleanHeader === '测试目标' || cleanHeader === '测试场景' || cleanHeader === '场景' || cleanHeader === '标题' || cleanHeader.includes('测试目标')) {
              testCase.scenario = value
            } else if (cleanHeader === '前置条件' || cleanHeader === '前置' || cleanHeader === '前提条件') {
              testCase.precondition = value
            } else if (cleanHeader === '测试步骤' || cleanHeader === '操作步骤' || cleanHeader === '步骤') {
              // 确保不要误匹配"预期结果"中包含的"步骤"字样
              if (!cleanHeader.includes('预期') && !cleanHeader.includes('结果')) {
                testCase.steps = value
              }
            } else if (cleanHeader === '预期结果' || cleanHeader === '预期' || cleanHeader === '结果' || cleanHeader.includes('预期结果')) {
              testCase.expected = value
            }
          })

          if (testCase.scenario || testCase.caseId) {
            // 如果没有steps字段，使用scenario作为steps的默认值
            if (!testCase.steps && testCase.scenario) {
              testCase.steps = '参考测试目标执行相应操作'
            }
            // 如果没有priority，设置默认值
            if (!testCase.priority) {
              testCase.priority = 'P2'
            }
            testCases.push(testCase)
          }
        }
      } else {
        // 结构化文本格式解析
        let currentTestCase = {}
        let caseNumber = 1
        
        for (const line of lines) {
          if (line.includes('测试用例') || line.includes('Test Case') || 
              line.match(/^(\d+\.|\*|\-|\d+、)/)) {
            
            if (Object.keys(currentTestCase).length > 0) {
              testCases.push(currentTestCase)
              caseNumber++
            }
            
            currentTestCase = {
              caseId: `TC${String(caseNumber).padStart(3, '0')}`,
              scenario: line.replace(/^(\d+\.|\*|\-|\d+、)\s*/, '').replace(/测试用例\d*[:：]?\s*/, ''),
              precondition: '',
              steps: '',
              expected: '',
              priority: '中'
            }
          } else if (line.includes('前置条件') || line.includes('前提')) {
            currentTestCase.precondition = line.replace(/.*?[:：]\s*/, '')
          } else if (line.includes('测试步骤') || line.includes('操作步骤') || line.includes('步骤')) {
            currentTestCase.steps = line.replace(/.*?[:：]\s*/, '')
          } else if (line.includes('预期结果') || line.includes('Expected')) {
            currentTestCase.expected = line.replace(/.*?[:：]\s*/, '')
          } else if (line.includes('优先级')) {
            currentTestCase.priority = line.replace(/.*?[:：]\s*/, '')
          }
        }
        
        if (Object.keys(currentTestCase).length > 0) {
          testCases.push(currentTestCase)
        }
      }
      
      return testCases
    },

    getStatusText(status) {
      const statusMap = {
        'pending': '需求分析中',
        'generating': '用例编写中',
        'reviewing': '用例评审中',
        'completed': '已完成',
        'failed': '失败'
      }
      return statusMap[status] || status
    },

    // 格式化列表中的文本，将<br>转换为换行
    formatTextForList(text) {
      if (!text) return ''
      // 将<br>、<br/>、<br />等标签替换为换行符
      return text.replace(/<br\s*\/?>/gi, '\n')
    },

    // 格式化文本，去除markdown标记并保留格式
    formatMarkdown(text) {
      if (!text) return ''

      // 先转义HTML标签，防止XSS
      let formatted = text.replace(/&/g, '&amp;')
                         .replace(/</g, '&lt;')
                         .replace(/>/g, '&gt;')

      // 去除markdown加粗标记 **text**，保留纯文本
      formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '$1')

      // 转换换行符为<br>
      formatted = formatted.replace(/\n/g, '<br>')

      return formatted
    },

    toggleSelectAll() {
      if (this.isAllSelected) {
        this.selectedCases = []
      } else {
        this.selectedCases = [...this.testCases]
      }
    },

    updateSelectAll() {
      // 这个方法会在单个checkbox变化时触发，用于更新全选状态
      // Vue的v-model会自动处理selectedCases数组的更新
    },

    async batchAdopt() {
      if (this.selectedCases.length === 0) {
        ElMessage.warning('请先选择要采纳的测试用例')
        return
      }

      try {
        await ElMessageBox.confirm(
          `确定要采纳选中的 ${this.selectedCases.length} 条测试用例吗？`,
          '确认采纳',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'success'
          }
        )
      } catch {
        return
      }

      try {
        const casesData = this.selectedCases.map((testCase, index) => ({
          title: testCase.scenario || `测试用例${index + 1}`,
          description: testCase.scenario || '',
          preconditions: testCase.precondition || '',
          steps: testCase.steps || '',
          expected_result: testCase.expected || '',
          priority: this.mapPriority(testCase.priority),
          test_type: 'functional',
          status: 'draft'
        }))

        await api.post(`/requirement-analysis/api/testcase-generation/${this.taskId}/batch-adopt-selected/`, {
          test_cases: casesData
        })

        ElMessage.success(`成功采纳 ${this.selectedCases.length} 条测试用例！`)
        this.selectedCases = []

        // 不再移除已采纳的用例，保留在列表中供多次采纳
        // this.testCases = this.testCases.filter(tc => !this.selectedCases.includes(tc))

      } catch (error) {
        console.error('批量采纳失败:', error)
        ElMessage.error('批量采纳失败: ' + (error.response?.data?.message || error.message))
      }
    },

    async batchDiscard() {
      if (this.selectedCases.length === 0) {
        ElMessage.warning('请先选择要弃用的测试用例')
        return
      }

      try {
        await ElMessageBox.confirm(
          `确定要弃用选中的 ${this.selectedCases.length} 条测试用例吗？此操作不可恢复。`,
          '确认弃用',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'warning',
            confirmButtonClass: 'el-button--danger'
          }
        )
      } catch {
        return
      }

      try {
        // 获取选中用例的全局索引（不是分页索引）
        const caseIndices = this.selectedCases.map(selectedCase => {
          // 在完整列表中查找索引
          const globalIndex = this.testCases.findIndex(tc =>
            tc.scenario === selectedCase.scenario &&
            tc.steps === selectedCase.steps &&
            tc.expected === selectedCase.expected
          )
          return globalIndex
        }).filter(index => index !== -1) // 过滤掉未找到的(-1)

        const response = await api.post(`/requirement-analysis/api/testcase-generation/${this.taskId}/discard-selected-cases/`, {
          case_indices: caseIndices
        })

        if (response.data.task_deleted) {
          ElMessage.success('所有测试用例已弃用，任务已删除')
          // 返回到AI生成用例记录列表
          this.$router.push('/generated-testcases')
        } else {
          ElMessage.success(`成功弃用 ${response.data.discarded_count} 条测试用例`)

          // 重新解析更新后的测试用例
          if (response.data.updated_test_cases) {
            this.testCases = this.parseTestCases(response.data.updated_test_cases)
            this.selectedCases = []
            this.currentPage = 1 // 重置到第一页
          }
        }

      } catch (error) {
        console.error('批量弃用失败:', error)
        ElMessage.error('批量弃用失败: ' + (error.response?.data?.error || error.message))
      }
    },

    // 将选中的用例（1条或多条）转为UI自动化AI用例，转换后可在 AI用例管理页直接执行
    async convertToUiAutomation(cases) {
      if (!cases || cases.length === 0) {
        ElMessage.warning('请先选择要转换的测试用例')
        return
      }

      const caseCount = cases.length
      try {
        await ElMessageBox.confirm(
          caseCount === 1
            ? '确定将这 1 条用例转为UI自动化AI用例吗？转换后可在 AI 用例管理页直接执行。'
            : `确定将选中的 ${caseCount} 条用例转为UI自动化AI用例吗？转换后可在 AI 用例管理页直接执行。`,
          '转为UI自动化',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'info'
          }
        )
      } catch {
        return
      }

      try {
        const res = await importGeneratedToAICase({
          task_id: this.taskId,
          cases: cases.map(c => ({
            scenario: c.scenario || '',
            precondition: c.precondition || '',
            steps: c.steps || '',
            expected: c.expected || '',
            priority: c.priority || '',
            caseId: c.caseId || ''
          }))
        })
        ElMessage.success((res.data && res.data.message) || '导入成功，已转为UI自动化AI用例')
        this.selectedCases = []
        this.$router.push('/ai-intelligent-mode/cases')
      } catch (error) {
        console.error('转换失败:', error)
        ElMessage.error('转换失败: ' + (error.response?.data?.error || error.message))
      }
    },

    viewCaseDetail(testCase, index) {
      this.selectedCase = testCase
      this.selectedCaseIndex = index
      this.showCaseDetail = true
    },

    closeCaseDetail() {
      this.showCaseDetail = false
      this.selectedCase = {}
      this.isEditing = false
      this.editForm = {
        caseId: '',
        scenario: '',
        precondition: '',
        steps: '',
        expected: '',
        priority: 'P2'
      }
    },

    // 开始编辑
    startEdit() {
      this.isEditing = true

      this.editForm = {
        caseId: this.selectedCase.caseId || '',
        scenario: this.selectedCase.scenario || '',
        // 将<br>转换为换行符以便编辑
        precondition: this.convertBrToNewline(this.selectedCase.precondition || ''),
        steps: this.convertBrToNewline(this.selectedCase.steps || ''),
        expected: this.convertBrToNewline(this.selectedCase.expected || ''),
        // 直接使用原始优先级值，不转换
        priority: this.selectedCase.priority || 'P2'
      }
    },

    // 取消编辑
    cancelEdit() {
      this.isEditing = false
      this.editForm = {
        caseId: '',
        scenario: '',
        precondition: '',
        steps: '',
        expected: '',
        priority: 'P2'
      }
    },

    // 保存编辑
    async saveEdit() {
      // 简单验证
      if (!this.editForm.scenario?.trim()) {
        ElMessage.warning('请输入测试场景')
        return
      }

      this.isSaving = true

      try {
        // 将换行符转换回<br>
        const updatedCase = {
          ...this.selectedCase,
          scenario: this.editForm.scenario,
          precondition: this.convertNewlineToBr(this.editForm.precondition),
          steps: this.convertNewlineToBr(this.editForm.steps),
          expected: this.convertNewlineToBr(this.editForm.expected),
          priority: this.editForm.priority
        }

        // 更新本地数组中的数据
        const index = this.testCases.findIndex(tc => tc === this.selectedCase)
        if (index !== -1) {
          this.testCases[index] = updatedCase
          this.selectedCase = updatedCase
        }

        // 重新生成表格格式的测试用例字符串
        const updatedTestCases = this.generateTestCasesString()

        // 调用后端API保存（使用自定义action接口）
        await api.post(`/requirement-analysis/api/testcase-generation/${this.taskId}/update-test-cases/`, {
          final_test_cases: updatedTestCases
        })

        // 更新内存中的task数据
        this.task.final_test_cases = updatedTestCases

        ElMessage.success('测试用例更新成功')
        this.isEditing = false
      } catch (error) {
        console.error('更新失败:', error)
        ElMessage.error('更新失败: ' + (error.response?.data?.error || error.message))
      } finally {
        this.isSaving = false
      }
    },

    // 将testCases数组重新生成为表格格式的字符串
    generateTestCasesString() {
      if (this.testCases.length === 0) return ''

      // 表头
      const headers = ['测试用例编号', '测试场景', '前置条件', '操作步骤', '预期结果', '优先级']
      let result = headers.join(' | ') + '\n'
      result += '|'.repeat(headers.length) + '\n'

      // 数据行
      this.testCases.forEach((testCase, index) => {
        const row = [
          testCase.caseId || `TC${String(index + 1).padStart(3, '0')}`,
          testCase.scenario || '',
          (testCase.precondition || '').replace(/\n/g, '<br>'),
          (testCase.steps || '').replace(/\n/g, '<br>'),
          (testCase.expected || '').replace(/\n/g, '<br>'),
          testCase.priority || 'P2'
        ]
        result += row.join(' | ') + '\n'
      })

      return result
    },

    // 将HTML的<br>标签转换为换行符
    convertBrToNewline(text) {
      if (!text) return ''
      return text.replace(/<br\s*\/?>/gi, '\n')
    },

    // 将换行符转换为HTML的<br>标签
    convertNewlineToBr(text) {
      if (!text) return ''
      return text.replace(/\n/g, '<br>')
    },

    async adoptSingleCase(testCase, index) {
      try {
        await ElMessageBox.confirm(
          `确定要采纳测试用例"${testCase.scenario}"吗？`,
          '确认采纳',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'success'
          }
        )
      } catch {
        return
      }

      try {
        const caseData = {
          title: testCase.scenario || `测试用例${index + 1}`,
          description: testCase.scenario || '',
          preconditions: testCase.precondition || '',
          steps: testCase.steps || '',
          expected_result: testCase.expected || '',
          priority: this.mapPriority(testCase.priority),
          test_type: 'functional',
          status: 'draft',
          feature_module_ids: this.task.feature_module ? [this.task.feature_module] : [],
          test_point_id: this.task.test_point || null,
        }

        await api.post('/testcases/', caseData)
        ElMessage.success('测试用例采纳成功！')

        // 不再移除已采纳的用例，保留在列表中供多次采纳
        // this.testCases.splice(this.testCases.indexOf(testCase), 1)

      } catch (error) {
        console.error('采纳用例失败:', error)
        ElMessage.error('采纳用例失败: ' + (error.response?.data?.message || error.message))
      }
    },

    async discardSingleCase(testCase, index) {
      try {
        await ElMessageBox.confirm(
          `确定要弃用测试用例"${testCase.scenario}"吗？此操作不可恢复。`,
          '确认弃用',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'warning',
            confirmButtonClass: 'el-button--danger'
          }
        )
      } catch {
        return
      }

      try {
        // 计算全局索引（当前页面起始位置 + 当前索引）
        const globalIndex = (this.currentPage - 1) * this.pageSize + index

        // 调用后端API弃用单个测试用例
        const response = await api.post(`/requirement-analysis/api/testcase-generation/${this.taskId}/discard-single-case/`, {
          case_index: globalIndex
        })

        if (response.data.task_deleted) {
          ElMessage.success('所有测试用例已弃用，任务已删除')
          // 返回到AI生成用例记录列表
          this.$router.push('/generated-testcases')
        } else {
          ElMessage.success('测试用例已弃用')

          // 重新解析更新后的测试用例
          if (response.data.updated_test_cases) {
            this.testCases = this.parseTestCases(response.data.updated_test_cases)

            // 如果当前页没有数据了，回到上一页
            if (this.currentPage > 1 && this.paginatedTestCases.length === 0) {
              this.currentPage--
            }
          }
        }

      } catch (error) {
        console.error('弃用用例失败:', error)
        ElMessage.error('弃用用例失败: ' + (error.response?.data?.error || error.message))
      }
    },

    mapPriority(priority) {
      const priorityMap = {
        '最高': 'critical',
        '高': 'high',
        '中': 'medium',
        '低': 'low',
        'P0': 'critical',
        'P1': 'high',
        'P2': 'medium',
        'P3': 'low'
      }
      return priorityMap[priority] || 'medium'
    },

    // 将英文优先级转换为中文显示
    priorityToChinese(priority) {
      const priorityMap = {
        'critical': '紧急',
        'high': '高',
        'medium': '中',
        'low': '低'
      }
      return priorityMap[priority] || '中'
    },

    // 导出到Excel
    exportToExcel() {
      if (this.testCases.length === 0) {
        ElMessage.warning('没有测试用例可以导出')
        return
      }

      this.isExporting = true

      try {
        // 创建工作簿
        const workbook = XLSX.utils.book_new()

        // 准备数据
        const worksheetData = []
        
        // 添加表头
        worksheetData.push(['测试用例编号', '测试场景', '前置条件', '操作步骤', '预期结果', '优先级'])

        // 添加数据行
        this.testCases.forEach((testCase, index) => {
          worksheetData.push([
            testCase.caseId || `TC${String(index + 1).padStart(3, '0')}`,
            testCase.scenario || '',
            this.formatTextForList(testCase.precondition || ''),
            this.formatTextForList(testCase.steps || ''),
            this.formatTextForList(testCase.expected || ''),
            testCase.priority || '中'
          ])
        })

        // 创建工作表
        const worksheet = XLSX.utils.aoa_to_sheet(worksheetData)

        // 设置列宽
        const colWidths = [
          { wch: 15 }, // 测试用例编号
          { wch: 30 }, // 测试场景
          { wch: 25 }, // 前置条件
          { wch: 50 }, // 操作步骤（增加宽度）
          { wch: 40 }, // 预期结果（增加宽度）
          { wch: 10 }  // 优先级
        ]
        worksheet['!cols'] = colWidths

        // 为所有单元格添加自动换行样式
        const range = XLSX.utils.decode_range(worksheet['!ref'])
        for (let row = range.s.r; row <= range.e.r; row++) {
          for (let col = range.s.c; col <= range.e.c; col++) {
            const cellAddress = XLSX.utils.encode_cell({ r: row, c: col })
            if (!worksheet[cellAddress]) continue
            worksheet[cellAddress].s = {
              alignment: {
                wrapText: true,
                vertical: 'top'
              }
            }
          }
        }

        // 将工作表添加到工作簿
        XLSX.utils.book_append_sheet(workbook, worksheet, '测试用例')

        // 生成文件名
        const fileName = `测试用例_${this.taskId}_${new Date().toISOString().slice(0, 10)}.xlsx`

        // 导出文件
        XLSX.writeFile(workbook, fileName)

        ElMessage.success('测试用例导出成功')
      } catch (error) {
        console.error('导出Excel失败:', error)
        ElMessage.error('导出Excel失败: ' + (error.message || '未知错误'))
      } finally {
        this.isExporting = false
      }
    }
  }
}
</script>

<style scoped>
.task-detail {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

/* 重新评审进度横幅 */
.rerun-progress-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 20px;
  background: linear-gradient(135deg, #e3f2fd, #bbdefb);
  border: 1px solid #64b5f6;
  border-radius: 8px;
  font-size: 14px;
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.progress-spinner {
  width: 18px;
  height: 18px;
  border: 3px solid #bbdefb;
  border-top-color: #1976d2;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.progress-text {
  color: #1565c0;
  font-weight: 500;
  flex: 1;
}

.progress-count {
  color: #1976d2;
  font-size: 12px;
  background: rgba(25, 118, 210, 0.1);
  padding: 2px 10px;
  border-radius: 10px;
}

.progress-refresh-btn {
  padding: 4px 12px;
  background: white;
  color: #1976d2;
  border: 1px solid #90caf9;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.progress-refresh-btn:hover {
  background: #1976d2;
  color: white;
}

/* 需求描述折叠卡片 */
.requirement-description-card {
  margin-bottom: 20px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 500;
}

.title-icon {
  font-size: 18px;
}

.title-text {
  color: #303133;
  font-weight: 600;
}

.title-hint {
  font-size: 13px;
  color: #909399;
  font-weight: normal;
}

/* 评审次数徽章 */
.review-meta-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: #409eff;
  border-radius: 10px;
  line-height: 1.6;
  vertical-align: middle;
}

/* 评审时间标签 */
.review-time-tag {
  margin-left: 6px;
  font-size: 12px;
  color: #67c23a;
  font-weight: normal;
  vertical-align: middle;
}

.requirement-content {
  padding: 16px 0;
}

.requirement-text {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 16px;
  line-height: 1.8;
  color: #606266;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Courier New', Courier, monospace;
  font-size: 14px;
  border-left: 4px solid #409eff;
}

.requirement-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

/* 自定义折叠面板样式 */
.requirement-description-card :deep(.el-collapse) {
  border: none;
}

.requirement-description-card :deep(.el-collapse-item__header) {
  background: #fafafa;
  border-bottom: 1px solid #e4e7ed;
  padding: 16px 20px;
  font-size: 15px;
}

.requirement-description-card :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.requirement-description-card :deep(.el-collapse-item__content) {
  padding: 0 20px 16px;
}

/* AI评审报告折叠卡片 */
.review-feedback-card {
  margin-bottom: 20px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  border-left: 4px solid #e6a23c;
}

.review-feedback-card :deep(.el-collapse) {
  border: none;
}

.review-feedback-card :deep(.el-collapse-item__header) {
  background: #fef9e7;
  border-bottom: 1px solid #f0d78c;
  padding: 16px 20px;
  font-size: 15px;
}

/* 重新评审按钮（标题栏内联） */
.rerun-review-btn-inline {
  margin-left: auto;
  padding: 6px 16px;
  background: linear-gradient(135deg, #e8f0fe, #d2e3fc);
  color: #1a73e8;
  border: 1px solid #a8c7fa;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.rerun-review-btn-inline:hover:not(:disabled) {
  background: linear-gradient(135deg, #d2e3fc, #a8c7fa);
  box-shadow: 0 2px 8px rgba(26, 115, 232, 0.2);
}

.rerun-review-btn-inline:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.rerun-review-btn-inline .spinner {
  width: 12px;
  height: 12px;
  border: 2px solid #a8c7fa;
  border-top-color: #1a73e8;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.review-feedback-card :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.review-feedback-card :deep(.el-collapse-item__content) {
  padding: 0 20px 16px;
}

.review-content {
  padding: 16px 0;
}

.review-text {
  background: #fef9e7;
  border-radius: 6px;
  padding: 16px;
  line-height: 1.8;
  color: #5d4e37;
  max-height: 600px;
  overflow-y: auto;
  font-size: 14px;
}

.review-text :deep(.review-h2) {
  font-size: 18px;
  color: #b88230;
  margin: 16px 0 8px;
  padding-bottom: 6px;
  border-bottom: 2px solid #f0d78c;
}

.review-text :deep(.review-h3) {
  font-size: 16px;
  color: #c79137;
  margin: 12px 0 6px;
}

.review-text :deep(.review-h4) {
  font-size: 14px;
  color: #d4a44c;
  margin: 10px 0 4px;
}

.review-text :deep(.review-code) {
  background: #fdf0d5;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: #8b6914;
}

.review-text :deep(.review-blockquote) {
  border-left: 3px solid #e6a23c;
  padding: 8px 12px;
  margin: 8px 0;
  background: #fdf3e0;
  color: #7a5d28;
  font-style: italic;
}

.review-text :deep(.review-ul) {
  padding-left: 20px;
  margin: 8px 0;
}

.review-text :deep(.review-ul li) {
  margin-bottom: 4px;
}

.review-text :deep(.review-hr) {
  border: none;
  border-top: 1px dashed #e6d5a8;
  margin: 16px 0;
}

.review-text :deep(strong) {
  color: #b88230;
  font-weight: 600;
}

/* 人工逐项确认回复区 */
.human-feedback-section {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 2px dashed #e6d5a8;
}

.human-feedback-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.human-feedback-header .section-icon {
  font-size: 18px;
}

.human-feedback-header .section-title {
  font-size: 15px;
  font-weight: 600;
  color: #8b6914;
}

.human-feedback-header .section-hint {
  font-size: 12px;
  color: #b7a06e;
}

/* AI自动检测徽章 */
.auto-detect-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: linear-gradient(135deg, #e8f5e9, #c8e6c9);
  color: #2e7d32;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 20px;
  border: 1px solid #a5d6a7;
  animation: pulse-badge 2s ease-in-out infinite;
}

@keyframes pulse-badge {
  0%, 100% { box-shadow: 0 0 0 0 rgba(46, 125, 50, 0.3); }
  50% { box-shadow: 0 0 0 6px rgba(46, 125, 50, 0); }
}

/* 自动检测的空状态 */
.feedback-auto-empty {
  background: #e8f5e9;
  border-radius: 8px;
  color: #2e7d32;
  font-weight: 500;
}

/* 自动检测的确认项卡片 */
.feedback-item-header .auto-icon {
  font-size: 16px;
}

/* 手动添加按钮行 */

/* 确认项卡片 */
.feedback-item-card {
  background: #fffef5;
  border: 1px solid #e6d5a8;
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
  transition: border-color 0.2s;
}

.feedback-item-card:hover {
  border-color: #c79137;
}

/* 已回复卡片样式 */
.feedback-item-replied {
  background: #f6fff6;
  border-color: #b7ddb7;
  opacity: 0.85;
}

.feedback-item-replied:hover {
  border-color: #67c23a;
  opacity: 1;
}

.replied-num {
  color: #4a8a4a !important;
}

/* 已回复项只读文本 */
.feedback-replied-text {
  font-size: 13px;
  color: #606266;
  padding: 6px 0;
  line-height: 1.5;
}

/* 已确认折叠 */
.replied-collapse {
  margin-top: 8px;
  margin-bottom: 8px;
  border: 1px solid #c8e6c8;
  border-radius: 8px;
  overflow: hidden;
}

.replied-collapse :deep(.el-collapse-item__header) {
  background: #f0faf0;
  color: #4a8a4a;
  font-size: 13px;
  padding: 0 14px;
  height: 38px;
}

.replied-collapse :deep(.el-collapse-item__content) {
  padding: 12px;
  background: #f6fff6;
}



.feedback-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #fdf3e0;
  border-bottom: 1px solid #e6d5a8;
}

.feedback-item-num {
  font-size: 13px;
  font-weight: 600;
  color: #8b6914;
}

.feedback-item-delete {
  font-size: 12px;
  color: #c0392b;
}

.feedback-item-body {
  padding: 12px 14px;
}

.feedback-field {
  margin-bottom: 10px;
}

.feedback-field:last-child {
  margin-bottom: 0;
}

.feedback-field-label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: #7a5d28;
  margin-bottom: 4px;
}

.feedback-field :deep(.el-input__wrapper),
.feedback-field :deep(.el-textarea__inner) {
  background: #fffef8;
  border-color: #e6d5a8;
  font-size: 13px;
}

.feedback-field :deep(.el-input__wrapper):hover,
.feedback-field :deep(.el-textarea__inner):hover {
  border-color: #d4a44c;
}

.feedback-field :deep(.el-input.is-focus .el-input__wrapper),
.feedback-field :deep(.el-textarea__inner:focus) {
  border-color: #c79137;
  box-shadow: 0 0 0 1px rgba(199, 145, 55, 0.2);
}

.feedback-field :deep(.el-input__inner::placeholder),
.feedback-field :deep(.el-textarea__inner::placeholder) {
  color: #c4b896;
  font-size: 12px;
}

/* 添加按钮行 */
.feedback-add-row {
  text-align: center;
  padding: 8px 0 4px;
}

/* 操作按钮 */
.human-feedback-actions {
  margin-top: 6px;
  display: flex;
  justify-content: flex-end;
}

/* ========== 知识库审计卡片 ========== */
.kb-audit-card {
  margin-bottom: 20px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.kb-audit-card :deep(.el-collapse) {
  border: none;
}

.kb-audit-card :deep(.el-collapse-item__header) {
  background: #e8f0fe;
  border-bottom: 1px solid #a4c2f4;
  padding: 16px 20px;
  font-size: 15px;
}

.kb-audit-card :deep(.el-collapse-item__header:hover) {
  background: #d2e3fc;
}

.kb-audit-card :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.kb-audit-card :deep(.el-collapse-item__content) {
  padding: 0 20px 16px;
}

.kb-audit-content {
  padding: 16px 0;
}

.kb-audit-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px;
  color: #5f6368;
  font-size: 14px;
  background: #f8fafd;
  border-radius: 8px;
}

.kb-audit-loading .loading-spinner {
  width: 20px;
  height: 20px;
  border: 3px solid #e8eaed;
  border-top-color: #4285f4;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.kb-audit-result {
  /* audit result text follows review-content styles */
}

.kb-audit-text {
  font-size: 14px;
  line-height: 1.7;
  color: #333;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.kb-audit-text :deep(h2) {
  font-size: 16px;
  color: #2c3e50;
  margin: 16px 0 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #eee;
}

.kb-audit-text :deep(h3) {
  font-size: 14px;
  color: #34495e;
  margin: 12px 0 6px;
}

.kb-audit-text :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 13px;
}

.kb-audit-text :deep(th),
.kb-audit-text :deep(td) {
  border: 1px solid #ddd;
  padding: 8px 10px;
  text-align: left;
}

.kb-audit-text :deep(th) {
  background: #e8f0fe;
  font-weight: 600;
}

.kb-audit-text :deep(tr:hover td) {
  background: #f8fafd;
}

.kb-audit-text :deep(strong) {
  color: #2c3e50;
}

.kb-audit-text :deep(code) {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: monospace;
  font-size: 12px;
}

.kb-audit-actions {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #eee;
  display: flex;
  justify-content: flex-end;
}

.kb-audit-empty {
  padding: 20px;
  text-align: center;
  color: #999;
  font-size: 14px;
}

.page-header {
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.header-left {
  flex: 1;
}

.page-header h2 {
  color: #2c3e50;
  margin: 0 0 10px 0;
}

.task-info {
  display: flex;
  gap: 20px;
  align-items: center;
}

.task-id {
  color: #666;
  font-family: monospace;
}

.task-status {
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 0.9rem;
  font-weight: bold;
}

.task-status.completed {
  background: #e8f5e8;
  color: #388e3c;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.export-btn {
  background: #27ae60;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: background 0.3s ease;
  white-space: nowrap;
}

.export-btn:hover:not(:disabled) {
  background: #229954;
}

.export-btn:disabled {
  background: #bdc3c7;
  cursor: not-allowed;
}
 
.rerun-review-btn {
  background: linear-gradient(135deg, #e8f0fe, #d2e3fc);
  color: #1a73e8;
  border: 1px solid #a8c8fa;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 500;
  transition: all 0.3s ease;
  white-space: nowrap;
  box-shadow: 0 2px 6px rgba(26, 115, 232, 0.15);
}

.rerun-review-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #d2e3fc, #b8d4f8);
  border-color: #7baaf7;
  color: #1557b0;
}

.rerun-review-btn:disabled {
  background: linear-gradient(135deg, #f5f5f5, #e0e0e0);
  color: #999;
  border-color: #d0d0d0;
  cursor: not-allowed;
  box-shadow: none;
}

.regenerate-btn {
  background: linear-gradient(135deg, #e6a23c, #f0c75e);
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 500;
  transition: all 0.3s ease;
  white-space: nowrap;
  box-shadow: 0 2px 6px rgba(230, 162, 60, 0.3);
}

.regenerate-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #d4922a, #e6b84d);
  box-shadow: 0 4px 12px rgba(230, 162, 60, 0.4);
  transform: translateY(-1px);
}

.regenerate-btn:disabled {
  background: linear-gradient(135deg, #d4c5a0, #e0d5b0);
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}

/* 基于调整重新生成 - 参数信息展示 */
.regen-info-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 14px 16px;
}
.regen-info-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.regen-info-label {
  font-size: 0.82rem;
  color: #909399;
  min-width: 64px;
  flex-shrink: 0;
  padding-top: 1px;
}
.regen-info-value {
  font-size: 0.9rem;
  color: #303133;
  font-weight: 500;
}
.regen-info-value.not-set {
  color: #e6a23c;
  font-weight: 400;
}
.regen-warning-box {
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 8px;
  padding: 14px 16px;
  font-size: 0.87rem;
  color: #606266;
  line-height: 1.6;
}

/* 从头重新生成按钮 */
.new-generate-btn {
  background: linear-gradient(135deg, #409eff, #66b1ff);
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 500;
  transition: all 0.3s ease;
  white-space: nowrap;
  box-shadow: 0 2px 6px rgba(64, 158, 255, 0.3);
}
.new-generate-btn:hover {
  background: linear-gradient(135deg, #337ecc, #529ee5);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.4);
  transform: translateY(-1px);
}

/* 从头重新生成弹窗 */
.regenerate-new-modal {
  background: white;
  border-radius: 12px;
  padding: 0;
  width: 640px;
  max-width: 95vw;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
}
.regenerate-new-body {
  padding: 20px 24px;
  overflow-y: auto;
  flex: 1;
}
.regenerate-new-body .form-group {
  margin-bottom: 18px;
}
.regenerate-new-body .form-group label {
  display: block;
  font-weight: 600;
  font-size: 0.9rem;
  margin-bottom: 6px;
  color: #303133;
}
.regenerate-new-body .field-hint {
  font-weight: 400;
  font-size: 0.8rem;
  color: #909399;
  margin-left: 6px;
}
.regenerate-new-body .field-tip {
  font-size: 0.78rem;
  color: #c0c4cc;
  margin-top: 4px;
  display: block;
}
.regenerate-new-body .form-select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  font-size: 0.9rem;
  color: #303133;
  background: white;
}
.regenerate-new-body .requirement-textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  font-size: 0.88rem;
  color: #303133;
  resize: vertical;
  font-family: inherit;
  box-sizing: border-box;
}
/* 生成模式卡片 */
.mode-cards {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.mode-card {
  flex: 1;
  min-width: 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 8px;
  border: 2px solid #dcdfe6;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
}
.mode-card:hover {
  border-color: #409eff;
  background: #ecf5ff;
}
.mode-card.active {
  border-color: #409eff;
  background: #ecf5ff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.25);
}
.mode-icon { font-size: 1.3rem; margin-bottom: 3px; }
.mode-label { font-weight: 600; font-size: 0.88rem; color: #303133; }
.mode-desc { font-size: 0.75rem; color: #909399; margin-top: 2px; }

.batch-actions {
  background: white;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.selection-info {
  display: flex;
  align-items: center;
  gap: 15px;
}

.select-all {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.selected-count {
  color: #3498db;
  font-weight: bold;
}

.batch-buttons {
  display: flex;
  gap: 10px;
}

.batch-adopt-btn, .batch-discard-btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.2s ease;
}

.batch-adopt-btn {
  background: #27ae60;
  color: white;
}

.batch-adopt-btn:hover:not(:disabled) {
  background: #229954;
}

.batch-discard-btn {
  background: #e74c3c;
  color: white;
}

.batch-discard-btn:hover:not(:disabled) {
  background: #c0392b;
}

.batch-adopt-btn:disabled, .batch-discard-btn:disabled {
  background: #bdc3c7;
  cursor: not-allowed;
}

.testcases-table {
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.table-header {
  display: grid;
  grid-template-columns: 60px 120px 1fr 1fr 1fr 1fr 80px 150px;
  background: #f8f9fa;
  font-weight: bold;
  color: #2c3e50;
}

.table-body .table-row {
  display: grid;
  grid-template-columns: 60px 120px 1fr 1fr 1fr 1fr 80px 150px;
  border-bottom: 1px solid #eee;
  transition: background 0.2s ease;
}

.table-row:hover {
  background: #f8f9fa;
}

.header-cell, .body-cell {
  padding: 12px 8px;
  display: flex;
  align-items: flex-start; /* 改为顶部对齐，避免内容被裁剪 */
  border-right: 1px solid #eee;
  word-break: break-word;
}

/* 操作步骤和预期结果列的特殊样式 */
.body-cell.text-limit-2 {
  align-items: flex-start;
  overflow: hidden;
}

.checkbox-cell {
  justify-content: center;
}

.header-cell:last-child, .body-cell:last-child {
  border-right: none;
}

.priority-tag {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: bold;
}

.text-limit-2 {
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  white-space: pre-wrap;
  line-height: 1.6;
  max-height: 3.6em; /* 2行 × 1.6行高 + 0.4em余量 */
  min-height: 3.2em; /* 确保有足够空间显示2行 */
  word-break: break-word;
}

.priority-tag.low {
  background: #e8f5e8;
  color: #388e3c;
}

.priority-tag.p3 {
  background: #e8f5e8;
  color: #388e3c;
}

.priority-tag.medium {
  background: #e3f2fd;
  color: #1976d2;
}

.priority-tag.p2 {
  background: #e3f2fd;
  color: #1976d2;
}

.priority-tag.high {
  background: #fff3e0;
  color: #f57c00;
}

.priority-tag.p1 {
  background: #fff3e0;
  color: #f57c00;
}

.priority-tag.critical {
  background: #ffebee;
  color: #d32f2f;
}

.priority-tag.p0 {
  background: #ffebee;
  color: #d32f2f;
}

.action-buttons {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.view-btn, .adopt-btn, .discard-btn {
  padding: 4px 8px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: all 0.2s ease;
}

.view-btn {
  background: #3498db;
  color: white;
}

.view-btn:hover {
  background: #2980b9;
}

.adopt-btn {
  background: #27ae60;
  color: white;
}

.adopt-btn:hover {
  background: #229954;
}

.discard-btn {
  background: #e74c3c;
  color: white;
}

.discard-btn:hover {
  background: #c0392b;
}

.pagination-section {
  margin-top: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 20px;
}

.page-size-selector {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pagination-buttons {
  display: flex;
  align-items: center;
  gap: 15px;
}

.pagination-buttons button {
  padding: 6px 12px;
  border: 1px solid #ddd;
  background: white;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.pagination-buttons button:hover:not(:disabled) {
  background: #f0f0f0;
}

.pagination-buttons button:disabled {
  color: #ccc;
  cursor: not-allowed;
}

.case-detail-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 12px;
  max-width: 800px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 30px;
  border-bottom: 1px solid #eee;
}

.modal-header h3 {
  margin: 0;
  color: #2c3e50;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}

.modal-body {
  padding: 30px;
}

.detail-item {
  margin-bottom: 20px;
}

.detail-item label {
  font-weight: bold;
  color: #2c3e50;
  display: block;
  margin-bottom: 8px;
}

.detail-item span, .detail-item p {
  color: #666;
  line-height: 1.6;
}

.test-steps {
  white-space: pre-line;
  background: #f8f9fa;
  padding: 15px;
  border-radius: 6px;
  border-left: 4px solid #3498db;
}

.loading-state, .error-state, .empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #666;
}

.error-state h3, .empty-state h3 {
  color: #2c3e50;
  margin-bottom: 10px;
}

.error-state a {
  color: #3498db;
  text-decoration: none;
}

.error-state a:hover {
  text-decoration: underline;
}

/* 编辑模式样式 */
.edit-mode {
  .form-item {
    margin-bottom: 20px;
  }

  .form-item label {
    font-weight: bold;
    color: #2c3e50;
    display: block;
    margin-bottom: 8px;
  }

  .readonly-field {
    color: #666;
    padding: 8px 12px;
    background: #f5f5f5;
    border-radius: 4px;
    display: inline-block;
  }
}

/* 底部操作栏 */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 30px;
  border-top: 1px solid #eee;
  background: #f9f9f9;
  border-radius: 0 0 12px 12px;
}

.action-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.edit-btn {
  background: #409eff;
  color: white;
}

.edit-btn:hover {
  background: #66b1ff;
}

.save-btn {
  background: #67c23a;
  color: white;
}

.save-btn:hover:not(:disabled) {
  background: #85ce61;
}

.save-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.cancel-btn {
  background: #909399;
  color: white;
}

.cancel-btn:hover:not(:disabled) {
  background: #a6a9ad;
}

.close-btn-footer {
  background: #e4e7ed;
  color: #606266;
}

.close-btn-footer:hover {
  background: #ecf5ff;
}
</style>

<style>
/* 全局样式：确保弹窗在 TaskDetail 独立访问时也能正常显示 */
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

.quick-version-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 24px;
  border-bottom: 1px solid #e4e7ed;
  background: #fafbfc;
  border-radius: 12px 12px 0 0;
}
.quick-version-header h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: #303133;
}

.preview-close {
  background: none;
  border: none;
  font-size: 1.2rem;
  color: #909399;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}
.preview-close:hover {
  background: #f0f0f0;
  color: #303133;
}

.quick-version-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #e4e7ed;
  background: #fafbfc;
  border-radius: 0 0 12px 12px;
}
</style>