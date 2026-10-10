# CODEBUDDY.md

TestHub 是一套前后端分离的智能测试管理与自动化执行平台，主线代码为根目录 `apps/` + `backend/` + `frontend/`。

> 本文件记录经过仓库配置核实的项目事实、事实源和高频陷阱。功能说明可参考 `README.md` / `CLAUDE.md`，但版本和运行方式必须以实际配置与代码为准。

## 事实源优先级

出现冲突时按以下顺序判断，不要仅凭 README 或历史日志下结论：

1. 实际代码与入口：`backend/settings.py`、`backend/asgi.py`、`backend/urls.py`、`docker_start.py`、`frontend/src/`
2. 依赖清单与构建配置：`requirements.txt`、`frontend/package.json`、`frontend/vite.config.js`、Dockerfile、Compose 文件
3. `.env.example` / `.env.dev.example` 等示例配置（不得读取或输出真实 `.env` 密钥）
4. `README.md`、`CLAUDE.md`、`docs/`（可能滞后）
5. `logs/`、`*_log*`、`tmp_*`、`_cmp_*` 等临时产物（只用于排障，不作为架构事实）

## 已核实技术栈

- **后端**：Python；Django 4.2.7；DRF 3.14；django-filter；drf-spectacular；SimpleJWT
- **前端**：Vue 3；Vite 7.3.1；Element Plus；Pinia；Vue Router；Axios；ECharts；Monaco Editor；vue-i18n；Sass
- **持久化**：MySQL 8.0（utf8mb4）为业务数据库；ChromaDB `PersistentClient` 为嵌入式向量存储
- **异步/实时相关**：Celery 5.3、Redis 客户端、Channels、Daphne 依赖已安装；SSE 已在需求分析模块实际使用
- **自动化**：pytest、Allure、Selenium、Playwright、browser-use、Appium、Airtest/Poco、ADB
- **AI**：OpenAI-compatible Chat/Embeddings、langchain-openai、Dify；可接入兼容协议的多模型服务
- **部署**：Docker Compose；后端镜像 Python 3.12 slim；前端静态文件由 Nginx Alpine 提供并反代 `/api/`、`/admin/`、`/media/`、`/static/`

## 当前架构边界（不要误判）

- `docker-compose.dev.yml` 有 MySQL 与 Redis；`docker-compose.yml` 当前没有 Redis、Celery worker 或 Celery beat 服务。生产是否使用外部 Redis/Worker 必须结合实际环境确认。
- `settings.py` 将 Celery broker/result backend 指向 `REDIS_URL`，代码中存在 `.delay()` 调用；但 `docker_start.py` 只迁移/初始化后执行 Django `runserver`，不会启动 Celery worker。
- 虽然安装了 Channels/Daphne 且存在 consumer，当前 `backend/asgi.py` 仅调用 `get_asgi_application()`，没有 `ProtocolTypeRouter` / WebSocket URLRouter；`CHANNEL_LAYERS` 当前还是 `InMemoryChannelLayer`。因此不能宣称跨进程 WebSocket 已完整启用。
- 需求分析的实时流式输出主要通过 `StreamingHttpResponse` + SSE 实现，这是当前代码中已确认的能力。
- 根目录 `apps/` 是主后端业务代码。`backend/apps/` 被 `.gitignore` 忽略，属于旧副本/本地产物，不要在那里开发或把它当作运行主线。
- `Dockerfile.frontend` 直接复制预构建的 `frontend/dist`，本身不执行 `npm run build`；部署前需确保 dist 已正确构建。

## 版本与环境提示

- README 中的版本描述可能落后，例如 README 写过 Vite 4.4，而 `frontend/package.json` 当前为 Vite 7.3.1。
- 容器后端以 Python 3.12 为基准；开发机 Python 版本可能不同。验证兼容性时优先使用容器或项目指定虚拟环境。
- 已知 Windows 本地虚拟环境入口：`E:\python_venv\testhub\Scripts\activate.bat`；若路径不存在，应先探测环境，不要直接假定。
- 前端开发端口是 3000，代理后端 `127.0.0.1:8000`；生产 Compose 默认暴露前端 8080、后端 8000。

## 编码与变更约定

### 后端

