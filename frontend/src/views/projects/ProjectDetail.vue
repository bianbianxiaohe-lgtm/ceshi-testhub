<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">项目详情</h1>
      <el-button type="primary" @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon>
        返回
      </el-button>
    </div>

    <div class="card-container">
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <!-- 项目信息 -->
        <el-tab-pane label="项目信息" name="info">
          <div v-if="project">
            <div style="margin-bottom:12px;text-align:right;">
              <el-button type="primary" :icon="Edit" @click="openProjectEditDialog">编辑项目</el-button>
            </div>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="项目名称">{{ project.name }}</el-descriptions-item>
              <el-descriptions-item label="项目状态">
                <el-tag :type="getStatusType(project.status)">{{ getStatusText(project.status) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="负责人">{{ project.owner?.username }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatDate(project.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="项目描述" :span="2">{{ project.description || '暂无描述' }}</el-descriptions-item>
              <el-descriptions-item label="知识库目录" :span="2">
                <template v-if="project.knowledge_base_path">
                  <code style="background:#f0f2f5;padding:2px 6px;border-radius:4px">{{ project.knowledge_base_path }}</code>
                </template>
                <span v-else style="color:#c0c4cc">未配置</span>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-tab-pane>

        <!-- 项目成员 -->
        <el-tab-pane label="项目成员" name="members">
          <div class="members-section">
            <el-button type="primary" @click="showAddMemberDialog = true">添加成员</el-button>
            <el-table :data="project?.members || []" style="width: 100%; margin-top: 20px;">
              <el-table-column prop="user.username" label="用户名" />
              <el-table-column prop="user.email" label="邮箱" />
              <el-table-column prop="role" label="角色" />
              <el-table-column prop="joined_at" label="加入时间">
                <template #default="{ row }">{{ formatDate(row.joined_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="100">
                <template #default="{ row }">
                  <el-button size="small" type="danger" @click="removeMember(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 环境配置 -->
        <el-tab-pane label="环境配置" name="environments">
          <div class="environments-section">
            <el-button type="primary" @click="showAddEnvDialog = true">添加环境</el-button>
            <el-table :data="project?.environments || []" style="width: 100%; margin-top: 20px;">
              <el-table-column prop="name" label="环境名称" />
              <el-table-column prop="base_url" label="基础URL" />
              <el-table-column prop="description" label="描述" />
              <el-table-column prop="is_default" label="默认环境">
                <template #default="{ row }">
                  <el-tag v-if="row.is_default" type="success">是</el-tag>
                  <span v-else>否</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 📚 知识库 (文件树 + DB 条目) -->
        <el-tab-pane label="📚 知识库" name="knowledge">
          <el-tabs v-model="kbSubTab" @tab-change="onKbSubTabChange" style="margin-top: -8px;">
            <el-tab-pane label="📂 文件知识库" name="kb-fs">
          <!-- 未配置文件型知识库时的提示（仅当确实没配置时才显示） -->
          <div v-if="!project?.knowledge_base_path" class="kb-not-configured">
            <el-result icon="info" title="尚未配置文件型知识库" sub-title="在项目信息中设置「知识库文件目录」后，此处将展示 Markdown 文件树。AI 生成测试用例时会自动读取所有 .md 文件内容注入提示词。">
              <template #extra>
                <el-button type="primary" @click="activeTab = 'info'">去配置</el-button>
              </template>
            </el-result>
          </div>

<!-- 已配置知识库目录：文件树 + Markdown 阅读器 -->
          <div v-if="project?.knowledge_base_path" class="kb-fs-layout">
            <!-- 左侧：文件树 -->
            <div class="kb-fs-tree">
              <div class="kb-fs-tree-header">
                <h4>📁 知识库文件</h4>
                <div style="display:flex;align-items:center;gap:6px;">
                  <el-button size="small" type="primary" plain @click="openKbGenerator">
                    🤖 AI 生成
                  </el-button>
                  <span class="kb-fs-tree-count">{{ flatFileCount }} 个文件</span>
                  <el-button size="small" :icon="Plus" circle title="新建文件" @click="showNewFileDialog = true" />
                </div>
              </div>
              <div v-if="fsLoading" class="kb-fs-tree-loading">
                <el-skeleton :rows="6" animated />
              </div>
              <div v-else-if="fsFiles.length === 0" class="kb-fs-tree-empty">
                <el-empty description="目录为空" :image-size="60" />
              </div>
              <div v-else class="kb-fs-tree-list">
                <KnowledgeTreeNode
                  :nodes="fsFiles"
                  :expanded-dirs="expandedDirs"
                  :selected-file="selectedFile"
                  :depth="0"
                  @toggle-dir="toggleDir"
                  @select-file="selectFile"
                />
              </div>
            </div>

            <!-- 右侧：内容区 -->
            <div class="kb-fs-content">
              <template v-if="!selectedFile">
                <div class="kb-fs-content-placeholder">
                  <el-empty description="从左侧文件树选择文件查看内容" :image-size="80" />
                  <p style="color:#909399;font-size:13px;margin-top:8px">
                    AI 生成测试用例时将自动读取以下目录的所有 .md 文件：<br/>
                    <code>{{ project.knowledge_base_path }}</code>
                  </p>
                </div>
              </template>
              <template v-else>
                <!-- 文件头 -->
                <div class="kb-fs-content-header">
                  <div class="kb-fs-content-title">
                    <el-icon><Document /></el-icon>
                    <span>{{ currentFileName }}</span>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;">
                    <span class="kb-fs-content-meta">{{ currentFileSize }} / {{ currentFileDate }}</span>
                    <template v-if="!fsEditing">
                      <el-button size="small" :icon="Edit" @click="startEdit">编辑</el-button>
                      <el-button size="small" type="danger" plain :icon="Delete" @click="deleteFile">删除</el-button>
                    </template>
                    <template v-else>
                      <el-button size="small" type="primary" :icon="Check" :loading="fsSaving" @click="saveFile">保存</el-button>
                      <el-button size="small" :icon="Close" @click="cancelEdit">取消</el-button>
                    </template>
                  </div>
                </div>
                <!-- Markdown 渲染区 / 编辑器 -->
                <div v-if="fsContentLoading" class="kb-fs-content-loading">
                  <el-skeleton :rows="10" animated />
                </div>
                <textarea
                  v-else-if="fsEditing"
                  v-model="fsEditContent"
                  class="kb-fs-edit-textarea"
                  spellcheck="false"
                />
                <div v-else class="kb-fs-content-body markdown-body" v-html="renderedMarkdown"></div>
              </template>
            </div>
          </div>
            </el-tab-pane>
            <el-tab-pane label="🗄️ DB 条目" name="kb-db">
              <div class="kb-db-fallback">
                <div class="kb-toolbar">
                  <el-select v-model="knowledgeFilter" placeholder="全部分类" clearable style="width:140px" @change="fetchKnowledge">
                    <el-option label="全部分类" value="" />
                    <el-option label="业务背景" value="background" />
                    <el-option label="关键术语" value="terminology" />
                    <el-option label="测试重点" value="test_focus" />
                    <el-option label="约束条件" value="constraints" />
                    <el-option label="注意事项" value="notes" />
                  </el-select>
                  <div style="display:flex;gap:8px;">
                    <el-button type="success" size="small" plain @click="openKbGenerator">🤖 AI 生成知识库</el-button>
                    <el-button type="primary" size="small" :icon="Plus" @click="openKnowledgeDialog()">新增条目</el-button>
                  </div>
                </div>
                <div v-if="knowledgeLoading" style="padding:20px"><el-skeleton :rows="3" animated /></div>
                <div v-else-if="knowledgeList.length === 0" style="padding:30px;text-align:center;color:#c0c4cc">暂无条目</div>
                <div v-else class="kb-db-list">
                  <div v-for="item in (knowledgeList || [])" :key="item && item.id" class="kb-db-card" :class="{ 'is-disabled': !item?.is_active, 'is-pending': item?.needs_review }">
                    <div class="kb-db-card-hd">
                      <el-tag :type="getCategoryTagType(item.category)" size="small">{{ item.category_display }}</el-tag>
                      <el-tag v-if="item?.source === 'zentao_coverage'" type="info" size="small" effect="plain">自动沉淀</el-tag>
                      <el-tag v-if="item?.needs_review" type="warning" size="small">待复核</el-tag>
                      <span class="kb-db-title">{{ item.title }}</span>
                      <el-switch v-model="item.is_active" size="small" @change="toggleKnowledge(item)" />
                      <el-button v-if="item?.needs_review" size="small" type="success" link @click="confirmKnowledge(item)">确认</el-button>
                      <el-button size="small" link @click="openKnowledgeDialog(item)">编辑</el-button>
                      <el-button size="small" type="danger" link @click="deleteKnowledge(item)">删除</el-button>
                    </div>
                    <div class="kb-db-content">{{ item.content }}</div>
                  </div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <!-- 📝 用例文档 -->
        <el-tab-pane label="📝 用例文档" name="cases">
          <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
            <el-select v-model="selectedCaseFile" placeholder="选择用例文档" clearable style="width:300px" @change="loadCaseFile">
              <el-option v-for="f in caseFiles" :key="f" :label="f" :value="f" />
            </el-select>
            <div style="display:flex;gap:8px;">
              <el-button size="small" type="success" :icon="Plus" @click="showNewCaseDialog = true">新建文档</el-button>
              <el-button v-if="selectedCaseFile" size="small" type="danger" @click="deleteCaseFile">删除文档</el-button>
            </div>
          </div>
          <div v-if="!selectedCaseFile" style="padding:40px;text-align:center;color:#c0c4cc;">
            <el-empty description="选择或新建用例文档" :image-size="80" />
          </div>
          <div v-else>
            <div style="margin-bottom:8px;display:flex;justify-content:flex-end;gap:8px;">
              <el-button v-if="!caseEditing" size="small" type="primary" :icon="Edit" @click="startCaseEdit">编辑</el-button>
              <template v-else>
                <el-button size="small" type="primary" :loading="caseSaving" :icon="Check" @click="saveCaseFile">保存</el-button>
                <el-button size="small" :icon="Close" @click="cancelCaseEdit">取消</el-button>
              </template>
            </div>
            <textarea
              v-if="caseEditing"
              v-model="caseEditContent"
              class="kb-fs-edit-textarea"
              style="min-height:400px;border:1px solid #e4e7ed;border-radius:6px;padding:12px;"
              spellcheck="false"
            />
            <div v-else class="markdown-body" style="border:1px solid #e4e7ed;border-radius:6px;padding:16px;min-height:200px;" v-html="caseRenderedMd" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 新建用例文档弹窗 -->
    <el-dialog v-model="showNewCaseDialog" title="📄 新建用例文档" width="480px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="文件名">
          <el-input v-model="newCaseFileName" placeholder="如：万年历_核心流程.md" />
        </el-form-item>
        <el-form-item label="初始内容">
          <el-input v-model="newCaseContent" type="textarea" :rows="8" placeholder="# 用例标题&#10;&#10;**步骤**：&#10;1. ...&#10;2. ..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showNewCaseDialog = false">取消</el-button>
        <el-button type="primary" @click="createCaseFile">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑项目弹窗 -->
    <el-dialog v-model="showProjectEditDialog" title="✏️ 编辑项目" width="560px" destroy-on-close>
      <el-form :model="projectEditForm" :rules="projectEditRules" ref="projectEditFormRef" label-width="100px">
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="projectEditForm.name" placeholder="项目名称" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input v-model="projectEditForm.description" type="textarea" :rows="3" placeholder="项目描述" />
        </el-form-item>
        <el-form-item label="项目状态">
          <el-select v-model="projectEditForm.status">
            <el-option label="进行中" value="active" />
            <el-option label="已暂停" value="paused" />
            <el-option label="已完成" value="completed" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item label="知识库目录">
          <el-input v-model="projectEditForm.knowledge_base_path" placeholder="如 /app/knowledge-bases/项目名/" />
          <small style="color:#909399">服务器上知识库 markdown 文件的绝对路径，留空则不启用文件型知识库</small>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showProjectEditDialog = false">取消</el-button>
        <el-button type="primary" @click="saveProject">保存</el-button>
      </template>
    </el-dialog>

    <!-- FS 新建文件弹窗 -->
    <el-dialog v-model="showNewFileDialog" title="📄 新建知识库文件" width="500px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="文件名">
          <el-input v-model="newFileName" placeholder="例：03-新功能说明.md" clearable />
          <div style="font-size:12px;color:#c0c4cc;margin-top:4px">必须以 .md 结尾；子目录用 / 分隔，如 subdir/文件名.md</div>
        </el-form-item>
        <el-form-item label="初始内容">
          <el-input v-model="newFileContent" type="textarea" :rows="7" placeholder="# 标题&#10;&#10;在此输入内容..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showNewFileDialog = false">取消</el-button>
        <el-button type="primary" :loading="newFileCreating" @click="createFile">创建</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成知识库弹窗 -->
    <el-dialog v-model="showKbGenerator" title="🤖 AI 生成知识库" width="800px" destroy-on-close :close-on-click-modal="false">
      <div class="kb-generator-body">
        <el-alert
          title="粘贴功能点文档或上传产品设计截图，AI 将自动分析业务背景并生成结构化的知识库 Markdown 文件。"
          type="info" :closable="false" style="margin-bottom:16px"
        />

        <el-form label-width="100px">
          <el-form-item label="功能点描述">
            <el-input
              v-model="kbGenRawText"
              type="textarea"
              :rows="5"
              placeholder="粘贴功能点文档、需求描述、产品说明等文字内容（可选，如已上传截图可留空）"
            />
          </el-form-item>

          <el-form-item label="设计截图">
            <div
              class="kb-gen-image-zone"
              @click="focusImageInput"
              @dragover.prevent="dragOver = true"
              @dragleave="dragOver = false"
              @drop.prevent="onDropImages"
              :class="{ 'drag-over': dragOver }"
            >
              <input
                ref="imageInputRef"
                type="file"
                accept="image/*"
                multiple
                style="display:none"
                @change="onImageFileChange"
              />
              <template v-if="kbGenImages.length === 0">
                <el-icon :size="40" color="#c0c4cc"><Plus /></el-icon>
                <p>拖拽截图到此处，或点击选择图片</p>
                <p style="font-size:12px;color:#c0c4cc">支持 Ctrl+V 粘贴剪贴板截图</p>
              </template>
              <div v-else class="kb-gen-image-preview-list">
                <div v-for="(img, idx) in kbGenImages" :key="idx" class="kb-gen-image-preview-item">
                  <img :src="img.dataUrl" />
                  <el-button size="small" circle type="danger" class="kb-gen-img-remove" @click="removeGenImage(idx)">
                    <el-icon><Close /></el-icon>
                  </el-button>
                </div>
                <div class="kb-gen-image-add-btn" @click.stop="focusImageInput">
                  <el-icon :size="24"><Plus /></el-icon>
                </div>
              </div>
            </div>
          </el-form-item>
        </el-form>


        <!-- 预览结果 -->
        <div v-if="kbGenResult" class="kb-gen-result">
          <el-divider>生成预览</el-divider>
          <p class="kb-gen-summary">
            共生成 <strong>{{ kbGenResult.files.length }}</strong> 个文件
            <el-tag v-if="kbGenResult.written" type="success" size="small">已写入文件系统</el-tag>
            <el-tag v-else type="warning" size="small">仅预览，未写入</el-tag>
          </p>
          <div class="kb-gen-file-list">
            <div v-for="(f, idx) in kbGenResult.files" :key="idx" class="kb-gen-file-card">
              <div class="kb-gen-file-header" @click="toggleKbGenFile(idx)">
                <el-icon class="kb-gen-file-icon">
                  <ArrowRight v-if="!expandedGenFiles.has(idx)" />
                  <ArrowDown v-else />
                </el-icon>
                <span class="kb-gen-file-path">📄 {{ f.path }}</span>
                <span class="kb-gen-file-meta">({{ f.content.length }} 字符)</span>
              </div>
              <div v-show="expandedGenFiles.has(idx)" class="kb-gen-file-content">
                <div class="markdown-body" v-html="renderKbGenMd(f.content)"></div>
              </div>
            </div>
          </div>

          <!-- ⚠️ 待确认项 -->
          <div v-if="kbGenResult.uncertain_items?.length && !kbGenResult.written" class="kb-gen-uncertain">
            <el-divider>⚠️ 待确认项（{{ kbGenResult.uncertain_items.length }} 条）</el-divider>
            <el-alert
              title="以下内容AI无法100%确定，请逐项确认后点击「确认并写入」精炼内容"
              type="warning" :closable="false" style="margin-bottom:12px"
            />
            <div v-for="(item, idx) in kbGenResult.uncertain_items" :key="'u'+idx" class="kb-gen-uncertain-item">
              <div class="kb-gen-uncertain-header">
                <el-tag type="warning" size="small">待确认 {{ idx + 1 }}</el-tag>
                <span class="kb-gen-uncertain-file">📄 {{ item.file }}</span>
              </div>
              <div class="kb-gen-uncertain-question">
                <strong>问题：</strong>{{ item.question }}
              </div>
              <div v-if="item.context" class="kb-gen-uncertain-context">
                <strong>当前推测：</strong>{{ item.context }}
              </div>
              <el-input
                v-model="kbGenReplies[idx]"
                type="textarea"
                :rows="2"
                placeholder="回复此问题（可选，留空则维持当前推测）"
                style="margin-top:8px"
              />
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showKbGenerator = false">关闭</el-button>
        <el-button type="info" :loading="kbGenLoading" @click="runKbGenerator(false)">
          🔍 预览生成（不写入）
        </el-button>
        <el-button
          v-if="hasUncertainItems"
          type="primary" :loading="kbGenLoading" @click="runKbGenerator(true)"
        >
          ✅ 确认并写入文件
        </el-button>
        <el-button
          v-else
          type="primary" :loading="kbGenLoading" @click="runKbGenerator(true)"
        >
          ✍️ 预览并写入文件
        </el-button>
      </template>
    </el-dialog>

    <!-- 添加成员弹窗 -->
    <el-dialog v-model="showAddMemberDialog" title="添加项目成员" width="460px" destroy-on-close @close="resetAddMemberForm">
      <el-form :model="addMemberForm" label-width="70px" ref="addMemberFormRef">
        <el-form-item label="成员" prop="user_id" :rules="[{required: true, message: '请选择成员', trigger: 'change'}]">
          <el-select
            v-model="addMemberForm.user_id"
            placeholder="请搜索或选择用户"
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="u in userList"
              :key="u.id"
              :label="`${u.username}${u.email ? ' (' + u.email + ')' : ''}`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="addMemberForm.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="开发者" value="developer" />
            <el-option label="测试者" value="tester" />
            <el-option label="观察者" value="viewer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddMemberDialog = false">取消</el-button>
        <el-button type="primary" :loading="addMemberLoading" @click="addMember">确认添加</el-button>
      </template>
    </el-dialog>

    <!-- DB 知识库弹窗 -->
    <el-dialog v-model="showKnowledgeDialog" :title="editingKnowledge ? '编辑知识库条目' : '新增知识库条目'" width="600px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon title="录入提示（提升 AI 按需精准召回）">
        <template #default>
          <div style="line-height:1.7;">
            <p style="margin:0 0 4px;">AI 生成时会结合具体需求判断功能异同，但同名条目过多会被召回上限（8 条）挤出视野。建议：</p>
            <ul style="margin:0;padding-left:18px;">
              <li>标题带 <code>【功能 / 版本】</code> 前缀，如 <code>【引导 / v1.6.1】</code>（辅助区分，非强制）</li>
              <li>内容开头点明适用功能/版本，并写<b>具体业务场景</b>（含「快手渠道」「H5 落地页」等区分词）——这是区分度的根本</li>
              <li>一条只讲一个功能/约束；避免「需要充分测试」等泛化废话污染召回</li>
            </ul>
          </div>
        </template>
      </el-alert>
      <el-form :model="knowledgeForm" label-width="90px" :rules="knowledgeRules" ref="knowledgeFormRef" style="margin-top:12px;">
        <el-form-item label="分类" prop="category">
          <el-select v-model="knowledgeForm.category" style="width:100%">
            <el-option label="业务背景" value="background" />
            <el-option label="关键术语" value="terminology" />
            <el-option label="测试重点" value="test_focus" />
            <el-option label="约束条件" value="constraints" />
            <el-option label="注意事项" value="notes" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题" prop="title">
          <el-input v-model="knowledgeForm.title" placeholder="建议带【功能 / 版本】前缀，如【引导 / v1.6.1】新增快手渠道引导" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="内容" prop="content">
          <el-input v-model="knowledgeForm.content" type="textarea" :rows="6" placeholder="开头点明适用功能/版本，并写具体业务场景（含「快手渠道」「H5 落地页」等区分词），便于 AI 按需精准召回" />
        </el-form-item>
        <el-form-item label="排序权重">
          <el-input-number v-model="knowledgeForm.sort_order" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="knowledgeForm.is_active" active-text="启用" inactive-text="禁用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showKnowledgeDialog = false">取消</el-button>
        <el-button type="primary" :loading="knowledgeSaving" @click="saveKnowledge">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Document, Edit, Delete, Check, Close, ArrowRight, ArrowDown } from '@element-plus/icons-vue'
import KnowledgeTreeNode from './KnowledgeTreeNode.vue'
import api from '@/utils/api'
import dayjs from 'dayjs'
import { marked } from 'marked'

const route = useRoute()
const project = ref(null)
const activeTab = ref('info')
const kbSubTab = ref('kb-fs')
const showProjectEditDialog = ref(false)
const projectEditForm = ref({ name: '', description: '', status: 'active', knowledge_base_path: '' })
const projectEditFormRef = ref(null)
const projectEditRules = {
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
}

const openProjectEditDialog = () => {
  projectEditForm.value = {
    name: project.value?.name || '',
    description: project.value?.description || '',
    status: project.value?.status || 'active',
    knowledge_base_path: project.value?.knowledge_base_path || '',
  }
  showProjectEditDialog.value = true
}

const saveProject = async () => {
  const valid = await projectEditFormRef.value?.validate().catch(() => false)
  if (!valid) return
  try {
    await api.patch(`/projects/${route.params.id}/`, projectEditForm.value)
    ElMessage.success('项目已更新')
    showProjectEditDialog.value = false
    fetchProject()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '更新失败')
  }
}
const showAddMemberDialog = ref(false)
const showAddEnvDialog = ref(false)

// ============================================================
// 添加成员
// ============================================================
const userList = ref([])
const addMemberFormRef = ref(null)
const addMemberLoading = ref(false)
const addMemberForm = ref({ user_id: null, role: 'tester' })

const fetchUsers = async () => {
  try {
    const res = await api.get('/auth/users/')
    userList.value = res.data.results || res.data || []
  } catch {
    // 静默失败
  }
}

const resetAddMemberForm = () => {
  addMemberForm.value = { user_id: null, role: 'tester' }
  addMemberFormRef.value?.resetFields()
}

const addMember = async () => {
  const valid = await addMemberFormRef.value?.validate().catch(() => false)
  if (!valid) return
  addMemberLoading.value = true
  try {
    await api.post(`/projects/${route.params.id}/members/add/`, {
      user_id: addMemberForm.value.user_id,
      role: addMemberForm.value.role
    })
    ElMessage.success('成员添加成功')
    showAddMemberDialog.value = false
    resetAddMemberForm()
    fetchProject()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '添加失败')
  } finally {
    addMemberLoading.value = false
  }
}

// ============================================================
// 文件系统知识库
// ============================================================
const fsFiles = ref([])
const fsLoading = ref(false)
const selectedFile = ref('')
const fsContentLoading = ref(false)
const fileContentCache = ref({})   // path -> content
const expandedDirs = ref(new Set())

// 编辑状态
const fsEditing = ref(false)
const fsEditContent = ref('')
const fsSaving = ref(false)
// 新建文件弹窗
const showNewFileDialog = ref(false)
const newFileName = ref('')
const newFileContent = ref('')
const newFileCreating = ref(false)

// ============================================================
// AI 生成知识库
// ============================================================
const showKbGenerator = ref(false)
const kbGenRawText = ref('')
const kbGenImages = ref([])  // [{dataUrl, base64}]
const kbGenLoading = ref(false)
const kbGenResult = ref(null)
const expandedGenFiles = ref(new Set())
const dragOver = ref(false)
const imageInputRef = ref(null)
const kbGenReplies = ref({})  // {idx: 'reply text'}

const hasUncertainItems = computed(() => {
  return kbGenResult.value?.uncertain_items?.length > 0 && !kbGenResult.value?.written
})

const flatFileCount = computed(() => {
  let count = 0
  const walk = (nodes) => {
    for (const n of nodes) {
      if (n.type === 'file') count++
      if (n.type === 'directory' && n.children) walk(n.children)
    }
  }
  walk(fsFiles.value)
  return count
})

const currentFileName = computed(() => {
  if (!selectedFile.value) return ''
  const segs = selectedFile.value.split('/')
  return segs[segs.length - 1]
})

const currentFileSize = computed(() => {
  const c = fileContentCache.value[selectedFile.value]
  if (!c) return ''
  return formatFileSize(c.size)
})

const currentFileDate = computed(() => {
  const c = fileContentCache.value[selectedFile.value]
  if (!c) return ''
  return dayjs.unix(c.modified).format('YYYY-MM-DD HH:mm')
})

const renderedMarkdown = computed(() => {
  const c = fileContentCache.value[selectedFile.value]
  if (!c) return ''
  try {
    return marked(c.content)
  } catch {
    return `<pre>${escapeHtml(c.content)}</pre>`
  }
})

const fetchFsTree = async () => {
  fsLoading.value = true
  try {
    const res = await api.get(`/projects/${route.params.id}/knowledge/fs/tree/`)
    fsFiles.value = res.data.files || []
    // 自动展开所有目录
    const dirs = new Set()
    const walk = (nodes) => {
      for (const n of nodes) {
        if (n.type === 'directory') {
          dirs.add(n.path)
          if (n.children) walk(n.children)
        }
      }
    }
    walk(fsFiles.value)
    expandedDirs.value = dirs
  } catch {
    // API 可能还没部署，静默失败
  } finally {
    fsLoading.value = false
  }
}

const toggleDir = (path) => {
  const next = new Set(expandedDirs.value)
  if (next.has(path)) {
    next.delete(path)
  } else {
    next.add(path)
  }
  expandedDirs.value = next
}

const selectFile = async (node) => {
  if (fsEditing.value) {
    fsEditing.value = false
    fsEditContent.value = ''
  }
  selectedFile.value = node.path
  // 已缓存则直接用
  if (fileContentCache.value[node.path]) return
  fsContentLoading.value = true
  try {
    const res = await api.get(`/projects/${route.params.id}/knowledge/fs/file/${encodeURIComponent(node.path)}/`)
    fileContentCache.value[node.path] = res.data
  } catch (e) {
    ElMessage.error('读取文件失败')
  } finally {
    fsContentLoading.value = false
  }
}

const startEdit = () => {
  const c = fileContentCache.value[selectedFile.value]
  fsEditContent.value = c ? c.content : ''
  fsEditing.value = true
}

const cancelEdit = () => {
  fsEditing.value = false
  fsEditContent.value = ''
}

const saveFile = async () => {
  fsSaving.value = true
  try {
    const res = await api.put(
      `/projects/${route.params.id}/knowledge/fs/file/${encodeURIComponent(selectedFile.value)}/`,
      { content: fsEditContent.value }
    )
    fileContentCache.value[selectedFile.value] = res.data
    fsEditing.value = false
    ElMessage.success('保存成功')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    fsSaving.value = false
  }
}

const deleteFile = async () => {
  try {
    await ElMessageBox.confirm(
      `确定删除文件「${currentFileName.value}」吗？此操作不可恢复！`,
      '危险操作', { type: 'warning', confirmButtonText: '确定删除', confirmButtonClass: 'el-button--danger' }
    )
    await api.delete(`/projects/${route.params.id}/knowledge/fs/file/${encodeURIComponent(selectedFile.value)}/`)
    ElMessage.success('删除成功')
    delete fileContentCache.value[selectedFile.value]
    selectedFile.value = ''
    fsEditing.value = false
    fetchFsTree()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

const createFile = async () => {
  const fname = newFileName.value.trim()
  if (!fname) { ElMessage.warning('请输入文件名'); return }
  if (!fname.endsWith('.md')) { ElMessage.warning('文件名必须以 .md 结尾'); return }
  newFileCreating.value = true
  try {
    const res = await api.post(`/projects/${route.params.id}/knowledge/fs/create/`, {
      path: fname,
      content: newFileContent.value
    })
    ElMessage.success('文件创建成功')
    showNewFileDialog.value = false
    newFileName.value = ''
    newFileContent.value = ''
    await fetchFsTree()
    selectedFile.value = res.data.path
    fileContentCache.value[res.data.path] = res.data
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '创建失败')
  } finally {
    newFileCreating.value = false
  }
}

// ============================================================
// 数据库知识库 (回退模式)
// ============================================================
const knowledgeList = ref([])
const knowledgeLoading = ref(false)
const knowledgeFilter = ref('')
const showKnowledgeDialog = ref(false)
const knowledgeSaving = ref(false)
const editingKnowledge = ref(null)
const knowledgeFormRef = ref(null)
const knowledgeForm = ref({ category: 'background', title: '', content: '', sort_order: 0, is_active: true })
const knowledgeRules = {
  category: [{ required: true, message: '请选择分类', trigger: 'change' }],
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, message: '请输入内容', trigger: 'blur' }]
}

