<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">历史缺陷复盘</h1>
        <div class="page-sub">
          整合项目历史有效缺陷，提炼为测试点，供新版本迭代生成更精准的用例
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新建复盘
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左：新建/数据源 -->
      <el-col :span="7">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">数据源</div>
          </template>
          <el-form label-position="top">
            <el-form-item label="禅道配置">
              <el-select
                v-model="form.config"
                filterable
                clearable
                placeholder="选择已保存的禅道配置"
                style="width: 100%"
                @change="handleConfigChange"
              >
                <el-option
                  v-for="c in configs"
                  :key="c.id"
                  :label="`${c.name}（${c.product_id ? '产品' + c.product_id : '未配置产品'}）`"
                  :value="c.id"
                />
              </el-select>
              <div class="form-tip">
                历史缺陷需直连禅道数据库读取（HTTP 接口只能拿到当前版本）。
              </div>
            </el-form-item>

            <el-form-item v-if="form.config" label="数据库连接">
              <div class="db-row">
                <el-tag v-if="currentConfig?.db_ready" type="success" size="small">已配置</el-tag>
                <el-tag v-else type="danger" size="small">未配置</el-tag>
                <el-button size="small" :loading="dbPinging" @click="testDb">测试连接</el-button>
              </div>
              <div v-if="dbInfo" class="form-tip db-info">
                库 {{ dbInfo.database }} · MySQL {{ dbInfo.server_version }}
              </div>
              <div v-if="dbError" class="form-tip db-error">{{ dbError }}</div>
            </el-form-item>

            <el-form-item v-if="dbProducts.length" label="禅道产品（取数范围）">
              <el-select
                v-model="form.product_ids"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择要复盘的产品，通常选 1 个"
                style="width: 100%"
              >
                <el-option
                  v-for="p in sortedDbProducts"
                  :key="p.id"
                  :label="productOptionLabel(p)"
                  :value="Number(p.id)"
                >
                  <span class="opt-name">{{ p.id }} - {{ p.name }}</span>
                  <span
                    class="opt-count"
                    :class="{ 'is-empty': !p.bug_count }"
                  >{{ productCountText(p) }}</span>
                </el-option>
              </el-select>
              <div v-if="pickedEmptyProducts.length" class="form-tip db-warn">
                已选产品中没有有效历史缺陷：{{ pickedEmptyProducts.join('、') }}。
                这份复盘会产出空报告，请确认是否选错了产品（禅道配置里的产品 ID
                可能指向别的产品）。
              </div>
            </el-form-item>

            <el-form-item label="关联项目（测试点归属）">
              <el-select v-model="form.project" filterable clearable style="width: 100%">
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>

            <!-- ⚠️ 不用 type="daterange"：实测（Element Plus 2.3.9）在只点一次时
                 会把结束日期补成与开始同一天，且反复修改开始日期会连带改结束日期，
                 实际无法选出区间（2026-10-22 用户反馈两次）。
                 改为两个独立 date-picker，各自独立取值，语义清晰不会互相污染。 -->
            <el-form-item label="缺陷开始日期（可选）">
              <el-date-picker
                v-model="form.dateFrom"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="不填表示不限"
                clearable
                style="width: 100%"
                :disabled-date="disabledFuture"
              />
            </el-form-item>
            <el-form-item label="缺陷结束日期（可选）">
              <el-date-picker
                v-model="form.dateTo"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="不填表示不限"
                clearable
                style="width: 100%"
                :disabled-date="disabledFuture"
              />
              <div v-if="dateRangeInvalid" class="form-tip db-error">
                开始日期不能晚于结束日期，请调整后再提交。
              </div>
              <div v-else-if="!form.dateFrom && !form.dateTo" class="form-tip">
                起止都留空表示统计该产品的全部历史缺陷。
              </div>
              <div v-else class="form-tip">
                将统计 {{ form.dateFrom || '最早' }} ~ {{ form.dateTo || '至今' }} 的缺陷。
              </div>
            </el-form-item>

            <el-form-item>
              <el-checkbox v-model="form.exclude_ui_types">
                排除界面优化类缺陷（interfaceoptimize）
              </el-checkbox>
            </el-form-item>

            <el-button
              type="primary"
              :loading="creating"
              :disabled="!canCreate"
              style="width: 100%"
              @click="submitCreate"
            >
              开始复盘
            </el-button>
            <div v-if="!canCreate" class="form-tip">
              需先选择禅道配置、数据库已配置，并至少选一个产品
            </div>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右：报告列表 -->
      <el-col :span="17">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              复盘报告
              <div class="header-actions" style="margin-left: auto">
                <el-button size="small" @click="loadReports">刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="reports" v-loading="loadingReports" size="small" @row-click="openReport">
            <el-table-column label="报告" min-width="180">
              <template #default="{ row }">
                <div>{{ row.name || `复盘 #${row.id}` }}</div>
                <div class="bug-meta">{{ row.project_name || '-' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="产品" min-width="100">
              <template #default="{ row }">{{ (row.product_ids || []).join(', ') || '-' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tooltip
                  :disabled="!row.error_message"
                  :content="row.error_message"
                  placement="top"
                >
                  <el-tag
                    :type="row.status === 'success' && row.error_message ? 'warning' : statusType(row.status)"
                    size="small"
                  >
                    {{ row.status === 'success' && row.error_message ? '无数据' : statusText(row.status) }}
                  </el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column prop="bug_total" label="缺陷" width="70" />
            <el-table-column prop="domain_count" label="功能域" width="80" />
            <el-table-column prop="testpoint_count" label="测试点" width="80">
              <template #default="{ row }">
                <span style="color: #67c23a; font-weight: 600">{{ row.testpoint_count }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" min-width="130">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" plain @click.stop="openReport(row)">查看</el-button>
                <el-button size="small" type="danger" plain @click.stop="removeReport(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 报告详情 -->
    <el-drawer v-model="drawer" title="历史缺陷复盘报告" size="78%">
      <div v-if="report" v-loading="loadingDetail">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="状态">
            {{ statusText(report.status) }}
          </el-descriptions-item>
          <el-descriptions-item label="纳入缺陷">{{ report.bug_total }}</el-descriptions-item>
          <el-descriptions-item label="功能域">{{ report.domain_count }}</el-descriptions-item>
          <el-descriptions-item label="测试点">{{ report.testpoint_count }}</el-descriptions-item>
        </el-descriptions>

        <!-- 失败 → error；成功但读到 0 条 → warning（原因可见，不是静默"完成"） -->
        <el-alert
          v-if="report.error_message || report.status === 'failed'"
          :type="report.status === 'failed' ? 'error' : 'warning'"
          :title="report.error_message || '分析失败'"
          :closable="false"
          style="margin-top: 12px"
          show-icon
        />

        <!-- 统计 -->
        <template v-if="report.status === 'success'">
          <el-card shadow="never" class="block">
            <template #header><div class="card-header">缺陷分布</div></template>
            <!-- 数量漏斗：把「禅道多少条 → 纳入多少条」的每一步摆出来，
                 避免出现"禅道 143 / 复盘 132"这类看起来像统计错误的情况 -->
            <div v-if="stats.funnel && stats.funnel.all_rows != null" class="funnel">
              <span class="funnel-step">禅道全部 <b>{{ stats.funnel.all_rows }}</b></span>
              <span class="funnel-arrow">→</span>
              <span class="funnel-step">剔除已删除 {{ stats.funnel.excluded_deleted }} 后 <b>{{ stats.funnel.alive }}</b></span>
              <span class="funnel-arrow">→</span>
              <span class="funnel-step">已闭环 <b>{{ stats.funnel.closed }}</b></span>
              <span class="funnel-arrow">→</span>
              <span class="funnel-step">类型过滤后 <b>{{ stats.funnel.final }}</b></span>
              <span class="funnel-arrow">=</span>
              <span class="funnel-step funnel-final">纳入复盘 <b>{{ stats.bug_eligible }}</b></span>
            </div>

            <el-row :gutter="12" style="margin-top: 12px">
              <el-col :span="8">
                <div class="sub-title">按功能域</div>
                <el-table :data="stats.by_domain" size="small" max-height="240">
                  <el-table-column prop="domain" label="功能域" min-width="120" />
                  <el-table-column prop="count" label="缺陷数" width="80" />
                  <el-table-column label="占比" width="90">
                    <template #default="{ row }">{{ row.ratio }}%</template>
                  </el-table-column>
                </el-table>
              </el-col>
              <el-col :span="8">
                <div class="sub-title">按易漏维度</div>
                <el-table :data="stats.by_scene" size="small" max-height="240">
                  <el-table-column prop="scene" label="维度" min-width="130" />
                  <el-table-column prop="count" label="缺陷数" width="80" />
                  <el-table-column label="占比" width="90">
                    <template #default="{ row }">{{ row.ratio }}%</template>
                  </el-table-column>
                </el-table>
              </el-col>
              <el-col :span="8">
                <div class="sub-title">按解决方案</div>
                <el-table :data="stats.by_resolution" size="small" max-height="240">
                  <el-table-column prop="name" label="解决方案" min-width="110" />
                  <el-table-column prop="count" label="缺陷数" width="80" />
                  <el-table-column label="占比" width="90">
                    <template #default="{ row }">{{ row.ratio }}%</template>
                  </el-table-column>
                </el-table>
                <div class="form-tip">
                  「外部原因」「设计如此」同样纳入复盘——它们往往是真实的产品问题，
                  只是当年被归类为外部依赖。
                </div>
              </el-col>
            </el-row>
            <div class="form-tip">
              有文字的复现步骤占 {{ stats.text_step_ratio }}%；易漏维度命中率
              {{ stats.scene_match_ratio }}%。本版按方案 A 只用标题 + 非空文字，忽略截图。
            </div>
          </el-card>

          <!-- 测试点 -->
          <el-card shadow="never" class="block">
            <template #header>
              <div class="card-header">
                测试点（{{ testpoints.length }} 条，已选 {{ selectedCount }} 条）
                <div class="header-actions" style="margin-left: auto">
                  <el-button size="small" @click="toggleSelectAll">
                    {{ allSelected ? '取消全选' : '全选' }}
                  </el-button>
                  <el-button size="small" type="primary" plain @click="openPromptPreview">
                    预览注入内容
                  </el-button>
                </div>
              </div>
            </template>

            <div class="filter-row">
              <el-select
                v-model="domainFilter"
                multiple
                collapse-tags
                clearable
                placeholder="按功能域筛选"
                size="small"
                style="width: 320px"
              >
                <el-option v-for="d in domainOptions" :key="d" :label="d" :value="d" />
              </el-select>
              <el-input
                v-model="keywordFilter"
                placeholder="搜索测试点/关键词"
                size="small"
                clearable
                style="width: 240px"
              />
            </div>

            <el-table :data="filteredTestpoints" size="small" border max-height="520">
              <el-table-column width="46">
                <template #default="{ row }">
                  <el-checkbox
                    :model-value="!!row.selected"
                    @change="(v) => toggleOne(row, v)"
                  />
                </template>
              </el-table-column>
              <el-table-column prop="tp_id" label="ID" width="80" />
              <el-table-column label="测试点" min-width="230">
                <template #default="{ row }">
                  <div class="tp-title">{{ row.title }}</div>
                  <div class="tp-kw">
                    <el-tag
                      v-for="k in row.keywords || []"
                      :key="k"
                      size="small"
                      type="info"
                      effect="plain"
                      class="kw-tag"
                    >{{ k }}</el-tag>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="为什么测（历史依据）" min-width="290">
                <template #default="{ row }">
                  <div class="tp-desc">{{ row.description }}</div>
                  <div v-if="row.examples?.length" class="tp-example">
                    例：{{ row.examples[0] }}
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="验证要点" min-width="260">
                <template #default="{ row }">
                  <div v-for="(c, i) in (row.checks || []).slice(0, 4)" :key="i" class="check-item">
                    · {{ c }}
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="count" label="缺陷数" width="80" />
              <el-table-column label="操作" width="80" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 注入预览 -->
          <el-card v-if="promptBlock || previewBlocked" shadow="never" class="block">
            <template #header>
              <div class="card-header">
                将注入用例生成的内容
                <el-tag v-if="previewMeta.suggested?.length" size="small" style="margin-left: 8px">
                  按需求自动筛选：{{ previewMeta.suggested.join('、') }}
                </el-tag>
                <el-tag v-if="previewBlocked" type="warning" size="small" style="margin-left: 8px">
                  已拦截，不注入
                </el-tag>
                <el-tag v-else-if="previewWeak" type="info" size="small" style="margin-left: 8px">
                  弱相关，仅注入 {{ previewMeta.used_count || 0 }} 条
                </el-tag>
                <el-tag v-else-if="previewMeta.used_count" size="small" style="margin-left: 8px">
                  注入 {{ previewMeta.used_count }} 条
                </el-tag>
                <div class="header-actions" style="margin-left: auto">
                  <el-button size="small" @click="promptBlock = ''; previewBlocked = false">
                    收起
                  </el-button>
                </div>
              </div>
            </template>

            <!--
              这里是「报告视角」的预览：报告本身不含需求，也不该要求用户在这里填需求。
              真实生成时是否注入、注入哪个域，取决于**生成任务里的需求文本**
              （ai_model_service._build_defect_review_section 用的是 task.requirement_text），
              报告页只负责说清楚「这份报告能提供什么」。
            -->
            <!-- 报告视角说明：没有需求可比对，展示的是报告全量测试点 -->
            <div v-if="previewReportScope" class="scope-tip">
              以下为这份复盘报告的全部测试点（已按勾选与条数上限截取）。
              实际注入哪几条，由**生成用例时**该次任务的需求决定：系统会把需求与测试点的
              功能域/变更意图比对，命中才注入；完全不相关时不注入。
            </div>

            <el-alert
              v-if="previewBlocked"
              type="warning"
              :closable="false"
              show-icon
              :title="previewBlockedTitle"
              style="margin-bottom: 10px"
            >
              <div>{{ previewMeta.relevance?.reason }}</div>
            </el-alert>

            <el-alert
              v-if="previewWeak"
              type="info"
              :closable="false"
              show-icon
              title="弱相关：本次需求没有命中复盘报告的具体功能域，仅按变更类型注入了少量参考"
              style="margin-bottom: 10px"
            >
              <div>{{ previewMeta.relevance?.reason }}</div>
              <div style="margin-top: 4px; color: #909399">
                如需注入特定功能域，可在下方手动选择域筛选，或先重建一份覆盖该模块的复盘报告。
              </div>
            </el-alert>

            <template v-if="!previewBlocked">
              <!-- 预算控制：详略档位 + 条数上限 + 实时 token 估算 -->
              <div class="preview-toolbar">
                <span class="toolbar-label">详略</span>
                <el-radio-group v-model="previewLevel" size="small" @change="onLevelChange">
                  <el-radio-button label="brief">精简</el-radio-button>
                  <el-radio-button label="standard">标准</el-radio-button>
                  <el-radio-button label="full">详细</el-radio-button>
                </el-radio-group>

                <span class="toolbar-label" style="margin-left: 12px">最多</span>
                <el-input-number
                  v-model="previewMaxPoints"
                  :min="1"
                  :max="60"
                  size="small"
                  controls-position="right"
                  style="width: 90px"
                  @change="refreshPreview"
                />

                <el-tag
                  :type="tokenTagType"
                  size="small"
                  style="margin-left: 12px"
                >
                  约 {{ previewMeta.estimated_tokens || 0 }} tokens
                  （精简 {{ previewMeta.size_compare?.brief || 0 }} /
                  标准 {{ previewMeta.size_compare?.standard || 0 }} /
                  详细 {{ previewMeta.size_compare?.full || 0 }}）
                </el-tag>
              </div>
              <div class="form-tip" style="margin-bottom: 8px">
                默认按「本次需求涉及的功能域」筛选，只注入相关测试点；留空域筛选则按缺陷数取前 N 条。
                建议控制在 3000 tokens 以内，避免稀释模型对需求文档的注意力。
              </div>

              <pre class="prompt-block">{{ promptBlock }}</pre>
            </template>
          </el-card>

          <!-- 反向使用记录：预览只能看「理论上会注入什么」，这里看「实际注入后发生了什么」 -->
          <el-card shadow="never" class="block">
            <template #header>
              <div class="card-header">
                使用记录
                <el-tag v-if="usageData" size="small" style="margin-left: 8px">
                  被 {{ usageData.task_total }} 个任务使用，共注入
                  {{ usageData.injected_point_total }} 条
                </el-tag>
                <div class="header-actions" style="margin-left: auto">
                  <el-button size="small" :loading="usageLoading" @click="loadUsage">
                    刷新
                  </el-button>
                </div>
              </div>
            </template>

            <div v-if="!usageData || !usageData.results?.length" class="form-tip">
              这份复盘报告还没有被任何用例生成任务使用。
              生成用例时在「历史缺陷测试点」里选中它，这里就会出现每次任务实际命中的测试点。
            </div>

            <el-table v-else :data="usageData.results" size="small" border>
              <el-table-column type="expand">
                <template #default="{ row }">
                  <div class="usage-detail">
                    <div v-if="!row.audited" class="form-tip">
                      该任务早于审计功能上线（或尚未执行到注入环节），没有记录明细。
                    </div>
                    <template v-else>
                      <div class="usage-reason">
                        <el-tag :type="row.injected ? 'success' : 'info'" size="small">
                          {{ row.injected ? '已注入' : '未注入' }}
                        </el-tag>
                        <span style="margin-left: 8px">{{ row.reason || '-' }}</span>
                      </div>
                      <div v-if="row.matched_domains?.length" class="form-tip">
                        命中功能域：{{ row.matched_domains.join('、') }}
                      </div>
                      <div v-if="row.items?.length" class="form-tip">
                        实际注入 {{ row.items.length }} 条 / {{ row.prompt_chars }} 字符
                        / 详略 {{ row.detail_level || '-' }}
                      </div>
                      <el-table
                        v-if="row.items?.length"
                        :data="row.items"
                        size="small"
                        border
                        style="margin-top: 8px"
                      >
                        <el-table-column prop="domain" label="功能域" width="140" />
                        <el-table-column prop="scene" label="维度" width="150" />
                        <el-table-column prop="title" label="测试点" />
                        <el-table-column prop="count" label="历史缺陷" width="90" />
                      </el-table>
                    </template>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="task_no" label="任务" width="150" />
              <el-table-column prop="title" label="标题" show-overflow-tooltip />
              <el-table-column prop="project_name" label="项目" width="130" />
              <el-table-column label="注入" width="110">
                <template #default="{ row }">
                  <el-tag v-if="!row.audited" type="info" size="small">无记录</el-tag>
                  <el-tag v-else-if="row.injected" type="success" size="small">
                    {{ row.used_count }} 条
                  </el-tag>
                  <el-tag v-else type="warning" size="small">未注入</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="created_by" label="创建人" width="110" />
              <el-table-column label="时间" width="150">
                <template #default="{ row }">
                  {{ formatTime(row.at || row.created_at) }}
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>
      </div>
    </el-drawer>

    <!-- 编辑测试点 -->
    <el-dialog v-model="editDialog" title="编辑测试点" width="620px">
      <el-form v-if="editForm" label-position="top">
        <el-form-item label="测试点标题">
          <el-input v-model="editForm.title" />
        </el-form-item>
        <el-form-item label="为什么测（历史依据）">
          <el-input v-model="editForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="验证要点（每行一条）">
          <el-input v-model="editForm.checksText" type="textarea" :rows="5" />
        </el-form-item>
        <el-form-item label="业务关注点（逗号或顿号分隔）">
          <el-input v-model="editForm.keywordsText" placeholder="如：待机动画, 预览动画" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingTp" @click="saveEdit">保存</el-button>
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
  createDefectReview,
  deleteDefectReview,
  editDefectReviewTestpoint,
  getDefectReview,
  getDefectReviews,
  getDefectReviewUsage,
  getZentaoConfigs,
  getZentaoDbProducts,
  pingZentaoDb,
  previewDefectReviewPrompt,
  selectDefectReviewTestpoints,
} from '@/api/zentao'

const configs = ref([])
const projects = ref([])
const reports = ref([])
const loadingReports = ref(false)
const creating = ref(false)

const dbProducts = ref([])
const dbPinging = ref(false)
const dbInfo = ref(null)
const dbError = ref('')

// 有历史缺陷的产品排前面（同数量按 ID 升序）：禅道里有 41 个产品，
// 但真正有缺陷的只有十来个，平铺列表会让用户翻很久。
const sortedDbProducts = computed(() =>
  [...dbProducts.value].sort(
    (a, b) => (b.bug_count || 0) - (a.bug_count || 0) || Number(a.id) - Number(b.id),
  ),
)

function productCountText(p) {
  const n = p.bug_count
  if (n === undefined || n === null) return ''
  return n > 0 ? `${n} 条缺陷` : '无有效缺陷'
}

function productOptionLabel(p) {
  return `${p.id} - ${p.name}`
}

// 已选产品中「确定没有有效缺陷」的那些，用于在表单里直接给出提示，
// 避免用户等到复盘跑完才发现是空报告。
const pickedEmptyProducts = computed(() => {
  const picked = form.value.product_ids || []
  const out = []
  picked.forEach((id) => {
    const hit = dbProducts.value.find((p) => Number(p.id) === Number(id))
    if (hit && hit.bug_count === 0) out.push(`${hit.id} - ${hit.name}`)
  })
  return out
})

const form = ref({
  config: null,
  product_ids: [],
  project: null,
  dateFrom: '',
  dateTo: '',
  exclude_ui_types: true,
})

const drawer = ref(false)
const report = ref(null)
const loadingDetail = ref(false)
const domainFilter = ref([])
const keywordFilter = ref('')
const promptBlock = ref('')
// 使用记录：这份报告被哪些生成任务用过、各命中哪几条（反向审计）
const usageData = ref(null)
const usageLoading = ref(false)

async function loadUsageFor(reportId) {
  if (!reportId) return
  usageLoading.value = true
  try {
    const res = await getDefectReviewUsage(reportId)
    usageData.value = res.data
  } catch (e) {
    // 报告可能还没有任何使用记录，或接口不可用；不要打断主视图
    usageData.value = null
  } finally {
    usageLoading.value = false
  }
}

function loadUsage() {
  return loadUsageFor(report.value && report.value.id)
}
// 严格模式相关性闸门：需求与历史缺陷体系无关时后端不注入，前端要给出可见原因
const previewBlocked = ref(false)
const previewMeta = ref({})

// 报告页预览不带需求文本（需求属于生成任务，不属于复盘报告）。
// 后端在无需求时按「报告视角」返回全量测试点，reason 以「未提供需求文本」开头。
const previewReportScope = computed(
  () => (previewMeta.value.relevance?.reason || '').indexOf('未提供需求文本') >= 0,
)

const previewBlockedTitle = computed(
  () => '本次需求与历史缺陷体系无明显关联，严格模式下不会注入历史测试点',
)
// 弱相关：只命中变更意图但没命中功能域 → 注入量会大幅收缩，需提示用户
const previewWeak = computed(
  () => !previewBlocked.value
    && previewMeta.value.relevance?.relevant === true
    && !(previewMeta.value.relevance?.matched_domains || []).length,
)
// 注入预算控制：默认「标准」+ 20 条，实测约 1600 tokens
const previewLevel = ref('standard')
// 用户是否手动切过档位：没切过就让后端按改动规模自动判断，保证与真实注入一致
const previewLevelTouched = ref(false)
const previewMaxPoints = ref(20)
const previewDomains = ref([])

// token 档位着色：>6000 提示可能过长
const tokenTagType = computed(() => {
  const t = previewMeta.value.estimated_tokens || 0
  if (t > 6000) return 'danger'
  if (t > 3000) return 'warning'
  return 'success'
})

const editDialog = ref(false)
const editForm = ref(null)
const savingTp = ref(false)

const currentConfig = computed(() => configs.value.find((c) => c.id === form.value.config) || null)

// 起止都是独立字段，只校验「开始晚于结束」这一种非法情况
const dateRangeInvalid = computed(() => {
  const { dateFrom, dateTo } = form.value
  return !!(dateFrom && dateTo && dateFrom > dateTo)
})

// 未来日期没有缺陷可查，直接禁选
function disabledFuture(d) {
  return d.getTime() > Date.now()
}

const canCreate = computed(
  () =>
    !!form.value.config &&
    !!currentConfig.value?.db_ready &&
    (form.value.product_ids || []).length > 0
)

const stats = computed(() => report.value?.stats_json || {})
const testpoints = computed(() => report.value?.testpoints_json || [])
const selectedCount = computed(() => testpoints.value.filter((t) => t.selected).length)
const allSelected = computed(
  () => testpoints.value.length > 0 && selectedCount.value === testpoints.value.length
)
const domainOptions = computed(() =>
  [...new Set(testpoints.value.map((t) => t.domain).filter(Boolean))]
)
const filteredTestpoints = computed(() => {
  const kw = keywordFilter.value.trim().toLowerCase()
  return testpoints.value.filter((t) => {
    if (domainFilter.value.length && !domainFilter.value.includes(t.domain)) return false
    if (!kw) return true
    const hay = [t.title, t.description, ...(t.keywords || []), ...(t.checks || [])]
      .join(' ')
      .toLowerCase()
    return hay.includes(kw)
  })
})

async function loadConfigs() {
  try {
    const res = await getZentaoConfigs()
    configs.value = res.data.results || res.data || []
  } catch (e) {
    // 配置加载失败不阻塞页面
  }
}

async function loadProjects() {
  const res = await api.get('/projects/all/')
  projects.value = res.data || []
}

async function loadReports() {
  loadingReports.value = true
  try {
    const res = await getDefectReviews()
    reports.value = res.data.results || res.data || []
    // running 中的报告自动刷新
    if (reports.value.some((r) => r.status === 'running')) {
      setTimeout(loadReports, 4000)
    }
  } finally {
    loadingReports.value = false
  }
}

async function handleConfigChange(id) {
  dbProducts.value = []
  dbInfo.value = null
  dbError.value = ''
  promptBlock.value = ''
  const cfg = configs.value.find((c) => c.id === id)
  if (!cfg) return
  if (!form.value.project && cfg.project) form.value.project = cfg.project
  if (cfg.db_ready) {
    await loadDbProducts(id)
  }
}

async function testDb() {
  if (!form.value.config) return
  dbPinging.value = true
  dbError.value = ''
  try {
    const res = await pingZentaoDb(form.value.config)
    dbInfo.value = res.data
    ElMessage.success('禅道数据库连接正常')
    await loadDbProducts(form.value.config)
  } catch (e) {
    const d = e.response?.data || {}
    // 后端区分了 auth / timeout / host_not_allowed / schema 等原因，原样展示
    dbError.value = d.error || '连接失败'
    ElMessage.error(dbError.value)
  } finally {
    dbPinging.value = false
  }
}

async function loadDbProducts(configId) {
  try {
    const res = await getZentaoDbProducts(configId)
    dbProducts.value = res.data.products || []
    const cfg = configs.value.find((c) => c.id === configId)
    // 默认预选配置里已绑定的产品，减少一次手选。
    // 但只在「该产品确实有历史缺陷」时才预选：这个 product_id 是覆盖率线维护的，
    // 可能指向一个从未录入缺陷的产品，预选它只会得到一份空报告
    // （2026-10-23 生产实测：配置指向的 product 52 缺陷数为 0）。
    if (cfg?.product_id && !form.value.product_ids.length) {
      const hit = dbProducts.value.find((p) => String(p.id) === String(cfg.product_id))
      if (hit && (hit.bug_count === undefined || hit.bug_count > 0)) {
        form.value.product_ids = [Number(hit.id)]
      }
    }
  } catch (e) {
    dbProducts.value = []
  }
}

function openCreate() {
  drawer.value = false
  promptBlock.value = ''
  form.value = {
    config: null,
    product_ids: [],
    project: null,
    dateFrom: '',
    dateTo: '',
    exclude_ui_types: true,
  }
  dbProducts.value = []
  dbInfo.value = null
  dbError.value = ''
  ElMessage.info('请在左侧选择禅道配置后开始复盘')
}

async function submitCreate() {
  if (!canCreate.value) return
  creating.value = true
  try {
    const payload = {
      config: form.value.config,
      project: form.value.project,
      product_ids: form.value.product_ids,
      exclude_ui_types: form.value.exclude_ui_types,
    }
    // 起止是两个独立字段，各自独立提交；只填一边也是有效筛选（单边不限）
    if (dateRangeInvalid.value) {
      ElMessage.warning('开始日期不能晚于结束日期')
      return
    }
    if (form.value.dateFrom) payload.date_from = form.value.dateFrom
    if (form.value.dateTo) payload.date_to = form.value.dateTo
    const res = await createDefectReview(payload)
    ElMessage.success(res.data.message || '复盘已启动')
    await loadReports()
    if (res.data.report_id) {
      // 立刻打开详情，让用户看到 running 状态
      const detail = await getDefectReviews({})
      const row = (detail.data.results || detail.data || []).find((r) => r.id === res.data.report_id)
      if (row) openReport(row)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '启动复盘失败')
  } finally {
    creating.value = false
  }
}

async function openReport(row) {
  drawer.value = true
  loadingDetail.value = true
  promptBlock.value = ''
  domainFilter.value = []
  keywordFilter.value = ''
  usageData.value = null
  // 使用记录与报告详情并行加载，互不阻塞（usage 失败不影响主视图）
  loadUsageFor(row.id)
  try {
    const res = await getDefectReview(row.id)
    report.value = res.data
    // 若仍在分析中，稍后自动刷新一次状态
    if (res.data.status === 'running') {
      setTimeout(async () => {
        const again = await getDefectReview(row.id)
        report.value = again.data
        if (again.data.status !== 'running') await loadReports()
      }, 5000)
    }
  } catch (e) {
    ElMessage.error('加载报告失败')
  } finally {
    loadingDetail.value = false
  }
}

async function removeReport(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name || '复盘 #' + row.id}」吗？已提炼的测试点会一并删除。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch (e) {
    return
  }
  try {
    await deleteDefectReview(row.id)
    ElMessage.success('已删除')
    if (report.value?.id === row.id) drawer.value = false
    await loadReports()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
}

async function toggleOne(row, checked) {
  try {
    await selectDefectReviewTestpoints(report.value.id, {
      tp_ids: [row.tp_id],
      selected: !!checked,
    })
    row.selected = !!checked
  } catch (e) {
    ElMessage.error('更新选择状态失败')
  }
}

async function toggleSelectAll() {
  const target = !allSelected.value
  const ids = testpoints.value.map((t) => t.tp_id)
  try {
    await selectDefectReviewTestpoints(report.value.id, { tp_ids: ids, selected: target })
    testpoints.value.forEach((t) => {
      t.selected = target
    })
  } catch (e) {
    ElMessage.error('更新选择状态失败')
  }
}

async function openPromptPreview() {
  previewDomains.value = []
  previewBlocked.value = false
  // 每次打开预览都重新回到"自动判断档位"，与真实注入保持一致
  previewLevelTouched.value = false
  previewLevel.value = 'standard'
  await fetchPreview()
  if (previewBlocked.value) {
    ElMessage.warning(previewBlockedTitle.value)
    return
  }
  if (!previewMeta.value.selected_count) {
    ElMessage.info('未勾选测试点，默认按缺陷数取前 N 条；建议先勾选相关测试点')
  }
}

// 切换档位/条数时重新预览（保持已选的域筛选）
async function refreshPreview() {
  if (!promptBlock.value && !previewBlocked.value) return
  await fetchPreview(previewDomains.value)
}

// 用户主动切档：此后预览就按用户选的档位，不再跟随自动判断
async function onLevelChange() {
  previewLevelTouched.value = true
  await refreshPreview()
}

async function fetchPreview(domains) {
  if (!report.value) return
  try {
    // 刻意不传 requirement_text：报告页预览展示的是「这份报告自带什么」，
    // 真正的相关性过滤由生成任务用自己的 requirement_text 完成。
    const payload = {
      report_id: report.value.id,
      max_points: previewMaxPoints.value,
    }
    // 首次预览不传档位，让后端按改动规模自动选（与真实注入完全一致）；
    // 用户在 radio 上主动切换后才显式传值。
    if (previewLevelTouched.value) payload.detail_level = previewLevel.value
    if (domains && domains.length) payload.domains = domains
    const res = await previewDefectReviewPrompt(payload)
    previewBlocked.value = res.data.relevance && res.data.relevance.relevant === false
    promptBlock.value = res.data.prompt_block || ''
    previewMeta.value = res.data
    // 后端可能按改动规模自动降档（小改动→精简），前端要把实际档位同步到 radio，
    // 否则会出现"界面显示标准、内容却是精简"的错位
    if (res.data.detail_level && res.data.detail_level !== previewLevel.value) {
      previewLevel.value = res.data.detail_level
    }
    if (Array.isArray(res.data.domains) && res.data.domains.length) {
      previewDomains.value = res.data.domains
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '预览失败')
  }
}

function openEdit(row) {
  editForm.value = {
    tp_id: row.tp_id,
    title: row.title,
    description: row.description,
    checksText: (row.checks || []).join('\n'),
    keywordsText: (row.keywords || []).join('、'),
  }
  editDialog.value = true
}

async function saveEdit() {
  if (!editForm.value) return
  savingTp.value = true
  try {
    const res = await editDefectReviewTestpoint(report.value.id, {
      tp_id: editForm.value.tp_id,
      title: editForm.value.title,
      description: editForm.value.description,
      checks: editForm.value.checksText.split('\n').map((s) => s.trim()).filter(Boolean),
      keywords: editForm.value.keywordsText
        .split(/[,，、]/)
        .map((s) => s.trim())
        .filter(Boolean),
    })
    const saved = res.data.testpoint
    const idx = testpoints.value.findIndex((t) => t.tp_id === saved.tp_id)
    if (idx >= 0) Object.assign(testpoints.value[idx], saved)
    editDialog.value = false
    promptBlock.value = ''
    ElMessage.success('测试点已保存')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '保存失败')
  } finally {
    savingTp.value = false
  }
}

function statusText(s) {
  return { running: '分析中', success: '完成', failed: '失败' }[s] || s
}

function statusType(s) {
  return { running: 'warning', success: 'success', failed: 'danger' }[s] || 'info'
}

function formatTime(v) {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'
}

onMounted(() => {
  loadConfigs()
  loadProjects()
  loadReports()
})
</script>

<style scoped>
.page-container {
  padding: 16px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.page-sub {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.card-header {
  display: flex;
  align-items: center;
  font-weight: 600;
}
.form-tip {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}
.db-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.db-info {
  color: #67c23a;
}
.db-error {
  color: #f56c6c;
}
.db-warn {
  color: #e6a23c;
}
.scope-tip {
  margin-bottom: 10px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
  background: #f4f8ff;
  border-left: 3px solid #409eff;
  border-radius: 2px;
}
.usage-detail {
  padding: 8px 16px 12px 48px;
}
.usage-reason {
  margin-bottom: 6px;
  font-size: 13px;
  color: #303133;
}
.opt-name {
  float: left;
}
.opt-count {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: #67c23a;
}
.opt-count.is-empty {
  color: #c0c4cc;
}
.bug-meta {
  color: #909399;
  font-size: 12px;
  margin-top: 2px;
}
.block {
  margin-top: 12px;
}
.sub-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.funnel {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 14px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  font-size: 12px;
  color: #606266;
}
.funnel-step b {
  color: #303133;
  font-size: 14px;
  margin-left: 2px;
}
.funnel-arrow {
  color: #c0c4cc;
  margin: 0 2px;
}
.funnel-final b {
  color: #67c23a;
}
.filter-row {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.tp-title {
  font-weight: 600;
  color: #303133;
  line-height: 1.4;
}
.tp-kw {
  margin-top: 4px;
}
.kw-tag {
  margin-right: 4px;
  margin-bottom: 2px;
}
.tp-desc {
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
}
.tp-example {
  font-size: 12px;
  color: #a8abb2;
  margin-top: 4px;
  line-height: 1.4;
}
.check-item {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}
.prompt-block {
  margin: 0;
  padding: 12px 14px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.7;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 420px;
  overflow: auto;
}
.preview-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.toolbar-label {
  font-size: 12px;
  color: #606266;
}
</style>