- 常规业务链路为 `models → serializers → views → urls`；优先沿用所在 app 的既有写法，不为统一风格做无关重构。
- 新 app 注册到 `INSTALLED_APPS`，顶层路由接入 `backend/urls.py`。
- ORM 列表接口注意 N+1，按关系使用 `select_related` / `prefetch_related`。
- Celery 任务放所属 app 的 `tasks.py`；新增异步调用时必须同时验证 worker/broker 的实际运行路径。
- 密钥、数据库密码、AI Key、邮件凭据只走环境变量或数据库配置，不得硬编码、提交或在输出中泄露。
- API 返回形式以相邻接口和前端调用约定为准。项目大量接口使用 `{code, data, message}`，但并非所有 DRF/SSE/文件响应都适合强行套该格式。
- 数据库变更优先走 Django migration；仓库包含历史手工 SQL/修复脚本，使用前必须确认目标库状态，避免重复执行。

#### 后端镜像构建慢/重建耗时的排查（2026-09-17 实测定型）

> **触发场景**：`docker compose build backend` 长时间停在下载依赖（现象如"已运行 29 分钟 / 下载到第 N 个包 / 60-80 KB/s"）。
> **先别急着重下，按下面顺序 30 秒定位，多数情况是可避免的白工。**

**1. 先确认缓存是否还在（不是猜，直接查）**

```powershell
docker buildx du --verbose | Select-String -Pattern "Description|Last used" -Context 0,1
```

每条 `Description:` 就是一层，紧跟的 `Last used:` 是它**最近一次被构建使用**的时间。据此可判：

| 观测 | 结论 |
|---|---|
| `Last used: About a minute ago` / `N minutes ago` | 该层**正在被本次构建使用**（= 构建卡在这一层） |
| `Last used: 2 weeks ago`（值很旧） | 该层**本次尚未轮到**，前一层还没过 |
| 找不到某层 | 缓存被清了（`buildx prune` / 磁盘清理） |

**2. 平行看镜像与容器（判断"构建是否已产出"）**

```powershell
docker images --format "{{.Repository}} | {{.Size}} | {{.CreatedSince}}" | Select-String testhub-backend
docker ps --format "{{.Names}} | {{.Status}}" | Select-String testhub-backend
```

- 镜像 `CreatedSince` 仍是旧的 **且** 容器 `Up N hours` 未被重启 → **构建还没产出，仍在进行**。
- 镜像已更新 / 容器刚重启 → 构建已完成。

**3. `Dockerfile.backend` 各层的缓存强度不同（这是"为什么慢"的根因）**

| 层 | 缓存机制 | 失效后代价 |
|---|---|---|
| `apt-get install ...`（第 10~23 行） | **普通 Docker 层缓存，无 cache mount** | ⚠️ **最慢**，全量装 gcc/build-essential/libgl 等约 200~300MB，国内访问 `deb.debian.org` 常只有几十 KB/s |
| `pip install -r requirements.lock.txt`（第 38 行） | `--mount=type=cache,target=/root/.cache/pip`（1.4GB 级） | 中等；缓存命中则秒过，**未命中会全量下 243 个包** |
| `playwright install chromium`（第 41 行） | 普通层缓存 | 慢，需下 Chromium ~150MB + apt 装图形库 |
| `COPY . .`（第 44 行） | 普通层缓存，**源码必变** | 正常重建，几分钟 |

**⚠️ 关键认知：`--mount=type=cache` 的缓存挂在「宿主机 Docker」上，不在镜像里。**
所以"以前构建过"不代表"这次不用重下"——**镜像层缓存和 cache mount 任缺其一都会退化为全量下载**。

**⚠️ 另一个高频误判：`pip` 慢 vs `apt` 慢。**
若 `buildx du` 显示**正在被使用的是 `apt-get` 那一层**，那么慢的是 **apt（Debian 源）**，不是 pip；
此时"换 PyPI 镜像源"完全无效，**要换的是 Debian 源**。

**4. 三条铁律（避免把几分钟的活干成几十分钟）**

- **禁止 `--no-cache`**：会让 `COPY requirements.lock.txt` 层失效 → 后面整条链全废 → 全量重下 243 包。
  仅当**前端 COPY 层**确需刷新时才考虑（那也只需重建 frontend）。
