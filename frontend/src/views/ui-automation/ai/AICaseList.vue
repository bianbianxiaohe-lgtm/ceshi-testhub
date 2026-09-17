<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">AI 用例管理</h1>
    </div>

    <div class="card-container">
      <div class="filter-bar">
        <el-select
          v-model="selectedProject"
          placeholder="选择项目"
          filterable
          clearable
          style="width: 260px;"
          @change="handleProjectChange"
        >
          <el-option
            v-for="p in allProjects"
            :key="p.id"
            :label="`${p.name}（${p.source === 'ui' ? 'UI' : 'AI'}）`"
            :value="p.id"
          />
        </el-select>
        <el-input
          v-model="searchText"
          placeholder="搜索用例名称或描述"
          clearable
          @input="handleSearch"
          style="width: 300px; margin-left: 12px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="openCreate" style="margin-left: 12px;">
          <el-icon><Plus /></el-icon>
          新建用例
        </el-button>
      </div>

      <el-table :data="cases" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="用例名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="执行模式" width="140" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.execution_mode === 'midscene'" type="warning" size="small">
              Midscene APP
            </el-tag>
            <el-tag v-else-if="row.execution_mode === 'midscene_web'" type="success" size="small">
              Midscene Web
            </el-tag>
            <el-tag v-else type="info" size="small">文本模式</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="140" show-overflow-tooltip />
        <el-table-column prop="task_description" label="任务描述" min-width="200" show-overflow-tooltip />
        <el-table-column label="执行设备" min-width="190">
          <template #default="{ row }">
            <!-- 设备在编辑用例时选定，这里把它显示出来，避免执行时不知道会跑在哪台机器上 -->
            <template v-if="row.device_detail">
              <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                <span>{{ row.device_detail.name }}</span>
                <el-tag :type="deviceStatusTagType(row.device_detail.status)" size="small" effect="light">
                  {{ row.device_detail.status_display }}
                </el-tag>
              </div>
              <div style="color: #909399; font-size: 12px; margin-top: 2px;">
                {{ row.device_detail.platform }} {{ row.device_detail.platform_version }}
              </div>
            </template>
            <span v-else-if="row.execution_mode === 'midscene'" style="color: #f56c6c;">未配置设备</span>
            <span v-else style="color: #c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="执行方式" width="110" align="center">
          <template #default="{ row }">
            <!-- 第一次用自然语言跑通后会自动固化坐标，之后走纯坐标回放、不调模型 -->
            <el-tag v-if="row.steps_frozen_at" type="success" size="small" effect="plain">
              脚本回放
            </el-tag>
            <el-tag v-else-if="row.execution_mode === 'midscene'" type="warning" size="small" effect="plain">
              AI 探索
            </el-tag>
            <span v-else style="color: #c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" :formatter="formatDate" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="runCase(row)">
              <el-icon><VideoPlay /></el-icon>
              执行
            </el-button>
            <el-button size="small" type="primary" @click="editCase(row)">
              <el-icon><Edit /></el-icon>
              编辑
            </el-button>
            <el-button size="small" type="danger" @click="deleteCase(row.id)">
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="pagination.currentPage"
          v-model:page-size="pagination.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </div>

    <!-- 执行对话框：执行时选设备 -->
    <!-- 设备也可以在「编辑用例」里预设，但实际执行经常需要临时换一台，
         所以在点「执行」时给一个明确的选择入口，并且只列出【在线】设备。 -->
    <el-dialog
      v-model="showRunDialog"
      title="执行用例"
      width="560px"
      :close-on-click-modal="false"
    >
      <div v-if="runTargetCase">
        <el-descriptions :column="1" border size="small" style="margin-bottom: 16px;">
          <el-descriptions-item label="用例名称">{{ runTargetCase.name }}</el-descriptions-item>
          <el-descriptions-item label="执行模式">
            <el-tag v-if="runTargetCase.execution_mode === 'midscene'" type="warning" size="small">Midscene APP</el-tag>
            <el-tag v-else-if="runTargetCase.execution_mode === 'midscene_web'" type="success" size="small">Midscene Web</el-tag>
            <el-tag v-else type="info" size="small">文本模式</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="runTargetCase.device_detail" label="原绑定设备">
            {{ runTargetCase.device_detail.name }}
            <span style="color:#909399;font-size:12px;">（{{ runTargetCase.device_detail.platform }} {{ runTargetCase.device_detail.platform_version }}）</span>
          </el-descriptions-item>
        </el-descriptions>

        <el-form label-width="90px">
          <el-form-item label="执行设备" required>
            <!-- 多选：选中的设备会「同一用例并行各跑一遍」，最多 MAX_RUN_DEVICES 台 -->
            <el-select
              v-model="runDeviceIds"
              multiple
              collapse-tags
              collapse-tags-tooltip
              :multiple-limit="MAX_RUN_DEVICES"
              placeholder="请选择设备（可多选，最多 3 台）"
              filterable
              style="width: 100%;"
              :loading="devicesLoading"
            >
              <!-- 在线设备排在最前面，离线设备置灰但仍可见，
                   让用户一眼看出「有哪些设备、哪台能用」。 -->
              <el-option
                v-for="dev in sortedRunDevices"
                :key="dev.id"
                :value="dev.id"
                :label="`${dev.name}（${dev.platform} ${dev.platform_version}）`"
                :disabled="dev.status !== 'online'"
              >
                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
                  <span class="run-dev-name">
                    <el-tag
                      :type="deviceStatusTagType(dev.status)"
                      size="small"
                      effect="light"
                      style="margin-right:6px;"
                    >{{ deviceStatusLabel(dev.status) }}</el-tag>
                    <span :style="{ color: dev.status === 'online' ? '' : '#c0c4cc' }">{{ dev.name }}</span>
                  </span>
                  <span style="color:#909399;font-size:12px;white-space:nowrap;">
                    {{ dev.platform }} {{ dev.platform_version }} · {{ dev.udid }}
                  </span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>

          <!-- 选中若干台时，明确告知「会并行跑几份」，避免误以为只是切换设备 -->
          <el-form-item v-if="runDeviceIds.length > 1" label=" ">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              :title="`将在 ${runDeviceIds.length} 台设备上并行执行同一用例`"
              description="每台设备会产生一条独立执行记录（各自有日志、截图和模型消耗）。"
            />
          </el-form-item>

          <el-form-item v-if="runDeviceIds.length === 1" label=" ">
            <div class="run-device-hint">
              <el-tag type="success" size="small" effect="light">在线</el-tag>
              <span class="run-device-hint-text">
                {{ selectedRunDeviceHint }}
              </span>
            </div>
          </el-form-item>

          <el-form-item v-if="sortedRunDevices.length === 0" label=" ">
            <el-alert
              type="warning"
              :closable="false"
              show-icon
              title="没有可用的设备"
              description="还没有录入任何设备。请先在「设备管理」里扫描或手动新增设备。"
            />
          </el-form-item>

          <el-form-item v-else-if="onlineDevices.length === 0" label=" ">
            <el-alert
              type="warning"
              :closable="false"
              show-icon
              title="当前没有在线设备"
              description="请先启动设备上的 WDA 服务（iOS 运行“一键启动WDA”脚本）或连接安卓设备，再点「刷新设备」后执行。"
            />
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button
          :loading="devicesLoading"
          style="float:left;"
          @click="refreshRunDevices"
        >
          刷新设备
        </el-button>
        <el-button @click="showRunDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="runSubmitting"
          :disabled="runDeviceIds.length === 0"
          @click="confirmRun"
        >
          {{ runDeviceIds.length > 1 ? `开始执行（${runDeviceIds.length} 台）` : '开始执行' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑对话框 -->
    <el-dialog v-model="showEditDialog" :title="currentCaseId ? '编辑 AI 用例' : '新建 AI 用例'" :close-on-click-modal="false" :close-on-press-escape="false" :modal="true" :destroy-on-close="false" width="860px">
      <el-form :model="editForm" :rules="formRules" ref="editFormRef" label-width="100px">
        <el-form-item label="用例名称" prop="name">
          <el-input v-model="editForm.name" placeholder="请输入用例名称" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="editForm.description" type="textarea" placeholder="请输入用例描述" />
        </el-form-item>

        <el-form-item label="执行模式" prop="execution_mode">
          <el-radio-group v-model="editForm.execution_mode">
            <el-radio value="text">文本模式(browser-use)</el-radio>
            <el-radio value="midscene">Midscene APP 自动化</el-radio>
            <el-radio value="midscene_web">Midscene Web 自动化</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- 文本模式：自然语言任务描述 -->
        <template v-if="editForm.execution_mode === 'text'">
          <el-form-item label="任务描述" prop="task_description" :rules="[{ required: true, message: '请输入自然语言任务描述', trigger: 'blur' }]">
            <el-input
              v-model="editForm.task_description"
              type="textarea"
              :rows="6"
              placeholder="请输入自然语言任务描述"
            />
          </el-form-item>
        </template>

        <!-- Midscene Web 模式：目标网址/结构化步骤 -->
        <template v-if="editForm.execution_mode === 'midscene_web'">
          <el-form-item label="目标网址" prop="base_url" :rules="[{ required: true, message: '请输入目标网址', trigger: 'blur' }]">
            <el-input v-model="editForm.base_url" placeholder="https://example.com" />
          </el-form-item>

          <el-form-item label="结构化步骤">
            <div class="steps-editor">
              <!-- 自然语言直接生成步骤（Web 模式同样支持） -->
              <div class="nl-box">
                <el-input
                  v-model="nlText"
                  type="textarea"
                  :rows="3"
                  placeholder="用大白话描述操作，AI 自动拆成结构化步骤。例如：打开首页，点击登录按钮，在用户名输入框中输入 admin，点击提交"
                />
                <div class="nl-actions">
                  <el-button
                    type="primary"
                    size="small"
                    :loading="nlGenerating"
                    @click="handleGenerateSteps"
                  >
                    <el-icon><MagicStick /></el-icon>
                    AI 生成步骤
                  </el-button>
                  <span class="hint">
                    生成的步骤会<strong>替换</strong>当前步骤列表，保存前你可以逐条修改；一个动作一步，失败时好定位
                  </span>
                </div>
              </div>

              <div class="steps-toolbar">
                <el-button size="small" type="primary" @click="addStep">+ 新增步骤</el-button>
                <span class="hint">使用自然语言描述操作，如“点击登录按钮”“在搜索框输入关键词”</span>
              </div>

              <div v-for="(step, index) in editForm.steps" :key="index" class="step-card">
                <div class="step-head">
                  <span class="step-no">步骤 {{ index + 1 }}</span>
                  <el-button size="small" type="danger" @click="removeStep(index)">删除</el-button>
                </div>

                <el-row :gutter="10">
                  <el-col :span="8">
                    <el-form-item label="操作类型">
                      <el-select v-model="step.action" size="small">
                        <el-option value="aiAct" label="aiAct（自然语言执行）" />
                        <el-option value="aiTap" label="aiTap（点击）" />
                        <el-option value="aiInput" label="aiInput（输入）" />
                        <el-option value="aiQuery" label="aiQuery（提取）" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                  <el-col :span="16">
                    <el-form-item label="步骤名称">
                      <el-input v-model="step.name" size="small" placeholder="可选" />
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-form-item label="自然语言指令">
                  <el-input v-model="step.prompt" type="textarea" :rows="2" placeholder="用语义描述，禁止写坐标" />
                </el-form-item>

                <el-form-item v-if="step.action === 'aiInput'" label="输入值">
                  <el-input v-model="step.value" placeholder="要输入的内容" />
                </el-form-item>
              </div>

              <el-empty v-if="editForm.steps.length === 0" description="点击「+ 新增步骤」开始编辑" />
            </div>
          </el-form-item>
        </template>

        <!-- Midscene APP 模式：应用/设备/结构化步骤 -->
        <template v-if="editForm.execution_mode === 'midscene'">
          <el-form-item label="应用配置" prop="app_config" :rules="[{ required: true, message: '请选择被测应用', trigger: 'change' }]">
            <el-select v-model="editForm.app_config" placeholder="选择被测应用" filterable style="width: 100%;">
              <el-option
                v-for="cfg in appConfigs"
                :key="cfg.id"
                :label="`${cfg.name}（${cfg.platform}）`"
                :value="cfg.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="执行设备" prop="device" :rules="[{ required: true, message: '请选择执行设备', trigger: 'change' }]">
            <el-select v-model="editForm.device" placeholder="选择真机/模拟器" filterable style="width: 100%;">
              <el-option
                v-for="dev in devices"
                :key="dev.id"
                :label="`${dev.name}（${dev.udid}）`"
                :value="dev.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="弹窗处理">
            <el-checkbox v-model="editForm.auto_dismiss_popup">自动处理弹窗</el-checkbox>
            <div class="form-hint">
              执行时遇到权限请求、隐私协议、开屏广告等弹窗会自动关闭并重试该步骤。
              如果这条用例本身就是要验证弹窗，请取消勾选。
            </div>
          </el-form-item>

          <el-form-item label="执行方式">
            <div v-if="currentCaseFrozenAt" class="frozen-hint">
              <el-tag type="success" size="small">脚本回放</el-tag>
              <span class="frozen-hint-text">
                已于 {{ formatDateTime(currentCaseFrozenAt) }} 固化坐标，执行时按坐标回放、不调用视觉模型。
              </span>
              <el-button link type="danger" size="small" @click="unfreezeCase">
                清除固化
              </el-button>
            </div>
            <div v-else class="form-hint">
              首次执行会用 AI 探索并自动采集每步坐标；跑通后自动固化为脚本，
              之后重复执行走纯坐标回放，不再消耗模型 token。
            </div>
          </el-form-item>



          <el-form-item label="结构化步骤">
            <div class="steps-editor">
              <!-- 自然语言直接生成步骤：不必先建公共步骤 -->
              <div class="nl-box">
                <el-input
                  v-model="nlText"
                  type="textarea"
                  :rows="3"
                  placeholder="用大白话描述操作，AI 自动拆成结构化步骤。例如：启动万年历，点击底部天气tab，点击左上角+，进入城市管理页面，点击添加城市，点击上海，回到城市管理，点击上海"
                />
                <div class="nl-actions">
                  <el-button
                    type="primary"
                    size="small"
                    :loading="nlGenerating"
                    @click="handleGenerateSteps"
                  >
                    <el-icon><MagicStick /></el-icon>
                    AI 生成步骤
                  </el-button>
                  <span class="hint">
                    生成的步骤会<strong>替换</strong>当前步骤列表，保存前你可以逐条修改；一个动作一步，失败时好定位
                  </span>
                </div>
              </div>

              <div class="steps-toolbar">
                <el-button size="small" @click="loadNeutralExample">载入中性示例</el-button>
                <el-button size="small" type="primary" @click="addStep">+ 新增步骤</el-button>
                <span class="hint">业务无关：步骤里的 extract 可提取任意数据写入上下文，后续步骤用 <code>${{ '{' }}key{{ '}' }}</code> 引用</span>
              </div>

              <div v-for="(step, idx) in editForm.steps" :key="idx" class="step-card" :class="{ 'step-card--ref': stepSource(step) === 'ref' }">
                <div class="step-head">
                  <span class="step-no">步骤 {{ idx + 1 }}</span>
                  <el-tag v-if="stepSource(step) === 'ref'" size="small" type="warning" style="margin-left: 8px">引用公共步骤</el-tag>
                  <el-button size="small" type="danger" text @click="removeStep(idx)">删除</el-button>
                </div>

                <!-- 步骤来源：直接操作 / 引用公共步骤
                     刻意不用 el-radio-button：不同 Element Plus 版本的取值属性
                     是 value / label 来回变，点不动的坑踩过一次，按钮最稳。
                     模式判定统一走 stepSource()（依赖不会丢的 _src 标记），
                     不要再直接判断 step.ref 是否存在。 -->
                <el-form-item label="来源" label-width="50px">
                  <el-button
                    size="small"
                    :type="stepSource(step) === 'inline' ? 'primary' : 'default'"
                    @click="switchStepSource(step, 'inline')"
                  >直接操作</el-button>
                  <el-button
                    size="small"
                    :type="stepSource(step) === 'ref' ? 'primary' : 'default'"
                    style="margin-left: 8px"
                    @click="switchStepSource(step, 'ref')"
                  >引用公共步骤</el-button>
                  <span v-if="!businessActions.length" class="ref-warn">
                    公共步骤库为空，请先到左侧「公共步骤库」新建
                  </span>
                </el-form-item>

                <!-- 历史空壳步骤：既没选引用也没填提示词，执行时会被引擎判失败。
                     必须显式提示，否则用户以为"步骤还在"，其实是空的。 -->
                <el-alert
                  v-if="stepSource(step) === 'inline' && !String(step.action || '').trim() && !String(step.prompt || '').trim()"
                  type="error"
                  :closable="false"
                  show-icon
                  title="这是一个空步骤：没有动作也没有提示词，执行时一定会失败"
                  description="请填写下方「提示词」，或删除该步骤。若你原本选的是公共步骤，请点上方「引用公共步骤」重新选择。"
                  style="margin-bottom: 10px"
                />

                <!-- 引用模式：选公共步骤 + 可选覆盖 -->
                <template v-if="stepSource(step) === 'ref'">
                  <el-form-item label="公共步骤" label-width="70px" :required="true">
                    <el-select v-model="step.ref" placeholder="选择公共步骤" filterable clearable style="width: 100%;">
                      <el-option-group v-for="grp in businessActionGroups" :key="grp.label" :label="grp.label">
                        <el-option
                          v-for="a in grp.items"
                          :key="a.name"
                          :label="a.name + (a.description ? '（' + a.description + '）' : '')"
                          :value="a.name"
                        />
                      </el-option-group>
                    </el-select>
                    <div v-if="step.ref && !actionExists(step.ref)" class="ref-warn">
                      公共步骤「{{ step.ref }}」已不存在（可能被删除），执行时该步会被跳过，请重新选择
                    </div>
                    <div class="form-hint">
                      在「公共步骤库」里维护；改一次，所有引用它的用例同步生效
                    </div>
                  </el-form-item>
                  <el-form-item label="输入覆盖" label-width="70px">
                    <el-input v-model="step.value" placeholder="可选：覆盖公共步骤里的输入值，如账号/搜索词" />
                  </el-form-item>
                  <el-form-item label="等待(ms)" label-width="70px">
                    <el-input-number v-model="step.wait_ms" :min="0" :step="500" controls-position="right" />
                  </el-form-item>
                </template>


                <!-- 直接操作模式：原有字段 -->
                <template v-else>
                  <el-row :gutter="12">
                    <el-col :span="8">
                      <el-form-item label="动作" :prop="`steps.${idx}.action`" label-width="50px" :required="true">
                        <el-select v-model="step.action" placeholder="action">
                          <el-option label="aiTap 点击" value="aiTap" />
                          <el-option label="aiInput 输入" value="aiInput" />
                          <el-option label="aiAct 操作" value="aiAct" />
                          <el-option label="aiQuery 查询" value="aiQuery" />
                          <el-option label="assert 断言" value="assert" />
                          <el-option label="launch 启动" value="launch" />
                          <el-option label="back 返回" value="back" />
                          <el-option label="home 主页" value="home" />
                          <el-option label="wait 等待" value="wait" />
                          <el-option label="screenshot 截图" value="screenshot" />
                        </el-select>
                      </el-form-item>
                    </el-col>
                    <el-col :span="16">
                      <el-form-item label="名称" :prop="`steps.${idx}.name`" label-width="50px" :required="true">
                        <el-input v-model="step.name" placeholder="步骤说明（仅展示）" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-form-item label="提示词" :prop="`steps.${idx}.prompt`" label-width="50px" :required="!['launch','back','home','wait','screenshot'].includes(step.action)">
                    <el-input v-model="step.prompt" type="textarea" :rows="2" placeholder="如：点击右下角的“我的”标签；支持 ${{ '{' }}key{{ '}' }} 引用上下文" />
                  </el-form-item>
                  <el-row :gutter="12">
                    <el-col :span="12">
                      <el-form-item label="输入值" :prop="`steps.${idx}.value`" label-width="50px" :required="step.action === 'aiInput'">
                        <el-input v-model="step.value" placeholder="aiInput 时填入；支持 ${{ '{' }}key{{ '}' }}" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="等待(ms)" :prop="`steps.${idx}.wait_ms`" label-width="70px">
                        <el-input-number v-model="step.wait_ms" :min="0" :step="500" controls-position="right" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <!-- extract：提取业务数据到上下文 -->
                  <el-form-item label="提取" label-width="50px">
                    <div class="extract-list">
                      <div v-for="(ex, ei) in (step.extract || [])" :key="ei" class="extract-row">
                        <el-input v-model="ex.key" placeholder="上下文变量名 key" style="width: 130px;" />
                        <el-input v-model="ex.prompt" placeholder="提取提示词（问页面要什么）" style="flex: 1;" />
                        <el-select v-model="ex.type" style="width: 110px;">
                          <el-option label="string" value="string" />
                          <el-option label="number" value="number" />
                          <el-option label="boolean" value="boolean" />
                          <el-option label="json" value="json" />
                        </el-select>
                        <el-checkbox v-model="ex.required">必填</el-checkbox>
                        <el-button size="small" text type="danger" @click="removeExtract(step, ei)">×</el-button>
                      </div>
                      <el-button size="small" @click="addExtract(step)">+ 提取项</el-button>
                    </div>
                  </el-form-item>

                  <!-- assert：断言 -->
                  <el-form-item label="断言" label-width="50px" :required="step.action === 'assert'">
                    <div class="assert-row">
                      <el-input v-model="step.assert.prompt" placeholder="断言提示词（如：当前页面显示“登录成功”）" style="flex: 1;" />
                      <el-input v-model="step.assert.expect" placeholder="期望结论（选填）" style="width: 160px;" />
                    </div>
                  </el-form-item>
                </template>
              </div>

              <el-empty v-if="!editForm.steps.length" description="暂无步骤，点击「载入中性示例」或「新增步骤」" />
            </div>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showEditDialog = false">取消</el-button>
          <el-button type="primary" @click="confirmEdit" :loading="saving">保存</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, VideoPlay, Edit, Delete, Plus, MagicStick } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import {
  getAICases,
  createAICase,
  updateAICase,
  deleteAICase,
  runAICase,
  getAppConfigs,
  getAppDevices,
  getBusinessActions,
  generateCaseSteps,
  refreshDeviceStatus
} from '@/api/ui_automation'
import { useUnifiedProjects } from '@/utils/useUnifiedProjects'

const router = useRouter()
const { allProjects, loadProjects } = useUnifiedProjects()
const cases = ref([])
const loading = ref(false)
const searchText = ref('')
const total = ref(0)
const pagination = reactive({
  currentPage: 1,
  pageSize: 20
})

// 当前选中的统一项目（"ui_1" / "proj_2" / 空）
const selectedProject = ref('')

const appConfigs = ref([])
const devices = ref([])

// ---- 执行对话框状态 ----
// 执行时会弹框让用户确认/选择设备。只列在线设备：离线设备跑用例
// 只会得到一串无意义的失败，后端也会拒绝。
//
// 支持多选：选中的设备会「同一用例并行各跑一遍」，后端为每台各建一条
// 执行记录。上限与后端 MAX_PARALLEL_DEVICES 保持一致。
const MAX_RUN_DEVICES = 3
const showRunDialog = ref(false)
const runTargetCase = ref(null)
const runDeviceIds = ref([])
const runSubmitting = ref(false)
const devicesLoading = ref(false)

// 当前编辑中的用例是否已固化（非空即已固化为脚本回放）
const currentCaseFrozenAt = ref(null)

const formatDateTime = (v) => {
  if (!v) return ''
  return new Date(v).toLocaleString()
}

const onlineDevices = computed(() => devices.value.filter((d) => d.status === 'online'))

// 执行对话框的设备下拉排序：在线 > 占用中/异常 > 离线，同级按名称。
// 目的：让用户第一眼看到的都是能用的设备，不用在离线设备里翻找。
const RUN_STATUS_ORDER = { online: 0, busy: 1, error: 2, offline: 3 }
const sortedRunDevices = computed(() =>
  [...devices.value].sort((a, b) => {
    const oa = RUN_STATUS_ORDER[a.status] ?? 9
    const ob = RUN_STATUS_ORDER[b.status] ?? 9
    if (oa !== ob) return oa - ob
    return String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN')
  })
)

// 设备状态显示文案（与 deviceStatusTagType 配色对应）
const DEVICE_STATUS_LABELS = {
  online: '在线',
  busy: '占用中',
  error: '异常',
  offline: '离线'
}
const deviceStatusLabel = (status) => DEVICE_STATUS_LABELS[status] || status || '未知'

const selectedRunDeviceHint = computed(() => {
  const d = devices.value.find((x) => x.id === runDeviceIds.value[0])
  if (!d) return ''
  if (d.platform === 'ios') {
    return `UDID ${d.udid} · WDA ${d.wda_host || '未配置'}:${d.wda_port || 8100}`
  }
  return `UDID ${d.udid} · adb ${d.adb_host || '本机'}`
})

// 公共步骤（业务动作）列表，供步骤编辑器「引用公共步骤」下拉使用
const businessActions = ref([])
const ACTION_CATEGORY_LABELS = {
  precondition: '前置准备',
  business: '业务操作',
  extract: '数据提取',
  teardown: '收尾清理',
  other: '其他'
}
const businessActionGroups = computed(() => {
  const groups = {}
  for (const a of businessActions.value) {
    const key = a.category || 'other'
    if (!groups[key]) groups[key] = []
    groups[key].push(a)
  }
  const order = ['precondition', 'business', 'extract', 'teardown', 'other']
  return order
    .filter((k) => groups[k] && groups[k].length)
    .map((k) => ({ label: ACTION_CATEGORY_LABELS[k] || '其他', items: groups[k] }))
})

const loadBusinessActions = async () => {
  try {
    const res = await getBusinessActions({ page_size: 500 })
    businessActions.value = res.data.results || res.data || []
  } catch (e) {
    console.error('加载公共步骤失败', e)
  }
}

// 引用的公共步骤是否还存在（被删掉时下拉会显示空白，需要显式提示）
const actionExists = (name) => businessActions.value.some((a) => a.name === name)

// 步骤来源标记：'inline' = 直接操作，'ref' = 引用公共步骤。
//
// 原来用「step.ref 属性是否存在」来区分两种模式，但 ref 一旦被 delete，
// 整个步骤就只剩 {value, wait_ms} —— 既不是合法引用也不是合法内联，
// **保存时就变成永久无法恢复的空步骤**（既不知道用户选过引用，也没了提示词）。
// 这是"我明明选了公共步骤，执行却什么都没做"的根因。
// 现在改成用一个**不会丢失的显式标记 `_src`** 承载模式，ref 只承载"选了哪一条"，
// 这样即使 ref 被清空，也仍然知道用户选的是引用模式，不会退化成空壳。
const stepSource = (step) => (step && step._src === 'ref' ? 'ref' : 'inline')

// 切换「直接操作 / 引用公共步骤」时清理另一侧的残留字段，
// 否则 steps 里会同时带 prompt 和 ref，引擎按 ref 分支处理会让人困惑。
const switchStepSource = (step, source) => {
  step._src = source === 'ref' ? 'ref' : 'inline'
  if (source === 'ref') {
    delete step.action
    delete step.prompt
    delete step.name
    delete step.selector_hint
    if (step.ref === undefined || step.ref === null) step.ref = ''
    if (step.value === undefined) step.value = ''
    if (step.wait_ms === undefined) step.wait_ms = 0
  } else {
    delete step.ref
    if (!step.action) step.action = 'aiTap'
    if (step.name === undefined) step.name = ''
    if (step.prompt === undefined) step.prompt = ''
    if (step.value === undefined) step.value = ''
    if (step.wait_ms === undefined) step.wait_ms = 0
    if (!step.extract) step.extract = []
    if (!step.assert) step.assert = { prompt: '', expect: '' }
  }
}

const showEditDialog = ref(false)
const saving = ref(false)
const currentCaseId = ref(null)
const editForm = reactive({
  name: '',
  description: '',
  execution_mode: 'text',
  task_description: '',
  app_config: null,
  device: null,
  auto_dismiss_popup: true,
  base_url: '',
  steps: []
})
const editFormRef = ref(null)

const formRules = {
  name: [{ required: true, message: '请输入用例名称', trigger: 'blur' }],
  execution_mode: [{ required: true, message: '请选择执行模式', trigger: 'change' }]
}

// 中性示例（业务无关，内容型 App 演示 extract + ${{key}} 上下文传递）
const NEUTRAL_EXAMPLE = [
  {
    action: 'launch',
    name: '启动应用',
    prompt: '',
    value: '',
    wait_ms: 3000,
    extract: [],
    assert: { prompt: '', expect: '' }
  },
  {
    action: 'aiTap',
    name: '进入内容列表',
    prompt: '点击首页的“推荐”入口',
    value: '',
    wait_ms: 1500,
    extract: [],
    assert: { prompt: '推荐列表已展示', expect: '' }
  },
  {
    action: 'aiTap',
    name: '打开第一条内容',
    prompt: '点击列表中第一条内容卡片',
    value: '',
    wait_ms: 1500,
    extract: [
      { key: 'contentTitle', prompt: '当前打开内容的标题是什么？', type: 'string', required: true }
    ],
    assert: { prompt: '', expect: '' }
  },
  {
    action: 'aiAct',
    name: '操作并使用上下文',
    prompt: '对标题为“${{contentTitle}}”的内容执行点赞操作',
    value: '',
    wait_ms: 1000,
    extract: [],
    assert: { prompt: '点赞状态已变为已点赞', expect: '' }
  }
]

const loadAppOptions = async () => {
  try {
    const params = { page_size: 200 }
    if (selectedProject.value) {
      params.project = selectedProject.value
    }
    const [cfgRes, devRes] = await Promise.all([
      getAppConfigs(params),
      getAppDevices({ page_size: 200 })
    ])
    appConfigs.value = cfgRes.data.results || []
    devices.value = devRes.data.results || []
  } catch (e) {
    console.error('加载应用/设备失败', e)
  }
}

// 切换项目时重新拉取该项目下的应用配置
const handleProjectChange = () => {
  loadAppOptions()
}

// 加载用例列表
const loadCases = async () => {
  loading.value = true
  try {
    const response = await getAICases({
      page: pagination.currentPage,
      page_size: pagination.pageSize,
      search: searchText.value
    })

    cases.value = response.data.results || []
    total.value = response.data.count || 0
  } catch (error) {
    console.error('获取用例列表失败:', error)
    ElMessage.error('获取用例列表失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  pagination.currentPage = 1
  loadCases()
}

const handleSizeChange = () => {
  pagination.currentPage = 1
  loadCases()
}

const handleCurrentChange = () => {
  loadCases()
}

const resetSteps = () => {
  editForm.steps = []
}

const addStep = () => {
  editForm.steps.push({
    _src: 'inline',
    action: 'aiTap',
    name: '',
    prompt: '',
    value: '',
    wait_ms: 0,
    extract: [],
    assert: { prompt: '', expect: '' }
  })
}

const removeStep = (idx) => {
  editForm.steps.splice(idx, 1)
}

const addExtract = (step) => {
  if (!step.extract) step.extract = []
  step.extract.push({ key: '', prompt: '', type: 'string', required: false })
}

const removeExtract = (step, ei) => {
  step.extract.splice(ei, 1)
}

const loadNeutralExample = () => {
  editForm.steps = JSON.parse(JSON.stringify(NEUTRAL_EXAMPLE))
  ElMessage.success('已载入中性示例步骤')
}

// 自然语言 → 结构化步骤。只生成、不落库：生成结果先填进编辑器，
// 用户改完点「保存」才写库（避免模型幻觉直接污染用例数据）。
const nlText = ref('')
const nlGenerating = ref(false)

const handleGenerateSteps = async () => {
  const text = (nlText.value || '').trim()
  if (!text) {
    ElMessage.warning('请先用大白话描述一下操作步骤')
    return
  }
  if (editForm.steps.length) {
    try {
      await ElMessageBox.confirm(
        `当前已有 ${editForm.steps.length} 个步骤，生成会整体替换它们。确定继续吗？`,
        '提示',
        { confirmButtonText: '替换', cancelButtonText: '取消', type: 'warning' }
      )
    } catch (e) {
      return
    }
  }

  nlGenerating.value = true
  try {
    const res = await generateCaseSteps({
      text,
      app_config: editForm.app_config || undefined
    })
    const data = res.data || {}
    if (!data.success) {
      ElMessage.error(data.message || '生成失败')
      return
    }
    const steps = Array.isArray(data.steps) ? data.steps : []
    if (!steps.length) {
      ElMessage.warning('没有生成出可用步骤，请把描述写得更具体一些（指明点哪个按钮）')
      return
    }
    editForm.steps = steps.map((s) => ({
      _src: 'inline',
      action: s.action || 'aiAct',
      name: s.name || '',
      prompt: s.prompt || '',
      value: s.value || '',
      wait_ms: s.wait_ms || 0,
      extract: (s.extract || []).map((e) => ({ ...e })),
      assert: {
        prompt: (s.assert && s.assert.prompt) || '',
        expect: (s.assert && s.assert.expect) || ''
      }
    }))
    ElMessage.success(data.message || `已生成 ${steps.length} 个步骤，请确认后保存`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.message || '生成失败，请检查模型配置是否可用')
  } finally {
    nlGenerating.value = false
  }
}

// 新建用例：打开空白对话框
const openCreate = () => {
  currentCaseId.value = null
  editForm.name = ''
  editForm.description = ''
  editForm.execution_mode = 'text'
  editForm.task_description = ''
  editForm.app_config = null
  editForm.device = null
  editForm.auto_dismiss_popup = true
  editForm.steps = []
  currentCaseFrozenAt.value = null
  showEditDialog.value = true
}

// 编辑用例
const editCase = (row) => {
  currentCaseId.value = row.id
  editForm.name = row.name
  editForm.description = row.description
  editForm.execution_mode = row.execution_mode || 'text'
  editForm.task_description = row.task_description
  editForm.app_config = row.app_config || null
  editForm.device = row.device || null
  // 老用例没有这个字段，缺省视为开启（与后端 default=True 一致）
  editForm.auto_dismiss_popup = row.auto_dismiss_popup !== false
  currentCaseFrozenAt.value = row.steps_frozen_at || null
  // midscene_web 模式：base_url 存在 task_description 字段
  editForm.base_url = (row.execution_mode === 'midscene_web' && row.task_description) || ''
  // 深拷贝 steps，确保每步都有 extract/assert 结构。
  // 带 ref 的步骤是「引用公共步骤」：只回填 ref/value/wait_ms，
  // 不能补 action，否则界面会把它当成「直接操作」而丢掉引用。
  // 用 _src 显式标记模式：即使 ref 为空串，也仍然是"引用模式"，
  // 不会因为 ref 缺失退化成无法识别的空壳步骤。
  editForm.steps = Array.isArray(row.steps)
    ? row.steps.map(s => {
        if (s && s.ref !== undefined && s.ref !== null) {
          return {
            _src: 'ref',
            ref: s.ref,
            value: s.value || '',
            wait_ms: s.wait_ms || 0
          }
        }
        // 已经是空壳的历史数据（既无 action 也无 prompt）：标记为 inline 但
        // 保留原样，用户在界面上能立刻看到它是空的并被保存校验拦下，
        // 而不是被悄悄"修"成一个看起来正常的步骤。
        return {
          _src: 'inline',
          action: s.action || '',
          name: s.name || '',
          prompt: s.prompt || '',
          value: s.value || '',
          wait_ms: s.wait_ms || 0,
          extract: (s.extract || []).map(e => ({ ...e })),
          assert: { prompt: (s.assert && s.assert.prompt) || '', expect: (s.assert && s.assert.expect) || '' }
        }
      })
    : []
  showEditDialog.value = true
}

const confirmEdit = async () => {
  if (!editFormRef.value) return

  await editFormRef.value.validate(async (valid) => {
    if (valid) {
      saving.value = true
      try {
        const payload = {
          name: editForm.name,
          description: editForm.description,
          execution_mode: editForm.execution_mode
        }
        if (editForm.execution_mode === 'text') {
          payload.task_description = editForm.task_description
        } else if (editForm.execution_mode === 'midscene_web') {
          // midscene_web 模式：保存 base_url，不需要 app_config/device
          payload.task_description = editForm.base_url || ''
        } else {
          payload.app_config = editForm.app_config
          payload.device = editForm.device
          payload.auto_dismiss_popup = editForm.auto_dismiss_popup !== false

          // 引用公共步骤的步骤必须先选到具体项。
          // 之前这里漏掉 ref 字段，导致界面上选好的引用保存后消失，
          // 存进库的只剩 value/assert/extract，执行时什么都不做。
          const badRefIdx = editForm.steps.findIndex(
            (s) => stepSource(s) === 'ref' && !String(s.ref || '').trim()
          )
          if (badRefIdx >= 0) {
            ElMessage.warning(`步骤 ${badRefIdx + 1} 选择了「引用公共步骤」但没选具体步骤，请选择或改回「直接操作」`)
            saving.value = false
            return
          }

          // 空步骤拦截：只有 value/wait_ms/extract 这些附属字段、既没有 action
          // 也没有 prompt 的步骤，执行时引擎会拿空提示词去"盲操作"，
          // 结果是什么都没做却显示通过。这里直接拦住。
          // （曾出现用例只存了 {value:'',assert:null,extract:[],wait_ms:0}，
          //   执行"通过"但真机毫无动静。）
          // 注意：必须按「模式」判断，不能按 ref 属性在不在判断 ——
          // 引用模式下 ref 可能被判空，但那是上面 badRefIdx 负责的事。
          const emptyIdx = editForm.steps.findIndex(
            (s) => stepSource(s) === 'inline'
              && !String(s.action || '').trim() && !String(s.prompt || '').trim()
          )
          if (emptyIdx >= 0) {
            ElMessage.warning(`步骤 ${emptyIdx + 1} 是空的：请填写「提示词」，或删除该步骤`)
            saving.value = false
            return
          }

          // 一个步骤都没有的用例执行起来毫无意义，允许保存但必须明确告知
          if (!editForm.steps.length) {
            try {
              await ElMessageBox.confirm(
                '该用例没有任何步骤，执行时不会做任何操作。确定要保存吗？',
                '提示',
                { confirmButtonText: '仍然保存', cancelButtonText: '返回补充', type: 'warning' }
              )
            } catch (e) {
              saving.value = false
              return
            }
          }

          // 清理空 extract/assert，保持数据干净
          payload.steps = editForm.steps.map(s => {
            // 引用模式：只保留 ref + 可选覆盖字段，绝不带 action/prompt，
            // 否则引擎端会分不清这是引用还是内联步骤。
            // **ref 必须落库**：这里是"选了公共步骤却什么都没执行"的最后一道关。
            if (stepSource(s) === 'ref') {
              const refStep = { ref: String(s.ref || '').trim() }
              if (s.value) refStep.value = s.value
              if (s.wait_ms) refStep.wait_ms = s.wait_ms
              return refStep
            }
            return {
              action: s.action,
              name: s.name,
              prompt: s.prompt,
              value: s.value,
              wait_ms: s.wait_ms || 0,
              extract: (s.extract || []).filter(e => e.key && e.prompt),
              assert: (s.assert && s.assert.prompt)
                ? { prompt: s.assert.prompt, expect: s.assert.expect }
                : null
            }
          })
          // 兜底自检：上面过滤掉的步骤若有引用，立刻暴露而不是静默丢
          payload.steps.forEach((p, i) => {
            if (stepSource(editForm.steps[i]) === 'ref' && !p.ref) {
              throw new Error(`步骤 ${i + 1} 的公共步骤引用丢失，请重新选择后再保存`)
            }
          })
        }

        if (currentCaseId.value) {
          await updateAICase(currentCaseId.value, payload)
          ElMessage.success('更新成功')
        } else {
          await createAICase(payload)
          ElMessage.success('创建成功')
        }

        showEditDialog.value = false
        loadCases()
      } catch (error) {
        console.error('保存失败:', error)
        ElMessage.error('保存失败')
      } finally {
        saving.value = false
      }
    }
  })
}

// 删除用例
const deleteCase = async (id) => {
  try {
    await ElMessageBox.confirm('确定要删除该用例吗?', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })

    await deleteAICase(id)
    ElMessage.success('删除成功')
    loadCases()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      ElMessage.error('删除失败')
    }
  }
}

// 设备状态 -> el-tag 类型
const deviceStatusTagType = (status) => {
  if (status === 'online') return 'success'
  if (status === 'busy') return 'warning'
  if (status === 'error') return 'danger'
  return 'info'
}

// 拉取设备列表（供执行对话框使用）
const loadRunDevices = async ({ silent = false } = {}) => {
  devicesLoading.value = true
  try {
    const devRes = await getAppDevices({ page_size: 200 })
    devices.value = devRes.data.results || []
    return true
  } catch (e) {
    console.error('加载设备列表失败', e)
    if (!silent) ElMessage.error('加载设备列表失败')
    return false
  } finally {
    devicesLoading.value = false
  }
}

// 对话框里的「刷新设备」：重新拉列表并调后端真实探活，
// 让「刚把 WDA 起起来」的设备立刻变成在线可选。
const refreshRunDevices = async () => {
  const ok = await loadRunDevices()
  if (!ok) return
  try {
    const res = await refreshDeviceStatus()
    const results = res?.data?.results || []
    // 把探活结论并回本地列表，避免再发一次列表请求
    const byId = {}
    for (const r of results) byId[r.id] = r
    devices.value = devices.value.map((d) => (byId[d.id] ? { ...d, ...byId[d.id] } : d))
    const online = results.filter((r) => r.online).length
    if (online > 0) {
      ElMessage.success(`已刷新：${online} 台设备在线`)
    } else {
      ElMessage.warning('已刷新：当前没有在线设备')
    }
    // 之前选中的设备里，把已经离线的剔掉；一台都不剩就补第一台在线的
    const onlineIds = new Set(onlineDevices.value.map((d) => d.id))
    const kept = runDeviceIds.value.filter((id) => onlineIds.has(id))
    if (kept.length !== runDeviceIds.value.length) {
      runDeviceIds.value = kept.length
        ? kept
        : (onlineDevices.value.length ? [onlineDevices.value[0].id] : [])
    }
  } catch (e) {
    console.error('探活失败', e)
    ElMessage.error(e?.response?.data?.error || '探活失败')
  }
}

// 执行用例
// 设备在「编辑用例」里可以预设，但实际执行时经常要临时换一台，所以点
// 「执行」先弹框让用户选设备。选择只对本次执行生效，不会改写用例绑定的设备。
const runCase = async (row) => {
  // 文本 / Web 模式不依赖真机，直接执行，不弹设备框
  if (row.execution_mode !== 'midscene') {
    try {
      await runAICase(row.id)
      ElMessage.success('用例开始执行')
      router.push('/ai-intelligent-mode/execution-records')
    } catch (error) {
      console.error('执行失败:', error)
      ElMessage.error(error?.response?.data?.error || '执行失败')
    }
    return
  }

  // Midscene APP 模式：弹框选设备（可多选，并行执行）
  runTargetCase.value = row
  runDeviceIds.value = []
  showRunDialog.value = true

  // 刷新一次设备列表，保证状态是最新的（刚启动好 WDA 的设备要能立刻看到）
  await loadRunDevices()

  // 默认选中：用例原本绑定的设备（若在线），否则第一台在线设备
  const bound = devices.value.find(
    (d) => d.id === row.device && d.status === 'online'
  )
  if (bound) {
    runDeviceIds.value = [bound.id]
  } else if (onlineDevices.value.length > 0) {
    runDeviceIds.value = [onlineDevices.value[0].id]
  }
}

// 清除固化：把用例退回 AI 探索模式，下次执行会重新采坐标并重新固化。
// 界面大改、换机型导致回放总是点空时用这个。
const unfreezeCase = async () => {
  if (!currentCaseId.value) return
  try {
    await ElMessageBox.confirm(
      '清除固化后，该用例会退回 AI 探索模式：下次执行将重新用视觉模型识别每一步，' +
      '跑通后会再次自动固化。确认清除吗？',
      '清除固化',
      { type: 'warning', confirmButtonText: '清除', cancelButtonText: '取消' }
    )
  } catch (e) {
    return
  }
  try {
    // 清掉坐标 + 时间戳，同时保留其余步骤配置
    const steps = (editForm.steps || []).map((s) => {
      const copy = { ...s }
      delete copy.center_x
      delete copy.center_y
      return copy
    })
    await updateAICase(currentCaseId.value, {
      steps,
      steps_frozen_at: null
    })
    editForm.steps = steps
    currentCaseFrozenAt.value = null
    ElMessage.success('已清除固化，下次执行将重新探索')
    loadCases()
  } catch (error) {
    console.error('清除固化失败:', error)
    ElMessage.error(error?.response?.data?.detail || '清除固化失败')
  }
}

// 执行对话框里点「开始执行」
// 支持多选：选中 N 台就并行跑 N 份（后端为每台各建一条执行记录）。
const confirmRun = async () => {
  if (!runTargetCase.value || runDeviceIds.value.length === 0) return

  const picked = runDeviceIds.value
    .map((id) => devices.value.find((d) => d.id === id))
    .filter(Boolean)

  if (picked.length === 0) {
    ElMessage.error('设备不存在，请重新选择')
    return
  }
  const offline = picked.filter((d) => d.status !== 'online')
  if (offline.length) {
    ElMessage.error(
      `设备「${offline.map((d) => d.name).join('、')}」不在线，只有在线设备可以执行`
    )
    return
  }
  if (picked.length > MAX_RUN_DEVICES) {
    ElMessage.error(`一次最多同时执行 ${MAX_RUN_DEVICES} 台设备`)
    return
  }

  runSubmitting.value = true
  try {
    await runAICase(runTargetCase.value.id, picked.map((d) => d.id))
    showRunDialog.value = false
    if (picked.length > 1) {
      ElMessage.success(`已在 ${picked.length} 台设备上并行开始执行`)
    } else {
      ElMessage.success(`已在「${picked[0].name}」上开始执行`)
    }
    router.push('/ai-intelligent-mode/execution-records')
  } catch (error) {
    console.error('执行失败:', error)
    ElMessage.error(error?.response?.data?.error || '执行失败')
  } finally {
    runSubmitting.value = false
  }
}

const formatDate = (row, column, cellValue) => {
  if (!cellValue) return ''
  return new Date(cellValue).toLocaleString()
}

onMounted(() => {
  loadProjects()
  loadCases()
  loadAppOptions()
  loadBusinessActions()
})
</script>

<style lang="scss" scoped>
.page-container {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;

  .page-title {
    font-size: 20px;
    font-weight: 600;
    margin: 0;
  }
}

.card-container {
  background-color: #fff;
  border-radius: 4px;
  padding: 20px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.filter-bar {
  margin-bottom: 20px;
}

.pagination-container {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.steps-editor {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 12px;
  width: 100%;

  .nl-box {
    background: #f5f7fa;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 12px;
  }

  .nl-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 8px;
  }

  .steps-toolbar {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    flex-wrap: wrap;

    .hint {
      color: #909399;
      font-size: 12px;

      code {
        background: #f4f4f5;
        padding: 0 4px;
        border-radius: 3px;
        color: #c4561c;
      }
    }
  }

  .ref-warn {
    margin-left: 12px;
    font-size: 12px;
    color: #e6a23c;
  }

  .step-card {
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 12px;
    margin-bottom: 12px;
    background: #fafafa;

    /* 引用公共步骤的步骤用左侧色条区分，一眼能看出哪几步是复用来的 */
    &--ref {
      background: #fdf6ec;
      border-color: #f3d19e;
      border-left: 3px solid #e6a23c;
    }

    .step-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;

      .step-no {
        font-weight: 600;
        color: #409eff;
      }
    }
  }

  .extract-list {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .extract-row {
      display: flex;
      align-items: center;
      gap: 8px;
    }
  }

  .assert-row {
    display: flex;
    gap: 8px;
  }
}

.run-device-hint {
  display: flex;
  align-items: center;
  gap: 8px;

  .run-device-hint-text {
    color: #606266;
    font-size: 12px;
    font-family: monospace;
  }
}

.form-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.6;
  margin-top: 4px;
}

.frozen-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;

  .frozen-hint-text {
    color: #606266;
    font-size: 12px;
  }
}
</style>
