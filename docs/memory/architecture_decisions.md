# 架构决策记录 (Architecture Decision Records - ADR)

> **定义**：ADR 记录平台技术选型与架构演进的关键决策，回答“为什么这么设计”以及“权衡考量是什么”，避免后续开发盲目重构导致历史缺陷复现。

---

## ADR-001：团队开发共用同一套共享开发数据库（Shared Dev DB）

* **状态**：`已采纳 (Accepted)`
* **日期**：2026-10-10
* **背景与上下文**：
  TestHub 作为测试平台，具备复杂的业务模型（项目、版本、用例、步骤、环境、执行记录、设备池、墨刀解析记录等共有 145+ 张表）。如果每位开发者在本地搭建一套空白数据库，不仅各人需要手动制造复杂的业务测试数据，而且由于自动化用例录制需要依赖前置数据，极易出现“在我机器上跑得好好的，到别人机器上缺数据”的问题。
* **决策内容**：
  * 团队统一以负责人机器上的 MySQL（`192.168.8.75:13306`，库名 `testhub_dev`）为唯一共享开发库。
  * 开发者本地通过 `.env.dev` 配置 `DB_HOST=192.168.8.75` 和 `DB_PORT=13306` 直连共享库。
* **权衡与影响**：
  * **优势**：开箱即用，所有成员随时享有 11 个真实项目的全量测试资产。
  * **代价与约束**：**严禁任何开发者在本地随意执行 `python manage.py migrate`**，多节点并发迁移会破坏 `django_migrations` 图，导致全局服务 500。

---

## ADR-002：基于分层基础镜像的 Docker 极速构建机制

* **状态**：`已采纳 (Accepted)`
* **日期**：2026-10-10
* **背景与上下文**：
  后端 Python 运行环境极为庞大，涵盖 Playwright 浏览器（~184MB）、ADB 客户端、OpenCV、MySQLClient 以及 243 个 pip 依赖包。若采用单体 Dockerfile 从零构建，在国内网络环境下因重装 243 个包极易耗时 30~40 分钟甚至频繁超时失败。
* **决策内容**：
  * 拆分为“基础镜像层”与“业务源码层”：
    1. 基础镜像 `testhub-backend-base:20261010`（约 2.94GB）：预先固化操作系统底包、ADB、全量 pip 包与 Playwright Chromium；
    2. 业务镜像 `Dockerfile.backend`：直接 `FROM testhub-backend-base:20261010`，仅执行 `COPY . .` 和创建目录。
* **权衡与影响**：
  * **优势**：本地 `docker compose build backend` 重建耗时从数十分钟降至 **10 秒以内**。
  * **约束**：新增第三方依赖包不能只改 `requirements.txt`，必须由负责人重新生成 `Dockerfile.backend-base` 并分发基础镜像。

---

## ADR-003：启动期幂等 DDL 补齐策略（docker_start.py 代替随意 Migrate）

* **状态**：`已采纳 (Accepted)`
* **日期**：2026-10-10
* **背景与上下文**：
  在“共享库模式”下，普通成员如果新增了模型字段（例如新增 `role_id` 或 `step_results`），无法直接执行 migrate，否则会与他人并发冲突。
* **决策内容**：
  * 新增字段/表时，除了生成迁移文件记录架构意图外，**必须同步在 `docker_start.py` 中编写幂等 SQL 检查**：
    ```python
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'xxx' AND column_name = 'yyy'")
    if not cur.fetchone():
        cur.execute("ALTER TABLE xxx ADD COLUMN yyy ...")
    ```
  * `docker_start.py` 在容器启动时自动以幂等方式补齐字段，无需人工干预。
* **权衡与影响**：
  * **优势**：新成员拉取代码后重启容器即可自动平滑升级表结构，无需手动打 patch，也不会污染共享库迁移记录表。

---

## ADR-004：Swagger 接口文档自动化与根路径重定向规范

* **状态**：`已采纳 (Accepted)`
* **日期**：2026-10-12
* **背景与上下文**：
  TestHub 属于纯前后端分离架构，后端不提供页面模板渲染。前端通过统一 API 契约调用后端。如果开发者直接在浏览器访问根域名 `http://localhost:18000/`，原先返回 404 易引起“服务未正常启动”的误解。
* **决策内容**：
  * 采用 `drf-spectacular` 作为 OpenAPI 3.0 事实源，接口文档入口为 `/api/docs/`。
  * 在 `backend/urls.py` 中将根路径 `""` 通过 `RedirectView` 302 重定向到 `/api/docs/`。
* **权衡与影响**：
  * **优势**：浏览器直连后端根域名即可直接进入交互式接口文档，方便自测、入参查阅与联调。