- **只改代码时根本不需要重建镜像**：生产/开发同步后端 `.py` 一律走 `docker cp`（见下），秒级完成、不碰依赖。
- **改动 `Dockerfile.backend` 任何一行都会使其后所有层失效**，因此**不要在有人正在构建时改它**；
  改完后的**首次**构建必然重跑 apt + pip，属预期，之后恢复命中。

**5. lock 文件的两个数字别搞混**

`requirements.lock.txt` **总行数 254**，但**实际包数量 243**（254 含空行/注释）。
看到"第 57/254"这类输出时，254 是**行数**不是包数，**不要据此推断"lock 被改过"**。
校验 lock 是否真被改：`git diff requirements.lock.txt`（空 = 未改）。

**6. 只同步后端代码时的标准流程（不重建镜像）**

```powershell
# Windows 下 docker cp 目录会随机漏文件 → 先在宿主打 tar
tar -cf _sync.tar -C <repo根> apps backend
docker cp _sync.tar testhub-backend:/tmp/
docker exec testhub-backend sh -c "tar -xf /tmp/_sync.tar -C /app && find /app -name __pycache__ -type d -exec rm -rf {} +"
docker restart testhub-backend
# 等约 25s 后验证（404 = Django dev 正常活着）
curl -w "%{http_code}" http://localhost:8000/api/
```

**7. 构建耗时的真实参考（2026-09-17 实测：全量重建约 1 小时）**

`requirements.lock.txt`（243 包）全量重建（apt → pip → playwright → COPY）分布：

| 阶段 | 实测 |
|---|---|
| apt（**无 cache mount**，走 Debian 官方源） | 5~20 分钟 |
| pip（部分命中 cache mount，**新增包需真下载**） | 30~40 分钟 |
| playwright chromium（**无 cache mount**，~150MB） | 30~50 分钟 |
| COPY . . + 导出镜像 | 3~6 分钟 |

**⚠️ 判断构建是否卡死不能只看 `docker buildx du`**：
`Last used` **只在挂载那一刻更新一次**，不反映层内部进度。
实例：pip 正在下载一个 47.7MB 的大包时，`Last used` 会一直停在"37 分钟前"不动，
看起来像"卡死/中断"，实际构建完全正常。
**⇒ 判断细粒度进度只能看构建方终端/AI 的实时日志；`buildx du` 只适合判断"哪一层是瓶颈"。**


### 前端


- 页面放 `frontend/src/views/`，公共组件放合适的组件目录，Pinia store 放 `stores/`，请求封装放 `api/`。
- 组件不要新写裸 axios；复用统一请求封装、JWT 刷新和错误处理逻辑。
- 路由与用户可见文字优先沿用现有模块的懒加载及 i18n 方式，不假定旧页面已经全部国际化。
- 样式优先沿用 Element Plus 变量及当前页面约定，局部样式通常使用 scoped SCSS。
- `package.json` 有 lint 脚本，但当前未发现 ESLint/Prettier 配置文件。不要声称 lint 已可用；新增配置前先确认 Vite 7、ESLint 8 和现有代码的兼容性，不要凭记忆套模板。

## 验证原则

- 后端改动至少做针对性 Django check / 测试或模块级验证；涉及数据库时先确认连接目标与迁移影响。
- 前端改动至少做针对性构建；不要把仓库中已有 `frontend/dist` 当作源码已验证的证据。
- 涉及 Celery、WebSocket、设备、浏览器或 AI 外部服务时，分别报告“静态配置通过”和“端到端运行通过”，不能混为一谈。
- Airtest/Appium/ADB 和浏览器自动化受宿主机、设备、图形库与驱动影响。容器已安装部分 Linux 依赖和 ADB/Chromium，但具体模式能否运行必须实测，不要笼统断言只能在某一操作系统运行。

## 墨刀需求分析的人工确认闸门

- 结构化结果使用 A/B/C/D 证据等级：A 为原文/视觉精确验证，B 为跨页面推导，C 为模型建议或需求缺失，D 为证据验证失败。
- C/D 级内容以及澄清清单中的位置、交互、缺失和边界问题必须由人工填写结论；不能把模型建议直接当作正式需求。
- 最终测试用例生成必须经过服务端人工批准，不以单纯前端确认弹窗为准。
- 批准记录绑定当前 `clarification_log` 与 `final_testpoints_json` 的 SHA-256 指纹；批准后修改任一内容，旧批准自动失效，必须重新确认。
- 在人工确认前，允许完成原型读取、结构化分析、澄清清单和测试点合并，但不得生成最终测试用例、冒烟用例、质量报告或 Excel。

