# TestHub 已修 Bug 回归清单（优化前必读）

> **用途**：防止迭代优化时「同样的 bug 反复出现 / 月累计越改越多」。
> **规则**：每次对 `apps/`、`frontend/` 做功能优化或重构前，先读本文件，逐项核对「优化前必跑」项；改完再核对一次。
> AI 助理在开始优化任务时，应主动加载本文件并结合 `CODEBUDDY.md`。

---

## 一、已知 Bug 台账（已核对代码，标注修复质量）

### BUG-01 · 流式生成 async 外键未预取（TASK_9E7FAF26）
- **预期**：`comprehensive` 等模式的流式测试用例生成正常完成（含带 `version_id`、走知识库的任务）。
- **实际（修复前）**：`generate_test_cases_stream` 在 async 循环里访问懒加载 ForeignKey / 查 `CoverageReport`，触发同步 DB 查询失败（`SynchronousOnlyOperation`），任务失败需重生成。
- **根因**：async 函数体内直接做 ORM（`writer_prompt_config.content`、`build_knowledge_context` 查知识库、`_build_abnormal_scene_section` 查 `CoverageReport`、`writer_model_config`）。原补丁仅在调用点预取了 4 个 FK，但函数体内仍懒加载，且 `build_knowledge_context` / 异常场景统计仍在 async 内被再次查询——带 `version_id` 的任务必崩。
- **修复（已根治，2026-08-27）**：所有 ORM 访问移到 `views.py` 的**同步预取段**（`execute_task` 进入 `loop.run_until_complete` 之前），结果挂到 `task` 实例（`_pre_writer_prompt` / `_pre_reviewer_prompt` / `_pre_writer_model` / `_pre_reviewer_model` / `_pre_fetched_knowledge_context` / `_pre_abnormal_scene`）；四个走该预取段的 async 函数（`generate_test_cases`、`generate_test_cases_stream`、`review_test_cases`、`review_test_cases_stream`、`revise_test_cases_based_on_review`）改为只读缓存属性，函数体内**零 ORM**。
- **修复质量**：✅ **根治**。async 内不再有任何 DB 查询，新增 FK/知识库访问若漏预取会立即报 AttributeError（fail-fast），而非偶发异步崩溃。
- **遗留项**：`audit_knowledge_base`（models.py:2661/2676/2679）仍在 async 上下文直接读 `reviewer_model_config`/`writer_model_config`，属同类隐患，若该函数也被 async 调用需同样处理（当前为同步调用，暂安全）。
- **优化前必跑**：✅ 跑一次 `comprehensive` 流式生成（含带 `version_id` 的任务）；`grep -n "task.writer_prompt_config\b\|task.reviewer_prompt_config\b\|task.writer_model_config\b\|task.reviewer_model_config\b" apps/requirement_analysis/models.py` 应只剩 `getattr(..., task.xxx)` 兜底与 `kb_audit` 两处。

### BUG-02 · rerun_review 三项（中文分词失效 / 未回复项注入 / human_feedback 覆盖）
- **预期**：重跑评审只注入「已真正回复」的确认项，不覆盖已有 `human_feedback`。
- **实际（修复前）**：未回复项（"(未填写)"）被当作已确认结论注入；`human_feedback` 被覆盖。
- **修复位置（已验证）**：`apps/requirement_analysis/views.py:3442` `rerun_review`；`:3494-3514` 用正则 `确认回复[：:]\s*(?!\(未填写\))` 过滤未回复确认项；`:3487` 处理 `human_feedback`；结构为「同步取 ORM → 纯异步调 AI → 同步存」。
- **修复质量**：✅ **扎实**。
- **优化前必跑**：✅ 对有 `"(未填写)"` 确认项的任务重跑评审，确认报告不把未回复项列为「已确认」，且 `human_feedback` 未被覆盖。

