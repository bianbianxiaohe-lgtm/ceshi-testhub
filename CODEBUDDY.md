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