const fetchProject = async () => {
  try {
    const res = await api.get(`/projects/${route.params.id}/`)
    project.value = res.data
  } catch {
    ElMessage.error('获取项目详情失败')
  }
}

const fetchKnowledge = async () => {
  knowledgeLoading.value = true
  try {
    const params = {}
    if (knowledgeFilter.value) params.category = knowledgeFilter.value
    const res = await api.get(`/projects/${route.params.id}/knowledge/`, { params })
    knowledgeList.value = res.data.results || res.data || []
  } catch {
    ElMessage.error('获取知识库失败')
  } finally {
    knowledgeLoading.value = false
  }
}

const openKnowledgeDialog = (item = null) => {
  editingKnowledge.value = item
  if (item) {
    knowledgeForm.value = { category: item.category, title: item.title, content: item.content, sort_order: item.sort_order, is_active: item.is_active }
  } else {
    knowledgeForm.value = { category: 'background', title: '', content: '', sort_order: 0, is_active: true }
  }
  showKnowledgeDialog.value = true
}

const saveKnowledge = async () => {
  const valid = await knowledgeFormRef.value?.validate().catch(() => false)
  if (!valid) return
  knowledgeSaving.value = true
  try {
    if (editingKnowledge.value) {
      await api.patch(`/projects/${route.params.id}/knowledge/${editingKnowledge.value.id}/`, knowledgeForm.value)
      ElMessage.success('更新成功')
    } else {
      await api.post(`/projects/${route.params.id}/knowledge/`, knowledgeForm.value)
      ElMessage.success('添加成功')
    }
    showKnowledgeDialog.value = false
    fetchKnowledge()
  } catch {
    ElMessage.error(editingKnowledge.value ? '更新失败' : '添加失败')
  } finally {
    knowledgeSaving.value = false
  }
}

