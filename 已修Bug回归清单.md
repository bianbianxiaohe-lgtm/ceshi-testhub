# TestHub 已修 Bug 回归清单（优化前必读）

> **用途**：防止迭代优化时「同样的 bug 反复出现」，让每次优化前有可执行的核对动作。
> **规则**：对 `apps/`、`frontend/`、部署脚本做功能优化或重构前，先读本文件，按改动波及范围核对对应条目；改完交付前再核对一次。
> **触发**：本文件已在 `CODEBUDDY.md` 登记，AI 每次会话注入 CODEBUDDY.md 时必看到本文件，开始优化任务应主动加载并核对。

---

## 核对方式（怎么用）

1. 先判断本次改动**波及哪些模块**（前端 / 后端 / 部署 / 需求分析…），只看相关条目，不要全量核对。
2. 每条 P0 有两个动作：**「优化前预防」**（动工前确认没踩坑）和 **「改完验证」**（交付前确认没回归）。
3. P1 条目仅在改动波及对应模块时核对。
4. 全部核对通过再交付；任何一条验证失败，按「修复记录」要求追加登记。

---

## P0 高频回归点（每次优化必核对）

### 1. 前端改完「没生效」
- **模块**：`frontend/` 部署
- **Bug 现象**：改了前端代码，部署后页面还是旧版 / chunk 名没变 / 浏览器缓存。
- **根因**：①`Dockerfile.frontend` 只 COPY `frontend/dist`，没 build；②Vite `.vite` 缓存使 chunk hash 不变；③Windows `docker compose build` COPY 层常命中缓存。
- **优化前预防**：改前端前先确认要改的源码文件路径，不要直接改 `dist` 产物。
- **改完验证**：`npm run build` 前清 `node_modules/.vite` + `dist`；`docker compose build frontend` 加 `--no-cache`；部署后检查 `index-<hash>.js` 依赖映射引用新 chunk（grep 容器内 `ModaoSkillView-<hash>`）；浏览器 Ctrl+F5。

### 2. 后端同步后 Python 报 `SyntaxError U+FEFF`
- **模块**：部署 / 后端热更新
- **Bug 现象**：`.py` 覆盖进容器后启动报 BOM 语法错误。
- **根因**：PowerShell `Get-Content -Encoding UTF8 -Raw | docker exec` 注入 BOM。
- **优化前预防**：不把 PowerShell 管道输出直接灌进容器。
- **改完验证**：用 `docker cp` 覆盖本地无 BOM 文件；或确认 `docker cp` 源文件无 BOM。

### 3. 生产热同步漏文件（Windows `docker cp` 目录随机漏文件）
- **模块**：部署 / 后端同步
- **Bug 现象**：同步一批 `.py` 后容器里部分文件还是旧版，行为不一致。
- **根因**：Windows `docker cp <目录> <容器>:/app/` 随机漏文件不报错。
- **优化前预防**：涉及多文件同步时不用 `docker cp` 目录。
- **改完验证**：宿主 `tar -cf _sync.tar -C <repo根> apps backend` → `docker cp _sync.tar <c>:/tmp/` → 容器内 `tar -xf /tmp/_sync.tar -C /app`；同步后清 `__pycache__` 再 restart。

### 4. dev 容器名写错导致 restart/build 无效
- **模块**：部署命令
- **Bug 现象**：`docker restart testhub-dev-backend` 报错或操作了不存在的容器。
- **根因**：dev 容器名带 `-1` 后缀：`testhub-dev-frontend-1`(18080)、`testhub-dev-backend-1`(18000)；prod 才是 `testhub-frontend`/`testhub-backend`。
- **优化前预防**：写容器操作命令前先 `docker ps` 确认名字。
- **改完验证**：重启后 `docker ps` 确认目标容器确实重启。

### 5. 墨刀「编辑用例设计产物」弹窗结构破坏
- **模块**：`frontend/src/views/requirement-analysis/ModaoSkillView.vue`
- **Bug 现象**：保存编辑后 testcases/pci/风险数据结构损坏或丢失。
- **根因**：①用例/冒烟每条是 `{testcase:{...}, module, _raw}` 包裹，解析须展开 `tc.testcase`，字段名是 `precondition`（单数）；②PCI 可能是 `{pci_list:[...]}` 或 `{module, data:{...}}`，兼容 `v.pci_list || v.data.pci_list`；③风险同理 `v.risk_points || v.data.risk_points`；④写回时未定位原容器（wrapper.data）会破坏结构。
- **优化前预防**：改动该弹窗相关逻辑前先确认三种容器的包裹结构。
- **改完验证**：编辑保存后重新拉取，校验 testcases_json/smoke_json/pci_json/risks_json 结构完整、原有包裹字段仍在。