## 墨刀逐页读取与质量门禁

- 墨刀分享页当前真正可点击的页面行是带 `data-cid`、`data-interactive-target-type="6"` 的 `.rn-list-item.page`；`.screen-item-icon` 只是内部图标，点击它不能可靠切换画布。
- 逐页读取必须用截图 SHA-256 校验独立画布；多页原型中重复截图比例超过 20% 时，阶段 0 标记失败并阻断后续分析，不能用“枚举到 N 个页面树节点”冒充“N 页读取成功”。
- 阶段 3 模块拆分必须覆盖阶段 1 识别的模块；有遗漏时阻断测试点生成。
- 向量去重必须把保留项、删除项、相似度、阈值和原因写入 `dedup_audit_json`，不能只记录删除数量。
- 质量报告 `overall_result=FAIL` 或存在 `blocking_issues` 时，保留用例和质量报告供修正，但状态标记失败且不得导出正式 Excel。
- 墨刀/webshare 创建页默认启用双路融合：每页分别保留 `dom_text` 与 `vision_text`，分批抽取后把 `fused_requirements` 落入 `extracted_json`，阶段 1 将其作为结构化主输入；不得只计算融合结果却不落库/不消费。
- 双路融合禁止对全部页面做固定长度的整体截断；按完整页面分批，单页极端超长时才分片。视觉未执行、视觉失败率超过 20%、融合结果为空或超过 20% 页面缺少 `source_pages` 证据时，阶段 0 必须阻断。
- 使用真实私有原型做端到端视觉/LLM 回归会把截图和 DOM 派生内容发送给所配置的第三方模型服务，执行前需获得用户对该数据外发的明确批准；无批准时只做本地模拟和无模型导航验证。

## Skill 注册表

> 单一事实源：本仓库的“skill / 提示词能力”分散在 4 处、2 种格式。下表为统一注册表；新增、修改或迁移 skill 时必须同步更新本表，避免注册表与磁盘不一致。

### 注册清单

| 名称 | 类型 | 位置 | 格式 | 由谁加载 | 维护方式 | 备注 |
|------|------|------|------|----------|----------|------|
| appium-android-capture | Agent Skill | `.codebuddy/skills/appium-android-capture/` | SKILL.md（标准） | AI 助理直接加载 | 编辑 SKILL.md/scripts；改后重新打包到 `skills-dist/` | Appium 流水线阶段1 |
| appium-android-run-pytest | Agent Skill | `.codebuddy/skills/appium-android-run-pytest/` | SKILL.md（标准） | AI 助理直接加载 | 同上 | 阶段2 |
| appium-android-allure-report | Agent Skill | `.codebuddy/skills/appium-android-allure-report/` | SKILL.md（标准） | AI 助理直接加载 | 同上 | 阶段3 |
| mobile-app-autotest | Agent Skill（导入·参考） | `_ext/mobile-app-autotest/mobile-app-autotest/` | SKILL.md（标准） | **未直接加载**（`_ext/` 非自动加载路径，仅作参考/待用） | 编辑 SKILL.md；`.cursor/` 路径残留已修 | **通用参考、非默认**；与 1/2/3 重叠，主线以 appium-android-* 为准 |
| modao_skill | 应用内自定义 Skill | `apps/requirement_analysis/modao_skill/` | 文件夹式（无 SKILL.md） | requirement_analysis 应用（modao_views.py 等） | 编辑 prompts/templates/tools/workflow；改后 `docker-compose build backend && docker rm -f testhub-backend && docker-compose up -d backend` | 墨刀原型→测试用例 |
| tester*.md 提示词库 | 提示词库 | 根目录 `tester.md` / `tester_pro.md` / `tester_new.md` / `tester_analyzer.md` | Markdown 角色提示词 | 用例生成后端代码（运行期经 `BASE_DIR/tester*.md` 读取，且根目录那份会进镜像） | 编辑文案；**运行期真源是根目录 `tester*.md`（已进镜像），`_ext/.../docs/tester*.md` 不进镜像、后端也不读，仅为本地/上游镜像，清理时以根目录为准** | 根目录与 `_ext` 为双源，但仅根目录那份生效 |
| ai-case-generation-module | git 子仓 | `_ext/ai-case-generation-module/` | git 仓（apps/ + frontend/ + docs/） | 需求分析/用例生成功能 | `cd _ext/ai-case-generation-module && git pull`（浅克隆，必要时 `git fetch --unshallow`） | “AI 用例生成模块”源码 |
| skills-dist | 分发包 | `skills-dist/` | zip 包 + README | 分发到其他仓库 | 由 `skill-creator/scripts/package_skill.py` 从 `.codebuddy/skills/` 重新生成 | 仅 3 个 Appium skill 的打包版 |