### BUG-03 · 前端详情页下拉框显示数字 ID 而非名称
- **预期**：详情页返回后下拉框显示名称；「下一步」返回用例列表。
- **实际**：下拉框显示数字 ID；返回/下一步路由错误。
- **位置**：`frontend/src/views/...`（**待定位具体组件**，疑似 `projects/` 或 `testcases/` 相关详情组件）。
- **状态**：🔍 需定位文件后补回归用例。
- **优化前必跑**：✅ 进入用例详情 → 返回 → 检查下拉框显示名称；检查「下一步」回用例列表。

### BUG-04 · 评审报告卡片缺失时间戳 / 需区分最终评审
- **预期**：评审报告卡片显示时间戳，并区分哪次为最终结果。
- **位置**：`apps/reviews/`（models.py / views.py / serializers.py）。
- **优化前必跑**：✅ 查看评审报告卡片是否带时间；多次评审时能区分最终结果。

### BUG-05 · Modao skill 9 次 LLM 调用优化（进行中）
- **位置**：`apps/requirement_analysis/modao_skill/prompts/`（共 9 次 LLM 调用）。
- **状态**：🔧 优化中（削减 token vs 保持质量的权衡）。
- **优化前必跑**：⚠️ 调用次数统计 + 输出质量回归（见 `apps/requirement_analysis/tests/test_modao_workflow_safety.py`）。

### BUG-06 · 墨刀横向多列画布只识别左列几页（0.85 硬切 + 切片未实现，已修复）
- **预期**：横向排列多列页面的墨刀画布（如「饮食情况」10 列）阶段0 能识别全部列页面。
- **实际（修复前）**：`_MODAO_BOUNDS_JS` 的 `b.left > vw*0.85` 在归一化后把右侧横向页面误当批注面板切掉（饮食情况 87 widget 只剩 6 个，只识别 3 页）；且 `_screenshot_canvas_roi` 注释承诺的切片从未实现，超宽画布整图降采样后视觉模型仍识别不全。
- **根因**：见「已修Bug回归清单.md」P0 #11（`#screens` bbox 铺满视口不可当裁剪框，但 `contains` 判断可靠；切片代码缺失）。
- **修复（已实测，2026-08-31）**：`modao_extractor.py` 归属判断改 `#screens.contains(w)`；`_screenshot_canvas_roi` 实现 2000CSS/OVERLAP60 网格切片，`_run_ocr_batch` 逐段 OCR 合并。
- **修复质量**：✅ **根治**（实测饮食情况识别出页面 10/11/12/13/14/15/16/20/22 共 9 页完整内容，其他画布截图 sha 未变、零影响）。
- **优化前必跑**：✅ 重跑含横向多列画布原型阶段0，确认该页 `screenshot_segments` 长度 >1 且 `vision_text` 覆盖全部列页面。