const toggleKnowledge = async (item) => {
  try {
    await api.patch(`/projects/${route.params.id}/knowledge/${item.id}/`, { is_active: item.is_active })
    ElMessage.success(item.is_active ? '已启用' : '已禁用')
  } catch {
    item.is_active = !item.is_active
    ElMessage.error('操作失败')
  }
}

const confirmKnowledge = async (item) => {
  // 确认前先做语义去重预检：若知识库已有高度相似（>=0.90）条目，提示人工判断
  try {
    const dupRes = await api.post(`/projects/${route.params.id}/knowledge/check-duplicate/`, {
      entry_id: item.id,
    })
    const dups = (dupRes.data && dupRes.data.duplicates) || []
    if (dupRes.data && dupRes.data.has_duplicate && dups.length) {
      const top = dups[0]
      const list = dups
        .map((d) => `• ${(d.title || '未命名')}（相似度 ${(d.similarity * 100).toFixed(1)}%）`)
        .join('\n')
      try {
        await ElMessageBox.confirm(
          `该条目与知识库中以下内容高度相似，确认后仍会重复沉淀：\n\n${list}\n\n是否仍然确认纳入？`,
          `疑似重复（${(top.similarity * 100).toFixed(1)}%）`,
          { type: 'warning', confirmButtonText: '仍然确认', cancelButtonText: '取消' }
        )
      } catch {
        return // 用户取消，不确认
      }
    }
  } catch {
    // 去重预检失败则放行，不阻断确认
  }
  try {
    await api.patch(`/projects/${route.params.id}/knowledge/${item.id}/`, { needs_review: false })
    item.needs_review = false
    ElMessage.success('已确认，知识条目已纳入生成召回')
  } catch {
    ElMessage.error('确认失败')
  }
}