### 6. 需求分析拆解结果白屏
- **模块**：需求分析前端（AnalysisTask / 拆解结果）
- **Bug 现象**：拆解结果用结构化表格渲染时白屏。
- **根因**：该模块结果**纯 markdown 渲染才稳定**，结构化表格布局在该组件里不可靠。
- **优化前预防**：改动结果展示组件时优先沿用 markdown 渲染链路，不引入新的表格布局。
- **改完验证**：用真实任务跑一遍拆解结果页，确认正常渲染。

### 7. 后端 `@action` 下划线方法名前端 404
- **模块**：后端 API + 前端 `api/`
- **Bug 现象**：前端调新接口 404。
- **根因**：DRF `@action` 下划线方法名的 URL 保留下划线；前端若转成驼峰/连字符就 404。
- **优化前预防**：新增 DRF action 时记录真实 URL 片段。
- **改完验证**：前端 api 调用使用下划线命名，实测接口 200。

### 11. 墨刀横向多列画布只识别出左列几页（0.85 硬切 + 切片未实现）
- **模块**：`apps/requirement_analysis/modao_extractor.py`（`_MODAO_BOUNDS_JS` + `_screenshot_canvas_roi`）
- **Bug 现象**：横向排列多列页面的画布（如「饮食情况」10 列）只识别出左侧 2-3 页，右侧页面被当作批注面板切掉；即使包围盒改对，超宽画布整图降采样后视觉模型仍识别不全。
- **根因**：①`_MODAO_BOUNDS_JS` 用 `b.left > vw*0.85` 硬切，归一化到 100% 后横向页面 right 超出视口被误判为右侧面板（实测 87 widget 只剩 6 个）；②`_screenshot_canvas_roi` 文档注释承诺的切片从未实现（`SEG_H` 定义了但无切片代码），永远只返回单段主图。
- **修复（2026-08-31，已实测）**：①归属判断改为 `#screens.contains(w)`（探针实测：`#screens` bbox 铺满视口**不能**用作裁剪框，但 `contains` 判断可靠，87 widget 全包含、页面树/批注面板不在其中）；②真正实现横向/纵向网格切片：`SEG_W=SEG_H=2000` CSS、`OVERLAP=60`、4x 采样 ≈8000 物理像素（低于 CDP 8192 上限），产出 `page_N_segN.jpg`，`_run_ocr_batch` 逐段 OCR 合并。
- **优化前预防**：墨刀画布包围盒**不要**用视口比例硬切横向区域；`#screens` 容器 bbox 不可直接当裁剪框。
- **改完验证**：重跑含横向多列画布原型阶段0，`extracted_json` 该页 `screenshot_segments` 长度 >1 且 `vision_text` 覆盖全部列页面（饮食情况实测：识别出页面 10/11/12/13/14/15/16/20/22 共 9 页完整内容）。

---

## P1 波及相关模块时核对

### 8. MySQL 迁移 / 加列
- **模块**：`models.py` + `docker_start.py` + `apps/*/migrations/`
- **经验**：`apps/*/migrations/0001_initial.py` 是空占位（表已存在），**勿补全建表**；加列用 `docker_start.py` 幂等 raw SQL（`information_schema` 判存在再 ALTER）；新增表须在 `docker_start.py` 显式 `CREATE TABLE`（外键列 INT），否则容器启动不建表。
- **验证**：部署后进容器 `SHOW COLUMNS FROM <表>` 确认新列存在。

### 9. Midscene model_family 必须走环境变量
- **模块**：`apps/requirement_analysis/modao_extractor.py`（midscene_engine）
- **经验**：`MIDSCENE_MODEL_FAMILY` 必须写成**环境变量**才能被 Node 服务继承；Python 端 `MidsceneConfig(model_family=...)` 不会自动映射，缺了会报 `Invalid MIDSCENE_MODEL_FAMILY`。改了 .py 后必须 `docker cp` + `docker restart testhub-dev-backend-1`。
- **验证**：真机连接时确认环境变量已注入，不再报 family 非法。