### BUG-07 · 单文件 H5 交互原型识别（新能力，已支持）
- **来源**：用户提供 `http://192.168.1.80/WebShare/.../loveydovey-v1-prototype-final-readonly.html`（WebShare 分享的单 HTML 只读页）。
- **格式**：自研单文件 H5 交互原型——内联 JS `const pages = [{id, group, title, states}]` 定义页面树，另有「页面 id → HTML 模板」的 JSON 对象（文本静态内联）；非墨刀、非 Axure（无 `data/document.js`）。
- **原状**：墨刀链路只读到初始 1 页；Axure/webshare 链路因无 `document.js` 直接返回空。
- **修复（已实测，2026-08-31）**：`modao_extractor.py` 新增单文件 H5 解析——`_parse_singlefile_h5`（`pages` 数组 + 模板 JSON，`_extract_js_balanced` 引号感知括号配对，模板源取「key 命中页面 id 最多」的 JSON 对象）；`extract_webshare_sync` 在 `document.js` 失败时 fallback 到 `_extract_singlefile_h5`；`extract_sync` AUTO-DETECT 在 `_is_axure_url` 失败后探测 `_detect_singlefile_h5` 自动路由；`_ocr_webshare_page_async` 支持 `post_js`（单文件 H5 用 `render('页面id')` 切页截图 + 视觉 OCR）；`modao_views.py` `/webshare/` 改为大小写不敏感。
- **修复质量**：✅ 纯文本链路实测识别 19 页（页面名「分组-标题」、dom_text 共 8098 字符）；`source_type='modao'` 误粘也能自动路由。✅ 视觉/双路融合端到端已验证（2026-09-01）：`writer_vision=qwen3.6-plus` 对 19 页 render 切页截图 OCR 全成功；`analyzer=deepseek-chat` 双路融合产出 130 条带 `source_pages/module/feature/interaction` 证据的需求，覆盖页 19/19；视觉失败率 0% 通过 20% 门禁。
- **【2026-09-01 成本优化·已实测】**：state 切换经源码+DOM+截图三重验证**不改变手机界面内容**（`setState(s)` 只重渲染 phone，而 `views[current]()` 按页面 id 取值；`render(id)` 会把 `currentState` 重置回 `states[0]`；118 个 state 的 `.phone/.screen` innerText 及整页截图 sha 均一致）。据此将 `_extract_singlefile_h5` 改为：①新增 `_read_singlefile_h5_screen_texts`（单次 Playwright 会话逐页 `render` 读 `.phone/.screen` DOM 文本，免费并入 dom_text，总量 8098→11571 字符）；②视觉 OCR 只对**默认态**兜底 1 次（不再逐 state OCR），`states` 元数据仍完整保留。实测全流程 188s（视觉 19/19 命中 sha 缓存、0 次模型调用），融合产出 118 条带证据需求。
- **优化前必跑**：⚠️ 改动 webshare/Axure 解析链路时勿破坏单文件 H5 fallback；此类原型回归用 `_extract_singlefile_h5(url)` 纯文本冒烟（不调模型）即可验证页面树与文本提取。

### BUG-08 · 单画布重读卡死在 extracting（单文件 H5，已修复 2026-09-02）
- **预期**：点「回退到读取（重读此画布）」后秒级完成，只重读选中那一张，任务回到 `extracted`。
- **实际（修复前）**：单文件 H5 原型单画布重读后任务永远停在 `extracting`（前端"读取中"不结束）。
- **根因（4 处）**：
  1. `run_extract` 单画布模式调 `extract_sync(url=...)` 未透传 `target_page_names`，`_extract_singlefile_h5` 对**全部画布**逐页 + 逐 state 调视觉 OCR → 后台线程长时间卡死；
  2. `run_extract` 开头无条件 `status='extracting'`，单模式 `return` 跳过全量收尾且只在 `pending/failed` 时复位 → 正常 `extracted` 态重读后停在 `extracting`；
  3. `update_or_create(page_name=p['page_name'])` 用 extractor 派生名（无 cookie 时缺 group 前缀如 `启动与登录`），与 DB 主键 `账户-启动与登录` 不一致 → 新建脏记录、原画布保持 `needs_rerun` → 用户反复触发（死循环）；
  4. `rerun_stages=None` 触发 `NOT NULL` 约束 `IntegrityError`。
- **修复**：`modao_extractor.py` 全链路透传 `target_page_names`，单画布重读**只对目标画布 OCR**（加 title 包含匹配兜底）；`modao_workflow.py` 单模式结尾统一复位 `status='extracted'`、`update_or_create` 用**前端传入 target 名作主键**、`_merge_extracted_json` 同步宽松匹配、`rerun_stages` 改 `''`、单画布重读 `selected=True` 不再自动过滤。
- **修复质量**：✅ **根治**（dev 任务66 实测 `cost=2.9s`、status 复位、原画布 `selected=True`、无脏记录）。
- **优化前必跑**：✅ 单文件 H5 原型点单画布「回退到读取」，确认 ①秒级回到 `extracted` ②只更新该画布（其余 `selected`/文本不变）③无残留 `extracting`/脏记录。改动 `_extract_singlefile_h5` 或 `run_extract` 单模式分支时必跑。

---