const deleteKnowledge = async (item) => {
  try {
    await ElMessageBox.confirm(`确定删除「${item.title}」吗？`, '提示', { type: 'warning' })
    await api.delete(`/projects/${route.params.id}/knowledge/${item.id}/`)
    ElMessage.success('删除成功')
    fetchKnowledge()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

const onTabChange = (name) => {
  if (name === 'knowledge') {
    // 文件系统模式优先
    if (project.value?.knowledge_base_path) {
      fetchFsTree()
    }
    // 默认加载 DB 知识
    if (kbSubTab.value === 'kb-db') {
      fetchKnowledge()
    }
  }
}

const onKbSubTabChange = (name) => {
  if (name === 'kb-fs' && project.value?.knowledge_base_path) {
    fetchFsTree()
  } else if (name === 'kb-db') {
    fetchKnowledge()
  }
}

// ============================================================
// AI 生成知识库
// ============================================================
const handleImageFiles = (files) => {
  files.forEach(file => {
    const reader = new FileReader()
    reader.onload = (ev) => {
      kbGenImages.value.push({
        dataUrl: ev.target.result,
        base64: ev.target.result.split(',')[1] || ev.target.result
      })
    }
    reader.readAsDataURL(file)
  })
}

const onDropImages = (e) => {
  dragOver.value = false
  const files = Array.from(e.dataTransfer?.files || []).filter(f => f.type.startsWith('image/'))
  if (files.length > 0) handleImageFiles(files)
}

const onImageFileChange = (e) => {
  const files = Array.from(e.target?.files || []).filter(f => f.type.startsWith('image/'))
  if (files.length > 0) handleImageFiles(files)
  // 重置 input，允许重复选择同一文件
  e.target.value = ''
}

const removeGenImage = (idx) => {
  kbGenImages.value.splice(idx, 1)
}

const focusImageInput = () => {
  imageInputRef.value?.click()
}

const openKbGenerator = () => {
  kbGenRawText.value = ''
  kbGenImages.value = []
  kbGenResult.value = null
  expandedGenFiles.value = new Set()
  kbGenReplies.value = {}
  showKbGenerator.value = true
}

const runKbGenerator = async (writeFiles) => {
  // ===== 待确认项 + 有人工回复 → 精炼模式 =====
  if (writeFiles && kbGenResult.value?.uncertain_items?.length > 0) {
    const items = kbGenResult.value.uncertain_items
    const replies = items
      .map((item, idx) => ({
        file: item.file,
        question: item.question,
        answer: kbGenReplies.value[idx] || ''
      }))
      .filter(r => r.answer)

    if (replies.length === 0) {
      // 无回复 → 直接写入当前内容
      await _doWriteKbFiles()
      return
    }

    // 有回复 → 精炼模式
    kbGenLoading.value = true
    try {
      const res = await api.post('/requirement-analysis/api/generate-knowledge-base/', {
        project_id: route.params.id,
        resolve_replies: replies,
        original_files: kbGenResult.value.files,
        dry_run: false
      })
      kbGenResult.value = {
        files: res.data.files || [],
        uncertain_items: res.data.uncertain_items || [],
        written: res.data.written || false
      }
      kbGenReplies.value = {}
      expandedGenFiles.value = new Set()
      if (res.data.written) {
        ElMessage.success('知识库文件已精炼并写入')
      } else {
        ElMessage.warning('精炼完成，但文件未写入：项目未配置知识库目录或目录无法访问')
      }

      if (project.value?.knowledge_base_path) {
        await fetchFsTree()
      }
    } catch (e) {
      ElMessage.error(e.response?.data?.error || '精炼失败')
    } finally {
      kbGenLoading.value = false
    }
    return
  }

  // ===== 首次生成 =====
  if (!kbGenRawText.value.trim() && kbGenImages.value.length === 0) {
    ElMessage.warning('请提供功能点描述或上传设计截图')
    return
  }

  kbGenLoading.value = true
  kbGenResult.value = null
  kbGenReplies.value = {}

  try {
    const payload = {
      project_id: route.params.id,
      dry_run: !writeFiles
    }
    if (kbGenRawText.value.trim()) {
      payload.raw_text = kbGenRawText.value.trim()
    }
    if (kbGenImages.value.length > 0) {
      payload.images = kbGenImages.value.map(img => img.base64)
    }

    const res = await api.post('/requirement-analysis/api/generate-knowledge-base/', payload)
    kbGenResult.value = {
      files: res.data.files || [],
      uncertain_items: res.data.uncertain_items || [],
      preview: res.data.preview || '',
      written: res.data.written || false
    }
    expandedGenFiles.value = new Set()
    if (writeFiles) {
      if (res.data.written) {
        ElMessage.success('知识库文件已写入')
      } else {
        ElMessage.warning('文件未写入：项目未配置知识库目录或目录无法访问')
      }
    } else {
      ElMessage.success('预览生成完成')
    }

    // 写入后刷新文件树
    if (writeFiles && project.value?.knowledge_base_path) {
      await fetchFsTree()
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '生成失败')
  } finally {
    kbGenLoading.value = false
  }
}

// 直接写入文件（无待确认项或用户未回复）
const _doWriteKbFiles = async () => {
  kbGenLoading.value = true
  try {
    const payload = {
      project_id: route.params.id,
      dry_run: false
    }
    // 必须携带原始输入，否则后端会报"缺少输入"
    if (kbGenRawText.value.trim()) {
      payload.raw_text = kbGenRawText.value.trim()
    }
    if (kbGenImages.value.length > 0) {
      payload.images = kbGenImages.value.map(img => img.base64)
    }
    const res = await api.post('/requirement-analysis/api/generate-knowledge-base/', payload)
    kbGenResult.value = {
      files: res.data.files || [],
      uncertain_items: res.data.uncertain_items || [],
      written: res.data.written || false
    }
    if (res.data.written) {
      ElMessage.success('知识库文件已写入')
    } else {
      ElMessage.warning('文件未写入：项目未配置知识库目录或目录无法访问')
    }
    if (project.value?.knowledge_base_path) {
      await fetchFsTree()
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '写入失败')
  } finally {
    kbGenLoading.value = false
  }
}

const toggleKbGenFile = (idx) => {
  if (expandedGenFiles.value.has(idx)) {
    expandedGenFiles.value.delete(idx)
  } else {
    expandedGenFiles.value.add(idx)
  }
  // 触发响应式更新
  expandedGenFiles.value = new Set(expandedGenFiles.value)
}

const renderKbGenMd = (content) => {
  try {
    return marked(content)
  } catch {
    return `<pre>${escapeHtml(content)}</pre>`
  }
}

const onKbGenPaste = (e) => {
  if (!showKbGenerator.value) return
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file) handleImageFiles([file])
      break
    }
  }
}

