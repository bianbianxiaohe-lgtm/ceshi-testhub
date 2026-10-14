# 高频踩坑与开发避坑指南 (Pitfalls & Rules)

> **原则**：血泪教训的沉淀。凡是在排查中耗费超过 15 分钟的深坑，必须记录于此，标明现象、根本原因与根治手段。

---

## 🕳️ 踩坑案例库

### 坑 1：Docker Compose 中的 `environment` 强制覆盖 `.env.dev`
* **现象**：在 `.env.dev` 里明明配置了 `DB_HOST=192.168.8.75`，后端启动后却仍然连到本地容器 `mysql:3306`，或者报 `Can't connect to MySQL server on 'mysql'`。
* **根因**：Docker Compose 机制中，`services.<name>.environment` 的优先级**高于** `env_file`。如果在 `docker-compose.dev.yml` 中硬编码了 `DB_HOST: mysql`，则 `.env.dev` 中的配置会被直接覆盖抹掉。
* **避坑准则**：
  * 在 `docker-compose.dev.yml` 中，如果某个变量希望优先由 `.env.dev` 提供，**绝对不要在 `environment:` 中硬编码赋值**。

---

### 坑 2：`# syntax=docker/dockerfile:1` 导致局域网/离线构建卡死
* **现象**：执行 `docker compose build backend` 时报 `failed to resolve source metadata for docker.io/docker/dockerfile:1: short read: expected 1406 bytes but got 0: unexpected EOF`。
* **根因**：第一行的 `# syntax=docker/dockerfile:1` 指示 Docker Buildx 在构建前从 Docker Hub 拉取远程解析器。如果在国内网络较差或无外网环境下，拉取失败会导致整个构建链路崩溃。
* **避坑准则**：
  * 本地基于固定基础镜像的常规构建，直接去掉 `# syntax=docker/dockerfile:1`，使用 Docker 本地自带的 Parser 即可，速度快且完全免疫外网断连。

---

### 坑 3：ViewSet 的 `filterset_fields` 包含不存在的模型字段引发 Swagger 500
* **现象**：访问 `/api/docs/` 页面报错白屏，后端控制台报 `TypeError: 'Meta.fields' must not contain non-model field names: <字段名>`。
* **根因**：`django-filter` 在与 `drf-spectacular` 集成生成 OpenAPI 文档时，会严格自省 Model 的所有字段。如果在 `filterset_fields` 中写了模型上不存在的字段（通常由从其他 ViewSet 复制粘贴遗留导致），会导致全局 `/api/schema/` 解析崩溃。
* **避坑准则**：
  * 编写 ViewSet 的 `filterset_fields` 时，务必核对对应 `models.py` 是否确实定义了该字段；若为非模型计算字段，须使用 `filterset_class` 自定义 Filter 方法。

---

### 坑 4：自定义 `db_table` 命名陷阱
* **现象**：直接写原生 SQL 或在脚本中连库查表时报 `Table 'testhub_dev.projects_project' doesn't exist`。
* **根因**：本项目大量模型没有采用 Django 默认的 `<app>_<model>` 命名，而是显式指定了自定义表名（例如 `Project` 对应 `projects`，`ProjectRole` 对应 `project_roles`，`User` 对应 `users_user`）。
* **避坑准则**：
  * 查表或写 DDL 前，先到对应 `models.py` 的 `class Meta:` 中核实 `db_table` 名称，不要想当然靠默认规则猜。

---

### 坑 5：清理 Docker 空间时切忌误用 `docker system prune -a`
* **现象**：清理磁盘空间后，下次构建后端突然重新下载 243 个 pip 包和 Playwright，耗时 40+ 分钟。
* **根因**：`docker system prune -a` 或 Docker Desktop 的 Purge Data 会清除未被使用的所有镜像，把本地好不容易拉取的 `testhub-backend-base:20261010` 一同抹除。
* **避坑准则**：
  * 清理 Docker 磁盘时，**只使用安全命令**：`docker image prune -f`（只清孤儿虚悬层，不删带 Tag 的基础镜像）。
