# 生产环境部署准备 — iOS 自动化 + 墨刀需求分析升级

> 编写日期：2026-09-17（晚间更新）
> 基于测试环境（fix/p0-low-risk 分支）与生产环境（main 分支）的对比分析

---

## 一、当前环境状态总览

| 项目 | 生产环境 (main) | 测试环境 (fix/p0-low-risk) |
|------|----------------|---------------------------|
| 最新提交 | 4d6ee41 | 5264474 |
| iOS 自动化 | 无 | 已实现（部分未提交） |
| Midscene 引擎 | 无 | Web + iOS |
| App 自动化流水线 | 无 | 已实现 |
| 弹窗自动处理 | 无 | 已实现 |
| Token 消耗统计 | 无 | 已实现 |
| Midscene 持久化卷 | 无 | testhub-midscene |
| 墨刀断点续读 | 无 | 已实现 |
| 墨刀 PRD 报告解析 | 无 | 已实现 |
| 墨刀单文件 H5 解析 | 无 | 已实现 |
| 墨刀画布级独立分支 | 无 | 已实现 |
| 墨刀任务列表页 | 无 | 已实现（ModaoListView） |
| 墨刀画布看板 | 无 | 已实现（ModaoCanvasBoard） |
| AIModelService 解耦 | 在 models.py | 已迁移至 ai_model_service.py |

当前分支 fix/p0-low-risk 领先 main 19 个提交，且有大量未提交的工作区改动。

---

## 二、iOS 自动化相关变更

### 2.1 已提交的变更

| 提交 | 日期 | 内容 |
|------|------|------|
| 98ee715 | 2026-08-26 | airtest_engine.py iOS 支持：WDA 连接、iosPoco 驱动 |
| 273a349 | 2026-09-10 | AppDevice 模型增加 platform 字段（android/ios） |

### 2.2 未提交的变更

#### 后端核心文件

| 文件 | 说明 |
|------|------|
| apps/ui_automation/midscene_ios_engine.py | 新增 iOS Midscene 引擎 |
| apps/ui_automation/midscene_ios_node/ | 新增 Node.js 服务目录 |
| apps/ui_automation/popup_handler.py | 新增 通用弹窗自动处理 |
| apps/ui_automation/llm_usage.py | 新增 模型调用消耗统计 |
| apps/ui_automation/airtest_engine.py | 修改 iOS WDA 连接增强 |
| apps/ui_automation/midscene_engine.py | 修改 Android 引擎增强 |
| apps/ui_automation/models.py | 修改 新增字段 |
| apps/ui_automation/views.py | 修改 新增 iOS API |

#### 数据库迁移文件（未提交）

| 迁移文件 | 说明 |
|----------|------|
| 0009_appdevice_wda.py | app_devices 增加 wda_host、wda_port |
| 0010_businessaction_category.py | businessaction 增加 category |
| 0011_aicase_auto_dismiss_popup.py | aicase 增加 auto_dismiss_popup |
| 0012_aicase_steps_frozen_at.py | aicase 增加 steps_frozen_at |
| 0013_aiexecutionrecord_tokens.py | aiexecutionrecord 增加 token 统计 |

#### iOS 运维脚本（13 个文件，未提交）

ios_detect_udid.ps1, ios_detect_lan_ip.ps1, ios_detect_wda.ps1,
ios_device_start.bat, ios_device_stop.bat, ios_diag.bat/ps1,
ios_find_exe.ps1, ios_register_device.ps1, ios_release_ports.ps1,
ios_resolve_server.ps1, ios_tunnel_diag.ps1, ios_wda_host.bat,
package_ios_host.py

---

## 三、墨刀需求分析模块升级（今晚新增）

### 3.1 后端变更

#### modao_extractor.py（+2533 行）

新增 3 种原型来源解析 + 断点续读机制：

| 新功能 | 说明 |
|--------|------|
| 断点续读检查点 | 每读完一页立即落盘，超时不再丢失已读画布 |
| 单文件 H5 原型解析 | 支持 WebShare 分享的单个 HTML 只读页 |
| PRD 报告页解析 | 支持自研 PRD 报告 HTML（侧边栏目录+截图+需求模块） |
| 页面层级检测 | 自动识别父子画布关系（parent_name） |
| 画布文件夹提取 | 按文件夹组织画布（folder 字段） |
| 组件文本提取 | 更精确的 UI 组件文字识别 |
| webshare 纯 HTTP 降级 | Playwright 不可用时降级为纯 HTTP 抓取 |

#### modao_workflow.py（+971 行）

