# 平台全景档案 (Project Profile)

> **最后更新**：2026-10-12  
> **适用版本**：TestHub v1.0.1（开发环境 Docker 模式）

---

## 1. 系统定位与核心能力

TestHub 是一套基于大模型与自动化测试引擎的前后端分离**智能测试管理与自动化执行平台**：
1. **测试资产管理**：项目、需求文档、测试用例库、测试套件、版本基线、用例评审、禅道覆盖率同步。
2. **UI / APP 自动化执行**：基于 Playwright、ADB、Appium、Airtest/Poco，并集成 Midscene（AI 视觉大模型驱动）实现 Web & 移动端智能操作录制与回放。
3. **需求分析与用例生成**：墨刀原型读取与画布拆解、PRD 文档分析、AI 追问澄清、测试点到用例的全自动提炼，采用 SSE（Server-Sent Events）实时流式呈现。
4. **测试数据工厂与缺陷管理**：数据生成造数、缺陷提单与生命周期闭环。

---

## 2. 真实技术栈清单

| 层级 | 技术选型 | 版本/事实源 | 关键说明 |
|---|---|---|---|
| **后端语言** | Python | 3.12 (容器内基准) | 依赖严格对齐 `requirements.lock.txt` |
| **Web 框架** | Django | 4.2.7 | 路由中心位于 `backend/urls.py` |
| **API 框架** | Django REST Framework | 3.14.0 | 身份认证采用 SimpleJWT (`Bearer <token>`) |
| **API 契约** | drf-spectacular | 0.27.x | OpenAPI 3.0，文档访问 `/api/docs/` |
| **前端语言** | Vue 3 + TypeScript / JS | 3.3.4 | 组合式 API (Composition API) |
| **前端构建** | Vite | 7.3.1 | 配置见 `frontend/vite.config.js` |
| **UI 组件库** | Element Plus | 2.3.9 | 配套 `@element-plus/icons-vue` |
| **状态管理/路由** | Pinia + Vue Router | Pinia 2.1 / Router 4.2 | 全局用户状态与菜单权限 |
| **富文本/代码** | Monaco Editor / Marked | 0.53 / 18.0 | 用例脚本编写与 Markdown 预览 |
| **主业务数据库** | MySQL | 8.0 (utf8mb4) | 团队共用远程库，见下文网络拓扑 |
| **缓存/任务代理** | Redis | 7.0-alpine | 本地容器运行，端口 6379 |
| **向量检索库** | ChromaDB | PersistentClient | 用于知识库检索与相似度比对 |
| **容器编排** | Docker Compose | Compose v2.x | 开发模式使用 `docker-compose.dev.yml` |

---

## 3. 服务与网络拓扑

### 3.1 端口与访问入口（开发模式）

| 服务名称 | 容器内端口 | 宿主机映射端口 | 访问 URL | 说明 |
|---|---|---|---|---|
| **前端服务 (Frontend)** | 80 (Nginx) | **18080** | [http://localhost:18080](http://localhost:18080) | Nginx 代理静态资源并将 `/api/` 转发给后端 |
| **后端 API (Backend)** | 8000 (Django) | **18000** | [http://localhost:18000/api/](http://localhost:18000/api/) | DRF 核心接口，根路径自动 302 重定向到 Swagger |
| **Swagger 接口文档** | 8000 | **18000** | [http://localhost:18000/api/docs/](http://localhost:18000/api/docs/) | 交互式 API 契约文档与在线调试 |
| **共享开发 MySQL** | 3306 | **13306** | `192.168.8.75:13306` | **团队共享数据库**，库名 `testhub_dev` |
| **本地 Redis** | 6379 | 6379 (内网) | `redis://redis:6379/0` | 仅供本地容器内部使用 |

### 3.2 环境变量事实源
* **开发环境**：`.env.dev`（由 `scripts/init_dev_env.ps1` 初始化，配置 `DB_HOST=192.168.8.75`, `DB_PORT=13306`, `DB_NAME=testhub_dev`, `DB_USER=testhub_dev`）。
* **重要安全防线**：`.env` 与 `.env.dev` 已配置在 `.gitignore`，严禁上传 Git。

---

## 4. 容器与分层构建架构

```
+--------------------------------------------------------------+
| 基础镜像: testhub-backend-base:20261010 (~2.94GB)             |
|   - Python 3.12-slim (Pin Digest)                            |
|   - 系统包 (mysqlclient, build-essential, OpenCV libs, wget)   |
|   - ADB Client                                               |
|   - 243 个 pip 依赖 (requirements.lock.txt)                  |
|   - Playwright Chromium 浏览器 (~184MB)                      |
+--------------------------------------------------------------+
                              |
                     COPY 源码层 (几秒钟)
                              v
+--------------------------------------------------------------+
| 运行镜像: testhub-dev-backend:latest                          |
|   - 挂载 ./apps -> /app/apps                                 |
|   - 挂载 ./backend -> /app/backend                           |
|   - 挂载 ./scripts -> /app/scripts                           |
|   - 挂载 ./manage.py -> /app/manage.py                       |
|   - 挂载 ./docker_start.py -> /app/docker_start.py           |
+--------------------------------------------------------------+
```

* **热重载特性**：代码挂载后，本地直接用 IDE 修改代码，容器内部实时同步；
* **不需要重建的情况**：修改业务代码、页面样式、添加 SQL 检查；
* **必须重启容器的情况**：修改了 `backend/urls.py`、安装了新 Django App；
* **必须重建基础镜像的情况**：升级或新增 pip 依赖包（需负责人统一处理）。