### 10. 质量门禁判定口径
- **模块**：需求分析导出 / 质量报告
- **经验**：仅 `blocking_issues` 非空才硬失败阻断导出；`overall_result=='FAIL'` 但无阻断项是软告警放行；`overall_result=FAIL` 或有 blocking_issues 时保留用例与报告但状态标记失败、不导出正式 Excel。
- **验证**：改动导出逻辑后跑一次 FAIL 场景确认阻断行为。

### 11. 「执行通过」但实际什么都没做（静默假通过）
- **模块**：`apps/ui_automation`（`midscene_engine.py` / `midscene_ios_engine.py`）+ 用例编辑器
- **Bug 现象**：用例状态「通过」，真机毫无动静；用户以为"我写的步骤没被执行"。
- **根因**：**给缺失字段兜底 = 把错误数据变成合法输入**。引擎曾把空步骤的 `action` 兜底成 `aiAct`、
  `prompt` 兜底成 `''`，于是拿空提示词去问视觉模型，模型随便点一下也返回 success。
- **优化前预防**：**执行入口不要给"必需字段"兜底**。缺失必需字段（prompt/action）必须显式失败，
  否则模型/工具的"随便返回"会伪装成成功。同理：编辑器保存时必须拦截不可执行的数据。
- **改完验证**：造一个空步骤（`{"value":"","extract":[],"wait_ms":0}`）执行 → 必须 `failed` 且错误信息指出第几步为空；
  在编辑器里留空步骤点保存 → 必须被拦下。**反例检查**：任何"通过"的执行，其 `steps_completed` 里不应出现无意义的 `Step 1`。

### 12. 「二选一模式」不要用「属性是否存在」承载
- **模块**：`frontend/src/views/ui-automation/ai/AICaseList.vue`（步骤来源：直接操作 / 引用公共步骤）
- **Bug 现象**：界面上明明选了引用公共步骤，保存后步骤变成空壳，执行什么都不做。
- **根因**：用 `step.ref === undefined` 判断模式，切换来源时 `delete step.ref` →
  步骤只剩附属字段，**两种模式都不是，且不可恢复**（不知道用户选过引用，也没有提示词）。
- **优化前预防**：多选一的模式标记要用**独立的、不会被清空的字段**（如 `_src: 'ref'|'inline'`）；
  **不要**用"某个业务属性在不在"当模式判据——那个属性随时可能被清空。
  同时校验逻辑必须按**模式**分支，不能按属性存在与否分支。
- **改完验证**：切到引用模式选一条 → 保存 → 查库里 steps 必须含 `{"ref":"<名称>"}`；
  再切回直接操作、再切回引用，保存后 `ref` 不得丢失。

### 13. 设备/资源类 status 字段「只写不降级」
- **模块**：`apps/ui_automation`（`AppDevice`）+ 任何新增的「状态」字段
- **Bug 现象**：设备早离线了，列表仍显示「在线」。
- **根因**：**状态字段只在写入时被置为正常值，没有任何"探测可达性 / 按时间差降级"的逻辑**，
  于是历史值永久残留（`last_heartbeat` 明明是好几天前）。
- **优化前预防**：给设备/服务/连接类模型加「状态」时，必须同时回答两个问题：
  ①**谁来把它改成失败态**（探活接口？执行失败回调？定时任务？）②**前端如何看出它其实已经过期**
  （相对时间 + 过期高亮，不能只渲染一个绿色「在线」标签）。
- **改完验证**：制造一次真实离线（拔线/关服务），确认状态能落为 `offline` 且**给出可读原因**；
  跑一次真实执行，确认执行中为 `busy`、结束后按结果回落，不会永远卡在 busy。

---

## 历史 Bug 登记表（边修边记，新增条目从这里加）

> 每条登记：日期 | 模块 | 现象 | 根因 | 修复 commit/动作 | 回归检查点（一句可执行验证）。

