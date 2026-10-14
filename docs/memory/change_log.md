# 变更流水与逻辑关联日志 (Change Log & Logic Trace)

> **记录规则**：按时间倒序排列。每次提交或重要环境/代码变更必须沉淀至此。

---

## 📅 2026-10-14

### 6. 画布级需求澄清隔离与跨画布数据串台治理

* **变更类型**：`fix` / `data-clean`
* **背景与原因**：
  在单画布流水线视图（如 Page 15 `失败弹窗`）中，发现其需求澄清卡片错误地包含了大量 `定制mini形象 状态动画加载 / 标注1（VA-002）` 等其他画布的澄清项。经排查，旧工作流中 `run_clarify()` 在多画布联合生成澄清时，执行了广播赋值（`p.page_clarification = out`），将全量联合清单无差别复制给了每一个参与画布，导致各画布的澄清数据严重串台。
* **涉及文件与修改点**：
  * [apps/requirement_analysis/modao_workflow.py](file:///D:/code/my-project/apps/requirement_analysis/modao_workflow.py)：
    1. 限制审查输入范围：当指定了画布子集时，`structured` 严格收敛为当前选中画布的 `page_summary` 集合，避免将全局需求摘要送入单画布澄清；
    2. 落地按画布隔离写回：在写回 `p.page_clarification` 时，基于条目的 `location` 字段与画布的 `page_name` / `page_no` 进行归属过滤，每个画布仅保留真正属于本画布的澄清项，杜绝跨画布污染。
  * **数据清洗**：
    清洗了 Page 1008（`失败弹窗`）中误混入的 7 条状态动画澄清项，恢复其唯一的本地缺失点，并同步修正了全局 `clarification_log`。
* **前后逻辑关联与连带影响**：
  * **正向收益**：单画布流水线与画布卡片上的澄清项精确对应当前画布，彻底解决“看 A 画布却显示 B 画布澄清点”的严重串台 bug，后续单画布生成用例时不会再被无关画布的未填写澄清阻断。
* **验证结果**：
  * Page 1008 `page_clarification` 已恢复为 1 条本地真实问题；
  * 后端容器重启生效，单画布流水线数据展示准确。

### 5. 原型底模降噪与测试点脑补规避（批注增量优先与未定义元素熔断）

* **变更类型**：`fix` / `prompt` / `refactor`
* **背景与原因**：
  在处理包含整页线框图底模与局部便签批注的画布（如 Page 14 `定制mini形象 状态动画加载`）时，多模态 OCR 提取了底图背景文字（`添加状态`、`自定义状态`、`常用状态`、`状态名称`）。阶段1（P0）因缺少底模降噪约束，误将底模文字提炼为新增业务功能（`key_features`），并产生待澄清点 `PCI-001`；阶段3（P2）受边界值全面覆盖硬约束驱使，机械套用输入框边界测试模板，导致凭空生成了与实际需求无关的用例点（如 `TP_状态动画_018: 自定义状态名称为空或超长边界验证`）。
* **涉及文件与修改点**：
  * [apps/requirement_analysis/modao_skill/prompts/p0_requirement_struct.md](file:///D:/code/my-project/apps/requirement_analysis/modao_skill/prompts/p0_requirement_struct.md)：
    1. 增加硬约束第 23 条「批注增量优先（Annotation-First）」：严格以便利贴、批注和说明所指向的变更点为需求基准，未提及的线框图固有元素绝非本次新增特性；
    2. 增加硬约束第 24 条「原型底模降噪」：底图占位控件仅作视觉背景，严禁提炼为新增功能，禁止无依据发起边界疑问；
    3. 在负向禁止中明确禁止将未批注的底图文字提炼到 key_features 及无端提问。
  * [apps/requirement_analysis/modao_skill/prompts/p2_testpoint_gen.md](file:///D:/code/my-project/apps/requirement_analysis/modao_skill/prompts/p2_testpoint_gen.md)：
    1. 增加硬约束第 9 条「严禁对未定义规则的底模元素脑补边界/异常测试点」：对于无字符限制/接口定义的底模元素，绝对禁止生成“为空/超长/非法字符”边界用例；
    2. 增加硬约束第 10 条「待澄清阻塞项不生成测试点」：凡未获得确认的 PCI blocked 猜想项，严禁生成正式断言测试点。
  * [apps/requirement_analysis/modao_workflow.py](file:///D:/code/my-project/apps/requirement_analysis/modao_workflow.py)：
    1. 重构 `_source_text` 与 `_source_text_for_pages` 输入组织结构，将【核心需求标注/便利贴批注】置顶并打上高权重标签；
    2. 将【画布全景 OCR / 背景底模文字】置底并显式标注“仅供视觉上下文参考，未批注提及的固有文字非本次需求”，引导大模型注意力。
* **前后逻辑关联与连带影响**：
  * **正向收益**：从 Prompt 和数据输入两端同时切断了底图背景噪音向测试用例渗透的链路，彻底消除类似 `TP_状态动画_018` 的幻觉测试点。
* **验证结果**：
  * 后端容器重启并重载 Prompt 缓存，服务健康正常。
  * 对 Page 14 画布（id 1007 `定制mini形象 状态动画加载`）执行阶段1（`run_struct(force=True)`）自测：结构化摘要中的 `key_features` 与 `business_flow` 已完全剔除底图无关元素（`添加状态/自定义状态/常用状态`），无任何自定义状态名称的歧义提问；
  * 执行阶段3（`run_design_phase1`）自测：重新生成 28 条业务测试点，原 `TP_状态动画_018: 自定义状态名称为空或超长边界验证` 彻底消失，新 018 转为合规业务测试点 `TP_状态动画_018: 任务状态编码0-5全量映射验证`；
  * 全量测试点与全局 `final_testpoints_json` 视图自动同步完成。

### 1. 墨刀画布生成后全选逻辑重构与全局全选/取消工具栏

* **变更类型**：`feat` / `ux`
* **背景与原因**：
  1. 墨刀需求提取完成后，旧逻辑会静默执行 `selected = True` 将全部画板直接全选。当画板包含封面/更新说明等非测试画板或涉及 20+ 个复杂页面时，不仅消耗巨量 Token，还会把无关内容混入后续结构化和用例设计中。
  2. 看板中画板分布在多个文件夹下，原本仅有各文件夹内的小复选框，缺乏全局统一控制条，导致无法一键清空或一键全选所有画板。
* **涉及文件与修改点**：
  * [apps/requirement_analysis/modao_workflow.py](file:///D:/code/my-project/apps/requirement_analysis/modao_workflow.py)：将新提取入库画板的默认属性改为 `selected = False`，实现“默认不全选，把选择权交给人工步骤”。
  * [frontend/src/views/requirement-analysis/ModaoCanvasBoard.vue](file:///D:/code/my-project/frontend/src/views/requirement-analysis/ModaoCanvasBoard.vue)：在看板顶部筛选栏新增全局控制按钮 `【☑ 全部勾选】`、`【☐ 全部取消勾选】` 及实时已选数量统计（`已勾选 X / 共 Y 个画布`），点击后一键更新并持久化至服务端。
  * [frontend/src/views/requirement-analysis/ModaoSkillView.vue](file:///D:/code/my-project/frontend/src/views/requirement-analysis/ModaoSkillView.vue)：修正列表头全选框的事件触发机制，避免 `@click.stop` 阻断 Element Plus 事件。
* **前后逻辑关联与连带影响**：
  * **正向收益**：测试人员进入看板后拥有清晰直观的画板初筛操作关卡，既可一键全选，也可一键清空后只挑重点画板，极大降低了大模型 Token 消耗并提升了测试针对性。
* **验证结果**：
  * 数据库原型 101 的 22 个画板已成功重置为未勾选；
  * 前端重新构建并部署生效，`http://localhost:18080` 返回 200。

### 2. 文件夹头部批量操作栏补充「🔧 结构化」入口与全局全选交互优化

* **变更类型**：`feat` / `ux`
* **背景与原因**：
  1. 墨刀画布工作流中，阶段3（测试设计）和阶段4（用例生成）强依赖阶段1生成的结构化摘要（`page_summary`）。此前文件夹头部批量操作条仅提供了 `🔍 澄清`、`📐 测试设计`、`📋 用例` 三个按钮，缺失了阶段1批量结构化入口，用户在画布看板只能逐个进入抽屉点击结构化，无法对勾选的画布一次性批量运行结构化。
  2. 原全局筛选控制栏中的按钮文本与高亮状态容易被误读为“当前已全选”，优化为带有半选（`indeterminate`）属性的标准 Element Plus `<el-checkbox>` 控件及「清空勾选」按钮，状态感知清晰。
* **涉及文件与修改点**：
  * [frontend/src/views/requirement-analysis/ModaoCanvasBoard.vue](file:///D:/code/my-project/frontend/src/views/requirement-analysis/ModaoCanvasBoard.vue)：
    1. 在 `.folder-actions` 批量工具栏前部新增 `<el-button size="mini" type="info" plain @click="onFolderBatchAction(fg, 'struct')">🔧 结构化 ({{ fg.selectedCount }})</el-button>`。
    2. 在 `onFolderBatchAction` 中注册 `'struct': '需求结构化'`，支持批量确认提示与串行排队运行。
    3. 顶部筛选栏替换为原生 `<el-checkbox>` 联动状态与「清空勾选」快捷按钮。
* **前后逻辑关联与连带影响**：
  * **正向收益**：补齐了从“画板勾选 -> 批量结构化 -> 批量澄清/设计/用例”的完整链路，用户无需重复进入抽屉单点触发，大幅提升批量处理效率。
* **验证结果**：
### 3. 需求澄清列表新增「删除澄清点」功能与数据级联同步

* **变更类型**：`feat` / `ux`
* **背景与原因**：
  大模型在阶段2生成需求澄清问题时，可能产生部分经人工业务确认无需考虑的冗余条目（如边界点：`定制mini形象 状态动画加载 / 便利贴批注1（状态映射规则）`）。旧逻辑下澄清项只能逐条填写回复或进入原文模式手动修改，无法直接一键移除；未填回复的条目还会阻断最终用例生成门禁（Gate 校验抛出“仍有 X 条问题未填写人工结论”）。
* **涉及文件与修改点**：
  * [frontend/src/views/requirement-analysis/CanvasArtifactCard.vue](file:///D:/code/my-project/frontend/src/views/requirement-analysis/CanvasArtifactCard.vue)：
    1. 在澄清逐条卡片头部（`.ci-head`）增加 `🗑️ 删除` 操作按钮，点击后弹出二次确认防误删；
    2. 确认删除后从 JSON 数组中剔除对应条目，写回 `page_clarification` 并重算卡片条数统计与空状态（`暂无澄清项`）；
  * [frontend/src/views/requirement-analysis/ModaoSkillView.vue](file:///D:/code/my-project/frontend/src/views/requirement-analysis/ModaoSkillView.vue)：
    1. 在阶段2卡片逐条视图及编辑弹窗（`clarifyEditItems`）中同步增加单条删除按钮与响应方法；
    2. 删除后即时持久化并触发用例门禁状态与变更刷新；
  * [apps/requirement_analysis/modao_views.py](file:///D:/code/my-project/apps/requirement_analysis/modao_views.py)：
    1. 在 `modao_edit` 中增加对 `clarification_log` 变更的级联同步（自动更新尚未单独修改过的画布级 `page_clarification`）；
    2. 在 `modao_page_edit` 中加入 `.strip()` 宽容度比对，保证画布级更新顺利同步任务级。
* **前后逻辑关联与连带影响**：
  * **正向收益**：业务人员能快速剔除无效澄清项，清理后下游阶段3测试设计与阶段4用例生成不会受到无关噪音干扰，门禁阻断风险完全消除。
* **验证结果**：
### 4. 测试点列表新增「删除测试点」功能与画布/任务级双向同步

* **变更类型**：`feat` / `ux`
* **背景与原因**：
  在阶段3测试设计完成后，系统基于大模型提取了若干测试点（如 `TP_状态动画_001 · 状态动画加载页入口可达性验证`）。但在实际业务测试评估中，部分测试点（如非必要链路、无需测试的兜底项）无需投入资源编写用例与执行测试。此前在画布看板抽屉的“测试点”卡片中，没有直接删除单条测试点的入口，用户只能被迫进入源码编辑弹窗手动删改 JSON。
* **涉及文件与修改点**：
  * [frontend/src/views/requirement-analysis/CanvasArtifactCard.vue](file:///D:/code/my-project/frontend/src/views/requirement-analysis/CanvasArtifactCard.vue)：
    1. 为结构化卡片视图（`.obj-card`）新增包含编号、ID 标签（如 `TP_状态动画_001`）、优先级标签和 `🗑️ 删除` 按钮的卡片头部（`.obj-head`）；
    2. 新增 `deleteStructuredItem` 方法，带精确二次确认弹窗（“确定要删除测试点「TP_状态动画_001 · 状态动画加载页入口可达性验证」吗？”）；
    3. 支持通用 JSON 数组及包装结构（`testpoints` / `smoke_testcases` / `data`）的原生剔除与空状态优雅回退。
  * [frontend/src/views/requirement-analysis/ModaoSkillView.vue](file:///D:/code/my-project/frontend/src/views/requirement-analysis/ModaoSkillView.vue)：
    1. 为主流程视图 `removeMainTpItem` 补充精准防误删确认弹窗。
  * [apps/requirement_analysis/modao_views.py](file:///D:/code/my-project/apps/requirement_analysis/modao_views.py)：
    1. 画布级删除自动触发全局 `final_testpoints_json` 重新聚合；
    2. 任务级全局删除测试点时，双向级联移除各画布 `page_testpoints_json` 中的对应测试点，维持数据一致性。
* **前后逻辑关联与连带影响**：
  * **正向收益**：测试人员可直观剔除冗余测试点，后续生成测试用例（阶段4）时直接减少大模型 Token 消耗并聚焦关键路径。
* **验证结果**：
  * 前端重新构建并部署，看板与主流程视图均已生效。

---

## 📅 2026-10-12

### 1. 团队开发环境接入与环境启动链条打通

* **变更类型**：`fix` / `config`
* **背景与原因**：
  新成员拉取代码后，在尝试接入团队共享开发环境时遇到以下连锁问题：
  1. Docker Desktop 处于停止状态；
  2. 基础镜像包存在于本地 `D:\docker_files\testhub-backend-base.tar` 但未加载；
  3. `Dockerfile.backend` 首行包含 `# syntax=docker/dockerfile:1`，在局域网/离线环境下 Buildx 解析远程语法抛出 `unexpected EOF` 导致后端构建中断；
  4. `docker-compose.dev.yml` 中的 `backend` 服务硬编码了 `DB_HOST: mysql` 和 `DB_PORT: 3306`，强制覆盖了 `.env.dev` 中的远程配置，导致即使配好了共享库也会连向本地空库。
* **涉及文件与修改点**：
  * [Dockerfile.backend](file:///D:/code/my-project/Dockerfile.backend)：删除了顶层 `# syntax=docker/dockerfile:1`，直接使用 Docker 内置解析器，确保离线快速构建成功。
  * [docker-compose.dev.yml](file:///D:/code/my-project/docker-compose.dev.yml)：移除了 `backend.environment` 下硬编码的 `DB_HOST: mysql` 和 `DB_PORT: 3306`，使 `env_file: .env.dev` 中的远程共享库配置（`192.168.8.75:13306`）正确生效。
* **前后逻辑关联与连带影响**：
  * **正向收益**：彻底打通了 `docker-compose.dev.yml` 与 `.env.dev` 的联动逻辑，新成员执行 `docker compose up -d` 即可直接拉通团队 11 个业务项目数据。
  * **风险评估**：零破坏性。本地起辅助 mysql 仍然健康运行，后端流量无缝指向共享库。
* **验证结果**：
  * 后端镜像构建耗时降至 13 秒；
  * `docker compose --profile app -f docker-compose.dev.yml up -d` 全套容器健康启动；
  * 使用默认账号 `admin` / `admin123` 登录成功并获取 JWT Token，调用 `/api/projects/` 返回 11 个项目（与接入文档完全对齐）。

---

### 2. Swagger 接口文档 500 崩溃与根路径 404 修复

* **变更类型**：`fix` / `feat`
* **背景与原因**：
  1. 打开 `http://localhost:18000/api/docs/` (Swagger UI) 报错白屏，排查后端日志发现 `GET /api/schema/` 抛出 `TypeError: 'Meta.fields' must not contain non-model field names: execution_mode` 导致 500 异常。
  2. 打开 `http://localhost:18000` 报 Django 默认 404 页面，体验不佳。
* **根本原因分析**：
  * [apps/ui_automation/views.py](file:///D:/code/my-project/apps/ui_automation/views.py#L551) 中的 `PageObjectViewSet` 声明了 `filterset_fields = ['project', 'execution_mode']`；
  * 但 [apps/ui_automation/models.py](file:///D:/code/my-project/apps/ui_automation/models.py#L232) 中 `PageObject` 模型并**不存在** `execution_mode` 字段（该字段属于 `AIExecutionRecord` / `AICase`）；
  * 当 `drf-spectacular` 生成 OpenAPI 模式遍历 ViewSet 时，`django-filters` 校验模型字段抛出 TypeError，拖垮了整个 `/api/schema/`。
* **涉及文件与修改点**：
  * [apps/ui_automation/views.py](file:///D:/code/my-project/apps/ui_automation/views.py#L551)：将 `filterset_fields` 修正为 `['project']`，剔除非模型字段。
  * [backend/urls.py](file:///D:/code/my-project/backend/urls.py#L14)：引入 `RedirectView`，为根路径 `""` 配置永久重定向到 `/api/docs/`。
* **前后逻辑关联与连带影响**：
  * **正向收益**：
    1. `/api/schema/` 恢复 `200 OK`，Swagger 接口文档完整渲染；
    2. 开发者在浏览器中输入 `http://localhost:18000` 即可自动跳转进入 Swagger 交互式文档界面。
  * **风险评估**：前端通过 `project` 过滤页面对象（PageObject）的功能完全不受影响，无任何破坏性。
* **验证结果**：
  * `curl -i http://localhost:18000/api/docs/` 返回 `200 OK`；
  * `curl -i http://localhost:18000/` 返回 `302 Found`（指向 `/api/docs/`）；
  * `curl -i http://localhost:18000/api/schema/` 正常返回 OpenAPI JSON 规范。

---

### 3. 创建持续演进项目记忆库系统

* **变更类型**：`docs`
* **背景与原因**：
  为后续团队长期协作、持续架构重构提供一致的上下文沉淀，规避跨轮次对话和跨人协作中的信息碎片化。
* **涉及文件**：
  * 创建了 [docs/memory/](file:///D:/code/my-project/docs/memory/) 目录；
  * 初始构建了 [README.md](file:///D:/code/my-project/docs/memory/README.md)、[project_profile.md](file:///D:/code/my-project/docs/memory/project_profile.md)、[change_log.md](file:///D:/code/my-project/docs/memory/change_log.md)、[architecture_decisions.md](file:///D:/code/my-project/docs/memory/architecture_decisions.md)、[pitfalls_and_rules.md](file:///D:/code/my-project/docs/memory/pitfalls_and_rules.md)、[roadmap_and_tasks.md](file:///D:/code/my-project/docs/memory/roadmap_and_tasks.md)。