### BUG-08 · 墨刀读取全部失败（extract() 收到意外关键字 target_page_names，已修复）
- **预期**：墨刀分享链接阶段0 读取正常返回全部画布（dom_text + 视觉 OCR）。
- **实际（修复前）**：**任意墨刀链接读取 100% 失败**，报错 `原型读取失败：· 未能从链接中读取到任何页面内容…· 双路融合未能生成有效结构化需求…`（ misleading，实际与链接/登录无关）。`work_log` 真实原因为 `地址1读取失败: ModaoExtractor.extract() got an unexpected keyword argument 'target_page_names'`。
- **根因**：`modao_workflow.run_extract` 总是把 `target_page_names` 透传给 `extractor.extract_sync(...)`；`extract_sync` 在 webshare 分支保留该参数（`extract_webshare_sync` 支持），但在 Playwright 回退分支 `loop.run_until_complete(self.extract(*args, **kwargs))` 把 `target_page_names`（即使 `=None`）传给**不支持该参数的 `extract()` 异步方法**，触发 `TypeError`，整次读取被 `except` 吞掉、`all_pages=[]` → 空页阻断。
- **修复（已实测，2026-09-07）**：`modao_extractor.py` 在 Playwright 回退调用 `self.extract()` 前 `kwargs.pop('target_page_names', None)`。单画布重读仍由工作流在落库阶段按 `_name_match` 按名过滤（extractor 读全量），无需 extractor 感知该参数。
- **修复质量**：✅ **根治**。dev 容器重跑失败任务（id 67，`modao.cc/proto/...HCaPjlRvtktwy8x9AG0aBI`，贴纸日历优化）成功：`run_extract OK, pages: 4, warnings: 0`，状态 `extracted`。
- **优化前必跑**：✅ 跑一次墨刀链接阶段0 读取（含单地址多画布 / 单画布重读 `run_extract(target_page_names=...)`），确认 `work_log` 不再出现 `unexpected keyword argument 'target_page_names'`；`grep -n "kwargs.pop('target_page_names'" apps/requirement_analysis/modao_extractor.py` 应命中 1 处。

## 二、配置事实（已核实，2026-09-01）

| 项 | 真实端口 | 说明 |
|---|---|---|
| 生产（docker-compose.yml）前端 | 8080 | 用户口头"prod 8080"即指此入口 |
| 生产（docker-compose.yml）后端 | 8000 | 容器 8000 → 宿主机 8000 |
| 开发（docker-compose.dev.yml）前端 | 18080（默认 `DEV_FRONTEND_PORT`） | 用户记忆"dev 18080"即指此 |
| 开发（docker-compose.dev.yml）后端 | 18000（默认 `DEV_BACKEND_PORT`，env 可覆盖） | 容器 8000 → 宿主机 18000 |
| 本地 `npm run dev` 前端 | 3000（代理 `127.0.0.1:8000`） | CODEBUDDY.md 第41行"3000"指此，非 docker dev |

> 注：用户记忆"prod 8080 / dev 18080"均为**前端**入口端口，与"后端 8000/18000"并非矛盾。此前误标为"冲突"已修正；事实源以 `docker-compose*.yml` 的 `ports` 为准。

---

## 三、优化前 / 优化后检查表（复制到任务里勾）

**优化前**
- [ ] 已读 `docs/REGRESSION.md` 与 `CODEBUDDY.md`
- [ ] 确认本次改动涉及哪些 BUG-0x，标记「优化前必跑」
- [ ] 跑 `pytest apps/requirement_analysis/tests/test_regression_smoke.py` 全绿

**优化后**
- [ ] 重新跑对应 BUG 的「优化前必跑」验证
- [ ] `pytest apps/requirement_analysis/tests/` 全绿
- [ ] 无新增 `tmp_*` / `debug_*.py` 散落根目录（保持仓库整洁，见下）

---

## 四、仓库整洁约定（防止雪球式垃圾文件）

根目录已存在大量 `tmp_*.py`、`debug_*.py`、`*_log*` 临时产物，是「裸改」的典型痕迹。约定：
- 临时脚本一律放 `scripts/` 或 `/tmp`，**不**进仓库根目录。
- 调试脚本用完即删或移入 `scripts/`，禁止长期留在根目录。
- 详见 `CODEBUDDY.md` 事实源优先级第 5 条。