| 日期 | 模块 | 现象 | 根因 | 修复动作 | 回归检查点 |
|------|------|------|------|----------|-----------|
| 2026-08-31 | modao_extractor.py | 墨刀横向多列画布（饮食情况）只识别出左列 3 页 | `_MODAO_BOUNDS_JS` 用 `left>vw*0.85` 硬切误伤横向页面 + 切片注释承诺未实现，超宽整图降采样后识别不全 | 归属判断改 `#screens.contains(w)`（探针实测可靠）；`_screenshot_canvas_roi` 真正实现 2000CSS/OVERLAP60 网格切片，`_run_ocr_batch` 逐段 OCR 合并 | 重跑该原型阶段0：饮食情况 `screenshot_segments`=2 段且 `vision_text` 覆盖页面 10/11/12/13/14/15/16/20/22 共 9 页（含第一餐/最后一餐/用餐场景/困扰/轻断食/热量管理/脸部变化/预测） |
| 2026-08-31 | modao_extractor.py / modao_views.py | 单文件 H5 交互原型（WebShare 单 HTML 只读页，loveydovey）墨刀/webshare 两条链路都识别不了 | 格式自研：内联 `const pages` 数组定义页面树 + 页面模板 JSON，非墨刀非 Axure（无 document.js） | 新增 `_parse_singlefile_h5`/`_detect_singlefile_h5`/`_extract_singlefile_h5`（纯 HTTP，模板源取命中页面 id 最多者）；`extract_webshare_sync` document.js 失败 fallback；`extract_sync` AUTO-DETECT 加 H5 探测；`_ocr_webshare_page_async` 支持 `post_js`(render)；`/webshare/` 改大小写不敏感 | 用 `_extract_singlefile_h5(url)`（vision_config=None）冒烟：页面树>=2 且每页 dom_text 非空（loveydovey 实测 19 页、8098 字符）；2026-09-01 已加 writer_vision(qwen3.6-plus) 视觉+deepseek-chat 双路融合端到端验证：19/19 页视觉成功，融合产出 130 条，失败率 0% 通过 20% 门禁；同日成本优化：state 切换实测不改变界面内容（setState 只重渲染 phone、views 按页面 id 取值、render 重置 currentState），改读 `.phone/.screen` DOM 文本（8098→11571 字符）并仅默认态 OCR 1 次，全流程 188s、视觉 0 次模型调用、融合 118 条。改动 webshare 链路时勿破坏此 fallback |
| 2026-09-15 | ui_automation（`views.py` `AppDeviceViewSet` / `AppDeviceList.vue`） | 设备已离线（拔线/关机/WDA 停），设备管理列表仍显示「在线」 | `AppDevice.status` 是**纯静态字段**：只在 `_upsert_app_device`（扫描/注册）和 `app_automation.sync_devices_to_ui_automation` 写入时被置 online，**没有任何可达性探测、也从不自动降级**；用例执行前后也不改状态。实测 6/7 台 status=online 但 `last_heartbeat` 是几天到几十天前 | 新增 `POST /api/ui-automation/app-devices/refresh_status/` 主动探活（iOS 探 `http://wda_host:port/status` 的 `value.ready`；Android 按 adb_host 分组跑 `adb devices`，先 2.5s TCP 探端口）；`busy` 设备跳过；执行期 `run_task` 开始置 busy、finally 按结果落 online/offline；`set_status` 置 online 时同步刷 `last_heartbeat`；前端加「刷新状态」+每行「探活」按钮，最后心跳列超 15 分钟标黄「· 已过期」 | 打开设备管理点「刷新状态」：真实离线的设备 status 变 `offline` 且 `detail` 给出可读原因（`adb 服务 <host> 不可达` / `adb devices 中未找到该序列号` / `连不上 <host>:8100`）；再拔线测一台，确认从 online 落为 offline；跑一次 midscene 用例，确认执行中 status=busy、结束后按结果回落 |
| 2026-09-15 | ui_automation 设备身份 + `scripts/ios_*.bat/ps1` | 同一台 iPhone 换电脑后会在设备列表**重复出现**（一条旧 IP、一条新 IP） | `_upsert_app_device` 只按 `(platform, wda_host, wda_port)` 兜底匹配且**不覆盖已有地址** → 设备换电脑（IP 变）就匹配不上、新建一条；且注册接口没有「离线」路径，`ios_device_stop.bat` 停机后无人通知平台 | 确立**UDID 唯一身份**契约：命中已有记录时 `wda_host/wda_port/adb_host` **无条件刷为本次上报值**、status 置上报值（online 才写 `last_heartbeat`）；记录永不删除；`device_agent_register` 统一 online/offline 路径（**离线上报不带 wda_host**）；`ios_register_device.ps1` 加 `-Status`；`ios_device_stop.bat` 加 `[4/4]` 在**隧道死前**抓 UDID 后上报 offline | 用同一 UDID 连发两次 register（先 `wda_host=10.0.0.11` 再 `10.0.0.22`）：列表**仍只有 1 条且 id 不变**、IP 为新值；再发 `status=offline`（不带 wda_host）：记录保留、状态 offline、**IP 未被清空**；再发 online 恢复。设备端：跑一遍 `ios_wda_host.bat` 看列表新增/更新，再跑 `ios_device_stop.bat` 看 `[4/4]` 后状态变离线 |
| 2026-09-15 | `midscene_engine.py` / `midscene_ios_engine.py` / `AICaseList.vue` | 用例「执行通过」但真机**什么都没做**（用户："步骤并未按照我写的执行"） | **空步骤被兜底成可执行**：`action = step.get('action','aiAct')` + `prompt = step.get('prompt','') or ''`，一个 `{"value":"","assert":null,"extract":[],"wait_ms":0}` 的空步骤会**拿空提示词问视觉模型**，模型随便点一下返回 success → 假通过。用例 58 的 steps 就是这种空壳（用户写的自然语言从没进过 steps） | 两个引擎加 `_step_has_content()`（有 ref/action/prompt 才算有效，**引用步骤豁免**）：空步骤直接 failed+可读原因，iOS 侧在**建会话前**拦截；需视觉模型的动作 **prompt 为空即抛错**；前端保存时拦截空步骤、0 步骤弹确认 | 直调用例 58 的真实 steps 执行：`status=failed` 且 error 为「第 1 个步骤是空的…」；`{}` 与只填 `value` 判空、`{action, prompt}` 与 `{ref}` 判有效；前端编辑器里留一个空步骤点保存 → 应被拦下并提示步骤号 |
| 2026-09-15 | `AICaseList.vue`（步骤编辑器模式标记） | 编辑器里明明选了「引用公共步骤」+具体项，**保存后变空壳**，执行什么都不做 | 模式靠「`step.ref` 属性是否存在」判定，而 `switchStepSource(step,'inline')` 会 `delete step.ref` → 步骤只剩 `{value,wait_ms}`，**既非合法引用也非合法内联，无法恢复**；叠加按 `s.ref === undefined` 判定的空步骤校验，ref 一丢就被当成空步骤 | 改用**不会丢失的显式标记 `_src`** 承载模式，新增 `stepSource(step)`，模板/校验/序列化统一用它；`editCase` 回填带 `_src`、不再把 `action` 兜底成 `aiTap`；保存时对引用步骤做 `ref` 兜底自检（丢了就抛错）；历史空壳步骤在编辑器里用 el-alert 红色告警显式标出 | 编辑器里对已存在用例选「引用公共步骤」+「进入工具页面」→ 保存 → 用 `json` 查库里 steps 应为 `[{"ref":"进入工具页面"}]`；再执行该用例，日志应打印展开后的 `aiAct` + 公共步骤 prompt。**反向**：把一个步骤切「直接操作」再切回「引用公共步骤」保存，ref 不得丢失 |
| 2026-09-15 | `views.py::_run_ios_engine`（iOS 执行路径） | 引用公共步骤的用例在 iOS 上执行报「步骤 1（aiAct）没有填写提示词 prompt」，Android 却正常 | **iOS 引擎是"直执行"，不认 `{ref}`**；引用展开（`_resolve_business_refs`）只在 `MidsceneAppEngine.run()` **内部**调用，`_run_ios_engine` 把 `ai_case.steps` 原样丢给 `execute_steps` → `{'ref':'xxx'}` 被当空步骤执行 | 在 `_run_ios_engine` 里**于 `execute_steps` 之前**调 `MidsceneAppEngine._resolve_business_refs()` 展开（`__new__` 造轻量实例拿方法，避免构造真机连接），展开日志并入 `engine.logs`，展开异常只告警不阻断 | 建一条只含 `{"ref":"<已存在的公共步骤名>"}` 的 iOS 用例并执行：日志必须先出现「引用公共步骤「xxx」-> aiAct: …」再出现 `[步骤 1] aiAct: <公共步骤的 prompt>`（不能再报"没有填写提示词"）。**改动 iOS 执行链时对照 `MidsceneAppEngine.run()` 逐条核对前置处理** |
| 2026-09-15 | `reports.py` + 两个 midscene 引擎 + `AIExecutionReport.vue` | 执行报告只显示「步骤 0 / 操作 aiAct」，且**没有任何步骤截图**（用户要"每步一一对应的页面截图"） | ①`_parse_detailed_steps` 只认 browser-use 的 `step_number`/`element`，Midscene 用的是 `index`/`name`/`prompt` → 全部兜底成 0/空/aiAct；②两个引擎**只在显式 screenshot 动作或失败时才截图**，成功的用例截图恒为空；③引擎返回**裸 base64**，`<img :src>` 需要 data URI 才能渲染 | ①步骤号按 `index+1` 转 1 基、`element` 依次退 `name`→`prompt`、补 `prompt`/`error`；②两个引擎在**每步执行后**都 `get_screenshot()`（跳过 screenshot 动作，失败只记日志）；③新增 `_normalize_shot()` 把裸 base64 包成 `data:image/png;base64,`；④报告卡片加 `el-image`（`preview-src-list` 放大 + `preview-teleported` 防弹窗裁剪）并标注成功/失败截图 | 跑一条 ≥3 步的 midscene 用例，打开报告「详细步骤」：步骤号应为 **1/2/3（不能是 0）**，每步都有「说明」和一张可点开放大的真机截图；故意让一步失败，该步应显示「失败时截图」+ 失败原因。**旧记录本来就没有截图，必须用新跑的用例验证** |