// ============================================================
// 工具函数
// ============================================================
const getStatusType = (s) => ({ active: 'success', paused: 'warning', completed: 'info', archived: 'info' }[s] || 'info')
const getStatusText = (s) => ({ active: '进行中', paused: '已暂停', completed: '已完成', archived: '已归档' }[s] || s)
const formatDate = (d) => dayjs(d).format('YYYY-MM-DD HH:mm')
const getCategoryTagType = (c) => {
  return { background: 'primary', terminology: 'success', test_focus: 'warning', constraints: 'danger', notes: 'info' }[c] || 'info'
}
const formatFileSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
const escapeHtml = (str) => str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const removeMember = async (member) => {
  try {
    await api.delete(`/projects/${route.params.id}/members/${member.id}/`)
    ElMessage.success('成员删除成功')
    fetchProject()
  } catch {
    ElMessage.error('删除成员失败')
  }
}

// ============================================================
// 用例文档 (Markdown cases)
// ============================================================
const caseFiles = ref([])
const selectedCaseFile = ref('')
const caseEditing = ref(false)
const caseEditContent = ref('')
const caseSaving = ref(false)
const showNewCaseDialog = ref(false)
const newCaseFileName = ref('')
const newCaseContent = ref('')

const caseRenderedMd = computed(() => {
  try { return marked(caseEditContent.value) } catch { return '' }
})

