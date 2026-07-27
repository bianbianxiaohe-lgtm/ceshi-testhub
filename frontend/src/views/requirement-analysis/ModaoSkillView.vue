<template>
  <div class="modao-skill">
    <div class="page-header">
      <h2>🧩 墨刀需求读取与用例生成</h2>
      <p class="subtitle">5 阶段引导式工作流：原型读取 → 需求通读 → 需求澄清 → 用例设计 → 冒烟执行</p>
      <div class="header-actions">
        <el-button size="small" @click="loadHistory" :loading="loadingHistory">刷新历史</el-button>
        <el-button size="small" type="primary" plain @click="onNew">+ 新建流程</el-button>
      </div>
    </div>

    <!-- 历史记录 -->
    <el-card class="history-card" shadow="never">
      <template #header>
        <span><b>📋 历史流程</b>（点击「继续」可恢复上次进度）</span>
      </template>
      <div v-if="history.length === 0 && !loadingHistory" class="empty-hint">
        暂无历史记录，先在下方「阶段0·原型接入」创建一次吧。
      </div>
      <el-table v-else :data="history" size="small" stripe style="width: 100%" row-key="id"
        :expand-row-keys="expandedRows" @row-click="toggleExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-detail">
              <!-- 工作日志 -->
              <div v-if="row.work_log" class="log-section">
                <h4>工作日志</h4>
                <pre class="log-box">{{ row.work_log }}</pre>
              </div>
              <!-- 错误信息 -->
              <div v-if="row.error_message" class="log-section error-section">
                <h4>错误信息</h4>
                <pre class="log-box error-box">{{ row.error_message }}</pre>
              </div>
              <!-- 无日志提示 -->
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
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="onContinue(row)">继续</el-button>
            <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-steps :active="step" align-center finish-status="success" class="steps">
      <el-step title="原型接入" description="墨刀逐页读取" />
      <el-step title="需求通读" description="结构化摘要" />
      <el-step title="需求澄清" description="识别模糊/缺失/边界" />
      <el-step title="用例设计" description="测试点/风险/PCI/合并/用例" />
      <el-step title="冒烟执行" description="执行决策" />
    </el-steps>

    <!-- 阶段0：原型接入 -->
    <el-card v-if="step === 0" class="stage-card">
      <template #header><b>阶段0 · 原型接入</b></template>
      <el-form :model="form" label-width="110px">
        <el-form-item label="需求来源">
          <el-radio-group v-model="form.source_type">
            <el-radio value="modao">墨刀原型链接</el-radio>
            <el-radio value="webshare">webshare 页面树链接</el-radio>
            <el-radio value="text">需求文本/文档</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.source_type === 'modao'" label="需求地址">
          <el-input v-model="form.url" type="textarea" :rows="4"
            placeholder="每行一个墨刀原型链接。例如：&#10;https://modao.cc/proto/xxxx/sharing?view_mode=read_only&#10;（若是 webshare/原型页面树地址，请选择上方「webshare 页面树链接」并粘贴到对应框；系统也会自动识别）" />
          <div class="form-hint">💡 每个页面地址一行。多个地址会逐个抓取并合并；若只填<strong>一个目录地址</strong>，将尝试自动发现该目录下的所有页面（依赖原型页面的页面树结构）。</div>
        </el-form-item>
        <el-form-item v-if="form.source_type === 'webshare'" label="webshare 页面树链接">
          <el-input v-model="form.webshare_url" type="textarea" :rows="4"
            placeholder="每行一个 webshare 目录/页面树地址，系统将自动枚举该目录下的所有页面。例如：&#10;http://192.168.1.80/webshare/WNLProducts/01%20需求原型/50%20其他/AI搜索解答/" />
          <div class="form-hint">💡 webshare 为 hash 路由原型：填写目录地址后，系统自动识别左侧页面树并逐个读取所有子页面（best-effort）。若页面树未被识别，可改为把每个页面地址一行粘贴（同样支持）。</div>
        </el-form-item>
        <el-form-item v-if="form.source_type === 'modao'" label="登录Cookie">
          <el-input v-model="form.cookies" type="textarea" :rows="3"
            placeholder="可选：粘贴导出的 cookie JSON 以绕过登录墙（首次可用可见浏览器扫码导出）" />
        </el-form-item>
        <el-form-item v-if="form.source_type === 'text'" label="需求文本">
          <el-input v-model="form.requirement_text" type="textarea" :rows="8"
            placeholder="直接粘贴需求正文" />
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="任务标题" />
        </el-form-item>
        <el-form-item label="归属项目">
          <div style="display:flex;gap:8px;align-items:center;width:100%">
            <el-select v-model="form.project" placeholder="选择项目（用于同步功能模块）" filterable
              style="flex:1" :loading="loadingProjects" @change="onProjectChange">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-button size="small" type="primary" plain title="快速新建项目"
              @click="showQuickProject = true">+ 新建项目</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="form.project" label="关联版本">
          <div style="display:flex;gap:8px;align-items:center;width:100%">
            <el-select v-model="form.version" placeholder="选择版本（可选）" filterable style="flex:1">
              <el-option v-for="v in versions" :key="v.id" :label="v.name" :value="v.id" />
            </el-select>
            <el-button size="small" type="primary" plain title="快速新建版本"
              @click="showQuickVersion = true">+ 新建版本</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="form.source_type !== 'text'" label="双路融合">
          <el-switch v-model="form.dual_fusion" />
          <div class="form-hint">默认开启。DOM 与视觉分别逐页提取，再由 AI 分批交叉融合；任一路覆盖不足会阻断后续分析，避免生成不完整用例。</div>
        </el-form-item>
      </el-form>
      <el-alert v-if="proto && proto.status === 'failed'" type="error" :title="'执行失败'"
        :description="proto.error_message" show-icon />
      <el-button type="primary" :loading="busy" @click="onCreate">{{ form.source_type === 'modao' ? '开始读取墨刀' : form.source_type === 'webshare' ? '开始读取 webshare 页面树' : '保存需求文本' }}</el-button>
      <el-button v-if="proto && proto.status === 'extracting'" :loading="true">读取中…</el-button>
      <el-button v-if="proto && proto.status === 'extracted' && proto.current_stage >= 0"
        type="success" @click="goStep(1)">✅ 已读取，进入阶段1</el-button>
    </el-card>

    <!-- 阶段1：需求通读 -->
    <el-card v-if="step === 1" class="stage-card">
      <template #header><b>阶段1 · 需求通读</b></template>
      <el-button type="primary" :loading="busy" @click="onStruct">运行需求结构化</el-button>
      <el-alert v-if="proto && proto.status === 'structuring'" type="info" title="结构化中…" />
      <el-alert v-if="proto && proto.status === 'failed'" type="error" :title="'执行失败'" :description="proto.error_message" show-icon />
      <div v-if="proto && proto.requirement_summary" class="artifact">
        <div class="artifact-head">
          <h4>需求摘要</h4>
          <el-button size="small" plain @click="beginEdit('requirement_summary')"
            :disabled="editingField && editingField !== 'requirement_summary'">✏️ 编辑</el-button>
        </div>
        <pre v-if="editingField !== 'requirement_summary'" class="md-box">{{ proto.requirement_summary }}</pre>
        <template v-else>
          <el-input v-model="editBuffer" type="textarea" :rows="12" />
          <div class="edit-actions">
            <el-button size="small" type="primary" @click="saveEdit">保存修改</el-button>
            <el-button size="small" @click="cancelEdit">取消</el-button>
          </div>
        </template>
        <modao-qa :proto-id="protoId" :stage="1" :qa-log="qaLogFor(1)" />
      </div>
      <el-alert v-if="proto && proto.feature_module_info" type="success" :closable="false"
        :title="`已同步功能模块：${proto.feature_module_info.name}`" show-icon />
      <el-button v-if="proto && proto.requirement_summary" type="success" @click="onConfirm(1)">确认摘要，进入阶段2</el-button>
    </el-card>

    <!-- 阶段2：需求澄清 -->
    <el-card v-if="step === 2" class="stage-card">
      <template #header><b>阶段2 · 需求澄清</b></template>
      <el-button type="primary" :loading="busy" @click="onClarify">识别澄清问题</el-button>
      <el-alert v-if="proto && proto.status === 'clarifying'" type="info" title="澄清分析中…" />
      <el-alert v-if="proto && proto.status === 'failed'" type="error" :title="'执行失败'" :description="proto.error_message" show-icon />
      <div v-if="proto && proto.clarification_log" class="artifact">
        <div class="artifact-head">
          <h4>澄清清单</h4>
          <el-button size="small" plain @click="toggleRawEdit"
            :disabled="editingField && editingField !== 'clarification_log'">
            {{ editingField === 'clarification_log' ? '✏️ 编辑逐条' : '✏️ 编辑原文' }}
          </el-button>
        </div>

        <!-- 逐条填写模式 -->
        <template v-if="clarifyParsed && editingField !== 'clarification_log'">
          <div v-for="(item, i) in clarifyItems" :key="i" class="clarify-item">
            <div class="clarify-item-head">
              <el-tag size="mini" :type="typeTag(item.type)">{{ item.type || '问题' }}</el-tag>
              <el-tag v-if="item.priority" size="mini" type="warning">{{ item.priority }}</el-tag>
              <span v-if="item.location" class="clarify-loc">📍 {{ item.location }}</span>
            </div>
            <div class="clarify-issue">{{ item.issue }}</div>
            <div v-if="item.suggested_question" class="clarify-suggest">
              <b>建议提问：</b>{{ item.suggested_question }}
            </div>
            <div v-if="item.impact" class="clarify-impact">影响范围：{{ item.impact }}</div>
            <el-input v-model="clarifyReplies[i]" type="textarea" :rows="2" class="mt"
              :placeholder="item.resolution ? '' : '填写与产品确认后的回复/结论…'" />
          </div>
          <el-button size="small" type="primary" class="mt" :disabled="!clarifyItems.length"
            @click="saveClarifyReplies">💾 保存全部回复</el-button>
        </template>

        <!-- 原文/未解析模式 -->
        <template v-else>
          <pre v-if="editingField !== 'clarification_log'" class="md-box">{{ proto.clarification_log }}</pre>
          <template v-else>
            <el-input v-model="editBuffer" type="textarea" :rows="12" />
            <div class="edit-actions">
              <el-button size="small" type="primary" @click="saveEdit">保存修改</el-button>
              <el-button size="small" @click="cancelEdit">取消</el-button>
            </div>
          </template>
        </template>
        <modao-qa :proto-id="protoId" :stage="2" :qa-log="qaLogFor(2)" />
      </div>
      <el-alert v-if="clarificationUnresolvedCount > 0" type="warning" :closable="false" show-icon
        :title="`还有 ${clarificationUnresolvedCount} 条位置/需求问题未填写人工结论，不能进入最终用例生成流程`" />
      <el-button v-if="proto && proto.clarification_log" type="success"
        :disabled="clarificationUnresolvedCount > 0" @click="onConfirm(2)">已与产品确认，进入阶段3</el-button>
    </el-card>

    <!-- 阶段3：用例设计 -->
    <el-card v-if="step === 3" class="stage-card">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
          <b>阶段3 · 用例设计（含风险/PCI/三路合并/质量自检）</b>
          <el-button size="small" type="primary" plain @click="openEditDialog()">✏️ 编辑产物</el-button>
        </div>
      </template>
      <div class="stage3-actions">
        <el-button type="primary" :loading="busy" @click="onDesign">① 运行测试点合并</el-button>
        <el-button v-if="proto && (proto.status === 'testpoints_ready' || proto.status === 'done') && proto.final_testpoints_json"
          type="success" :loading="busy" @click="onGenerateCases">② 确认测试点，生成测试用例</el-button>
      </div>
      <el-alert v-if="proto && proto.status === 'designing'" type="info" :closable="false" show-icon
        title="AI 处理中（测试点合并 或 用例生成）…请稍候" />
      <el-alert v-if="proto && proto.status === 'testpoints_ready'" type="warning" :closable="false" show-icon
        title="第一段完成：测试点已合并。请在下方「合并测试点」中查看/编辑确认后，点击「② 确认测试点，生成测试用例」" />
      <el-alert v-if="proto && proto.final_testpoints_json && generationGateReasons.length" type="warning"
        :closable="false" show-icon title="最终测试用例尚未获准生成"
        :description="generationGateReasons.join('；')" />
      <el-alert v-if="proto && proto.status === 'failed'" type="error" :title="'执行失败'" :description="proto.error_message" show-icon />

      <!-- 产物筛选标签页 -->
      <div v-if="hasAnyArtifact" class="stage3-filter-bar">
        <el-radio-group v-model="stage3ActiveTab" size="small" class="stage3-tabs">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button v-if="proto && proto.module_split" value="module_split">模块拆分</el-radio-button>
          <el-radio-button v-if="proto && proto.risks_json" value="risks_json">风险识别</el-radio-button>
          <el-radio-button v-if="proto && proto.pci_json" value="pci_json">待确认问题 PCI</el-radio-button>
          <el-radio-button v-if="proto && proto.final_testpoints_json" value="final_testpoints_json">合并测试点</el-radio-button>
          <el-radio-button v-if="proto && proto.testcases_json" value="testcases_json">测试用例</el-radio-button>
          <el-radio-button v-if="proto && proto.smoke_json" value="smoke_json">冒烟用例</el-radio-button>
          <el-radio-button v-if="proto && proto.quality_report_json" value="quality_report_json">质量报告</el-radio-button>
        </el-radio-group>
      </div>

      <div v-if="(stage3ActiveTab === 'all' || stage3ActiveTab === 'module_split') && proto && proto.module_split" class="artifact">
        <div class="artifact-head-row">
          <h4>模块拆分</h4>
          <el-button size="mini" type="text" @click="openEditDialog('module_split')">✏️ 编辑</el-button>
        </div>
        <pre class="md-box">{{ proto.module_split }}</pre>
      </div>
      <div v-if="(stage3ActiveTab === 'all' || stage3ActiveTab === 'risks_json') && proto && proto.risks_json" class="artifact">
        <div class="artifact-head-row">
          <h4>风险识别 (R1~R5) <el-tag size="mini" type="info">{{ mainPageParsedRisks.length }} 条</el-tag></h4>
          <el-button size="mini" type="text" @click="openEditDialog('risks_json')">✏️ 编辑</el-button>
        </div>
        <!-- 结构化卡片 -->
        <div v-if="mainPageParsedRisks.length" class="main-page-risk-list">
          <div v-for="(risk, i) in mainPageParsedRisks" :key="'mr'+i" class="main-page-risk-card">
            <div class="main-page-card-head">
              <el-tag v-if="risk._module" size="mini" type="success" effect="plain">{{ risk._module }}</el-tag>
              <span class="generic-card-index">{{ risk.id || ('R' + (i+1)) }}</span>
              <el-tag size="mini" :type="priTag(risk.impact)">{{ risk.impact || '-' }}</el-tag>
              <el-tag v-if="risk.category" size="mini" type="info">{{ risk.category }}</el-tag>
            </div>
            <div class="main-page-card-desc">{{ risk.description || '' }}</div>
            <div v-if="risk.related_testpoints && risk.related_testpoints.length" class="main-page-card-extra">
              <b>关联测试点：</b>{{ risk.related_testpoints.join(', ') }}
            </div>
            <div v-if="riskAnswer(risk)" class="pci-sub-a-wrap risk-mitigation-wrap">
              <label class="pci-sub-a-label">已确认处置：</label>
              <div class="pci-sub-a-text">{{ riskAnswer(risk) }}</div>
            </div>
          </div>
        </div>
        <pre v-else class="json-box">{{ pretty(proto.risks_json) }}</pre>
      </div>
      <div v-if="(stage3ActiveTab === 'all' || stage3ActiveTab === 'pci_json') && proto && proto.pci_json" class="artifact">
        <div class="artifact-head-row">
          <h4>待确认问题 PCI (Q1~Q5) <el-tag size="mini" type="warning">{{ mainPageFlatPci.length }} 个子问题</el-tag></h4>
          <el-button size="mini" type="text" @click="openEditDialog('pci_json')">✏️ 编辑</el-button>
        </div>
        <!-- 结构化卡片：每个子问题一张卡 -->
        <div v-if="mainPageFlatPci.length" class="main-page-pci-list">
          <div v-for="(item, idx) in mainPageFlatPci" :key="'mp'+item.pciIndex+'_'+item.subIndex"
               class="main-page-pci-card">
            <div class="main-page-card-head">
              <el-tag v-if="item.pci._module" size="mini" type="success" effect="plain">{{ item.pci._module }}</el-tag>
              <span class="generic-card-index">{{ item.pci.id || ('#' + (item.pciIndex+1)) }}</span>
              <el-tag size="mini" :type="priTag(item.pci.impact)">{{ item.pci.impact || '-' }}</el-tag>
              <el-tag size="mini" :type="item.pci.type === 'Q2' ? 'danger' : 'warning'">{{ item.pci.type || 'Q' }}</el-tag>
              <span class="pci-sub-qbadge">Q{{ item.subIndex + 1 }}</span>
            </div>
            <div v-if="item.pci.blocked_scenarios && item.pci.blocked_scenarios.length" class="main-page-card-extra">
              <b>🚫 阻塞场景：</b>
              <el-tag v-for="(bs, bi) in item.pci.blocked_scenarios" :key="bi" size="mini" class="ml-xs">{{ bs }}</el-tag>
            </div>
            <div class="pci-sub-q"><span class="pci-q-badge">问</span>{{ item.question }}</div>
            <div v-if="item.answer" class="pci-sub-a-wrap">
              <label class="pci-sub-a-label">A：</label>
              <div class="pci-sub-a-text">{{ item.answer }}</div>
            </div>
          </div>
        </div>
        <pre v-else class="json-box">{{ pretty(proto.pci_json) }}</pre>
      </div>
      <div v-if="(stage3ActiveTab === 'all' || stage3ActiveTab === 'final_testpoints_json') && proto && proto.final_testpoints_json" class="artifact">
        <div class="artifact-head-row">
          <h4>合并去重后测试点 <el-tag size="mini" type="info">{{ mainPageTestpoints.length }} 条</el-tag></h4>
          <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
            <el-button size="mini" type="text" @click="openEditDialog('final_testpoints_json')">✏️ 编辑</el-button>
            <el-button v-if="proto && proto.status !== 'designing'" size="mini" type="success"
              :loading="busy" @click="onGenerateCases">✅ 确认测试点，生成用例</el-button>
          </div>
        </div>
        <div v-if="mainPageTestpoints.length" class="main-page-tp-list">
          <div v-for="(tp, i) in mainPageTestpoints" :key="'mtp'+i" class="main-page-tp-card">
            <div class="main-page-card-head">
              <span class="generic-card-index">{{ i + 1 }}</span>
              <b v-if="tp.title">{{ tp.title }}</b>
            </div>
            <div class="main-page-card-desc">{{ tp.description || tp.issue || '' }}</div>
          </div>
        </div>
        <pre v-else class="json-box">{{ pretty(proto.final_testpoints_json) }}</pre>
      </div>
      <div v-if="(stage3ActiveTab === 'all' || stage3ActiveTab === 'testcases_json') && proto && proto.testcases_json" class="artifact">
        <div class="artifact-head-row">
          <h4>测试用例（{{ mainPageTestcases.total }} 条）</h4>
          <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
            <el-button size="mini" type="text" @click="openEditDialog('testcases_json')">✏️ 编辑</el-button>
            <el-button size="mini" type="success" :loading="adoptLoading"
              @click="adoptToLibrary(false)">📥 采纳到用例库</el-button>
          </div>
        </div>
        <div v-if="mainPageTestcases.groups.length" class="main-page-tc-wrap">
          <div v-for="(group, gi) in mainPageTestcases.groups" :key="'mtc'+gi" class="main-page-tc-group">
            <h5 class="main-page-tc-group-title">📦 {{ group.module }}（{{ group.items.length }} 条）</h5>
            <div v-for="(tc, ti) in group.items" :key="ti" class="main-page-tc-card">
              <div class="main-page-card-head">
                <span class="generic-card-index">{{ tc.id || ('#' + (ti+1)) }}</span>
                <b>{{ tc.title || ('用例 #' + (ti+1)) }}</b>
                <el-tag size="mini" :type="priTag(tc.priority)">{{ tc.priority || '-' }}</el-tag>
                <el-tag size="mini" :type="tc.type === 'UI' ? '' : 'warning'">{{ tc.type || '功能' }}</el-tag>
                <el-button v-if="!adoptedCaseMap['tc-'+gi+'-'+ti]" size="extra-mini" type="success" plain
                  @click.stop="adoptSingleCase(tc._rawIndex !== undefined ? tc._rawIndex : tc.index ?? ti, 'tc-'+gi+'-'+ti)">📥 采纳</el-button>
                <span v-else class="adopted-badge">✅ 已采纳</span>
              </div>
              <div v-if="tc.precondition || tc.preconditions" class="main-page-card-extra"><b>前置：</b>{{ tc.precondition || tc.preconditions }}</div>
              <ol v-if="Array.isArray(tc.steps) && tc.steps.length" class="main-page-tc-steps"><li v-for="(s, si) in tc.steps" :key="si">{{ s }}</li></ol>
              <div v-else-if="tc.steps" class="main-page-card-extra"><b>步骤：</b>{{ tc.steps }}</div>
              <div v-if="tc.expected" class="main-page-card-extra"><b>预期：</b><span class="tc-expected">{{ tc.expected }}</span></div>
            </div>
          </div>
        </div>
        <pre v-else class="json-box">{{ pretty(proto.testcases_json) }}</pre>
      </div>
      <div v-if="(stage3ActiveTab === 'all' || stage3ActiveTab === 'smoke_json') && proto && proto.smoke_json" class="artifact">
        <div class="artifact-head-row">
          <h4>冒烟用例（{{ mainPageSmoke.total }} 条）</h4>
          <el-button size="mini" type="text" @click="openEditDialog('smoke_json')">✏️ 编辑</el-button>
        </div>
        <div v-if="mainPageSmoke.groups.length" class="main-page-tc-wrap">
          <div v-for="(group, gi) in mainPageSmoke.groups" :key="'msm'+gi" class="main-page-tc-group">
            <h5 class="main-page-tc-group-title">📦 {{ group.module }}（{{ group.items.length }} 条）</h5>
            <div v-for="(tc, ti) in group.items" :key="ti" class="main-page-tc-card">
              <div class="main-page-card-head">
                <span class="generic-card-index">{{ tc.id || ('#' + (ti+1)) }}</span>
                <b>{{ tc.title || ('用例 #' + (ti+1)) }}</b>
                <el-tag size="mini" :type="priTag(tc.priority)">{{ tc.priority || '-' }}</el-tag>
                <el-tag size="mini" :type="tc.type === 'UI' ? '' : 'warning'">{{ tc.type || '功能' }}</el-tag>
                <el-tag v-if="tc.is_smoke" size="mini" type="success">冒烟</el-tag>
                <el-button v-if="!adoptedCaseMap['sm-'+gi+'-'+ti]" size="extra-mini" type="success" plain
                  @click.stop="adoptSingleCase(tc._rawIndex !== undefined ? tc._rawIndex : tc.index ?? ti, 'sm-'+gi+'-'+ti)">📥 采纳</el-button>
                <span v-else class="adopted-badge">✅ 已采纳</span>
              </div>
              <div v-if="tc.precondition || tc.preconditions" class="main-page-card-extra"><b>前置：</b>{{ tc.precondition || tc.preconditions }}</div>
              <ol v-if="Array.isArray(tc.steps) && tc.steps.length" class="main-page-tc-steps"><li v-for="(s, si) in tc.steps" :key="si">{{ s }}</li></ol>
              <div v-else-if="tc.steps" class="main-page-card-extra"><b>步骤：</b>{{ tc.steps }}</div>
              <div v-if="tc.expected" class="main-page-card-extra"><b>预期：</b><span class="tc-expected">{{ tc.expected }}</span></div>
            </div>
          </div>
        </div>
        <pre v-else class="json-box">{{ pretty(proto.smoke_json) }}</pre>
      </div>
      <div v-if="(stage3ActiveTab === 'all' || stage3ActiveTab === 'quality_report_json') && proto && proto.quality_report_json" class="artifact">
        <div class="artifact-head-row">
          <h4>质量自检报告</h4>
          <el-button size="mini" type="text" @click="openEditDialog('quality_report_json')">✏️ 编辑</el-button>
        </div>
        <div v-if="mainPageQuality" class="main-page-quality">
          <div v-for="(val, key) in mainPageQuality" :key="key" class="main-page-quality-row">
            <span class="main-page-quality-key">{{ qualityKeyLabel(key) }}</span>
            <span v-if="typeof val === 'object'" class="main-page-quality-val">
              <pre class="quality-json">{{ typeof val === 'string' ? val : JSON.stringify(val, null, 2) }}</pre>
            </span>
            <span v-else class="main-page-quality-val">{{ val }}</span>
          </div>
        </div>
        <pre v-else class="json-box">{{ pretty(proto.quality_report_json) }}</pre>
      </div>

      <div v-if="proto && proto.excel_path" class="artifact">
        <el-button type="warning" @click="onDownload">⬇️ 下载 Excel（按模块分 sheet）</el-button>
      </div>
      <modao-qa v-if="proto && proto.testcases_json" :proto-id="protoId" :stage="3" :qa-log="qaLogFor(3)" />
      <el-alert v-if="proto && proto.feature_module_info" type="info" :closable="false"
        title="确认后将自动把各子模块、测试点、用例同步到功能模块体系（阶段1 顶层模块的子模块）" show-icon />
      <el-alert v-else-if="proto && proto.status === 'done' && !proto.project" type="warning" :closable="false"
        title="未关联项目/版本，确认后不会同步功能模块（可在阶段0补充项目后重跑）" show-icon />
      <el-button v-if="proto && proto.status === 'done'" type="success" @click="onConfirm(3)">确认用例，进入阶段4</el-button>
      <el-divider v-if="proto && proto.testcases_json" content-position="left">一键采纳到用例库</el-divider>
      <div v-if="proto && proto.testcases_json" class="adopt-box">
        <el-alert type="info" :closable="false" show-icon
          :title="proto.project ? `将按「项目：${proto.project_name || proto.project}」自动创建功能模块并入库` : '请先在阶段0关联项目，否则无法入库'" />
        <div class="adopt-row">
          <el-checkbox v-model="adoptIncludeSmoke">同时采纳冒烟用例（自动标记「冒烟」标签）</el-checkbox>
          <el-button type="primary" :loading="adoptLoading"
            @click="adoptToLibrary(adoptIncludeSmoke)">📥 一键采纳全部用例到用例库</el-button>
        </div>
      </div>
    </el-card>

    <!-- 阶段3 产物编辑弹窗 -->
    <el-dialog title="编辑用例设计产物" v-model="editDialogVisible" width="900px" append-to-body top="3vh">
      <div class="edit-dlg-head">
        <span>选择产物：</span>
        <el-select v-model="editField" style="width: 200px">
          <el-option v-for="f in editFields" :key="f.value" :label="f.label" :value="f.value" />
        </el-select>
        <el-switch v-model="editRawMode" active-text="原文模式" inactive-text="结构化视图"
          style="margin-left:16px" />
      </div>

      <!-- 结构化视图 -->
      <div v-if="!editRawMode" class="structured-view">
        <!-- 测试用例：按模块分组卡片 -->
        <div v-if="(editField === 'testcases_json' || editField === 'smoke_json') && parsedTestcases.length">
          <div v-for="(group, gi) in parsedTestcases" :key="gi" class="tc-group">
            <h5 class="tc-group-title">📦 {{ group.module || '未分组' }}（{{ group.items.length }} 条）</h5>
            <div v-for="(tc, ti) in group.items" :key="ti" class="tc-card">
              <div class="tc-card-head">
                <span class="tc-id" v-if="tc.id">{{ tc.id }}</span>
                <b>{{ tc.title || ('用例 #' + (ti+1)) }}</b>
                <el-tag size="mini" :type="priTag(tc.priority)">{{ tc.priority || '-' }}</el-tag>
                <el-tag size="mini" :type="tc.type === 'UI' ? '' : 'warning'">{{ tc.type || '功能' }}</el-tag>
                <el-tag v-if="tc.is_smoke" size="mini" type="success">冒烟</el-tag>
              </div>
              <div class="tc-card-body">
                <div v-if="tc.precondition || tc.preconditions"><b>前置条件：</b>{{ tc.precondition || tc.preconditions }}</div>
                <ol v-if="Array.isArray(tc.steps) && tc.steps.length" class="tc-steps">
                  <li v-for="(s, si) in tc.steps" :key="si">{{ s }}</li>
                </ol>
                <div v-else-if="tc.steps"><b>步骤：</b>{{ tc.steps }}</div>
                <div v-if="tc.expected"><b>预期结果：</b><span class="tc-expected">{{ tc.expected }}</span></div>
                <div v-if="tc.requirement_ref" class="tc-ref"><b>需求引用：</b>{{ tc.requirement_ref }}</div>
                <div v-if="tc.notes" class="tc-notes"><b>备注：</b>{{ tc.notes }}</div>
              </div>
              <el-input v-model="group.items[ti]._raw" type="textarea" :rows="2"
                placeholder="查看/编辑原始 JSON…" class="mt" />
            </div>
          </div>
        </div>

        <!-- 合并测试点：卡片列表 -->
        <div v-else-if="editField === 'final_testpoints_json' && parsedTestpoints.length">
          <div v-for="(tp, i) in parsedTestpoints" :key="i" class="tp-card">
            <b>{{ tp.title || ('测试点 #' + (i+1)) }}</b>
            <p>{{ tp.description || tp.issue || '' }}</p>
            <el-input v-model="parsedTestpoints[i]._raw" type="textarea" :rows="2"
              placeholder="修改此条内容…" />
          </div>
        </div>

        <!-- 待确认问题 PCI：拆解为独立子问题卡片（一个问题一张卡，永远扁平） -->
        <div v-else-if="editField === 'pci_json' && flatPciItems.length" class="generic-json-list">
          <div v-for="(item, idx) in flatPciItems" :key="'sq' + item.pciIndex + '_' + item.subIndex"
               class="pci-card pci-sub-card" :class="{ 'pci-sub-confirmed': item.sub.confirmed }">
            <div class="pci-card-head">
              <el-tag v-if="item.pci._module" size="mini" type="success" effect="plain">{{ item.pci._module }}</el-tag>
              <span class="generic-card-index">{{ item.pci.id || ('#' + (item.pciIndex+1)) }}</span>
              <el-tag size="mini" :type="priTag(item.pci.impact)">{{ item.pci.impact || '-' }}</el-tag>
              <el-tag size="mini" :type="item.pci.type === 'Q2' ? 'danger' : 'warning'">{{ item.pci.type || 'Q' }}</el-tag>
              <span class="pci-sub-qbadge">Q{{ item.subIndex + 1 }}</span>
              <span v-if="item.pci.source" class="pci-source">{{ item.pci.source }}</span>
            </div>
            <div v-if="item.pci.blocked_scenarios && item.pci.blocked_scenarios.length" class="pci-blocked">
              <b>🚫 阻塞场景：</b>
              <span v-for="(bs, bi) in item.pci.blocked_scenarios" :key="bi" class="pci-bs-tag">{{ bs }}</span>
            </div>
            <div class="pci-sub-q">
              <span class="pci-q-badge">问</span>{{ item.sub.question }}
            </div>
            <div class="pci-sub-a-wrap">
              <label class="pci-sub-a-label">A：</label>
              <el-input v-model="item.sub.answer" type="textarea" :rows="3"
                placeholder="AI 解答草稿，可编辑修改..." />
            </div>
            <div class="pci-sub-foot">
              <el-checkbox v-model="item.sub.confirmed" size="small">已确认</el-checkbox>
              <el-button v-if="!item.sub.answer" size="mini" type="text" :loading="item.sub._loading"
                @click="askSingleSubQ(item.pciIndex, item.subIndex)">单独解答此题</el-button>
            </div>
          </div>

          <div class="mt" style="display:flex;gap:8px;align-items:center">
            <el-button size="small" type="primary" @click="savePciReplies">保存全部回复</el-button>
            <el-button size="small" type="success" :loading="allPciLoading" @click="splitAllPci">AI 全部解答</el-button>
            <el-button size="small" type="warning" plain @click="resetAllPciSplit">重置拆解</el-button>
            <span class="hint-text">共 {{ flatPciItems.length }} 个子问题（来自 {{ parsedPciItems.length }} 条 PCI）</span>
          </div>
        </div>

        <!-- 风险识别：展开 risk_points 每条为独立卡片 + 回复框 -->
        <div v-else-if="editField === 'risks_json' && parsedRiskItems.length" class="generic-json-list">
          <div v-for="(risk, i) in parsedRiskItems" :key="i" class="risk-card">
            <div class="risk-card-head">
              <el-tag v-if="risk._module" size="mini" type="success" effect="plain">{{ risk._module }}</el-tag>
              <span class="generic-card-index">{{ risk.id || ('R' + (i+1)) }}</span>
              <el-tag size="mini" :type="priTag(risk.impact)">{{ risk.impact || '-' }}</el-tag>
              <el-tag v-if="risk.category" size="mini" type="info">{{ risk.category }}</el-tag>
            </div>
            <div class="risk-card-desc">{{ risk.description || '' }}</div>
            <div v-if="risk.related_testpoints && risk.related_testpoints.length" class="risk-related">
              <b>关联测试点：</b>{{ risk.related_testpoints.join(', ') }}
            </div>
            <div class="pci-reply-section">
              <label class="pci-reply-label">✍️ 风险处置 / 缓解措施：</label>
              <el-input v-model="riskReplies[i]" type="textarea" :rows="2"
                placeholder="填写风险应对策略（如：接受/规避/转移/缓解）…" />
            </div>
            <el-input v-model="parsedRiskItems[i]._raw" type="textarea" :rows="2" class="mt"
              placeholder="修改此条原始 JSON…" />
          </div>
          <el-button size="small" type="primary" class="mt" @click="saveRiskReplies">💾 保存全部回复</el-button>
        </div>

        <!-- 其他产物：通用 JSON 数组卡片视图 -->
        <div v-else-if="parsedJsonArray.length" class="generic-json-list">
          <div v-for="(item, i) in parsedJsonArray" :key="i" class="generic-json-card">
            <div class="generic-card-head">
              <span class="generic-card-index">#{{ i + 1 }}</span>
              <span v-if="item.module" class="generic-card-module"><el-tag size="mini" type="info">{{ item.module }}</el-tag></span>
              <span v-if="item.title" class="generic-card-title">{{ item.title }}</span>
              <span v-else-if="item.id" class="generic-card-id">{{ item.id }}</span>
            </div>
            <div class="generic-card-body">
              <div v-for="(val, key) in displayFields(item)" :key="key" class="generic-field">
                <span class="generic-field-key">{{ fieldLabel(key) }}</span>
                <span class="generic-field-val">{{ formatFieldValue(val) }}</span>
              </div>
            </div>
            <el-input v-model="parsedJsonArray[i]._raw" type="textarea" :rows="3"
              class="mt" placeholder="修改此条 JSON…" />
          </div>
        </div>

        <div v-else class="empty-hint">当前产物为空或格式无法解析</div>
      </div>

      <!-- 原文模式 -->
      <div v-else class="raw-mode">
        <el-input v-model="editFieldValue" type="textarea" :rows="18" class="mono-font" />
      </div>

      <template #footer>
        <el-button @click="closeEditDialog">取消</el-button>
        <el-button size="small" type="warning" plain @click="revertEditField">放弃修改</el-button>
        <el-button type="primary" :disabled="!editFieldValue.trim()" @click="saveEditDialog">💾 保存修改</el-button>
      </template>
    </el-dialog>

    <!-- 阶段4：冒烟执行 -->
    <el-card v-if="step === 4" class="stage-card">
      <template #header><b>阶段4 · 冒烟执行决策</b></template>
      <p>请在 APP 端按冒烟用例清单逐项执行，记录 Pass / Fail / Block 后告知结果：</p>
      <el-radio-group v-model="smokeDecision">
        <el-radio value="passed">✅ 冒烟通过（进入全量测试）</el-radio>
        <el-radio value="rejected">❌ 冒烟失败（生成驳回邮件）</el-radio>
      </el-radio-group>
      <el-input v-if="smokeDecision === 'rejected'" v-model="rejectEmail" type="textarea" :rows="5"
        placeholder="驳回邮件正文（失败用例、环境、收件人等）" class="mt" />
      <div class="mt">
        <el-button type="primary" :disabled="!smokeDecision" @click="onSmoke">提交决策</el-button>
      </div>
      <el-alert v-if="proto && proto.stage4_decision" type="success"
        :title="'已记录决策：' + (proto.stage4_decision === 'passed' ? '冒烟通过' : '冒烟驳回')" show-icon />
    </el-card>

    <!-- 快速新建项目弹窗 -->
    <el-dialog v-model="showQuickProject" title="新建项目" width="480px" append-to-body>
      <el-form label-width="80px">
        <el-form-item label="项目名称">
          <el-input v-model="quickProjectName" placeholder="输入项目名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="quickProjectDesc" type="textarea" :rows="3" placeholder="可选：项目描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showQuickProject = false">取消</el-button>
        <el-button type="primary" :disabled="!quickProjectName.trim()" @click="createQuickProject">创建</el-button>
      </template>
    </el-dialog>

    <!-- 快速新建版本弹窗 -->
    <el-dialog v-model="showQuickVersion" title="新建版本" width="480px" append-to-body>
      <el-form label-width="80px">
        <el-form-item label="版本名称">
          <el-input v-model="quickVersionName" placeholder="输入版本号/名称，如 V1.0.0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showQuickVersion = false">取消</el-button>
        <el-button type="primary" :disabled="!quickVersionName.trim()" @click="createQuickVersion">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import request from '@/utils/api'