| 新功能 | 说明 |
|--------|------|
| 画布级独立运行 | page_ids 参数，每个画布独立分支互不干扰 |
| 单画布重读模式 | target_page_names，只重读指定画布不影响其他 |
| YAML 引号修复 | 自动修复 LLM 输出的「引号半包裹」坏行 |
| 部分成功状态 | status='partial'，超时保留已读画布可继续 |
| 画布级流水线 | 每个画布独立走 阶段1摘要→阶段2澄清→阶段3设计 |
| 画布审批机制 | page_approved 字段，按画布粒度采纳 |
| 文件夹级选择 | 按文件夹批量勾选/取消画布 |

#### modao_views.py（+757 行）

新增 API：

| API 路由 | 说明 |
|----------|------|
| GET /api/modao/<pk>/folders/ | 获取画布文件夹树 |
| POST /api/modao/<pk>/select-by-folder/ | 按文件夹批量选择画布 |
| POST /api/modao/<pk>/approve-pages/ | 批量审批画布用例 |
| PUT /api/modao/<pk>/pages/<page_id>/edit/ | 编辑单个画布级产物 |

#### models.py 重构

| 变更 | 说明 |
|------|------|
| AIModelService 解耦 | 从 models.py 迁移至 ai_model_service.py（-2339 行/+9 行） |
| ModaoPage 新增字段 | parent_name（父级分组） |

#### 新增文件

| 文件 | 说明 |
|------|------|
| apps/requirement_analysis/ai_model_service.py | AIModelService 独立模块 |
| apps/requirement_analysis/independent_skill/ | 独立技能模块目录 |
| apps/requirement_analysis/migrations/0016_modao_page_folder.py | modao_page.folder 字段迁移 |

### 3.2 前端变更

#### 路由重构

原入口 /modao-skill → 现在指向 ModaoListView（任务列表页）
画布工作页移至 /modao-canvas/:id → ModaoSkillView

新增路由：

| 路由 | 组件 | 说明 |
|------|------|------|
| /modao-canvas/:id | ModaoSkillView.vue | 画布工作页（原主页面） |
| /modao-board/:id | ModaoCanvasBoard.vue | 画布任务看板 |
| /modao-pipeline/:id | CanvasPipelineView.vue | 画布流水线视图 |
| /modao-case-merge/:id | CaseMergeView.vue | 用例合并视图 |
| /automation/dashboard | Dashboard.vue | 自动化测试统一首页 |
| /ui-automation/app-devices | AppDeviceList.vue | App 设备管理 |
| /ui-automation/midscene-web-playground | WebMidscenePlayground.vue | Web Midscene 调试场 |

#### 新增前端文件

| 文件 | 说明 |
|------|------|
| ModaoListView.vue | 墨刀任务列表（新入口页） |
| ModaoCanvasBoard.vue | 画布任务看板 |
| CanvasPipelineView.vue | 画布流水线视图 |
| CaseMergeView.vue | 用例合并视图 |
| CanvasArtifactCard.vue | 画布产物卡片组件 |
| WebMidscenePlayground.vue | Web Midscene 调试场 |

### 3.3 docker-compose.dev.yml 变更

后端端口绑定从 127.0.0.1 改为 0.0.0.0：
`yaml
# 旧：只允许本机访问
- "127.0.0.1:\:8000"
# 新：允许局域网访问（iOS 设备注册需要）
- "\:8000"
`

---

## 四、部署前必须完成的准备工作

### 步骤 1：提交所有未提交的代码

`powershell
cd C:\TestHub

# --- 后端 iOS 核心 ---
git add apps/ui_automation/midscene_ios_engine.py
git add apps/ui_automation/midscene_ios_node/
git add apps/ui_automation/popup_handler.py
git add apps/ui_automation/llm_usage.py
git add apps/ui_automation/migrations/0009_appdevice_wda.py
git add apps/ui_automation/migrations/0010_businessaction_category.py
git add apps/ui_automation/migrations/0011_aicase_auto_dismiss_popup.py
git add apps/ui_automation/migrations/0012_aicase_steps_frozen_at.py
git add apps/ui_automation/migrations/0013_aiexecutionrecord_tokens.py
git add apps/ui_automation/airtest_engine.py
git add apps/ui_automation/midscene_engine.py
git add apps/ui_automation/models.py
git add apps/ui_automation/views.py
git add apps/ui_automation/serializers.py
git add apps/ui_automation/urls.py
git add apps/ui_automation/reports.py

# --- 后端墨刀模块 ---
git add apps/requirement_analysis/modao_extractor.py
git add apps/requirement_analysis/modao_workflow.py
git add apps/requirement_analysis/modao_views.py
git add apps/requirement_analysis/models.py
git add apps/requirement_analysis/serializers.py
git add apps/requirement_analysis/urls.py
git add apps/requirement_analysis/views.py
git add apps/requirement_analysis/ai_model_service.py
git add apps/requirement_analysis/independent_skill/
git add apps/requirement_analysis/migrations/0016_modao_page_folder.py

# --- iOS 运维脚本 ---
git add scripts/ios_*
git add scripts/package_ios_host.py

# --- 前端 ---
git add frontend/src/

# --- 配置 ---
git add backend/settings.py
git add docker-compose.yml
git add docker-compose.dev.yml
git add docker_start.py
git add Dockerfile.backend

git commit -m "feat: iOS 自动化 + 墨刀需求分析大升级（断点续读/PRD解析/画布独立分支）"
`

