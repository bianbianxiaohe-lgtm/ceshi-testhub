<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">禅道覆盖分析</h1>
      <div class="header-actions">
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新建配置
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">禅道配置</div>
          </template>
          <el-form label-width="90px" label-position="top">
            <el-form-item label="选择配置">
              <el-select
                v-model="currentConfigId"
                filterable
                clearable
                placeholder="选择已保存的配置（自动读取账号密码）"
                style="width: 100%"
                @change="handleSelectConfig"
              >
                <el-option
                  v-for="c in configs"
                  :key="c.id"
                  :label="`${c.name}（${versionName(c.version) || c.base_url}）${c.product_id ? '' : ' - 未配置产品'}`"
                  :value="c.id"
                />
              </el-select>
            </el-form-item>
            <el-alert
              v-if="form.id && !form.product_id"
              type="warning"
              :closable="false"
              style="margin-bottom: 12px"
              title="该配置未填写禅道产品/版本，无法同步。请点“保存并自动匹配”重新配置。"
            />
            <el-divider style="margin: 4px 0 12px" />
            <el-form-item label="关联项目">
              <el-select
                v-model="form.project"
                filterable
                clearable
                placeholder="选择项目（用于筛选版本）"
                style="width: 100%"
                @change="handleProjectChange"
              >
                <el-option
                  v-for="p in projects"
                  :key="p.id"
                  :label="p.name"
                  :value="p.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="关联版本">
              <el-select
                v-model="form.version"
                filterable
                :disabled="!form.project"
                placeholder="选择 TestHub 版本"
                style="width: 100%"
              >
                <el-option
                  v-for="v in filteredVersions"
                  :key="v.id"
                  :label="v.name"
                  :value="v.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="配置名称">
              <el-input v-model="form.name" placeholder="如：轻练-禅道同步" />
            </el-form-item>
            <el-form-item label="禅道地址">
              <el-input v-model="form.base_url" placeholder="http://192.168.1.81:8051" />
            </el-form-item>
            <el-form-item label="账号">
              <el-input v-model="form.account" placeholder="禅道账号" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password placeholder="不修改请留空" />
            </el-form-item>
            <el-alert
              type="info"
              :closable="false"
              style="margin-bottom: 12px"
              title="只需填地址+账号密码。保存并自动匹配后，会按「本项目 ↔ 禅道项目」映射自动定位禅道产品，再拉该产品的版本(Build)列表，选版本即可精确同步该版本 Bug。"
            />
            <el-form-item v-if="form.project" label="项目匹配">
              <div class="mapping-row">
                <span v-if="currentMapping" class="mapping-text">
                  {{ projectName(form.project) }} → 禅道「{{ currentMapping.zentao_product_name }}」
                </span>
                <span v-else class="mapping-text text-muted">未设置映射（将按项目名自动匹配禅道产品）</span>
              </div>
            </el-form-item>
            <el-form-item label="禅道产品">
              <el-select
                v-model="form.product_id"
                filterable
                clearable
                placeholder="保存并自动匹配后自动带出，也可手动选"
                style="width: 100%"
                @visible-change="(v) => v && !form.product_id && loadProjectsApi()"
                @change="handleProductChange"
              >
                <el-option
                  v-for="(name, id) in productOptions"
                  :key="id"
                  :label="`${id} - ${name}`"
                  :value="String(id)"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="版本（Build）">
              <el-select
                v-model="form.build_id"
                filterable
                clearable
                :disabled="!form.product_id || buildLoading"
                :loading="buildLoading"
                :placeholder="buildPlaceholder"
                style="width: 100%"
                @visible-change="(v) => v && !buildLoading && loadBuildsByProduct()"
                @change="handleBuildChange"
              >
                <el-option
                  v-for="b in buildOptions"
                  :key="b.id"
                  :label="`${b.id} - ${b.name}`"
                  :value="String(b.id)"
                />
              </el-select>
              <div style="font-size: 12px; color: #909399; margin-top: 4px;">
                {{ buildStatusText }}
              </div>
            </el-form-item>
            <el-form-item label="覆盖率目标(%)">
              <el-input-number v-model="form.coverage_target" :min="0" :max="100" :step="5" style="width: 100%" />
            </el-form-item>
            <el-button type="primary" :loading="saving" style="width: 100%" @click="saveAndAutoMatch">
              保存并自动匹配
            </el-button>
            <el-button :loading="saving" style="width: 100%; margin-top: 8px" @click="saveConfig">
              仅保存
            </el-button>
            <div class="form-tip">
              产品/执行/版本关键字由系统根据所选版本自动匹配，一般无需手动填写；
              同地址同账号新建配置时密码留空会自动沿用。
            </div>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              配置列表
              <div class="header-actions" style="margin-left: auto">
                <el-button size="small" @click="loadConfigs">刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="configs" v-loading="loadingConfigs" size="small">
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column label="项目" min-width="100">
              <template #default="{ row }">
                {{ projectName(row.project) }}
              </template>
            </el-table-column>
            <el-table-column label="版本" min-width="130">
              <template #default="{ row }">
                {{ versionName(row.version) }}
              </template>
            </el-table-column>
            <el-table-column prop="base_url" label="地址" min-width="150" show-overflow-tooltip />
            <el-table-column label="禅道映射" min-width="140">
              <template #default="{ row }">
                产品 {{ row.product_id || '-' }} / 版本 {{ row.build_id || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="Bug数" width="90">
              <template #default="{ row }">
                <span v-if="syncingId === row.id" style="color: #e6a23c">同步中…</span>
                <span v-else-if="row.bug_count > 0" style="color: #67c23a; font-weight: 600">
                  {{ row.bug_count }}
                </span>
                <span v-else style="color: #909399">-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="editConfig(row)">编辑</el-button>
                <el-button size="small" type="primary" plain @click="testConnection(row)">测试连接</el-button>
                <el-button size="small" type="warning" :loading="syncingId === row.id" @click="syncBugs(row)">同步Bug</el-button>
                <el-tooltip
                  :disabled="row.bug_count > 0 && syncingId !== row.id"
                  content="请先同步Bug，同步成功后才能分析"
                >
                  <span>
                    <el-button
                      size="small"
                      type="danger"
                      :disabled="!row.bug_count || syncingId === row.id"
                      :loading="coverageId === row.id"
                      @click="runCoverage(row)"
                    >覆盖率</el-button>
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header>
            <div class="card-header">
              覆盖率报告
              <div class="header-actions" style="margin-left: auto">
                <el-select
                  v-model="reportConfigFilter"
                  clearable
                  placeholder="按配置筛选"
                  size="small"
                  style="width: 160px"
                  @change="loadReports"
                >
                  <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id" />
                </el-select>
              </div>
            </div>
          </template>
          <el-table :data="reports" v-loading="loadingReports" size="small" @row-click="openReport">
            <el-table-column label="项目 / 版本" min-width="150">
              <template #default="{ row }">
                <div>{{ row.project_name || '-' }}</div>
                <div class="bug-meta">{{ row.version_name || '-' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="分析时间" min-width="140">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="reportStatusType(row.status)" size="small">{{ reportStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total_bugs" label="Bug数" width="70" />
            <el-table-column prop="covered_bugs" label="覆盖" width="70" />
            <el-table-column prop="uncovered_bugs" label="未覆盖" width="80" />
            <el-table-column label="覆盖率" width="110">
              <template #default="{ row }">
                <span :style="{ color: row.coverage_rate >= 90 ? '#67c23a' : '#e6a23c', fontWeight: 600 }">
                  {{ row.coverage_rate }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="matched_by" label="匹配方式" min-width="110" />
            <el-table-column prop="case_count" label="用例数" width="70" />
            <el-table-column v-if="reports.some(r => r.error_message)" prop="error_message" label="错误" min-width="120" show-overflow-tooltip />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" plain @click.stop="openReport(row)">查看</el-button>
                <el-button size="small" type="info" plain @click.stop="openLogViewer(row.id)">日志</el-button>
                <el-button size="small" type="danger" plain @click.stop="deleteReport(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-drawer v-model="reportDrawer" title="覆盖率报告明细" size="68%">
      <div v-if="currentReport">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="状态">{{ reportStatusText(currentReport.status) }}</el-descriptions-item>
          <el-descriptions-item label="Bug总数">{{ currentReport.total_bugs }}</el-descriptions-item>
          <el-descriptions-item label="覆盖率">
            <b :style="{ color: currentReport.coverage_rate >= 90 ? '#67c23a' : '#e6a23c' }">{{ currentReport.coverage_rate }}%</b>
          </el-descriptions-item>
          <el-descriptions-item label="已覆盖">{{ currentReport.covered_bugs }}</el-descriptions-item>
          <el-descriptions-item label="未覆盖">{{ currentReport.uncovered_bugs }}</el-descriptions-item>
          <el-descriptions-item label="匹配方式">{{ currentReport.matched_by }}</el-descriptions-item>
          <el-descriptions-item label="参与用例数">{{ currentReport.case_count }}</el-descriptions-item>
          <el-descriptions-item label="使用模型">
            判定 {{ currentReport.detail?.llm_model || '-' }} / 向量 {{ currentReport.detail?.embedder_model || '-' }}
            <template v-if="currentReport.detail?.reranker_model"> / 精排 {{ currentReport.detail.reranker_model }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="采纳率">
            {{ currentReport.detail?.adoption_rate != null ? currentReport.detail.adoption_rate + '%' : '数据不足' }}
          </el-descriptions-item>
          <el-descriptions-item label="需求使用率">
            {{ currentReport.detail?.requirement_usage_rate != null ? currentReport.detail.requirement_usage_rate + '%' : '数据不足' }}
          </el-descriptions-item>
          <el-descriptions-item label="目标达标">
            <el-tag
              :type="(currentReport.detail?.coverage_target ?? 90) > 0 && currentReport.coverage_rate >= (currentReport.detail?.coverage_target ?? 90) ? 'success' : 'danger'"
              size="small"
            >
              目标 {{ currentReport.detail?.coverage_target ?? 90 }}%：{{ currentReport.coverage_rate >= (currentReport.detail?.coverage_target ?? 90) ? '达标' : '未达标' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="AI用例占比">
            {{ currentReport.detail?.true_coverage_rate ?? 0 }}%
          </el-descriptions-item>
          <el-descriptions-item label="用例来源">
            AI {{ currentReport.detail?.ai_case_count ?? 0 }} / 人工 {{ currentReport.detail?.manual_case_count ?? 0 }} / 未标记 {{ currentReport.detail?.unknown_case_count ?? 0 }}
          </el-descriptions-item>
          <el-descriptions-item v-if="(currentReport.detail?.fake_covered_count ?? 0) > 0" label="剔除假覆盖">
            {{ currentReport.detail.fake_covered_count }} 条
          </el-descriptions-item>
          <el-descriptions-item v-if="(currentReport.detail?.ui_optimization_bug_count ?? 0) > 0" label="界面优化Bug（未计入覆盖率）">
            {{ currentReport.detail.ui_optimization_bug_count }} 条
          </el-descriptions-item>
          <el-descriptions-item v-if="(currentReport.detail?.low_confidence_count ?? 0) > 0" label="低置信判定">
            {{ currentReport.detail.low_confidence_count }} 条建议人工确认
          </el-descriptions-item>
          <el-descriptions-item label="分析时间">{{ formatTime(currentReport.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="操作者">{{ currentReport.created_by_name || '-' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 有效真实 Bug 反推 + 低覆盖诊断 -->
        <div v-if="currentReport.status === 'success' && hasValidBugStats" style="margin-top: 16px">
          <el-card shadow="never" class="diag-card">
            <template #header>
              <div class="card-header">
                <span>有效真实 Bug 反推</span>
                <el-tag
                  :type="effectiveCoverage >= (currentReport.detail?.coverage_target ?? 90) ? 'success' : 'danger'"
                  size="small"
                >
                  有效覆盖 {{ effectiveCoverage }}% / 目标 {{ currentReport.detail?.coverage_target ?? 90 }}%
                </el-tag>
              </div>
            </template>
            <el-row :gutter="12">
              <el-col :span="6">
                <div class="stat-box">
                  <div class="stat-num">{{ currentReport.detail?.valid_bug_total ?? 0 }}</div>
                  <div class="stat-label">有效真实 Bug 池</div>
                  <div class="stat-sub">已解决/已关闭且 resolution=fixed</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="stat-box ok">
                  <div class="stat-num">{{ currentReport.detail?.effective_discovered_bugs ?? 0 }}</div>
                  <div class="stat-label">AI 用例已发现</div>
                  <div class="stat-sub">可创造的有效真实 Bug 数</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="stat-box warn">
                  <div class="stat-num">{{ currentReport.detail?.missed_valid ?? 0 }}</div>
                  <div class="stat-label">本应发现却遗漏</div>
                  <div class="stat-sub">有效 Bug 中未被覆盖</div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="stat-box">
                  <div class="stat-num" :style="{ color: effectiveCoverage >= (currentReport.detail?.coverage_target ?? 90) ? '#67c23a' : '#e6a23c' }">
                    {{ effectiveCoverage }}%
                  </div>
                  <div class="stat-label">有效真实覆盖率</div>
                  <div class="stat-sub">分母已剔除未闭环/不予解决</div>
                </div>
              </el-col>
            </el-row>
            <div class="diag-tip">
              说明：分母仅统计禅道上「开发真正修复并闭环」的 Bug（status=resolved/closed 且 resolution=fixed），
              排除了未解决、不予解决(willnotfix)、设计如此(bydesign)、重复(duplicate)、外部(external)、
              无法重现(notrepro)、转需求(tostory) 等无效项，使覆盖率更贴近 AI 用例对真实缺陷的发现能力。
            </div>
          </el-card>

          <el-card
            v-if="currentReport.detail?.coverage_diagnosis"
            shadow="never"
            class="diag-card"
            style="margin-top: 12px"
          >
            <template #header>
              <div class="card-header">
                <span>低覆盖诊断</span>
                <el-tag
                  :type="diagnosisLevelType"
                  size="small"
                >{{ diagnosisLevelText }}</el-tag>
              </div>
            </template>
            <el-alert
              :type="diagnosisLevelType"
              :closable="false"
              :title="currentReport.detail.coverage_diagnosis.conclusion"
              style="margin-bottom: 12px"
            />
            <template v-if="diagnosisHasBreakdown">
              <div class="diag-breakdown-title">未覆盖有效 Bug 归因分布</div>
              <el-progress
                v-if="causeBreakdown.ai_misunderstanding > 0"
                :percentage="causePercent(causeBreakdown.ai_misunderstanding)"
                :stroke-width="14"
                color="#f56c6c"
                :format="() => `思路方向问题 ${causeBreakdown.ai_misunderstanding}`"
                style="margin-bottom: 8px"
              />
              <el-progress
                v-if="causeBreakdown.case_design_gap > 0"
                :percentage="causePercent(causeBreakdown.case_design_gap)"
                :stroke-width="14"
                color="#e6a23c"
                :format="() => `场景遗漏 ${causeBreakdown.case_design_gap}`"
                style="margin-bottom: 8px"
              />
              <el-progress
                v-if="causeBreakdown.unknown > 0"
                :percentage="causePercent(causeBreakdown.unknown)"
                :stroke-width="14"
                color="#c0c4cc"
                :format="() => `未归因 ${causeBreakdown.unknown}`"
                style="margin-bottom: 8px"
              />
              <div
                v-if="currentReport.detail.coverage_diagnosis.top_missing_scenes?.length"
                class="diag-scenes"
              >
                <div class="diag-breakdown-title">高频缺失场景 Top</div>
                <div
                  v-for="(s, i) in currentReport.detail.coverage_diagnosis.top_missing_scenes"
                  :key="i"
                  class="scene-item"
                >
                  <el-tag size="small" type="info">{{ s.scene_type }}</el-tag>
                  <span class="scene-count">{{ s.count }} 例</span>
                  <span v-if="s.examples?.length" class="scene-examples">{{ s.examples.join('；') }}</span>
                </div>
              </div>
            </template>
          </el-card>
        </div>

        <el-alert
          v-if="currentReport.error_message"
          type="error"
          :title="currentReport.error_message"
          style="margin-top: 12px"
          :closable="false"
        />

        <h4 style="margin: 18px 0 10px">逐条判定</h4>
        <div class="form-tip" style="margin-bottom: 8px">
          最终匹配由 LLM 在 Top 5 候选中按语义判定，匹配用例不一定是相似度最高那条；「匹配相似度」为被选中用例自身的分数。
        </div>
        <el-table :data="currentReport.items" size="small" border>
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag :type="row.covered ? 'success' : 'danger'" size="small">
                {{ row.covered ? '已覆盖' : '未覆盖' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="禅道Bug" min-width="220">
            <template #default="{ row }">
              <div class="bug-title">#{{ row.bug.zentao_id }} {{ row.bug.title }}</div>
              <div class="bug-meta">严重度 {{ row.bug.severity }}｜{{ row.bug.status }}｜{{ row.bug.opened_build }}</div>
            </template>
          </el-table-column>
          <el-table-column label="匹配用例" min-width="180">
            <template #default="{ row }">
              <span v-if="row.matched_case_title">{{ row.matched_case_title }}</span>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="匹配相似度" width="100">
            <template #default="{ row }">
              {{ row.matched_score != null ? row.matched_score.toFixed(3) : (row.match_score != null ? row.match_score.toFixed(3) : '-') }}
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="130">
            <template #default="{ row }">
              <template v-if="row.judge_confidence != null">
                {{ row.judge_confidence.toFixed(2) }}
                <el-tag v-if="row.judge_confidence < 0.7" type="warning" size="small" style="margin-left: 4px">建议人工确认</el-tag>
              </template>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="判定理由" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">{{ row.reason || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click="openReview(row)">复核</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin: 14px 0 4px; display: flex; gap: 8px">
          <el-button size="small" type="info" plain @click.stop="openLogViewer(currentReport)">查看分析日志</el-button>
        </div>

        <div class="suggest-header">
          <h4 style="margin: 18px 0 10px">提高覆盖率建议</h4>
          <div class="suggest-actions">
            <el-tag v-if="suggestionsDirty" type="warning" size="small" effect="plain">已修改未保存</el-tag>
            <el-tag v-else-if="currentReport.suggestions_edited_by" type="info" size="small" effect="plain">
              人工编辑：{{ currentReport.suggestions_edited_by }} · {{ formatTime(currentReport.suggestions_edited_at) }}
            </el-tag>
            <template v-if="suggestionsEditable">
              <el-button v-if="suggestionsDirty" size="small" @click="resetSuggestionsEdit">撤销修改</el-button>
              <el-button size="small" :loading="savingSuggestions" @click="saveSuggestions">保存修改</el-button>
            </template>
            <el-button
              v-if="suggestionsEditable && currentReport.improvement_suggestions_ai"
              size="small"
              text
              @click="restoreAiSuggestions"
            >恢复 AI 原文</el-button>
            <el-button
              v-if="currentReport.status === 'success' && currentReport.uncovered_bugs > 0"
              type="primary"
              plain
              size="small"
              :loading="pushingKnowledge"
              @click="pushKnowledge"
            >{{ suggestionsDirty ? '保存并写入知识库' : '将未覆盖缺陷+调优建议写入知识库' }}</el-button>
          </div>
        </div>
        <template v-if="suggestionsEditable">
          <el-input
            v-model="suggestionsDraft"
            type="textarea"
            :rows="12"
            placeholder="可直接编辑 AI 建议后再写入知识库；也可在下方追加补充要求"
          />
          <div class="suggest-append">
            <el-input
              v-model="suggestionsAppend"
              type="textarea"
              :rows="2"
              placeholder="追加补充（可选）：例如「补充：iqoo neo9 之外，iqoo 全系加入必测矩阵」"
            />
            <el-button
              size="small"
              :disabled="!suggestionsAppend.trim()"
              @click="appendSuggestion"
            >追加到建议</el-button>
          </div>
          <div class="form-tip">
            编辑仅影响本报告与「写入知识库」的内容，原始 AI 建议已留档，可随时「恢复 AI 原文」。
          </div>
        </template>
        <pre v-else-if="currentReport.improvement_suggestions" class="suggest-readonly">{{ currentReport.improvement_suggestions }}</pre>
        <el-empty v-else description="暂无建议" />
      </div>
    </el-drawer>

    <!-- 覆盖率分析实时日志面板 -->
    <el-drawer v-model="logDrawerVisible" title="覆盖率分析实时日志" size="60%" @close="closeLogViewer">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
        <span style="font-size: 12px; color: #909399">
          报告 #{{ logReportId }} · 每 3 秒自动刷新
        </span>
        <div>
          <el-button size="small" @click="fetchReportLogs">刷新</el-button>
          <el-button size="small" type="primary" @click="scrollLogToBottom">滚动到底部</el-button>
        </div>
      </div>
      <div
        ref="logBodyEl"
        style="
          background: #1e1e1e; color: #d4d4d4; font-family: 'Consolas', 'Menlo', monospace;
          font-size: 12px; line-height: 1.7; padding: 12px; border-radius: 4px;
          height: calc(100vh - 160px); overflow: auto; white-space: pre-wrap;
        "
      >
        <div v-if="logLines.length === 0" style="color: #6a9955">（暂无日志，分析进行中…）</div>
        <div v-for="(line, i) in logLines" :key="i" style="white-space: pre-wrap">{{ line }}</div>
      </div>
    </el-drawer>

    <el-dialog v-model="reviewDialog" title="人工复核覆盖判定" width="520px">
      <div v-if="reviewItem">
        <el-alert
          type="info"
          :closable="false"
          style="margin-bottom: 12px"
          :title="`Bug #${reviewItem.bug.zentao_id} ${reviewItem.bug.title}`"
        />
        <el-form label-width="80px" label-position="left">
          <el-form-item label="原判定">
            <el-tag :type="reviewItem.covered ? 'success' : 'danger'" size="small">
              {{ reviewItem.covered ? '已覆盖' : '未覆盖' }}
            </el-tag>
            <span class="text-muted" style="margin-left: 8px">{{ reviewItem.reason || '无理由' }}</span>
          </el-form-item>
          <el-form-item label="修正为">
            <el-radio-group v-model="reviewForm.covered">
              <el-radio :label="true">已覆盖</el-radio>
              <el-radio :label="false">未覆盖</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="备注">
            <el-input
              v-model="reviewForm.note"
              type="textarea"
              :rows="3"
              placeholder="可选：说明人工修正的理由（会记录并可追溯）"
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingReview" @click="submitReview">保存复核</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import api from '@/utils/api'
import {
  createZentaoConfig,
  deleteCoverageReport,
  editReportSuggestions,
  getCoverageReport,
  getCoverageReportLogs,
  getCoverageReports,
  getZentaoBugs,
  getZentaoBuildsByProduct,
  getZentaoConfigs,
  getZentaoProjects,
  getProductMappings,
  pushReportToKnowledge,
  probeZentaoProducts,
  probeZentaoBuildsByProduct,
  reviewCoverageItem,
  saveProductMapping,
  testZentaoConnection,
  triggerCoverage,
  triggerZentaoSync,
  updateZentaoConfig,
} from '@/api/zentao'

const versions = ref([])
const projects = ref([])
const productOptions = ref({})
const buildOptions = ref([])
const buildLoading = ref(false)
const mappings = ref([])
const configs = ref([])
const loadingConfigs = ref(false)
const currentConfigId = ref(null)
const saving = ref(false)
const syncingId = ref(null)
const coverageId = ref(null)
// 覆盖率分析实时日志面板
const logDrawerVisible = ref(false)
const logLines = ref([])
const logPollTimer = ref(null)
const logReportId = ref(null)
const logBodyEl = ref(null)
const reports = ref([])
const loadingReports = ref(false)
const reportConfigFilter = ref(null)
const reportDrawer = ref(false)
const currentReport = ref(null)
// 有效真实 Bug 反推 + 低覆盖诊断（仅当报告 detail 含新字段时展示，兼容历史报告）
const hasValidBugStats = computed(() => {
  const d = currentReport.value?.detail
  return !!(d && d.valid_bug_total != null && d.effective_coverage_rate != null)
})
const effectiveCoverage = computed(() => {
  const v = currentReport.value?.detail?.effective_coverage_rate
  return typeof v === 'number' ? v : 0
})
const diagnosisLevelType = computed(() => {
  const level = currentReport.value?.detail?.coverage_diagnosis?.level
  if (level === 'ok') return 'success'
  if (level === 'high') return 'danger'
  return 'warning'
})
const diagnosisLevelText = computed(() => {
  const level = currentReport.value?.detail?.coverage_diagnosis?.level
  if (level === 'ok') return '达标'
  if (level === 'high') return '需优化（思路/遗漏）'
  if (level === 'low') return '偏低（非生成问题）'
  return '未知'
})
const diagnosisHasBreakdown = computed(() => {
  const cb = currentReport.value?.detail?.coverage_diagnosis?.cause_breakdown
  return !!(cb && (cb.ai_misunderstanding || cb.case_design_gap || cb.unknown))
})
const causeBreakdown = computed(() => {
  const cb = currentReport.value?.detail?.coverage_diagnosis?.cause_breakdown
  return cb || { ai_misunderstanding: 0, case_design_gap: 0, unknown: 0, total: 0 }
})
function causePercent(n) {
  const total = causeBreakdown.value.total || 0
  if (!total) return 0
  return Math.round((n / total) * 100)
}
const pushingKnowledge = ref(false)
// 提高覆盖率建议：支持人工编辑后再写入知识库
const suggestionsDraft = ref('')
const suggestionsOrigin = ref('')
const suggestionsAppend = ref('')
const savingSuggestions = ref(false)
const suggestionsEditable = computed(
  () => !!currentReport.value && currentReport.value.status === 'success'
)
const suggestionsDirty = computed(
  () => suggestionsEditable.value && suggestionsDraft.value !== suggestionsOrigin.value
)
const reviewDialog = ref(false)
const reviewItem = ref(null)
const reviewForm = ref({ covered: true, note: '' })
const savingReview = ref(false)

const currentMapping = computed(() =>
  mappings.value.find((m) => Number(m.project) === Number(form.value.project)) || null
)

const emptyForm = () => ({
  id: null,
  name: '禅道',
  base_url: '',
  account: '',
  password: '',
  product_id: '',
  build_id: '',
  build_name: '',
  opened_build_keyword: '',
  project: null,
  version: null,
  coverage_target: 90,
})
const form = ref(emptyForm())

const filteredVersions = computed(() => {
  if (!form.value.project) return versions.value
  return versions.value.filter((v) =>
    (v.projects || []).some((p) => Number(p.id) === Number(form.value.project))
  )
})

async function loadVersions() {
  const params = {}
  if (form.value.project) params.projects = form.value.project
  const res = await api.get('/versions/', { params })
  versions.value = res.data.results || res.data || []
}

async function loadProjects() {
  const res = await api.get('/projects/all/')
  projects.value = res.data || []
}

async function handleProjectChange() {
  form.value.version = null
  form.value.opened_build_keyword = ''
  await loadVersions()
}

async function loadConfigs() {
  loadingConfigs.value = true
  try {
    const res = await getZentaoConfigs()
    configs.value = res.data.results || res.data || []
    if (configs.value.length && !currentConfigId.value) {
      // 默认加载可用配置（已填产品/版本），避免落在未配置的测试配置上
      const best = configs.value.find((c) => c.product_id && c.build_id) || configs.value[0]
      currentConfigId.value = best.id
      editConfig(best)
    } else if (!configs.value.length) {
      currentConfigId.value = null
      form.value = emptyForm()
    }
  } finally {
    loadingConfigs.value = false
  }
}

function versionName(id) {
  const v = versions.value.find((x) => x.id === id)
  return v ? v.name : id || '-'
}

function projectName(id) {
  const p = projects.value.find((x) => x.id === id)
  return p ? p.name : id || '-'
}

function openCreate() {
  form.value = emptyForm()
  currentConfigId.value = null
  productOptions.value = {}
  buildOptions.value = []
  const saved = loadSavedCredentials()
  const last = configs.value.find((c) => c.id) || null
  if (saved) {
    form.value.base_url = saved.base_url || ''
    form.value.account = saved.account || ''
    form.value.password = saved.password || ''
  } else if (last) {
    form.value.base_url = last.base_url || ''
    form.value.account = last.account || ''
  }
  loadVersions()
}

function handleSelectConfig(id) {
  if (!id) {
    openCreate()
    return
  }
  const row = configs.value.find((c) => c.id === id)
  if (row) editConfig(row)
}

function loadSavedCredentials() {
  try {
    return JSON.parse(localStorage.getItem('zentao_last_credentials') || 'null')
  } catch (e) {
    return null
  }
}

function saveCredentials() {
  // 地址+账号任一为空则不存，避免覆盖成空
  if (!form.value.base_url || !form.value.account) return
  let password = form.value.password || ''
  // 密码为空（编辑沿用服务端密码）时，保留本地已存的同地址同账号密码，避免下次新建丢失
  if (!password) {
    const saved = loadSavedCredentials()
    if (saved && saved.base_url === form.value.base_url && saved.account === form.value.account) {
      password = saved.password || ''
    }
  }
  try {
    localStorage.setItem('zentao_last_credentials', JSON.stringify({
      base_url: form.value.base_url,
      account: form.value.account,
      password,
    }))
  } catch (e) {
    // 忽略存储失败
  }
}

function editConfig(row) {
  form.value = {
    id: row.id,
    name: row.name,
    base_url: row.base_url,
    account: row.account,
    password: '',
    product_id: row.product_id,
    build_id: row.build_id || '',
    build_name: row.build_name || '',
    opened_build_keyword: row.opened_build_keyword,
    project: row.project,
    version: row.version,
    coverage_target: row.coverage_target ?? 90,
  }
  // 本地记住的账号密码直接带出（未记住则留空，库中密码同步时仍会使用）
  const saved = loadSavedCredentials()
  if (saved && saved.base_url === row.base_url && saved.account === row.account) {
    form.value.password = saved.password || ''
  }
  productOptions.value = {}
  buildOptions.value = []
  if (form.value.product_id) {
    loadProjectsApi().then(() => {
      if (form.value.build_id) loadBuildsByProduct()
    })
  }
}

async function loadProjectsApi() {
  try {
    const res = form.value.id
      ? await getZentaoProjects(form.value.id)
      : await probeZentaoProducts({
          base_url: form.value.base_url,
          account: form.value.account,
          password: form.value.password,
        })
    productOptions.value = res.data.projects || {}
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '获取产品/项目列表失败，请检查地址/账号/密码')
  }
}

async function loadBuildsByProduct() {
  if (!form.value.product_id) return
  buildLoading.value = true
  try {
    let res
    if (form.value.id) {
      res = await getZentaoBuildsByProduct(form.value.id, form.value.product_id)
    } else {
      // 未保存配置：用临时凭证探测
      res = await probeZentaoBuildsByProduct({
        base_url: form.value.base_url,
        account: form.value.account,
        password: form.value.password,
        product_id: form.value.product_id,
      })
    }
    buildOptions.value = res.data.builds || []
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '获取版本/Build 列表失败')
    buildOptions.value = []
  } finally {
    buildLoading.value = false
  }
}

const buildPlaceholder = computed(() => {
  if (!form.value.product_id) return '请先选择禅道产品'
  if (buildLoading.value) return '版本加载中…'
  return '选择版本/Build（选产品后自动获取）'
})

const buildStatusText = computed(() => {
  if (buildLoading.value) return '版本列表加载中，首次加载可能需几秒…'
  if (!form.value.product_id) return '未选产品：请先在上方「禅道产品」下拉选择产品'
  const n = buildOptions.value.length
  if (n === 0) return '该产品暂未加载到版本（可重新展开下拉触发加载）'
  return `已加载 ${n} 个版本（产品 ${form.value.product_id}）`
})

async function handleProductChange() {
  // 保留用户新选的产品（el-select @change 触发时 form.value.product_id 已是新值），
  // 清空已选版本，重新加载新产品的版本列表
  form.value.build_id = null
  buildOptions.value = []
  buildLoading.value = false
  await loadBuildsByProduct()
}

function handleBuildChange() {
  // 选版本后把显示名(build_name)一并记录，供后端按 openedBuild 精确过滤
  const picked = buildOptions.value.find((b) => String(b.id) === String(form.value.build_id))
  form.value.build_name = picked ? picked.name : ''
}

function autoFillKeyword() {
  // 新流程按 build 精确拉取，关键字不再必需；保留为空即可
  form.value.opened_build_keyword = ''
}

async function saveConfig() {
  if (!form.value.base_url || !form.value.account) {
    ElMessage.warning('请填写禅道地址和账号')
    return
  }
  if (!form.value.version) {
    ElMessage.warning('请选择关联版本')
    return
  }
  if (!form.value.build_id) {
    ElMessage.warning('请在版本下拉中选择禅道版本(Build)')
    return
  }
  saving.value = true
  try {
    const payload = { ...form.value }
    if (payload.id) {
      await updateZentaoConfig(payload.id, payload)
      ElMessage.success('配置已更新')
    } else {
      await createZentaoConfig(payload)
      ElMessage.success('配置已创建')
    }
    saveCredentials()
    form.value = emptyForm()
    currentConfigId.value = null
    await loadConfigs()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function extractVersionDigits(name) {
  const m = String(name || '').match(/(\d+(?:\.\d+){1,3})/)
  return m ? m[1] : ''
}

function extractCjkPrefix(name) {
  const m = String(name || '').match(/^[\u4e00-\u9fffA-Za-z]+/)
  return m ? m[0] : ''
}

function matchProductByVersion(versionName) {
  const entries = Object.entries(productOptions.value || {})
  if (!entries.length) return null
  // 1) 项目产品映射优先（如 轻卡日常 ↔ 卡鲁狸）
  if (currentMapping.value && currentMapping.value.zentao_product_name) {
    const target = currentMapping.value.zentao_product_name.trim()
    const hit =
      entries.find(([, name]) => name.trim() === target) ||
      entries.find(([, name]) => name.includes(target))
    if (hit) return hit[0]
  }
  // 2) 按版本名中文前缀匹配
  const prefix = extractCjkPrefix(versionName)
  if (prefix) {
    const exact = entries.find(([, name]) => name.trim() === prefix)
    if (exact) return exact[0]
    const starts = entries.find(([, name]) => name.trim().startsWith(prefix))
    if (starts) return starts[0]
    const includes = entries.find(([, name]) => name.includes(prefix))
    if (includes) return includes[0]
  }
  return null
}

async function loadMappings() {
  try {
    const res = await getProductMappings()
    mappings.value = res.data.results || res.data || []
  } catch (e) {
    // 映射加载失败不阻塞
  }
}

async function rememberMapping() {
  if (!form.value.project || !form.value.product_id) return
  const name = productOptions.value[form.value.product_id]
  if (!name) {
    ElMessage.warning('请先在产品下拉中选择禅道产品')
    return
  }
  try {
    await saveProductMapping({
      project: form.value.project,
      zentao_product_name: name,
      zentao_product_id: String(form.value.product_id),
    })
    await loadMappings()
    ElMessage.success(`已记住映射：${projectName(form.value.project)} → ${name}`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存映射失败')
  }
}

function matchBuildByVersion(digits) {
  if (!digits) return null
  const hit = buildOptions.value.find((b) => String(b.name).includes(digits))
  return hit ? String(hit.id) : null
}

async function saveAndAutoMatch() {
  if (!form.value.base_url || !form.value.account) {
    ElMessage.warning('请填写禅道地址和账号')
    return
  }
  if (!form.value.version) {
    ElMessage.warning('请选择关联版本')
    return
  }
  saving.value = true
  try {
    let payload = { ...form.value }
    if (payload.id) {
      await updateZentaoConfig(payload.id, payload)
    } else {
      const res = await createZentaoConfig(payload)
      payload.id = res.data.id
      form.value.id = payload.id
    }
    saveCredentials()

    // 若已手动选了产品（编辑已有配置或新建时已选择），直接保留并加载版本，不重复自动匹配
    if (form.value.product_id) {
      await loadProjectsApi()
      await loadBuildsByProduct()
      ElMessage.success(`已保存配置并加载产品「${productOptions.value[form.value.product_id] || form.value.product_id}」的版本列表`)
      await loadConfigs()
      return
    }

    // 新建且未选产品：自动匹配禅道产品（优先「TestHub项目 ↔ 禅道产品名」映射，其次按项目名匹配）
    await loadProjectsApi()
    const pid = matchProductByProject()
    if (pid) {
      form.value.product_id = String(pid)
      // 保存产品选择
      await updateZentaoConfig(form.value.id, { ...form.value })
      // 加载该产品的版本列表供用户选择
      await loadBuildsByProduct()
      ElMessage.success(`已自动匹配禅道产品「${productOptions.value[pid]}」，请在版本下拉中选择版本(Build)`)
    } else {
      ElMessage.warning('未能自动匹配禅道产品（当前项目与禅道产品名不一致，且未配置映射）。请在产品下拉中手动选择禅道产品，或先到「产品映射」配置「TestHub项目 ↔ 禅道产品名」后再次保存。')
    }

    await loadConfigs()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

function matchProductByProject() {
  const entries = Object.entries(productOptions.value || {})
  if (!entries.length) return null
  // 1) 项目映射优先（如 轻练 ↔ 卡鲁狸）
  if (currentMapping.value && currentMapping.value.zentao_product_name) {
    const target = currentMapping.value.zentao_product_name.trim()
    const hit =
      entries.find(([, name]) => name.trim() === target) ||
      entries.find(([, name]) => name.includes(target))
    if (hit) return hit[0]
  }
  // 2) 按 TestHub 项目名匹配禅道产品名（项目即产品，同一套名字）
  const thName = (projectName(form.value.project) || '').trim()
  if (thName) {
    const exact = entries.find(([, name]) => name.trim() === thName)
    if (exact) return exact[0]
    const includes = entries.find(([, name]) => name.includes(thName) || thName.includes(name))
    if (includes) return includes[0]
  }
  return null
}

async function testConnection(row) {
  try {
    const res = await testZentaoConnection(row.id)
    const products = Object.entries(res.data.products || {})
    ElMessageBox.alert(
      `<div style="max-height: 360px; overflow: auto">${products
        .map(([id, name]) => `<div>${id} - ${name}</div>`)
        .join('')}</div>`,
      '禅道连接成功，产品列表',
      { dangerouslyUseHTMLString: true, confirmButtonText: '关闭' },
    )
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '连接失败')
  }
}

async function syncBugs(row) {
  syncingId.value = row.id
  try {
    await triggerZentaoSync(row.id)
    ElMessage.success('同步任务已启动，等待同步完成…')
    await pollConfigSync(row.id)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '启动同步失败')
  } finally {
    syncingId.value = null
  }
}

async function pollConfigSync(configId) {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 5000))
    try {
      const res = await getZentaoConfigs()
      configs.value = res.data.results || res.data || []
      const row = configs.value.find((c) => c.id === configId)
      const sync = row?.last_sync_status
      if (row && row.bug_count > 0 && sync?.status === 'success') {
        ElMessage.success(`同步完成，共 ${row.bug_count} 条 Bug，可进行覆盖率分析`)
        return
      }
      if (row && sync?.status === 'failed') {
        ElMessage.error(`同步失败：${sync.message || '未知错误'}`)
        return
      }
    } catch (e) {
      // 继续轮询
    }
  }
  ElMessage.warning('同步耗时较长，请稍后在配置列表查看状态')
}

async function runCoverage(row) {
  if (!row.product_id || !row.build_id) {
    ElMessage.warning('该配置未选择产品/版本(Build)，请先配置并同步 Bug')
    return
  }
  coverageId.value = row.id
  try {
    const res = await triggerCoverage(row.id)
    const reportId = res.data.report_id
    ElMessage.success('覆盖率分析已启动，正在调用 AI 判定…')
    // 自动打开实时日志面板（分析刚启动，强制轮询）
    openLogViewer({ id: reportId, status: 'running' })
    // 立即刷新列表，让用户看到 running 状态的新任务（避免以为没点到）
    await loadReports()
    pollReport(reportId)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '启动分析失败')
  } finally {
    coverageId.value = null
  }
}

// 打开覆盖率分析实时日志面板（reportId 可为数字，或传入 report 对象判断状态）
function openLogViewer(reportOrId) {
  const reportId = typeof reportOrId === 'object' ? reportOrId.id : reportOrId
  const isRunning = typeof reportOrId === 'object' ? reportOrId.status === 'running' : false
  logReportId.value = reportId
  logLines.value = []
  logDrawerVisible.value = true
  stopLogPolling()
  fetchReportLogs()
  // 仅在分析仍在进行时自动轮询；已结束的报告日志不再变化，避免无意义 3 秒轮询
  if (isRunning) {
    logPollTimer.value = setInterval(fetchReportLogs, 3000)
  }
}

async function fetchReportLogs() {
  if (!logReportId.value) return
  try {
    const res = await getCoverageReportLogs(logReportId.value, 500)
    logLines.value = res.data.lines || []
    scrollLogToBottom()
  } catch (e) {
    // 日志接口失败不阻塞
  }
}

function stopLogPolling() {
  if (logPollTimer.value) {
    clearInterval(logPollTimer.value)
    logPollTimer.value = null
  }
}

function scrollLogToBottom() {
  requestAnimationFrame(() => {
    const el = logBodyEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function closeLogViewer() {
  stopLogPolling()
  logDrawerVisible.value = false
  logReportId.value = null
}

async function pollReport(reportId) {
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 5000))
    try {
      const res = await getCoverageReport(reportId)
      const report = res.data
      if (report.status !== 'running') {
        // 分析结束，停止实时日志轮询并拉取最终日志
        stopLogPolling()
        await fetchReportLogs()
        setCurrentReport(report)
        reportDrawer.value = true
        if (report.status === 'failed') {
          ElMessage.error(report.error_message || '分析失败')
        } else {
          ElMessage.success(`分析完成，覆盖率 ${report.coverage_rate}%`)
        }
        await loadReports()
        return
      }
    } catch (e) {
      // 继续轮询
    }
  }
  ElMessage.warning('分析超时，请稍后在报告列表中查看')
}

async function loadReports() {
  loadingReports.value = true
  try {
    const params = {}
    if (reportConfigFilter.value) params.config_id = reportConfigFilter.value
    const res = await getCoverageReports(params)
    reports.value = res.data.results || res.data || []
    // 自动刷新 running 中的报告
    if (reports.value.some((r) => r.status === 'running')) {
      setTimeout(loadReports, 8000)
    }
  } finally {
    loadingReports.value = false
  }
}

async function openReport(row) {
  try {
    const res = await getCoverageReport(row.id)
    setCurrentReport(res.data)
    reportDrawer.value = true
  } catch (e) {
    ElMessage.error('加载报告失败')
  }
}

// 统一入口：设置当前报告并同步「提高覆盖率建议」编辑草稿
function setCurrentReport(report) {
  currentReport.value = report
  suggestionsOrigin.value = report?.improvement_suggestions || ''
  suggestionsDraft.value = suggestionsOrigin.value
  suggestionsAppend.value = ''
}

function resetSuggestionsEdit() {
  suggestionsDraft.value = suggestionsOrigin.value
}

function appendSuggestion() {
  const extra = suggestionsAppend.value.trim()
  if (!extra) return
  suggestionsDraft.value = suggestionsDraft.value.trim()
    ? `${suggestionsDraft.value.trimEnd()}\n\n${extra}`
    : extra
  suggestionsAppend.value = ''
}

async function saveSuggestions(silent = false) {
  if (!currentReport.value) return null
  savingSuggestions.value = true
  try {
    const res = await editReportSuggestions(currentReport.value.id, {
      content: suggestionsDraft.value,
    })
    const content = res.data.improvement_suggestions ?? suggestionsDraft.value
    currentReport.value.improvement_suggestions = content
    currentReport.value.suggestions_edited_by = res.data.edited_by
    currentReport.value.suggestions_edited_at = res.data.edited_at
    suggestionsOrigin.value = content
    suggestionsDraft.value = content
    if (!silent) ElMessage.success('建议已保存')
    return content
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '保存建议失败')
    return null
  } finally {
    savingSuggestions.value = false
  }
}

async function restoreAiSuggestions() {
  const ai = currentReport.value?.improvement_suggestions_ai
  if (ai == null) return
  try {
    await ElMessageBox.confirm('将用 AI 原文覆盖当前建议（含人工编辑内容），确定吗？', '恢复 AI 原文', {
      type: 'warning',
      confirmButtonText: '恢复',
      cancelButtonText: '取消',
    })
  } catch (e) {
    return
  }
  suggestionsDraft.value = ai
  await saveSuggestions(true)
  ElMessage.success('已恢复为 AI 原文')
}

async function deleteReport(row) {
  const isRunning = row.status === 'running'
  const baseMsg = `${row.project_name || '-'} / ${row.version_name || '-'}（覆盖率 ${row.coverage_rate}%）`
  const message = isRunning
    ? `该报告正在分析中，删除将立即停止后台任务并删除报告。\n${baseMsg}`
    : `确定删除该报告吗？\n${baseMsg}`
  try {
    await ElMessageBox.confirm(
      message,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch (e) {
    return
  }
  try {
    await deleteCoverageReport(row.id)
    ElMessage.success(isRunning ? '已停止分析并删除报告' : '报告已删除')
    await loadReports()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
}

async function pushKnowledge() {
  if (!currentReport.value) return
  pushingKnowledge.value = true
  try {
    // 有未保存的编辑时，连同编辑后的正文一起提交，保证写入的是人工确认版
    const payload = suggestionsDirty.value
      ? { improvement_suggestions: suggestionsDraft.value }
      : {}
    const res = await pushReportToKnowledge(currentReport.value.id, payload)
    if (suggestionsDirty.value) {
      // 后端已落库本次提交的建议，同步本地编辑态
      currentReport.value.improvement_suggestions = suggestionsDraft.value
      suggestionsOrigin.value = suggestionsDraft.value
      if (res.data.edited_by) currentReport.value.suggestions_edited_by = res.data.edited_by
    }
    ElMessage.success(res.data.message || '已写入知识库')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '写入知识库失败')
  } finally {
    pushingKnowledge.value = false
  }
}

function openReview(row) {
  reviewItem.value = row
  reviewForm.value = { covered: !!row.covered, note: '' }
  reviewDialog.value = true
}

async function submitReview() {
  if (!currentReport.value || !reviewItem.value) return
  savingReview.value = true
  try {
    const res = await reviewCoverageItem(currentReport.value.id, {
      item_id: reviewItem.value.id,
      covered: reviewForm.value.covered,
      note: reviewForm.value.note,
    })
    reviewDialog.value = false
    ElMessage.success(res.data.message || '复核已保存')
    // 重新拉取整个报告，确保明细标签、理由、覆盖率统计全部刷新
    try {
      const refreshed = await getCoverageReport(currentReport.value.id)
      // 复核只影响判定明细，保留建议编辑草稿，避免用户未保存的编辑被覆盖
      const draft = suggestionsDraft.value
      const origin = suggestionsOrigin.value
      setCurrentReport(refreshed.data)
      if (draft !== origin) suggestionsDraft.value = draft
    } catch (e) {
      // 拉取失败则就地更新，避免整页刷新丢失上下文
      reviewItem.value.covered = reviewForm.value.covered
      reviewItem.value.reason = `[人工复核] 原判定：${reviewItem.value.reason || '无'}；人工修正为：${
        reviewForm.value.covered ? '已覆盖' : '未覆盖'
      }${reviewForm.value.note ? `；备注：${reviewForm.value.note}` : ''}`
      currentReport.value.covered_bugs = res.data.covered_bugs
      currentReport.value.uncovered_bugs = res.data.uncovered_bugs
      currentReport.value.coverage_rate = res.data.coverage_rate
    }
    await loadReports()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '保存复核失败')
  } finally {
    savingReview.value = false
  }
}

function reportStatusText(s) {
  return { running: '分析中', success: '完成', failed: '失败' }[s] || s
}

function reportStatusType(s) {
  return { running: 'warning', success: 'success', failed: 'danger' }[s] || 'info'
}

function formatTime(value) {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-'
}

onMounted(() => {
  loadProjects()
  loadVersions()
  loadConfigs()
  loadReports()
  loadMappings()
})
</script>

<style scoped>
.page-container {
  padding: 16px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.card-header {
  display: flex;
  align-items: center;
  font-weight: 600;
}
.bug-title {
  font-weight: 500;
  line-height: 1.4;
}
.bug-meta {
  color: #909399;
  font-size: 12px;
  margin-top: 2px;
}
.text-muted {
  color: #c0c4cc;
}
.form-tip {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}
.mapping-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 8px;
}
.mapping-text {
  font-size: 12px;
  color: #606266;
  flex: 1;
}
.diag-card {
  margin-top: 12px;
}
.diag-card .card-header {
  justify-content: space-between;
}
.stat-box {
  text-align: center;
  padding: 14px 8px;
  border-radius: 8px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
}
.stat-box.ok {
  background: #f0f9eb;
  border-color: #e1f3d8;
}
.stat-box.warn {
  background: #fdf6ec;
  border-color: #faecd8;
}
.stat-num {
  font-size: 26px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}
.stat-label {
  font-size: 13px;
  color: #606266;
  margin-top: 6px;
}
.stat-sub {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}
.diag-tip {
  margin-top: 12px;
  padding: 8px 12px;
  background: #f4f4f5;
  border-radius: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
.diag-breakdown-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin: 4px 0 10px;
}
.diag-scenes {
  margin-top: 14px;
  border-top: 1px dashed #ebeef5;
  padding-top: 12px;
}
.scene-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
}
.scene-count {
  color: #e6a23c;
  font-weight: 600;
  white-space: nowrap;
}
.scene-examples {
  color: #909399;
  flex: 1;
}
.suggest-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.suggest-header h4 {
  margin-right: auto;
}
.suggest-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.suggest-append {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 8px;
}
.suggest-readonly {
  margin: 0;
  padding: 12px 14px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