import ModaoQA from './ModaoQA.vue'

export default {
  name: 'ModaoSkillView',
  components: { ModaoQA },
  data() {
    return {
      step: 0,
      protoId: null,
      proto: null,
      busy: false,
      pollTimer: null,
      smokeDecision: '',
      rejectEmail: '',
      history: [],
      isAdmin: false,
      loadingHistory: false,
      expandedRows: [],
      // 编辑态
      editingField: null,
      editBuffer: '',
      // 阶段2 澄清清单逐条填写
      clarifyItems: [],
      clarifyReplies: [],
      clarifyParsed: false,
      // 阶段3 产物编辑弹窗
      editDialogVisible: false,
      editField: 'testcases_json',
      editFieldValue: '',
      editRawMode: false,
      // PCI / Risks 逐条回复
      pciReplies: [],
      riskReplies: [],
      pciLoading: [],
      pciSubQuestions: [],   // 每条 PCI 拆解出的子问题数组
      flatPciItemsList: [],  // 弹窗 PCI 子问题扁平列表（避免 computed 写自身依赖）
      allPciLoading: false,  // 全部拆解按钮 loading
      editFields: [
        { value: 'module_split', label: '模块拆分' },
        { value: 'risks_json', label: '风险识别' },
        { value: 'pci_json', label: '待确认问题 PCI' },
        { value: 'final_testpoints_json', label: '合并测试点' },
        { value: 'testcases_json', label: '测试用例' },
        { value: 'smoke_json', label: '冒烟用例' },
        { value: 'quality_report_json', label: '质量自检报告' },
      ],
      projects: [],
      versions: [],
      loadingProjects: false,
      syncMsg: '',
      // 快速新建
      showQuickProject: false,
      showQuickVersion: false,
      quickProjectName: '',
      quickProjectDesc: '',
      quickVersionName: '',
      form: {
        source_type: 'modao',
        url: '',
        webshare_url: '',
        cookies: '',
        requirement_text: '',
        title: '墨刀需求梳理',
        project: null,
        version: null,
        dual_fusion: true,
      },
      // 一键采纳到用例库
      adoptLoading: false,
      adoptIncludeSmoke: false,
      // 逐条采纳追踪（key 为 "gi-ti" 或 "smoke-gi-ti"，value 为 true=已采纳）
      adoptedCaseMap: {},
      // 阶段3产物筛选标签页
      stage3ActiveTab: 'all',
    }
  },
  beforeUnmount() {
    if (this.pollTimer) clearInterval(this.pollTimer)
  },
  watch: {
    'proto.clarification_log'() { this.parseClarify() },
    // 切换编辑字段前，先把当前字段的未保存内容存为草稿
    editField(newVal, oldVal) {
      if (oldVal && oldVal !== newVal) {
        this.saveDraft(oldVal)
      }
      this.onEditFieldChange()
    },
    // 从原文模式切回结构化视图时，确保 PCI 子问题卡片重新生成
    editRawMode(newVal) {
      if (!newVal && this.editField === 'pci_json') {
        this.$nextTick(() => this.recomputeFlatPciItems())
      }
    },
    // editFieldValue 变化（打开字段/切换/放弃修改/恢复草稿）时，重建 PCI 扁平列表为真实响应式对象，
    // 保证输入框 v-model 绑定持久化对象。注意：用户在结构化视图内输入 answer 不会改动 editFieldValue，
    // 因此不会误触发重建，输入不会被打断。
    editFieldValue() {
      if (this.editField === 'pci_json' && !this.editRawMode) {
        this.recomputeFlatPciItems()
      }
    },
  },
  methods: {
    base() { return '/requirement-analysis/api/modao' },
    statusLabel(s) {
      const m = { pending: '待处理', extracting: '读取中', extracted: '已读取', structuring: '结构化中', clarifying: '澄清中', designing: '用例设计中', done: '已完成', failed: '失败' }
      return m[s] || s
    },
    statusType(s) {
      const m = { pending: 'info', extracting: 'warning', extracted: 'success', structuring: 'warning', clarifying: 'warning', designing: 'warning', done: 'success', failed: 'danger' }
      return m[s] || 'info'
    },
    stageLabel(n) {
      const m = { 0: '原型接入', 1: '需求通读', 2: '需求澄清', 3: '用例设计', 4: '冒烟执行' }
      return m[n] || ''
    },
    toggleExpand(row) {
      const idx = this.expandedRows.indexOf(row.id)
      if (idx >= 0) {
        this.expandedRows.splice(idx, 1)
      } else {
        // 若无日志数据，先从详情接口拉取
        if (!row.work_log && !row.error_message) {
          request({ url: `${this.base()}/${row.id}/`, method: 'get' }).then(res => {
            const target = this.history.find(h => h.id === row.id)
            if (target) Object.assign(target, res.data)
          }).catch(() => {})
        }
        this.expandedRows.push(row.id)
      }
    },
    pretty(jsonStr) {
      try { return JSON.stringify(JSON.parse(jsonStr), null, 2) } catch (e) { return jsonStr }
    },
    countOf(jsonStr) {
      try { return JSON.parse(jsonStr).length } catch (e) { return 0 }
    },
    startPoll() {
      if (this.pollTimer) clearInterval(this.pollTimer)
      this.pollTimer = setInterval(() => this.refresh(), 3000)
    },
    stopPoll() {
      if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null }
    },
    async refresh() {
      if (!this.protoId) return
      try {
        const res = await request({ url: `${this.base()}/${this.protoId}/`, method: 'get' })
        this.proto = res.data
        this.parseClarify()
        const s = res.data.status
        if (!['extracting', 'structuring', 'clarifying', 'designing'].includes(s)) {
          this.stopPoll()
          this.busy = false
        }
      } catch (e) { /* ignore */ }
    },
    goStep(n) { this.step = n },
    // ---------- 内容编辑 ----------
    beginEdit(field) {
      this.editingField = field
      this.editBuffer = this.proto[field] || ''
    },
    cancelEdit() {
      this.editingField = null
      this.editBuffer = ''
    },
    async saveEdit() {
      if (!this.editingField) return
      try {
        await request({
          url: `${this.base()}/${this.protoId}/edit/`, method: 'patch',
          data: { field: this.editingField, value: this.editBuffer },
        })
        this.proto[this.editingField] = this.editBuffer
        this.$message.success('已保存修改')
        this.editingField = null
        this.editBuffer = ''
      } catch (e) {
        this.$message.error('保存失败：' + (e.response?.data?.detail || e.message))
      }
    },
    // ---------- 阶段2 澄清清单：逐条填写回复 ----------
    parseClarify() {
      const raw = (this.proto && this.proto.clarification_log) || ''
      if (!raw.trim()) {
        this.clarifyItems = []
        this.clarifyReplies = []
        this.clarifyParsed = false
        return
      }
      let items = null
      // 策略1：直接解析为 JSON 数组
      try { items = JSON.parse(raw) } catch (e) { items = null }
      // 策略2：提取 ```json 或 ```yaml 代码块内容再解析
      if (!Array.isArray(items)) {
        const m = raw.match(/```(?:json|yaml|yml)?\s*\n([\s\S]*?)```/i)
        if (m) {
          const inner = m[1].trim()
          try { items = JSON.parse(inner) } catch (e) { items = null }
        }
      }
      // 策略3：全文找首个 [...] JSON 数组（LLM 可能在前后加了说明文字）
      if (!Array.isArray(items)) {
        const arrMatch = raw.match(/\[[\s\S]*?\](?=\s*[\n]|$)/)
        if (arrMatch) {
          try { items = JSON.parse(arrMatch[0]) } catch (e) { items = null }
        }
      }
      if (Array.isArray(items) && items.length && items[0] && typeof items[0] === 'object') {
        this.clarifyItems = items
        this.clarifyReplies = items.map(it => (it && (it.resolution || it.answer)) || '')
        this.clarifyParsed = true
      } else {
        this.clarifyItems = []
        this.clarifyReplies = []
        this.clarifyParsed = false
      }
    },
    async saveClarifyReplies() {
      if (!this.clarifyParsed) return
      const items = this.clarifyItems.map((it, i) => ({
        ...it,
        resolution: (this.clarifyReplies[i] || '').trim(),
      }))
      const value = JSON.stringify(items, null, 2)
      try {
        await request({
          url: `${this.base()}/${this.protoId}/edit/`, method: 'patch',
          data: { field: 'clarification_log', value },
        })
        this.proto.clarification_log = value
        this.$message.success('澄清回复已保存')
      } catch (e) {
        this.$message.error('保存失败：' + (e.response?.data?.detail || e.message))
      }
    },
    toggleRawEdit() {
      if (this.editingField === 'clarification_log') {
        this.cancelEdit()
      } else {
        this.beginEdit('clarification_log')
      }
    },
    typeTag(t) {
      const m = { '模糊点': 'warning', '缺失点': 'danger', '边界点': 'info' }
      return m[t] || ''
    },
    // ---------- 阶段3 产物编辑弹窗 ----------
    openEditDialog(field) {
      const target = field || 'testcases_json'
      this.editDialogVisible = true
      if (this.editField === target) {
        // 同一字段：直接恢复草稿 / 从 proto 初始化
        this.onEditFieldChange()
      } else {
        // 不同字段：交给 watch 处理（先存旧字段草稿，再初始化新字段）
        this.editField = target
      }
    },
    // ---------- 编辑草稿：未保存内容自动保留（关闭/切换/刷新后重进都不丢）----------
    draftKey(field) {
      return `modao_edit_draft_${this.protoId}_${field}`
    },
    saveDraft(field) {
      if (!field || !this.proto) return
      const draft = {
        editFieldValue: this.editFieldValue,
        editRawMode: this.editRawMode,
        pciReplies: this.pciReplies,
        pciSubQuestions: this.pciSubQuestions,
        riskReplies: this.riskReplies,
      }
      try { localStorage.setItem(this.draftKey(field), JSON.stringify(draft)) } catch (e) { /* 忽略隐私模式等异常 */ }
    },
    loadDraft(field) {
      try {
        const s = localStorage.getItem(this.draftKey(field))
        return s ? JSON.parse(s) : null
      } catch (e) { return null }
    },
    clearDraft(field) {
      try { localStorage.removeItem(this.draftKey(field)) } catch (e) { /* noop */ }
    },
    async closeEditDialog() {
      // PCI 弹窗：若已填写/确认了子问题，关闭时自动落库，确保外部列表立即可见（无需再点「保存全部回复」）
      if (this.editField === 'pci_json' && this.hasPciUnsavedContent) {
        await this.savePciReplies()
      } else {
        // 关闭前存草稿，下次重进可恢复
        this.saveDraft(this.editField)
      }
      this.editDialogVisible = false
    },
    revertEditField() {
      // 放弃未保存修改，回到后端原始数据
      this.clearDraft(this.editField)
      this.onEditFieldChange()
    },
    onEditFieldChange() {
      // 优先恢复未保存草稿（关闭弹窗 / 切换字段 / 刷新页面后重新进入都能保留）
      const draft = this.loadDraft(this.editField)
      if (draft) {
        this.editFieldValue = draft.editFieldValue || ''
        this.editRawMode = !!draft.editRawMode
        this.pciReplies = draft.pciReplies || []
        // 仅当草稿含有效子问题才恢复，避免空草稿把 pciSubQuestions 置空后直接 return 跳过拆分
        this.pciSubQuestions = (draft.pciSubQuestions && draft.pciSubQuestions.length) ? draft.pciSubQuestions : []
        this.riskReplies = draft.riskReplies || []
      } else {
        // 无草稿：从 proto 原始数据初始化
        this.editFieldValue = this.proto[this.editField] || ''
      }
      // 兜底：PCI 字段且尚未拆解出子问题时，本地快速拆分（保证 v-model 绑定真实响应式对象，而非临时副本）
      if (this.editField === 'pci_json') {
        if (!this.pciSubQuestions.length && this.parsedPciItems.length) {
          this.splitAllPciLocal()
        }
        this.recomputeFlatPciItems()
        this.pciReplies = (this.parsedPciItems || []).map(it => (it && (it.answer || it.resolution_condition || it.resolution)) || '')
        this.pciLoading = (this.parsedPciItems || []).map(() => false)
      } else if (this.editField === 'risks_json') {
        this.riskReplies = (this.parsedRiskItems || []).map(it => (it && it.mitigation) || '')
      }
    },
    // ---------- PCI 子问题拆解与逐条解答 ----------
    // 纯前端本地快速拆分（按中文标点，零等待）
    // 优先直接读取已保存的 sub_questions（与主视图 mainPageFlatPci 逻辑一致），
    // 仅在 sub_questions 缺失/损坏时回退到按 description 拆分，避免重开弹窗后出现"新问题"。
    splitAllPciLocal() {
      this.parsedPciItems.forEach((pci, i) => {
        // 1) 优先：已有结构化子问题则直接采用（保留各自独立的 question/answer/confirmed）
        const savedSubs = (pci.sub_questions || []).filter(s => s && s.question)
        if (savedSubs.length) {
          this.pciSubQuestions[i] = savedSubs.map(s => ({
            question: s.question,
            answer: s.answer || pci.answer || pci.resolution_condition || pci.resolution || '',
            confirmed: !!s.confirmed,
            _loading: false,
          }))
          return
        }
        // 2) 回退：无 sub_questions 时按 description 中文标点拆分
        const desc = (pci.description || '').trim()
        if (!desc) {
          this.pciSubQuestions[i] = [{ question: '(无描述内容)', answer: (pci.answer || pci.resolution_condition || ''), confirmed: false, _loading: false }]
          return
        }
        const parts = desc.split(/\s*(?:且|以及|；|,)\s*/).map(s => s.trim()).filter(Boolean)
        const items = parts.map(p => ({
          question: p,
          answer: pci.answer || pci.resolution_condition || pci.resolution || '',
          confirmed: false,
          _loading: false,
        }))
        this.pciSubQuestions[i] = items.length ? items : [{ question: desc, answer: '', confirmed: false, _loading: false }]
      })
    },
    // 重新计算弹窗 PCI 子问题的扁平列表。
    // 关键：始终以 parsedPciItems 为准，为每条 PCI 固化出「真实响应式子问题对象」到 pciSubQuestions，
    // 再引用这些真实对象生成扁平列表 —— 这样 v-model="item.sub.answer" 永远绑定持久化对象，
    // 彻底避免旧草稿结构不匹配导致 out 为空、进而回退到「兜底纯计算临时对象」而无法输入的问题。
    recomputeFlatPciItems() {
      const pcis = this.parsedPciItems || []
      // 1) 确保每条 PCI 都有一个有效的子问题数组（缺失/损坏则按描述重新拆分并直接赋值固化）
      pcis.forEach((pci, i) => {
        const cur = this.pciSubQuestions[i]
        if (!Array.isArray(cur) || !cur.length) {
          // 优先直接读取已保存的 sub_questions（与主视图一致，避免重建时混入"新问题"）
          const savedSubs = (pci.sub_questions || []).filter(s => s && s.question)
          if (savedSubs.length) {
            this.pciSubQuestions[i] = savedSubs.map(s => ({
              question: s.question,
              answer: s.answer || pci.answer || pci.resolution_condition || pci.resolution || '',
              confirmed: !!s.confirmed,
              _loading: false,
            }))
            return
          }
          // 回退：无 sub_questions 时按 description 拆分
          const desc = (pci.description || '').trim()
          const parts = desc ? desc.split(/\s*(?:且|以及|；|,)\s*/).map(s => s.trim()).filter(Boolean) : ['(无描述内容)']
          const items = (parts.length ? parts : [desc || '(无描述内容)']).map(q => ({
            question: q,
            answer: pci.answer || pci.resolution_condition || pci.resolution || '',
            confirmed: false,
            _loading: false,
          }))
          this.pciSubQuestions[i] = items
        } else {
          // 数组已存在：同步已有答案到子问题对象（避免重开弹窗后答案丢失）
          const savedSubs = (pci.sub_questions || []).filter(s => s && s.question)
          const savedMap = {}
          savedSubs.forEach(s => { savedMap[(s.question || '').trim()] = { answer: (s.answer || '').trim(), confirmed: !!s.confirmed } })
          cur.forEach(sub => {
            const trimmed = (sub.question || '').trim()
            const saved = savedMap[trimmed]
            if (saved) {
              if (saved.answer && !sub.answer) sub.answer = saved.answer
              if (saved.confirmed) sub.confirmed = true
            }
          })
        }
      })
      // 2) 生成扁平列表：一律引用 pciSubQuestions 里的真实对象
      const out = []
      pcis.forEach((pci, i) => {
        const items = this.pciSubQuestions[i] || []
        items.forEach((sub, j) => out.push({ pci, pciIndex: i, sub, subIndex: j }))
      })
      this.flatPciItemsList = out
    },
    // 将单条 PCI 的 description 拆分为子问题数组，每条自动生成解答（AI）
    async splitAndAnswerPci(i) {
      const pci = this.parsedPciItems[i]
      if (!pci) return
      this.pciLoading[i] = true
      try {
        const prompt =
          '你是一名资深测试分析师。下面是一条"待确认问题(PCI)"的完整描述内容。\n' +
          '请将其拆分为若干个**独立的、具体的子问题**（每个子问题只关注一个确认点），然后对每个子问题给出专业的解答/处置建议。\n\n' +
          '要求：\n' +
          '1. 必须返回合法 JSON 数组，格式：[{"question":"子问题描述","answer":"解答或建议"}]\n' +
          '2. 每个子问题要具体、可操作（如："动画每步的具体时长是否需要限制？" 而非笼统描述）\n' +
          '3. 解答要给出明确结论（接受风险 / 需补充设计 / 降级处理 / 阻塞发布等）及理由\n' +
          '4. 只输出 JSON 数组，不要其他文字\n\n' +
          'PCI 描述：\n' + (pci.description || '') + '\n' +
          (pci.blocked_scenarios && pci.blocked_scenarios.length ? '\n阻塞场景：' + pci.blocked_scenarios.join(', ') : '')
        const res = await request({
          url: `${this.base()}/${this.protoId}/ask/`, method: 'post',
          data: { stage: 3, question: prompt },
        })
        let items = []
        try {
          const text = (res.data.answer || '').trim()
          // 尝试从回答中提取 JSON 数组
          const jsonMatch = text.match(/\[[\s\S]*?\]/)
          if (jsonMatch) {
            items = JSON.parse(jsonMatch[0])
          }
        } catch (e) { /* 解析失败则用原始文本作为单个子问题 */ }
        if (!Array.isArray(items) || !items.length) {
          items = [{ question: pci.description || '', answer: res.data.answer || '' }]
        }
        // 给每项加 confirmed 和 _loading
        items = items.map(it => ({
          question: it.question || '',
          answer: it.answer || '',
          confirmed: false,
          _loading: false,
        }))
        // 合并策略：保留用户已编辑的 answer（避免异步返回覆盖用户正在输入的内容）
        const existing = this.pciSubQuestions[i] || []
        items = items.map((it, j) => {
          const old = (existing.length > j) ? existing[j] : null
          if (old && old.answer && !it.answer) {
            // AI 没给答案但用户已有编辑 → 保留用户的
            return { ...it, answer: old.answer, confirmed: old.confirmed }
          }
          if (old && old.answer && it.answer && old.answer !== it.answer) {
            // 用户和 AI 都有内容 → 保留用户的（用户优先）
            return { ...it, answer: old.answer, confirmed: old.confirmed }
          }
          return it
        })
        this.pciSubQuestions[i] = items
        this.recomputeFlatPciItems()
        this.$message.success(`PCI ${pci.id || ('#' + (i+1))} 拆解为 ${items.length} 个子问题`)
      } catch (e) {
        this.$message.error('拆解失败：' + (e.response?.data?.detail || e.message))
      } finally {
        this.pciLoading[i] = false
      }
    },
    // 单独解答某个子问题
    async askSingleSubQ(pciIdx, subIdx) {
      const sq = (this.pciSubQuestions[pciIdx] || [])[subIdx]
      if (!sq) return
      sq._loading = true
      try {
        const res = await request({
          url: `${this.base()}/${this.protoId}/ask/`, method: 'post',
          data: { stage: 3, question: sq.question },
        })
        sq.answer = res.data.answer || ''
      } catch (e) {
        this.$message.error('解答失败：' + (e.response?.data?.detail || e.message))
      } finally {
        sq._loading = false
      }
    },
    // 重置某条 PCI 的拆解状态
    resetPciSplit(i) {
      this.pciSubQuestions[i] = []
      this.recomputeFlatPciItems()
    },
    // 重置全部 PCI 的拆解状态
    resetAllPciSplit() {
      this.pciSubQuestions = []
      this.recomputeFlatPciItems()
    },
    // 一键全部拆解所有 PCI 条目（并发，单条失败不影响整体）
    async splitAllPci() {
      this.allPciLoading = true
      try {
        await Promise.all(this.parsedPciItems.map((_, i) =>
          (this.pciSubQuestions[i] && this.pciSubQuestions[i].length)
            ? Promise.resolve()
            : this.splitAndAnswerPci(i)
        ))
        this.$message.success('所有 PCI 已拆解为子问题')
      } catch (e) {
        /* 单条错误已在 splitAndAnswerPci 内处理 */
      } finally {
        this.allPciLoading = false
        this.recomputeFlatPciItems()
      }
    },
    async savePciReplies() {
      const items = this.parsedPciItems.map((it, i) => {
        // 如果有子问题，汇总子问题的答案
        let answer = (this.pciReplies[i] || '').trim()
        const subs = this.pciSubQuestions[i] || []
        if (subs.length) {
          const subAnswers = subs
            .filter(s => s.answer && s.answer.trim())
            .map((s, si) => `[Q${si + 1}] ${s.question}\n    A: ${s.answer.trim()}`)
          if (subAnswers.length) {
            answer = subAnswers.join('\n\n')
          }
        }
        return {
          ...it,
          answer,
          resolution_condition: answer,
          // 同时保存子问题结构化数据
          sub_questions: subs.map(({ _loading, ...rest }) => rest),
        }
      })
      // 重组回原始结构：多模块时按 _moduleIdx/_listIdx 精确回填各自模块的 pci_list（不再全塞第一个模块）
      let wrapper = {}
      try { wrapper = JSON.parse(this.editFieldValue) } catch (e) { wrapper = {} }
      const strip = ({ _raw, _idx, _moduleIdx, _listIdx, _module, ...rest }) => rest
      wrapper = this.writeBackModuleList(wrapper, items, 'pci_list', strip)
      const value = JSON.stringify(wrapper, null, 2)
      try {
        await request({
          url: `${this.base()}/${this.protoId}/edit/`, method: 'patch',
          data: { field: 'pci_json', value },
        })
        this.proto.pci_json = value
        this.editFieldValue = value
        this.clearDraft('pci_json')
        this.$message.success('PCI 回复已保存')
      } catch (e) {
        this.$message.error('保存失败：' + (e.response?.data?.detail || e.message))
      }
    },
    async saveRiskReplies() {
      const items = this.parsedRiskItems.map((it, i) => ({
        ...it,
        mitigation: (this.riskReplies[i] || '').trim(),
      }))
      let wrapper = {}
      try { wrapper = JSON.parse(this.editFieldValue) } catch (e) { wrapper = {} }
      const strip = ({ _raw, _idx, _moduleIdx, _listIdx, _module, ...rest }) => rest
      wrapper = this.writeBackModuleList(wrapper, items, 'risk_points', strip)
      const value = JSON.stringify(wrapper, null, 2)
      try {
        await request({
          url: `${this.base()}/${this.protoId}/edit/`, method: 'patch',
          data: { field: 'risks_json', value },
        })
        this.proto.risks_json = value
        this.editFieldValue = value
        this.clearDraft('risks_json')
        this.$message.success('风险处置回复已保存')
      } catch (e) {
        this.$message.error('保存失败：' + (e.response?.data?.detail || e.message))
      }
    },
    async saveEditDialog() {
      // PCI / 风险 字段已有专门的结构化保存逻辑（会把子问题 answer 汇总并写回 sub_questions），
      // 点「保存修改」时同样走结构化保存，避免只保存原始 JSON 导致子问题答案丢失。
      if (this.editField === 'pci_json') {
        await this.savePciReplies()
        this.editDialogVisible = false
        return
      }
      if (this.editField === 'risks_json') {
        await this.saveRiskReplies()
        this.editDialogVisible = false
        return
      }
      try {
        await request({
          url: `${this.base()}/${this.protoId}/edit/`, method: 'patch',
          data: { field: this.editField, value: this.editFieldValue },
        })
        this.proto[this.editField] = this.editFieldValue
        this.clearDraft(this.editField)
        this.$message.success('已保存修改')
        this.editDialogVisible = false
      } catch (e) {
        this.$message.error('保存失败：' + (e.response?.data?.detail || e.message))
      }
    },
    // ---------- 编辑弹窗：结构化视图 ----------
    // 通用：从可能的「多模块数组」结构中展开指定 listKey 的所有条目。
    // 兼容：[{module,data:{pci_list}}...] / [{module,pci_list}...] / {data:{pci_list}} / {pci_list} / 裸条目数组。
    // 每条附带 _moduleIdx（顶层模块索引，-1 表示单容器/裸数组）、_listIdx（模块内索引）、_module（模块名），供写回时精确定位。
    flattenModuleList(v, listKey) {
      const out = []
      const push = (list, moduleIdx, moduleName) => {
        if (!Array.isArray(list)) return
        list.forEach((item, idx) => out.push({
          ...(item && typeof item === 'object' ? item : { value: item }),
          _moduleIdx: moduleIdx,
          _listIdx: idx,
          _module: moduleName || (item && item.module) || '',
        }))
      }
      if (Array.isArray(v)) {
        // 判断是否为「模块包裹数组」：某元素含 listKey 或 data.listKey
        const wrapped = v.some(m => m && (Array.isArray(m[listKey]) || (m.data && Array.isArray(m.data[listKey]))))
        if (wrapped) {
          v.forEach((m, mi) => {
            const list = Array.isArray(m[listKey]) ? m[listKey]
              : (m && m.data && Array.isArray(m.data[listKey]) ? m.data[listKey] : null)
            push(list, mi, m && (m.module || (m.data && m.data.module)))
          })
        } else {
          push(v, -1, '')  // 裸条目数组
        }
      } else if (v && typeof v === 'object') {
        if (Array.isArray(v[listKey])) push(v[listKey], -1, v.module)
        else if (v.data && Array.isArray(v.data[listKey])) push(v.data[listKey], -1, v.module || v.data.module)
      }
      return out
    },
    // 把已编辑的条目按 _moduleIdx/_listIdx 精确写回原 wrapper（多模块时逐条回填对应模块的 list）
    writeBackModuleList(wrapper, items, listKey, stripInternal) {
      const multi = items.some(it => it._moduleIdx >= 0)
      if (multi && Array.isArray(wrapper)) {
        items.forEach(it => {
          const m = wrapper[it._moduleIdx]
          if (!m) return
          const target = Array.isArray(m[listKey]) ? m[listKey]
            : (m.data && Array.isArray(m.data[listKey]) ? m.data[listKey] : null)
          if (target && it._listIdx != null && target[it._listIdx] != null) {
            target[it._listIdx] = stripInternal(it)
          }
        })
        return wrapper
      }
      // 单容器/裸结构：整体替换
      const cleanItems = items.map(stripInternal)
      if (Array.isArray(wrapper) && wrapper.length && wrapper[0].data && Array.isArray(wrapper[0].data[listKey])) {
        wrapper[0].data[listKey] = cleanItems
      } else if (wrapper && wrapper.data && Array.isArray(wrapper.data[listKey])) {
        wrapper.data[listKey] = cleanItems
      } else if (Array.isArray(wrapper) && wrapper.length && Array.isArray(wrapper[0][listKey])) {
        wrapper[0][listKey] = cleanItems
      } else {
        if (!wrapper || typeof wrapper !== 'object' || Array.isArray(wrapper)) wrapper = {}
        wrapper[listKey] = cleanItems
      }
      return wrapper
    },
    isStructuredField(f) {
      return ['testcases_json', 'final_testpoints_json', 'module_split', 'smoke_json'].includes(f)
    },
    priTag(p) {
      const m = { P0: 'danger', P1: 'warning', P2: '', critical: 'danger', high: 'warning', medium: 'info', low: 'info' }
      return m[p] || ''
    },
    riskAnswer(risk) {
      if (!risk || typeof risk !== 'object') return ''
      return risk.mitigation || risk.answer || risk.resolution_condition || risk.resolution || ''
    },
    // 冒烟用例字段归一化：技能 p4 输出用 test_steps/pass_criteria/is_core，
    // 前端/测试用例统一用 steps/expected/is_smoke
    normalizeSmokeCase(tc) {
      if (!tc || typeof tc !== 'object') return tc
      return {
        ...tc,
        steps: tc.steps || tc.test_steps || [],
        expected: tc.expected || tc.pass_criteria || '',
        is_smoke: tc.is_smoke !== undefined ? tc.is_smoke : !!tc.is_core,
      }
    },
    // ---------- 通用 JSON 卡片辅助 ----------
    displayFields(item) {
      // 过滤掉内部字段和已单独展示的字段
      const skip = ['_raw', 'module', 'title', 'id']
      const obj = {}
      Object.keys(item).forEach(k => {
        if (!skip.includes(k) && item[k] != null) obj[k] = item[k]
      })
      return obj
    },
    fieldLabel(key) {
      const m = {
        type: '类型', priority: '优先级', impact: '影响',
        description: '描述', category: '分类',
        extended_test_points: '扩展测试点', related_testpoints: '关联测试点',
        data: '数据内容', schema_version: '版本',
        risk_points: '风险点', question: '问题',
        suggested_answer: '建议答案', resolution: '结论',
        status: '状态', score: '得分', suggestion: '建议',
        preconditions: '前置条件', steps: '步骤', expected: '预期结果',
      }
      return m[key] || key
    },
    qualityKeyLabel(key) {
      const m = {
        summary: '总体评价', score: '质量得分', passed: '是否通过',
        issues: '存在问题', suggestions: '改进建议', coverage: '覆盖率',
        completeness: '完整度', correctness: '正确性', clarity: '清晰度',
        total: '总计', detail: '明细', passed_count: '通过数',
        failed_count: '未通过数', rate: '通过率',
      }
      return m[key] || key
    },
    formatFieldValue(val) {
      if (Array.isArray(val)) return val.join(', ')
      if (typeof val === 'object') return JSON.stringify(val)
      return String(val)
    },
    // 取某阶段的答疑问答记录
    qaLogFor(stage) {
      try {
        return (JSON.parse(this.proto?.qa_log || '[]')).filter(i => i.stage === stage)
      } catch (e) { return [] }
    },
    async loadHistory() {
      this.loadingHistory = true
      try {
        const res = await request({ url: `${this.base()}/list/`, method: 'get' })
        const data = res.data
        if (Array.isArray(data)) {
          // 兼容旧接口（直接返回数组）
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
    async onContinue(row) {
      this.protoId = row.id
      this.proto = row
      this.step = row.current_stage || 0
      // 若仍在进行中，启动轮询
      const s = row.status
      if (['extracting', 'structuring', 'clarifying', 'designing'].includes(s)) {
        this.busy = true
        this.startPoll()
      } else {
        this.busy = false
        this.stopPoll()
      }
      await this.refresh()
      this.$message.success(`已恢复流程「${row.title}」`)
    },
    onNew() {
      this.stopPoll()
      this.protoId = null
      this.proto = null
      this.step = 0
      this.busy = false
      this.smokeDecision = ''
      this.rejectEmail = ''
      this.clarifyItems = []
      this.clarifyReplies = []
      this.clarifyParsed = false
      this.form = { source_type: 'modao', url: '', webshare_url: '', cookies: '', requirement_text: '', title: '墨刀需求梳理', project: null, version: null, dual_fusion: true }
    },
    async onDelete(row) {
      try {
        await this.$confirm(`确认删除「${row.title}」？`, '提示', { type: 'warning' })
      } catch (e) { return }
      try {
        await request({ url: `${this.base()}/${row.id}/`, method: 'delete' })
        if (this.protoId === row.id) this.onNew()
        await this.loadHistory()
        this.$message.success('已删除')
      } catch (e) {
        this.$message.error('删除失败：' + (e.response?.data?.detail || e.message))
      }
    },
    async onCreate() {
      this.busy = true
      try {
        // 根据来源类型，把对应输入框按行拆成 urls 传给后端
        let urls = []
        if (this.form.source_type === 'modao') {
          urls = (this.form.url || '').split('\n').map(s => s.trim()).filter(Boolean)
        } else if (this.form.source_type === 'webshare') {
          urls = (this.form.webshare_url || '').split('\n').map(s => s.trim()).filter(Boolean)
        }
        const payload = { ...this.form, urls }
        const res = await request({ url: `${this.base()}/create/`, method: 'post', data: payload })
        this.protoId = res.data.id
        this.proto = res.data
        if (this.form.source_type === 'modao' || this.form.source_type === 'webshare') {
          await request({ url: `${this.base()}/${this.protoId}/extract/`, method: 'post', data: payload })
          this.startPoll()
        } else {
          // 文本来源：直接可进入阶段1
          this.busy = false
          this.goStep(1)
        }
      } catch (e) {
        this.busy = false
        this.$message.error('创建失败：' + (e.response?.data?.detail || e.message))
      }
    },
    async runStage(action) {
      this.busy = true
      try {
        await request({ url: `${this.base()}/${this.protoId}/${action}/`, method: 'post', data: this.form })
        this.startPoll()
      } catch (e) {
        this.busy = false
        this.$message.error('启动失败：' + (e.response?.data?.detail || e.message))
      }
    },
    onStruct() { this.runStage('struct') },
    onClarify() { this.runStage('clarify') },
    onDesign() { this.runStage('design') },
    async onGenerateCases() {
      try {
        await this.$confirm(
          '请确认：所有位置、交互和需求疑问均已由人工给出结论，且当前合并测试点可用于生成最终测试用例。确认后系统会记录批准人和当前内容指纹；后续编辑会使本次批准失效。',
          '人工批准生成最终测试用例', { type: 'warning', confirmButtonText: '确认并批准生成' })
      } catch (e) { return }
      this.busy = true
      try {
        await request({
          url: `${this.base()}/${this.protoId}/approve-case-generation/`, method: 'post', data: {},
        })
        await request({
          url: `${this.base()}/${this.protoId}/generate-cases/`, method: 'post', data: this.form,
        })
        this.startPoll()
      } catch (e) {
        this.busy = false
        const data = e.response?.data || {}
        const reasons = data.generation_gate?.reasons || []
        this.$message.error(data.detail || reasons.join('；') || e.message)
        await this.refresh()
      }
    },
    async loadProjects() {
      this.loadingProjects = true
      try {
        const res = await request({ url: '/projects/all/', method: 'get' })
        console.log('[loadProjects] res.data:', JSON.stringify(res.data).slice(0, 300))
        this.projects = res.data.results || res.data || []
        console.log('[loadProjects] projects count:', this.projects.length)
      } catch (e) {
        console.error('[loadProjects] error:', e)
        this.projects = []
        this.$message.error('加载项目失败: ' + (e.response?.data?.detail || e.message))
      } finally {
        this.loadingProjects = false
      }
    },
    async onProjectChange(pid) {
      this.form.version = null
      this.versions = []
      if (!pid) return
      try {
        const res = await request({ url: `/versions/projects/${pid}/versions/`, method: 'get' })
        this.versions = res.data.results || res.data || []
      } catch (e) {
        this.versions = []
      }
    },
    // ---------- 快速新建项目/版本 ----------
    async createQuickProject() {
      try {
        const res = await request({
          url: '/projects/', method: 'post',
          data: { name: this.quickProjectName.trim(), description: (this.quickProjectDesc || '').trim() || undefined },
        })
        const p = res.data
        await this.loadProjects()
        this.form.project = p.id
        this.showQuickProject = false
        this.quickProjectName = ''
        this.quickProjectDesc = ''
        this.$message.success('已创建项目：' + p.name)
      } catch (e) {
        this.$message.error('创建失败：' + (e.response?.data?.name?.[0] || e.response?.data?.detail || e.message))
      }
    },
    async createQuickVersion() {
      if (!this.form.project) {
        this.$message.warning('请先选择归属项目')
        return
      }
      try {
        const res = await request({
          url: '/versions/', method: 'post',
          data: { name: this.quickVersionName.trim(), project_ids: [this.form.project] },
        })
        const v = res.data
        // 刷新版本列表
        const vRes = await request({ url: `/versions/projects/${this.form.project}/versions/`, method: 'get' })
        this.versions = vRes.data.results || vRes.data || []
        this.form.version = v.id
        this.showQuickVersion = false
        this.quickVersionName = ''
        this.$message.success('已创建版本：' + v.name)
      } catch (e) {
        this.$message.error('创建失败：' + (e.response?.data?.name?.[0] || e.response?.data?.detail || e.message))
      }
    },
    async adoptToLibrary(includeSmoke) {
      if (!this.protoId) return
      if (!this.proto || !this.proto.project) {
        this.$message.warning('请先在阶段0关联项目，再采纳到用例库')
        return
      }
      this.adoptLoading = true
      try {
        const res = await request({
          url: `${this.base()}/${this.protoId}/adopt/`, method: 'post',
          data: { include_smoke: !!includeSmoke },
        })
        const d = res.data || {}
        let msg = `已采纳 ${d.testcases} 条用例、自动创建 ${d.modules} 个功能模块到用例库`
        if (d.smoke) msg += `，冒烟 ${d.smoke} 条`
        if (d.skipped) msg += `（跳过已存在 ${d.skipped} 条）`
        this.$message.success(msg)
        await this.refresh()
      } catch (e) {
        this.$message.error('采纳失败：' + (e.response?.data?.detail || e.message))
      } finally {
        this.adoptLoading = false
      }
    },
    async adoptSingleCase(caseIndex, caseKey) {
      if (!this.protoId) return
      if (!this.proto || !this.proto.project) {
        this.$message.warning('请先在阶段0关联项目，再采纳到用例库')
        return
      }
      // 防重复点击
      if (this.adoptedCaseMap[caseKey]) return
      try {
        const res = await request({
          url: `${this.base()}/${this.protoId}/adopt-single/`,
          method: 'post',
          data: { index: caseIndex },
        })
        const d = res.data || {}
        // 标记已采纳（Vue 3 无需 $set，直接赋值即可触发响应式更新）
        this.adoptedCaseMap[caseKey] = true
        this.$message.success(d.detail || '已采纳')
      } catch (e) {
        this.$message.error('采纳失败：' + (e.response?.data?.detail || e.message))
      }
    },
    async onConfirm(stage) {
      // 确认前若有未保存的编辑，先落库
      if (this.editingField) {
        await this.saveEdit()
      }
      try {
        const res = await request({ url: `${this.base()}/${this.protoId}/confirm/`, method: 'post', data: { stage } })
        await this.refresh()
        this.showSync(res.data.sync, stage)
        if (stage === 3) this.showKbSync(res.data.kb_sync)
        this.goStep(stage + 1) // 进入下一阶段
      } catch (e) {
        this.$message.error('确认失败：' + (e.response?.data?.detail || e.message))
      }
    },
    showKbSync(kb) {
      if (!kb || !kb.created_count) return
      this.$message.success(`已自适应沉淀 ${kb.created_count} 条新知识到项目知识库（跳过已存在 ${kb.skipped_count} 条）`)
    },
    showSync(sync, stage) {
      if (!sync) {
        if (stage === 1 && !this.proto.project) {
          this.syncMsg = '未选择归属项目，未同步功能模块（可在阶段0补充项目后重新确认）'
        }
        return
      }
      if (stage === 1) {
        this.syncMsg = `已自动同步功能模块「${sync.name}」`
        this.$message.success(this.syncMsg)
      } else if (stage === 3) {
        this.syncMsg = `已同步 ${sync.modules} 个子模块 / ${sync.testpoints} 条测试点 / ${sync.testcases} 条用例到功能模块`
        this.$message.success(this.syncMsg)
      }
    },
    async onSmoke() {
      try {
        await request({
          url: `${this.base()}/${this.protoId}/smoke/`, method: 'post',
          data: { decision: this.smokeDecision, reject_email: this.rejectEmail },
        })
        await this.refresh()
        this.$message.success('冒烟决策已记录')
      } catch (e) {
        this.$message.error('提交失败：' + (e.response?.data?.detail || e.message))
      }
    },
    onDownload() {
      const base = request.defaults.baseURL || '/api'
      window.open(`${base}${this.base()}/${this.protoId}/excel/`, '_blank')
    },
  },
  mounted() {
    this.loadHistory()
    this.loadProjects()
  },
  computed: {
    clarificationUnresolvedCount() {
      return this.proto?.generation_gate?.unresolved_count || 0
    },
    generationGateReasons() {
      return this.proto?.generation_gate?.reasons || []
    },
    hasAnyArtifact() {
      const p = this.proto
      return p && (p.module_split || p.risks_json || p.pci_json || p.final_testpoints_json || p.testcases_json || p.smoke_json || p.quality_report_json)
    },
    // 判断 PCI 子问题是否有已填/已确认的未落库内容
    hasPciUnsavedContent() {
      const subs = this.pciSubQuestions || []
      return subs.some(arr => Array.isArray(arr) && arr.some(s => (s.answer && s.answer.trim()) || s.confirmed))
    },
    formattedValue() {
      try {
        const v = JSON.parse(this.editFieldValue)
        return JSON.stringify(v, null, 2)
      } catch (e) {
        return this.editFieldValue
      }
    },
    parsedJsonArray() {
      try {
        const v = JSON.parse(this.editFieldValue)
        if (Array.isArray(v)) return v.map(item => ({ ...item, _raw: JSON.stringify(item, null, 2) }))
        if (typeof v === 'object') return [{ ...v, _raw: JSON.stringify(v, null, 2) }]
        return []
      } catch (e) { return [] }
    },
    parsedTestcases() {
      let arr = this.parsedJsonArray
      // 冒烟用例产物可能是 {smoke_overview, smoke_testcases, execution_suggestion}，需取出 smoke_testcases 数组
      if (this.editField === 'smoke_json') {
        try {
          const v = JSON.parse(this.editFieldValue)
          const list = (v && Array.isArray(v.smoke_testcases)) ? v.smoke_testcases
            : (Array.isArray(v) ? v : [])
          arr = list.map(tc => ({ ...this.normalizeSmokeCase(tc), _raw: JSON.stringify(tc, null, 2) }))
        } catch (e) { arr = [] }
      }
      if (!arr.length) return []
      // 每条可能是 { testcase: {...}, module, _raw } 嵌套包裹，或扁平用例对象
      const groups = {}
      arr.forEach((tc) => {
        const real = tc.testcase || tc
        // 去掉内部 _raw，重新生成干净的原始 JSON（避免嵌套转义串越叠越大）
        const clean = {}
        Object.keys(real).forEach(k => { if (k !== '_raw') clean[k] = real[k] })
        const mod = (tc.module || real.module || real.feature_module) || '未分组'
        if (!groups[mod]) groups[mod] = []
        groups[mod].push({ ...clean, module: mod, _raw: JSON.stringify(clean, null, 2) })
      })
      return Object.keys(groups).map(k => ({ module: k, items: groups[k] }))
    },
    parsedTestpoints() {
      const arr = this.parsedJsonArray
      return arr.map(tp => ({ ...tp, _raw: JSON.stringify(tp, null, 2) }))
    },
    // PCI：从嵌套的 pci_list 中展开每条（兼容多种结构）
    // 可能是: {pci_list:[...]} / {data:{pci_list:[...]}} / [{data:{pci_list:[...]}}] / [{pci_list:[...]}]
    parsedPciItems() {
      try {
        const v = JSON.parse(this.editFieldValue)
        // 遍历「所有模块」展开 pci_list（不再只取第一个模块）
        return this.flattenModuleList(v, 'pci_list').map((item, idx) => {
          const { _moduleIdx, _listIdx, _module, ...pure } = item
          return { ...item, _raw: JSON.stringify(pure, null, 2), _idx: idx }
        })
      } catch (e) { return [] }
    },
    // 弹窗 PCI 子问题扁平列表（优先用方法层维护的真实对象，兜底纯计算避免回退通用 JSON 视图）
    flatPciItems() {
      if (this.flatPciItemsList && this.flatPciItemsList.length) {
        return this.flatPciItemsList
      }
      // flatPciItemsList 尚未就绪（极端时序）：异步补算为真实对象，下一帧即替换本帧的临时对象，
      // 从而恢复可输入状态；本帧仅用纯计算结果占位，避免回退到通用 JSON 视图。
      if (this.parsedPciItems && this.parsedPciItems.length) {
        this.$nextTick(() => this.recomputeFlatPciItems())
      }
      // 兜底：只读计算生成子问题卡片（不修改任何 data，避免 computed 副作用）
      const out = []
      const pcis = this.parsedPciItems || []
      pcis.forEach((pci, i) => {
        const desc = (pci.description || '').trim()
        const parts = desc ? desc.split(/\s*(?:且|以及|；|,)\s*/).map(s => s.trim()).filter(Boolean) : ['(无描述内容)']
        const items = (parts.length ? parts : [desc || '(无描述内容)']).map(q => ({
          question: q,
          answer: pci.answer || pci.resolution_condition || pci.resolution || '',
          confirmed: false,
          _loading: false,
        }))
        items.forEach((sub, j) => out.push({ pci, pciIndex: i, sub: sub, subIndex: j }))
      })
      return out
    },
    // 风险识别：从嵌套的 risk_points 中展开每条（兼容多种结构，同 PCI）
    parsedRiskItems() {
      try {
        const v = JSON.parse(this.editFieldValue)
        // 遍历「所有模块」展开 risk_points（不再只取第一个模块）
        return this.flattenModuleList(v, 'risk_points').map((item, idx) => {
          const { _moduleIdx, _listIdx, _module, ...pure } = item
          return { ...item, _raw: JSON.stringify(pure, null, 2), _idx: idx }
        })
      } catch (e) { return [] }
    },
    // ── 主页面展示用：基于 proto.xxx_json（非弹窗 editFieldValue）──
    mainPageParsedRisks() {
      try {
        const raw = this.proto && this.proto.risks_json
        if (!raw) return []
        // 遍历所有模块展开 risk_points（不再只取第一个模块）
        return this.flattenModuleList(JSON.parse(raw), 'risk_points')
      } catch (e) { return [] }
    },
    mainPageParsedPci() {
      try {
        const raw = this.proto && this.proto.pci_json
        if (!raw) return []
        // 遍历所有模块展开 pci_list（不再只取第一个模块）
        return this.flattenModuleList(JSON.parse(raw), 'pci_list')
      } catch (e) { return [] }
    },
    // 主页面 PCI 扁平展示（同 flatPciItems 逻辑，但基于 proto）
    // 优先使用保存的结构化子问题 sub_questions，使每个子问题分别展示各自独立的答案；
    // 无 sub_questions 的旧数据回退到「按描述拆分 + 共用 PCI 汇总 answer」。
    mainPageFlatPci() {
      const out = []
      const pcis = this.mainPageParsedPci || []
      pcis.forEach((pci, i) => {
        const subs = pci.sub_questions
        const fallbackAnswer = pci.answer || pci.resolution_condition || pci.resolution || ''
        if (Array.isArray(subs) && subs.length) {
          subs.forEach((s, j) => {
            out.push({
              pci, pciIndex: i,
              question: s.question || '',
              subIndex: j,
              // 兼容旧数据：历史版本可能只保存 PCI 顶层结论，
              // 同时留下 answer 为空的 sub_questions，外层展示需回退顶层答案。
              answer: s.answer || fallbackAnswer,
            })
          })
        } else {
          const desc = (pci.description || '').trim()
          const parts = desc ? desc.split(/\s*(?:且|以及|；|,)\s*/).map(s=>s.trim()).filter(Boolean) : ['(无描述内容)']
          const answer = fallbackAnswer
          ;(parts.length ? parts : [desc || '(无描述内容)']).forEach((q, j) => {
            out.push({ pci, pciIndex: i, question: q, subIndex: j, answer })
          })
        }
      })
      return out
    },
    // ── 主页面：合并去重后测试点 ──
    mainPageTestpoints() {
      try {
        const raw = this.proto && this.proto.final_testpoints_json
        if (!raw) return []
        const v = JSON.parse(raw)
        return Array.isArray(v) ? v : (Array.isArray(v.testpoints) ? v.testpoints : [])
      } catch (e) { return [] }
    },
    // ── 主页面：测试用例（按模块分组，兼容嵌套包裹）──
    mainPageTestcases() {
      try {
        const raw = this.proto && this.proto.testcases_json
        if (!raw) return []
        const v = JSON.parse(raw)
        const arr = Array.isArray(v) ? v : []
        const groups = {}
        let total = 0
        arr.forEach((tc, rawIdx) => {
          const real = tc.testcase || tc
          const mod = (tc.module || real.module || real.feature_module) || '未分组'
          if (!groups[mod]) groups[mod] = []
          groups[mod].push({ ...real, module: mod, _rawIndex: rawIdx })
          total++
        })
        return { groups: Object.keys(groups).map(k => ({ module: k, items: groups[k] })), total }
      } catch (e) { return { groups: [], total: 0 } }
    },
    // ── 主页面：冒烟用例（同测试用例结构）──
    mainPageSmoke() {
      try {
        const raw = this.proto && this.proto.smoke_json
        if (!raw) return []
        const v = JSON.parse(raw)
        // 兼容技能原始输出 {smoke_overview, smoke_testcases, execution_suggestion} 或纯数组
        const src = Array.isArray(v) ? v
          : (v && Array.isArray(v.smoke_testcases) ? v.smoke_testcases : [])
        const arr = src.map(tc => this.normalizeSmokeCase(tc))
        const groups = {}
        let total = 0
        arr.forEach((tc, rawIdx) => {
          const real = tc.testcase || tc
          const mod = (tc.module || real.module || real.feature_module) || '未分组'
          if (!groups[mod]) groups[mod] = []
          groups[mod].push({ ...real, module: mod, _rawIndex: rawIdx })
          total++
        })
        return { groups: Object.keys(groups).map(k => ({ module: k, items: groups[k] })), total }
      } catch (e) { return { groups: [], total: 0 } }
    },
    // ── 主页面：质量自检报告 ──
    mainPageQuality() {
      try {
        const raw = this.proto && this.proto.quality_report_json
        if (!raw) return null
        return JSON.parse(raw)
      } catch (e) { return null }
    },
  },
}
</script>

<style scoped>
.modao-skill { padding: 20px 28px; max-width: 1100px; margin: 0 auto; }
.page-header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.page-header h2 { margin: 0 4px 0 0; }
.header-actions { margin-left: auto; display: flex; gap: 8px; }
.history-card { margin: 16px 0; }
.empty-hint { color: #999; font-size: 13px; padding: 8px 0; }
.subtitle { color: #888; margin: 0 0 16px; font-size: 13px; }
.steps { margin-bottom: 22px; }
.stage-card { margin-bottom: 16px; }
.md-box, .json-box {
  background: #0f172a; color: #e2e8f0; padding: 14px; border-radius: 8px;
  max-height: 460px; overflow: auto; font-size: 12.5px; line-height: 1.6; white-space: pre-wrap;
  margin-top: 12px;
}
.artifact { margin-top: 14px; }
/* 阶段3产物筛选标签页 */
.stage3-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
.form-hint { font-size: 12px; color: #909399; line-height: 1.5; margin-top: 4px; }
.stage3-filter-bar { margin: 14px 0 6px; }
.stage3-tabs { flex-wrap: wrap; }
.stage3-tabs :deep(.el-radio-button__inner) { font-size: 12px; padding: 6px 10px; }
.stage3-tabs :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-left-color: #dcdfe6;
}
/* 逐条采纳按钮 */
.main-page-card-head .el-button.el-button--extra-mini {
  font-size: 11px; padding: 2px 8px; margin-left: auto; flex-shrink: 0;
}
.adopted-badge {
  font-size: 11px; color: #67c23a; margin-left: auto; white-space: nowrap;
}
.artifact h4 { margin: 0 0 4px; color: #1f2937; }
.artifact-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.artifact-head .hint { color: #9ca3af; font-size: 12px; }
.clarify-item {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; margin-top: 12px;
  background: #fff;
}
.clarify-item-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.clarify-loc { color: #6b7280; font-size: 12px; }
.clarify-issue { color: #1f2937; font-size: 13px; line-height: 1.7; margin-top: 8px; }
.clarify-suggest { color: #374151; font-size: 12.5px; line-height: 1.7; margin-top: 6px; background: #f3f4f6; border-radius: 6px; padding: 6px 10px; }
.clarify-impact { color: #6b7280; font-size: 12px; margin-top: 6px; }
.edit-actions { margin-top: 8px; display: flex; gap: 8px; }
.mt { margin-top: 12px; }
.expand-detail { padding: 8px 16px; background: #f8f9fb; border-radius: 4px; }
.log-section { margin-bottom: 10px; }
.log-section h4 { margin: 0 0 6px; color: #1f2937; font-size: 13px; }
.log-box {
  background: #fff; color: #374151; padding: 10px; border-radius: 6px;
  max-height: 300px; overflow: auto; font-size: 12px; line-height: 1.7;
  white-space: pre-wrap; font-family: 'Courier New', monospace; border: 1px solid #e5e7eb;
}
.error-section h4 { color: #dc2626; }
.error-box { color: #dc2626; background: #fef2f2; border-color: #fecaca; }

/* 编辑产物弹窗 - 结构化视图 */
.edit-dlg-head { display: flex; align-items: center; margin-bottom: 12px; }
.structured-view { max-height: 62vh; overflow-y: auto; padding-right: 4px; }
.raw-mode { max-height: 62vh; overflow-y: auto; }
.mono-font .el-textarea__inner { font-family: 'Courier New', Consolas, monospace; font-size: 12px; line-height: 1.6; }
.tc-group { margin-bottom: 20px; }
.tc-group-title {
  font-size: 14px; color: #1f2937; background: #eff6ff;
  padding: 8px 12px; border-radius: 6px; border-left: 3px solid #3b82f6; margin-bottom: 10px;
}
.tc-card {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; margin-top: 8px;
  background: #fff; transition: box-shadow .15s;
}
.tc-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.tc-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.tc-card-head b { color: #1f2937; font-size: 13.5px; }
.tc-id { color: #6b7280; font-size: 11.5px; font-family: monospace; background: #f3f4f6; padding: 1px 6px; border-radius: 4px; }
.tc-card-body > div { font-size: 13px; line-height: 1.7; color: #374151; margin-bottom: 4px; }
.tc-steps { padding-left: 18px; margin: 6px 0; }
.tc-steps li { font-size: 13px; line-height: 1.7; color: #4b5563; margin-bottom: 2px; }
.tc-expected { color: #059669; }
.tc-ref { color: #4b5563; background: #f8fafc; border-radius: 6px; padding: 4px 8px; font-size: 12px; }
.tc-notes { color: #6b7280; font-size: 12.5px; }
.tp-card {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px;
  background: #fff;
}
.tp-card b { color: #1f2937; font-size: 13.5px; }
.tp-card p { color: #6b7280; font-size: 12.5px; margin: 4px 0 8px; line-height: 1.6; }
.json-box {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
  padding: 16px; font-family: 'Courier New', Consolas, monospace;
  font-size: 12px; line-height: 1.65; white-space: pre-wrap; word-break: break-all;
  max-height: 55vh; overflow-y: auto;
}

/* 通用 JSON 卡片列表 */
.generic-json-list { display: flex; flex-direction: column; gap: 12px; }
.generic-json-card {
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px 16px;
  background: #fff; transition: box-shadow .15s;
}
.generic-json-card:hover { box-shadow: 0 2px 10px rgba(0,0,0,.07); }
.generic-card-head {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #f0f0f0;
}
.generic-card-index {
  background: #3b82f6; color: #fff; font-size: 11px; font-weight: 600;
  width: 24px; height: 24px; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center;
}
.generic-card-title { color: #1f2937; font-size: 14px; font-weight: 600; }
.generic-card-id { color: #6b7280; font-size: 12px; font-family: monospace; }
.generic-card-body { display: flex; flex-direction: column; gap: 5px; }
.generic-field { display: flex; gap: 6px; font-size: 12.5px; line-height: 1.7; }
.generic-field-key {
  color: #6b7280; min-width: 90px; flex-shrink: 0;
  font-weight: 500; position: relative; padding-left: 10px;
}
.generic-field-key::before { content: '•'; position: absolute; left: 0; color: #93c5fd; }
.generic-field-val { color: #374151; word-break: break-all; }

/* ── 主页面结构化卡片（风险/PCI 只读展示）── */
.main-page-risk-list, .main-page-pci-list {
  display: flex; flex-direction: column; gap: 10px; margin-top: 8px;
}
.main-page-risk-card, .main-page-pci-card {
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 14px;
  background: #fff; transition: box-shadow .15s;
}
.main-page-risk-card:hover, .main-page-pci-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.main-page-card-head {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid #f3f4f6;
}
.main-page-card-edit { margin-left: auto; padding: 0 4px; }
.main-page-card-desc {
  color: #374151; font-size: 13px; line-height: 1.7;
}
.main-page-card-extra {
  color: #6b7280; font-size: 12px; margin-top: 6px; line-height: 1.6;
}
/* 区块标题行：标题 + 右侧编辑按钮 */
.artifact-head-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; margin-bottom: 4px;
}
.artifact-head-row h4 { margin: 0; color: #1f2937; }
.artifact-head-row .el-button { padding: 0 2px; }

/* 合并测试点卡片 */
.main-page-tp-list { display: flex; flex-direction: column; gap: 10px; margin-top: 8px; }
.main-page-tp-card {
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 14px;
  background: #fff; transition: box-shadow .15s;
}
.main-page-tp-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.06); }

/* 测试用例 / 冒烟用例分组卡片 */
.main-page-tc-wrap { display: flex; flex-direction: column; gap: 14px; margin-top: 8px; }
.main-page-tc-group-title { margin: 0 0 8px; color: #374151; font-size: 14px; }
.main-page-tc-card {
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 14px;
  background: #fff; margin-bottom: 10px; transition: box-shadow .15s;
}
.main-page-tc-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.main-page-tc-steps { margin: 6px 0 0; padding-left: 20px; color: #374151; font-size: 12.5px; line-height: 1.7; }
.tc-expected { color: #047857; }

/* 质量自检报告 */
.main-page-quality {
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 16px;
  background: #fff; margin-top: 8px; display: flex; flex-direction: column; gap: 8px;
}
.main-page-quality-row { display: flex; gap: 10px; font-size: 13px; line-height: 1.6; }
.main-page-quality-key {
  color: #6b7280; min-width: 100px; flex-shrink: 0; font-weight: 500;
}
.main-page-quality-val { color: #374151; word-break: break-all; }
.quality-json {
  background: #f8fafc; border: 1px solid #eef2f7; border-radius: 6px;
  padding: 8px 10px; margin: 0; font-size: 12px; max-height: 240px; overflow: auto;
  white-space: pre-wrap; color: #334155;
}

/* PCI 卡片 */
.pci-card {
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px 16px;
  background: #fff; transition: box-shadow .15s;
}
.pci-card:hover { box-shadow: 0 2px 10px rgba(0,0,0,.07); }
.pci-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.pci-source { color: #6b7280; font-size: 12px; font-family: monospace; }
.pci-card-desc {
  color: #1f2937; font-size: 13px; line-height: 1.75; margin-bottom: 8px;
  padding: 8px 12px; background: #fefce8; border-radius: 6px; border-left: 3px solid #eab308;
}
.pci-q-badge {
  display: inline-block; margin-right: 6px; padding: 0 6px; background: #eab308; color: #fff;
  border-radius: 4px; font-size: 11px; font-weight: 600; vertical-align: middle;
}
.pci-reply-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.pci-reply-head .pci-reply-label { margin-bottom: 0; }
.pci-blocked { margin-bottom: 8px; }
.pci-blocked b { color: #dc2626; font-size: 12.5px; }
.pci-bs-tag {
  display: inline-block; margin: 2px 4px 2px 0; padding: 1px 8px;
  background: #fef2f2; color: #dc2626; border-radius: 4px; font-size: 11.5px;
}
.pci-reply-section { margin-top: 10px; padding-top: 10px; border-top: 1px dashed #e5e7eb; }
.pci-reply-label { display: block; font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 6px; }

/* 风险卡片 */
.risk-card {
  border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px 16px;
  background: #fff; transition: box-shadow .15s;
}
.risk-card:hover { box-shadow: 0 2px 10px rgba(0,0,0,.07); }
.risk-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.risk-card-desc {
  color: #1f2937; font-size: 13px; line-height: 1.75; margin-bottom: 8px;
  padding: 8px 12px; background: #fef2f2; border-radius: 6px; border-left: 3px solid #ef4444;
}
.risk-related { margin-bottom: 8px; font-size: 12.5px; color: #4b5563; }

/* PCI 子问题拆解 */
.pci-split-btn-wrap {
  display: flex; align-items: center; gap: 10px;
  padding: 12px; background: #f0fdf4; border-radius: 8px;
  border: 1px dashed #86efac; margin-top: 10px;
}
.hint-text { color: #9ca3af; font-size: 12px; }
.pci-sub-list { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
.pci-sub-card {
  border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px;
  background: #fff; transition: all .2s;
}
.pci-sub-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.pci-sub-confirmed {
  background: #f0fdf4; border-color: #86efac;
  opacity: 0.85;
}
.pci-sub-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.pci-sub-index {
  display: inline-block; width: 26px; height: 26px; line-height: 26px;
  text-align: center; background: #3b82f6; color: #fff;
  border-radius: 50%; font-size: 12px; font-weight: 700;
}
.pci-sub-q {
  font-size: 13px; line-height: 1.7; color: #1f2937;
  padding: 6px 10px; background: #fefce8; border-radius: 6px;
  border-left: 3px solid #eab308; margin-bottom: 8px;
}
.pci-sub-a-wrap { display: flex; gap: 6px; align-items: flex-start; }
.pci-sub-a-label {
  font-weight: 600; color: #059669; font-size: 13px;
  white-space: nowrap; margin-top: 4px;
}
.pci-sub-a-text {
  flex: 1;
  font-size: 13px; line-height: 1.7; color: #065f46;
  padding: 6px 10px; background: #ecfdf5; border-radius: 6px;
  border-left: 3px solid #10b981;
  white-space: pre-wrap; word-break: break-word;
}
.pci-sub-summary {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: #f8fafc; border-radius: 6px;
  font-size: 12.5px; color: #6b7280; margin-top: 8px;
}
.pci-sub-qbadge {
  display: inline-block; padding: 0 7px; background: #3b82f6; color: #fff;
  border-radius: 4px; font-size: 11px; font-weight: 700; line-height: 18px;
}
.pci-sub-foot {
  display: flex; align-items: center; gap: 12px; margin-top: 8px;
  padding-top: 8px; border-top: 1px dashed #e5e7eb;
}
</style>