### 步骤 2：合并到 main 分支

`powershell
git checkout main
git merge fix/p0-low-risk
git push origin main
`

### 步骤 3：补充 docker_start.py 的幂等 DDL

当前 docker_start.py 已覆盖的字段：
- app_devices.wda_host / wda_port
- app_automation_devices.platform
- ui_business_actions.category
- modao_page.folder, page_summary, page_clarification, page_testpoints_json 等

还需要补充：

`python
# modao_page.parent_name（画布父级分组，今晚新增）
cur.execute(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'modao_page' "
    "AND column_name = 'parent_name'"
)
if not cur.fetchone():
    cur.execute(
        "ALTER TABLE modao_page ADD COLUMN parent_name "
        "VARCHAR(200) NOT NULL DEFAULT ''"
    )
    print('ensured column parent_name on modao_page')

# ui_ai_cases.auto_dismiss_popup
# ui_ai_cases.steps_frozen_at
# ui_ai_execution_record.model_calls / prompt_tokens / completion_tokens
# ui_ai_execution_record.tokens_estimated / replay_mode / error_message
# （同上，见 iOS 部分）
`

### 步骤 4：确认 docker-compose.yml 变更

生产 docker-compose.yml 需要新增 testhub-midscene 卷：

`yaml
# backend volumes 新增：
- testhub-midscene:/root/.midscene

# volumes 声明新增：
testhub-midscene:
`

### 步骤 5：iOS 宿主机环境准备

iPhone --USB--> Windows 电脑 (WDA:8100) --网络--> TestHub 服务器 (Docker)

1. 安装 iTunes（Apple USB 驱动）
2. 安装 go-iOS 或 tidevice（USB 隧道）
3. 编译/部署 WebDriverAgent (WDA)
4. 部署 scripts/ios_* 到该 Windows 电脑
5. 修改 ios_register_device.ps1 中 ServerUrl 指向生产地址
6. 确保 8100 端口对 TestHub 服务器可达

### 步骤 6：生产部署执行

`powershell
cd C:\TestHub
git pull origin main
deploy.bat
`

### 步骤 7：部署后验证清单

- [ ] 后端启动无报错
- [ ] 前端页面正常加载
- [ ] 墨刀需求分析入口变为任务列表页（ModaoListView）
- [ ] 点击「继续」进入画布工作页（ModaoSkillView）
- [ ] 画布任务看板可正常打开
- [ ] 断点续读功能正常（超时后可继续读取）
- [ ] 设备管理页面能看到 iOS 平台选项
- [ ] iOS 设备注册/在线状态正常
- [ ] Midscene 引擎首次执行正常

---

## 五、风险评估

| 风险项 | 等级 | 说明 | 缓解措施 |
|--------|------|------|----------|
| 未提交代码丢失 | 高 | iOS + 墨刀大量代码未入库 | 立即提交 |
| 墨刀路由变更 | 中 | /modao-skill 入口变了 | 旧书签需更新 |
| AIModelService 迁移 | 中 | 从 models.py 拆出 | 确保 ai_model_service.py 一起提交 |
| 迁移执行失败 | 中 | docker_start.py 未覆盖所有新字段 | 补充 DDL |
| Midscene 首次启动慢 | 中 | Node 运行时首次下载慢 | 已挂卷持久化 |
| iOS WDA 连接失败 | 中 | 网络/证书/USB 隧道问题 | 使用 ios_diag.bat 诊断 |

---

## 六、部署顺序建议

1. 提交代码（iOS + 墨刀）
2. 补充 docker_start.py 幂等 DDL（parent_name + iOS 字段）
3. 合并到 main 并 push
4. 生产服务器 git pull
5. deploy.bat
6. 验证后端启动 + 数据库迁移
7. 验证前端页面（特别是墨刀模块路由变化）
8. iOS 宿主机环境搭建
9. 注册 iOS 设备 → 执行测试

---

*文档结束*
