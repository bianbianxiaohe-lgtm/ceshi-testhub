# TestHub 模块解耦体检报告

> 目的：找出「一改就牵连一大片」的高耦合点，给出优先级解耦建议，从源头降低 bug 月累计。
> 体检范围：`apps/requirement_analysis`（最高频改动 + 历史 bug 集中区）。

## 一、核心发现

### 1. `AIModelService` 是塞进 `models.py` 的巨型类（高耦合）— ✅ 已完成解耦
- **事实（2026-08-27 前）**：`apps/requirement_analysis/models.py:562` 定义 `class AIModelService`，其方法延伸至 `:2000+` 行（含 `generate_test_cases_stream` 在 `:1913`）。
- **现状**：`AIModelService` 已整体迁移至 `apps/requirement_analysis/ai_model_service.py`（~2300 行）。`models.py` 仅 `from apps.requirement_analysis.ai_model_service import AIModelService` 重新导出，**所有 50+ 调用方零改动**。迁移用 AST 静态分析抓取类依赖自动生成，避免漏导。
- **问题**：models 层应只放数据模型。AI 调用、流式生成、提示词拼装全堆在 models.py，导致：
  - 文件超大、难读、难单测；
  - 业务逻辑与 ORM 强耦合。
- **建议（已落地）**：将 `AIModelService` 整体迁移到 `apps/requirement_analysis/ai_model_service.py`（注：因同包已存在 `services.py` 模块，不能再用 `services/` 包名，故用 `ai_model_service.py` 文件名），models.py 仅保留数据模型 + re-export。

### 2. 同名 `generate_test_cases` 双定义（歧义风险）
- **事实**：`ai_model_service.py` 中 `AIModelService.generate_test_cases`（async）与 `apps/requirement_analysis/services.py:232` 独立的 `async def generate_test_cases(...)` 并存。
- **问题**：两处同名不同签名/归属，调用方易混淆，重构时易改错。
- **建议**：统一为单一实现，明确入口；删除重复定义。

### 3. async 外键修复是「线程补丁」而非「根因修复」（脆弱）→ 2026-08-27 已根治
- **事实（修复前）**：`views.py:1604-1605` 新建事件循环 + `:1600-1602` 预取 + `:1658` 注释要求用 `_id` 后缀；但 `models.py` 的 `generate_test_cases_stream` 体内仍懒加载 FK，且 `build_knowledge_context` / `_build_abnormal_scene_section`（查 `CoverageReport`）在 async 内被再次查询——带 `version_id` 的任务必崩。
- **问题（本质）**：修复依赖「调用方记得预取 + 函数内不碰懒加载」，任一新调用点漏做即复发。
- **已实施的根治（替代原 select_related 方案）**：在 `views.py` 的 `execute_task` 同步预取段（进入 `loop.run_until_complete` 之前）统一构建全部上下文（writer/reviewer 提示词、`writer_model_config`/`reviewer_model_config`、知识库上下文、异常场景统计），挂到 `task` 实例（`_pre_*` 属性）；四个 async 函数（`generate_test_cases`、`generate_test_cases_stream`、`review_test_cases`、`review_test_cases_stream`、`revise_test_cases_based_on_review`）改为只读缓存属性，**函数体内零 ORM**。
- **为何选「预取 stash」而非文档初稿的 `select_related`**：`task` 由 serializer 创建后在同一线程复用，stash 比再发一次 `select_related` 查询更直接，且把「所有 ORM 必须在同步段完成」这条约束显式固化，fail-fast 更明显（漏预取会 AttributeError 而非偶发异步崩溃）。

### 4. `requirement_analysis` 模块 models 层零 `select_related`/`prefetch_related`
- **事实**：全仓库 grep，`requirement_analysis` 下 **无任何** `select_related/prefetch_related`，仅在 `views.py` 个别地方补救。
- **问题**：N+1 与 async 外键风险全压在视图层打补丁，易遗漏。
- **建议**：对外键/反向关系的查询，在 service/query 层集中预取，视图层不再各自补救。

### 5. Modao 9 次 LLM 调用耦合在 workflow
- **位置**：`apps/requirement_analysis/modao_skill/`、`modao_workflow.py`。
- **建议**：先梳理调用依赖图，无依赖的抽取类步骤合并为「多字段结构化输出」单次调用；简单子任务降级小模型（见 BUG-05）。

## 二、优先级清单

| 优先级 | 项 | 收益 | 风险 |
|---|---|---|---|
| **P0** | ✅ 已实施：async 函数体内零 ORM，所有 FK/知识库/异常场景访问移到 `views.py` 同步预取段挂 `task._pre_*`（见 §3） | 根治 BUG-01 复发 | 已完成（2026-08-27） |
| **P1** | `AIModelService` 移出 `models.py` 到 `ai_model_service.py` | 降低耦合、可单测 | ✅ 已完成（re-export 保调用方零改动） |
| **P1** | 合并双 `generate_test_cases` 定义 | 消除歧义 | 低 |
| **P2** | `requirement_analysis` 查询集中 `select_related/prefetch_related` | 消除 N+1 + 外键雷 | 低 |
| **P2** | Modao 调用合并/降级 | 降 token、提稳定 | 中（需质量回归） |

## 三、验收标准
- P0 已完成（2026-08-27）：`generate_test_cases_stream` / `generate_test_cases` / `review_test_cases_stream` / `review_test_cases` / `revise_test_cases_based_on_review` 函数体内**不再有任何 ORM**。验证：`grep -n "task.writer_prompt_config\b\|task.reviewer_prompt_config\b\|task.writer_model_config\b\|task.reviewer_model_config\b" apps/requirement_analysis/ai_model_service.py` 应只剩 `getattr(..., task.xxx)` 兜底与 `audit_knowledge_base`（kb_audit，同步调用）两处。
- P1 已完成（2026-08-27）：`models.py` 不再含 `class AIModelService`（已迁至 `ai_model_service.py`，仅 re-export）；`test_regression_smoke.py` 仍应全绿。