### Skill 维护约定

- **统一入口**：所有“标准 Agent Skill”放 `.codebuddy/skills/<name>/SKILL.md`；应用内能力放 `apps/<app>/<name>/`（文件夹式）；需要跨仓分发再打包进 `skills-dist/`。
- **改完必打包**：修改 `.codebuddy/skills/` 下任一 Appium skill 后，必须重新执行 `package_skill.py` 更新 `skills-dist/`，否则分发的是旧版。Windows 下先 `set PYTHONIOENCODING=utf-8` 避免 emoji 编码报错。
- **改完必重建对应环境**：`modao_skill/` 与根目录 `tester*.md` 属于进镜像的应用代码，任何改动必须对该环境执行 `docker-compose build backend && docker rm -f testhub-backend && docker-compose up -d backend` 后才生效；dev/prod 各自独立，未重建部署的环境不受影响。`.codebuddy/skills/`、`_ext/`、`skills-dist/` 不进镜像，改了无需重建。
- **App 自动化主线唯一**：仓库标准 App 自动化 = `.codebuddy/skills/` 下的 `appium-android-*`（capture → run-pytest → allure-report，基于 `appium_workspace/` + pytest + Allure）。`mobile-app-autotest`（`_ext/`）为通用参考技能、非默认，仅当用户明确要求 iOS / 云真机 / Java / TypeScript 等多语言工程时启用；其 `description` 已收窄触发词，不会与主线抢请求。
- **提示词单源（以根目录为准）**：运行期真源为根目录 `tester*.md`（进镜像、后端经 `BASE_DIR/tester*.md` 读取）；`_ext/ai-case-generation-module/docs/tester*.md` 不进镜像、后端不读，仅本地/上游镜像，已加注释标注、不作为维护真源。改提示词只改根目录，禁止双源并行维护。
- **新增 / 删除 / 迁移**：先在 CODEBUDDY.md 本表登记或更新，再落地文件，保证注册表与磁盘一致。

### 已知待办（注册时发现）

- ~~`mobile-app-autotest` 的 SKILL.md 引用 `.cursor/skills/...`~~ ✅ 已修复（改为 `_ext/mobile-app-autotest/mobile-app-autotest/scripts/`）。
- ~~1/2/3 与 `mobile-app-autotest` 功能重叠~~ ✅ 已定主线：App 自动化默认主线 = `appium-android-*`（1/2/3）；`mobile-app-autotest` 降为通用参考（非默认），其 `description` 已收窄触发词、SKILL.md 已加 STATUS 标注，不会抢标准 Android 请求。
- ~~根目录 `tester*.md` 与 `_ext/.../tester*.md` 双源~~ ✅ 已处理：运行期只认根目录；`_ext` 两份加注释标注、保留不删（用户决策：保持标注、不从上游同步时直接删），维护以根目录为准。

## 目录速览

```text
TestHub/
├── apps/              # Django 主业务代码
├── backend/           # Django 设置、URL、ASGI/WSGI
├── frontend/          # Vue 3 源码与前端构建产物
├── docs/              # 项目文档（可能滞后）
├── scripts/           # 校验、初始化、迁移辅助脚本
├── knowledge-base/    # 知识库挂载目录（gitignore）
├── media/             # 上传文件、Allure 结果/报告等
├── logs/              # 运行日志
├── requirements.txt
└── docker-compose*.yml
```

## 常用开发入口

```powershell
# 后端（确认虚拟环境存在后）
E:\python_venv\testhub\Scripts\activate.bat
python manage.py runserver 0.0.0.0:8000

# 前端
Set-Location frontend
npm run dev

# 开发基础设施
docker compose -f docker-compose.dev.yml up -d mysql redis
```