const fetchCaseFiles = async () => {
  try {
    // 列出 appium_workspace/cases/ 目录下的 .md 文件
    const res = await api.get(`/projects/${route.params.id}/knowledge/fs/tree/`, {
      params: { dir: 'appium_workspace/cases' }
    })
    const flatten = (nodes) => {
      const out = []
      for (const n of nodes || []) {
        if (n.type === 'file' && n.name.endsWith('.md')) {
          out.push(n.name)
        } else if (n.type === 'directory' && n.children) {
          out.push(...flatten(n.children))
        }
      }
      return out
    }
    caseFiles.value = flatten(res.data.files)
  } catch {
    caseFiles.value = []
  }
}

const loadCaseFile = async () => {
  if (!selectedCaseFile.value) return
  caseEditing.value = false
  try {
    const res = await api.get(`/projects/${route.params.id}/knowledge/fs/file/${encodeURIComponent('appium_workspace/cases/' + selectedCaseFile.value)}/`)
    caseEditContent.value = res.data.content || ''
  } catch {
    ElMessage.error('读取文件失败')
  }
}

const startCaseEdit = () => { caseEditing.value = true }
const cancelCaseEdit = () => {
  caseEditing.value = false
  loadCaseFile()
}

const saveCaseFile = async () => {
  caseSaving.value = true
  try {
    await api.put(`/projects/${route.params.id}/knowledge/fs/file/${encodeURIComponent('appium_workspace/cases/' + selectedCaseFile.value)}/`, {
      content: caseEditContent.value
    })
    ElMessage.success('保存成功')
    caseEditing.value = false
  } catch {
    ElMessage.error('保存失败')
  } finally {
    caseSaving.value = false
  }
}