| 2026-09-15 | `apps/ui_automation/views.py::AppDeviceViewSet.refresh_status` | **两台 iOS 设备共用同一个 `wda_host:wda_port` 时全部被判「在线」**（误报）。用户实测：`iPhone 15 Pro` 已不在 `192.168.8.71` 那台电脑上，但列表里和 `ios-14` 一样显示「在线」 | 探活只做 `GET http://<wda_host>:<port>/status` 取 `value.ready`，**只回答"这个地址上有台 WDA 在跑吗"，不回答"是不是我这台"** → 两台设备地址相同时结果必然相同。而 WDA 的 `/status` 响应里**没有 UDID**（只有 `os.version`/`sdkVersion`/`device`/`ios.ip`），无法用它反查设备身份 | 物理事实：一台手机插一台电脑，那台电脑只转发自己的 8100 → **同一 `host:port` 只能对应一台真机**，重复必然是残留数据。探活前先按 `(wda_host, wda_port)` 对 iOS 设备分组，**同组内 `last_heartbeat` 最新的那台赢**，其余标 `offline` 并给出可读原因（`当前记录的 xxx:port 上是「yyy」的 WDA…本机若已改插别的电脑，在该电脑上跑一次 ios_wda_host.bat，地址会自动更新为本机；若未接入任何电脑，则保持离线`）。冲突失败者**不推进 `last_heartbeat`**，保留最后一次真实成功时间。**注意提示语不能教用户"手工改 IP"**：地址是设备端上报时按 UDID 自动覆盖的（`device_agent_register` → `_upsert_app_device`），换电脑后跑一次脚本就会自己更新 | ①先确认 iOS 设备列表里有**两台及以上**共用同一 `WDA地址`（图中 `ios-14` 与 `iPhone 15 Pro` 都是 `192.168.8.71:8100`）；②点「刷新状态」；③**只能有一台显示「在线」**（`last_heartbeat` 最新那台），其余显示「离线」，且行内「探活」弹出的原因含「**已被「xxx」占用**」字样；④连点两次「刷新状态」，结果必须稳定、不来回抖动 |

**登记规则**：
- 修复一个 bug 时，若它是**容易复发**的类型（缓存、结构包裹、路径/命名、部署同步），必须补一条到 P0/P1 对应位置，否则只填登记表。
- 回归检查点必须是一句**可执行**的验证（不是"确保正常"），AI 下一步就能照做。

---

## 维护约定

- 本文件是「已修 bug → 回归检查点」的结构化提炼，与 `.codebuddy/memory/`（跨会话事实）互补，不重复维护同样内容。
- 优化前读、改完核对的规则登记在 `CODEBUDDY.md`，AI 每次会话注入时必看到。
- 条目过时（验证方式已变 / bug 已不可能复发）时更新对应行，不要直接删除，注明「已过时」。
