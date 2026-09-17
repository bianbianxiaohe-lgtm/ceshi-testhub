# 独立线 AI 用例生成 Skill（Independent AI Test Case Generation Skill）

> 与墨刀线 Skill（`modao_skill/`）并列的第二个独立 Skill。两条线**完全独立运营，不要混改**。

## 一、职责边界

**本 Skill 做什么**：
- 输入：用户提供的**纯文本需求**（`requirement_text`）或上传的 pdf/word/ppt 文档；
- 输出：结构化测试用例 + AI 评审报告 + 人工反馈记录。

**本 Skill 不做什么**：
- ❌ 不读墨刀分享页 URL（→ 墨刀线 Skill）；
- ❌ 不处理原型截图/便签/批注（→ 墨刀线 Skill）；
- ❌ 不参与禅道覆盖率分析、bug 同步（→ zentao app）；
- ❌ 不导出 Excel/xmind（那是导出器，非 LLM Skill）。

## 二、包内资产

```
apps/requirement_analysis/independent_skill/
  SKILL.md           ← 本文件（包级说明）
  prompts/           ← 提示词库（运行期真源，已进镜像）
    tester.md        ← writer 角色（生成用例）
    tester_pro.md    ← reviewer 角色（评审用例）
    tester_analyzer.md ← 前置拆解角色（人话/截图→结构化逻辑表）
    （tester_new.md 已并入 tester.md，2026-09-03 删除）
  tools/             ← 占位，未来抽离 ai_model_service 独立线方法
  workflow/          ← 占位，未来补独立线流水线文档
  TODO.md            ← 提示词攒批优化清单（2026-09-03 建，改提示词前对照）
```

## 三、流水线（5 步）

```
1. 上传/录入 → 创建 TestCaseGenerationTask
     ├─ 输入：requirement_text（必填）+ 项目/版本（必填）+ confirmed_answers（可选）
     └─ 输出：task.status='pending'
2. 后台 prefetch（views.py:1594）
     ├─ writer_prompt（prompts/tester.md，含增强组织规则）
     ├─ reviewer_prompt（prompts/tester_pro.md）
     ├─ 知识库 RAG 上下文（build_knowledge_context）
     ├─ 异常场景统计（_build_abnormal_scene_section）
     └─ confirmed_answers / human_feedback 注入（_build_*_context）
3. generate_test_cases_stream（writer 调用）
     ├─ 输入：requirement_text + 知识库 + confirmed_answers + 模式指令
     ├─ 输出：task.generated_test_cases + stream_buffer（流式实时）
     └─ 模式指令：prompts/_build_generation_instructions（智能/快速/标准/全面）
4. review_test_cases_stream（reviewer 调用）
     ├─ 输入：生成用例
     ├─ 输出：task.review_feedback + uncertain_items（自动检测）
     └─ 评审维度见 tester_pro.md
5. 人工反馈循环
     ├─ TaskDetail.vue 展示：需求描述 / 功能点清单 / 建议补充 / 评审报告 / 用例列表
     ├─ 人工逐项确认不确定项 → human_feedback
     └─ 可触发 rerun_review（基于 human_feedback 再评审）
```

## 四、运行期关键调用

- 默认提示词加载：`PromptConfigViewSet.load_defaults`（views.py:1056）→ 读本包 `prompts/tester*.md`；
- 写入流程：`apps/requirement_analysis/ai_model_service.py`（共用层，墨刀线也调用部分方法，未来抽离本 Skill 专用方法到 `tools/`）；
- API 端点：`/api/requirement-analysis/testcase-generation/`（独立线任务 CRUD）；
- 前端入口：`frontend/src/views/requirement-analysis/RequirementAnalysisView.vue`（任务列表/新建）+ `TaskDetail.vue`（详情/评审/确认）。

## 五、与墨刀线 Skill 的关系

| 维度 | 独立线（本 Skill） | 墨刀线（`modao_skill/`） |
|------|-------------------|------------------------|
| 输入 | 文本需求 / pdf/word/ppt | 墨刀 URL |
| 流水线入口 | 单任务一键跑 | 多阶段 0~4 |
| 提示词位置 | `independent_skill/prompts/` | `modao_skill/prompts/` |
| 模型配置 | writer_model + reviewer_model 双角色 | analyzer_config 单角色 |
| 数据模型 | TestCaseGenerationTask | ModaoPrototype + ModaoPage |
| 人工门禁 | 评审确认卡片 | 阶段1 澄清+阶段3 测试点+阶段4 冒烟 |

**共用层**（仍留在 `apps/requirement_analysis/ai_model_service.py`）：
- 知识库 RAG（`build_knowledge_context` / `_rag_retrieve_kb`）—— 两线都要用；
- LLM 客户端（`call_openai_compatible_api*`）—— 共用；
- 异常场景注入（`_build_abnormal_scene_section`，仅墨刀线有覆盖率报告源）；
- 知识沉淀（`auto_fill_knowledge_from_modao_products` / `auto_fill_knowledge_from_confirmations`）。

## 六、变更约束

1. **改提示词**：只改本包 `prompts/tester*.md`，不要再去改根目录的同名文件；
2. **改模式指令**：改 `ai_model_service._build_generation_instructions`（提示词工程，影响所有模式）；
3. **改评审**：改 `tester_pro.md` 或 `ai_model_service._build_human_feedback_context` 注入逻辑；
4. **改前端**：改 `RequirementAnalysisView.vue` / `TaskDetail.vue`；
5. **新增提示词角色**：在本包 `prompts/` 加新 .md，并在 `PromptConfigViewSet.load_defaults` 增加读取路径；
6. **抽离服务到 tools/**：当 `ai_model_service.py` 里某段**只被独立线使用**时，可抽到 `tools/` 子模块（如 `instruction_builder.py`、`post_processor.py`），从 `ai_model_service` import 引用；
7. **不要把独立线逻辑写进 `modao_skill/`**——两 Skill 边界已定，混入会破坏后续维护。

## 七、回归验证

- 走完整流程一次：新建任务 → 生成 → 评审 → 人工确认 → rerun_review；
- 看 TaskDetail 三个折叠卡片（需求描述 / 功能点清单 / 建议补充 / 评审报告）是否正常渲染；
- 检查默认提示词 API：`GET /api/requirement-analysis/prompts/load_defaults/` 返回 `writer` / `reviewer` / `analyzer` 三项；
- 同步墨刀线**无回归**：跑一个墨刀 URL 任务确认工作流无异常。

## 八、双源问题（运行期真源）

- ✅ **真源**：`apps/requirement_analysis/independent_skill/prompts/tester*.md`（进镜像，后端读取）；
- ⚠️ 历史根目录 `tester*.md` 文件保留（旧运行期直读路径），是过渡期兼容；
- ⚠️ `_ext/ai-case-generation-module/docs/tester*.md` **不进镜像不读**，仅上游参考。