const createCaseFile = async () => {
  const fname = newCaseFileName.value.trim()
  if (!fname) { ElMessage.warning('请输入文件名'); return }
  if (!fname.endsWith('.md')) { ElMessage.warning('文件名必须以 .md 结尾'); return }
  try {
    const targetPath = 'appium_workspace/cases/' + fname
    await api.post(`/projects/${route.params.id}/knowledge/fs/create/`, {
      path: targetPath,
      content: newCaseContent.value || '# 新用例\n\n**步骤**：\n1. \n2. \n'
    })
    ElMessage.success('创建成功')
    showNewCaseDialog.value = false
    newCaseFileName.value = ''
    newCaseContent.value = ''
    await fetchCaseFiles()
    selectedCaseFile.value = fname
    await loadCaseFile()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '创建失败')
  }
}

const deleteCaseFile = async () => {
  try {
    await ElMessageBox.confirm(`确定删除「${selectedCaseFile.value}」吗？`, '提示', { type: 'warning' })
    await api.delete(`/projects/${route.params.id}/knowledge/fs/file/${encodeURIComponent('appium_workspace/cases/' + selectedCaseFile.value)}/`)
    ElMessage.success('删除成功')
    selectedCaseFile.value = ''
    caseEditContent.value = ''
    await fetchCaseFiles()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

onMounted(() => {
  fetchProject()
  fetchUsers()
  fetchCaseFiles()
  document.addEventListener('paste', onKbGenPaste)
})

onUnmounted(() => {
  document.removeEventListener('paste', onKbGenPaste)
})
</script>

<style lang="scss" scoped>
.members-section, .environments-section { padding: 20px 0; }

// ============== 文件系统知识库布局 ==============
.kb-not-configured {
  padding: 20px 0;
}

.kb-db-fallback {
  .kb-toolbar {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 12px;
  }
  .kb-db-list { display: flex; flex-direction: column; gap: 8px; }
  .kb-db-card {
    border: 1px solid #e4e7ed; border-radius: 6px; padding: 10px 14px;
    background: #fff;
    &.is-disabled { opacity: 0.5; background: #f9f9f9; }
    &.is-pending { border-color: #e6a23c; background: #fdf6ec; }
    .kb-db-card-hd { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
    .kb-db-title { font-weight: 600; color: #303133; flex: 1; }
    .kb-db-content { font-size: 13px; color: #606266; white-space: pre-wrap; }
  }
}

.kb-fs-layout {
  display: flex;
  height: calc(100vh - 260px);
  min-height: 420px;
  max-height: 760px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}

.kb-fs-tree {
  width: 280px;
  min-width: 220px;
  max-width: 360px;
  flex-shrink: 0;
  border-right: 1px solid #e4e7ed;
  background: #fafafa;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.kb-fs-tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
  h4 { margin: 0; font-size: 14px; color: #303133; white-space: nowrap; }
  .kb-fs-tree-count { font-size: 12px; color: #c0c4cc; white-space: nowrap; }
}

.kb-fs-tree-loading { padding: 16px; }
.kb-fs-tree-empty { padding: 30px 0; }

.kb-fs-tree-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 10px;
}

.kb-fs-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  min-width: 0;
}

.kb-fs-content-placeholder {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 40px; text-align: center;
}

.kb-fs-content-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
  flex-shrink: 0;
  .kb-fs-content-title {
    display: flex; align-items: center; gap: 6px;
    font-size: 14px; font-weight: 600; color: #303133;
  }
  .kb-fs-content-meta { font-size: 12px; color: #c0c4cc; }
}

.kb-fs-content-loading { padding: 20px; }

.kb-fs-content-body {
  flex: 1; padding: 20px 24px;
  overflow-y: auto;
  line-height: 1.75;
  font-size: 14px; color: #303133;
}

// Markdown 渲染样式
.markdown-body {
  :deep(h1) { font-size: 1.6em; border-bottom: 2px solid #eee; padding-bottom: 8px; margin: 20px 0 12px; }
  :deep(h2) { font-size: 1.35em; border-bottom: 1px solid #eee; padding-bottom: 6px; margin: 18px 0 10px; }
  :deep(h3) { font-size: 1.15em; margin: 14px 0 8px; }
  :deep(h4) { font-size: 1.05em; margin: 10px 0 6px; }
  :deep(p) { margin: 8px 0; }
  :deep(ul), :deep(ol) { padding-left: 24px; margin: 8px 0; }
  :deep(li) { margin: 4px 0; }
  :deep(code) { background: #f0f2f5; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; font-family: 'Consolas', 'Courier New', monospace; }
  :deep(pre) { background: #f6f8fa; border: 1px solid #e1e4e8; border-radius: 6px; padding: 14px; overflow-x: auto; margin: 10px 0;
    code { background: transparent; padding: 0; }
  }
  :deep(blockquote) { border-left: 3px solid #409eff; padding: 4px 14px; margin: 10px 0; color: #606266; background: #f5f7fa; }
  :deep(table) { border-collapse: collapse; width: 100%; margin: 10px 0;
    th, td { border: 1px solid #e4e7ed; padding: 8px 12px; text-align: left; }
    th { background: #f5f7fa; font-weight: 600; }
  }
  :deep(strong) { font-weight: 600; color: #303133; }
  :deep(hr) { border: none; border-top: 1px solid #e4e7ed; margin: 16px 0; }
}

.kb-fs-edit-textarea {
  flex: 1;
  width: 100%;
  resize: none;
  border: none;
  outline: none;
  padding: 20px 24px;
  font-size: 13.5px;
  font-family: 'Consolas', 'Courier New', 'Menlo', monospace;
  line-height: 1.75;
  color: #303133;
  background: #fafcff;
  box-sizing: border-box;
  tab-size: 2;
}

// ============== AI 生成知识库 ==============
.kb-generator-body {
  .kb-gen-image-zone {
    border: 2px dashed #dcdfe6;
    border-radius: 8px;
    padding: 40px 20px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    min-height: 120px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    p { margin: 0; color: #909399; font-size: 14px; }
    &:hover { border-color: #409eff; background: #f0f7ff; }
    &.drag-over { border-color: #409eff; background: #ecf5ff; }
  }
  .kb-gen-image-preview-list {
    display: flex; flex-wrap: wrap; gap: 12px; justify-content: center;
  }
  .kb-gen-image-preview-item {
    position: relative;
    width: 120px; height: 120px;
    border: 1px solid #e4e7ed; border-radius: 6px;
    overflow: hidden;
    img { width: 100%; height: 100%; object-fit: cover; }
    .kb-gen-img-remove {
      position: absolute; top: 4px; right: 4px; opacity: 0.85;
      &:hover { opacity: 1; }
    }
  }
  .kb-gen-image-add-btn {
    width: 120px; height: 120px;
    border: 2px dashed #dcdfe6; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; transition: border-color 0.2s;
    color: #c0c4cc;
    &:hover { border-color: #409eff; color: #409eff; }
  }
  .kb-gen-result {
    .kb-gen-summary {
      font-size: 14px; color: #606266; margin-bottom: 12px;
      display: flex; align-items: center; gap: 8px;
    }
  }
  .kb-gen-file-list { display: flex; flex-direction: column; gap: 8px; }
  .kb-gen-file-card {
    border: 1px solid #e4e7ed; border-radius: 6px; overflow: hidden;
  }
  .kb-gen-file-header {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px;
    cursor: pointer; background: #f5f7fa;
    font-size: 13px;
    &:hover { background: #ecf5ff; }
    .kb-gen-file-icon { color: #409eff; flex-shrink: 0; }
    .kb-gen-file-path { font-weight: 600; color: #303133; flex: 1; }
    .kb-gen-file-meta { font-size: 12px; color: #c0c4cc; flex-shrink: 0; }
  }
  .kb-gen-file-content {
    padding: 16px 20px;
    max-height: 350px; overflow-y: auto;
    border-top: 1px solid #ebeef5;
  }

  .kb-gen-uncertain {
    margin-top: 12px;
    .kb-gen-uncertain-item {
      border: 1px solid #faecd8; border-radius: 6px;
      padding: 12px 14px; margin-bottom: 10px;
      background: #fef9f0;
    }
    .kb-gen-uncertain-header {
      display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
    }
    .kb-gen-uncertain-file { font-size: 12px; color: #909399; }
    .kb-gen-uncertain-question { font-size: 14px; color: #303133; margin-bottom: 4px; }
    .kb-gen-uncertain-context { font-size: 13px; color: #909399; font-style: italic; }
  }
}

// ============== 响应式适配 ==============
@media (max-width: 768px) {
  .kb-fs-layout {
    flex-direction: column;
    height: auto;
    min-height: 520px;
    max-height: none;
  }

  .kb-fs-tree {
    width: 100%;
    max-width: none;
    min-width: auto;
    max-height: 40vh;
    border-right: none;
    border-bottom: 1px solid #e4e7ed;
  }

  .kb-fs-content {
    min-height: 280px;
  }

  .kb-fs-content-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 14px;
  }

  .kb-fs-content-body {
    padding: 14px 16px;
  }

  .kb-fs-edit-textarea {
    padding: 14px 16px;
  }
}

@media (max-width: 480px) {
  .kb-fs-tree-header {
    flex-wrap: wrap;
    gap: 8px;
  }

  .kb-fs-content-header {
    .kb-fs-content-title {
      font-size: 13px;
    }
  }

  .kb-fs-content-body {
    padding: 12px;
    font-size: 13px;
  }

  .kb-fs-edit-textarea {
    padding: 12px;
    font-size: 13px;
  }
}
</style>
