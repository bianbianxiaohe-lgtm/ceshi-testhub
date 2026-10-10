---
title: 墨刀原型解析 · 模型配置与调用流程
category: modao
order: 2
updated: 2026-10-09
desc: 五个阶段、九次主调用、视觉与去重模型怎么用
---

# 墨刀原型解析 · 模型配置与调用流程

这条线把磨刀原型（URL 或纯文本）解析成结构化页面信息，再产出测试点与用例。
它和「AI 用例生成」是**两条独立的线**（`independent_skill/SKILL.md:3`），流程、提示词、调用次数都不同，
但**共用同一张 AI 模型配置表**，所以配错角色会影响两边。

入口只接受 **URL / 文本**，不支持上传文件（`modao_views.py:578`）。

## 一、五个阶段

| 阶段 | status | 主函数 | 产物 |
| --- | --- | --- | --- |
| 0 读取 | `extracting` → `extracted` | `run_extract` `modao_workflow.py:822` | `extracted_json` |
| 1 结构化 | `structuring` | `run_struct:1832` | 逐画布 `page_summary` |
| 2 澄清 | `clarifying` | `run_clarify:1982` | `clarification_log` |
| 3 设计 | `designing` | `run_design_phase1:2377`（测试点）/ `run_design_phase2:3130`（用例） | 测试点 / 用例 / 冒烟 |
| 4 冒烟执行 | — | `record_smoke_decision:3583` | 纯人工，**0 次 LLM** |

## 二、模型调用顺序

共 9 个主调用点，另有若干条件触发的重试与自愈调用。

| # | 角色 | 用途 | 位置 | 必需 / 失败表现 |
| --- | --- | --- | --- | --- |
| 1 | analyzer | p0 结构化（逐画布） | `1874`（重试 `1888`） | 必需，失败中断 |
| 2 | analyzer | 生成澄清清单 | `2085` | 必需 |
| 3 | analyzer | p1 模块拆分 | `2476`（聚焦补全 `2488`，重试 `2514`） | 必需；缺模块时合成占位 `2497` 或置 failed `2589` |
| 4 | analyzer | p2 测试点（分批） | `2642 / 2651`（空重试 `2670`） | 模块级 try，失败跳过该模块 `2815` |
| 5 | analyzer | p5 风险分析 | `2692` | 同上 |
| 6 | analyzer | p6 PCI | `2736`（重试 `2748`） | 同上 |
| 7 | analyzer | p7 三路合并 | `2790` | 结果为空时降级用去重输入 `2797` |
| 8 | **writer** | p3 生成用例（本线唯一 writer 主调用） | `3200`（max_tokens 16000） | 模块级跳过 `3226` |
| 9 | analyzer | p4 冒烟用例 | `3272` | 必需 |

条件触发的额外调用：

- 步骤自愈 `3110`（writer 优先，回退 analyzer），失败则标记需人工补充 `3121`
- 人工答疑 `ask_question:803`（按需）
- 双路 DOM + 视觉融合 `modao_extractor.py:3840`（可选，失败返回空）

> p8 质量自检已改为代码级实现 `_code_quality_check:3000`，**不再消耗 LLM**。

## 三、视觉模型什么时候会用到

配置位置：`modao_views.py:173` 取 `writer_vision`，`:176` 取 `writer_vision_ocr`，
**OCR 没配就回退到 `writer_vision`**（另有二次兜底 `modao_workflow.py:536`）。

是否调用视觉模型由 DOM 文本量决定（`modao_extractor.py:588` 的 `vision_attempted`）：

- DOM 文本 **≥ 800 字** → 跳过视觉（`571`）
- DOM 文本 **≥ 400 字** 且没有大量 img / canvas / svg → 跳过（`575`）
- 文字很少或视觉元素重 → 走 OCR（webshare 分支见 `:587`，DOM < 30 字或有视觉元素时触发）

图片来源与处理：

- 用 **Playwright 截图**（`1974-1997`），viewport 1920×1200、scale=4、整页截图
- 超长画布分段截图 → `screenshot_segments`，逐段 OCR 后合并（`3786-3810`）
- OCR 主调用 `_ocr_screenshot:3598` → `3649`，决策表重试 `3686`、状态矩阵重试 `3721`
- 并发上限 `OCR_CONCURRENCY=8`（`:31`）

## 四、向量化模型（embedder）在做什么

四处用途，全部**不阻断流程**：

| 用途 | 位置 | 阈值 |
| --- | --- | --- |
| 测试点向量去重（模块内 `2779` + 全局二次 `2829`） | `_vector_dedup:634` | 相似度 0.80 |
| PCI 对已澄清项去重 | `:696` | 余弦 ≥ 0.80 或字面 ≥ 0.55 |
| 跨模块 PCI 聚类 | `2882` | — |
| 采纳后跨画布去重 | `2343` | — |

降级路径：`_embed:600` 取不到配置 / 超时 / 异常 → 返回 `None` → `_vector_dedup:651` 跳过去重；
`_cosine_sim:619` 返回 `None` 时退化为 difflib 字面兜底。

## 五、澄清阶段怎么交互

不是对话式追问，而是**一次性给清单**：

1. 一次 LLM 产出 JSON 清单（`2085` → `2105`）
2. 人工在前端逐条填写 `resolution`（`modao_views.py:1046 / 1120`）
3. 已回答的结论经 `_build_confirmed_context:3390` 注入用例 prompt（`3196-3199`），并用于 PCI 去重（`2755`）
4. 闸门 `modao_approve_case_generation:904`：**有未填结论时返回 409**，不允许进入生成

另有可选的答疑入口 `ask_question:803`。

## 六、重跑与缓存

- `run_struct` 对已完成的画布**增量跳过**（`1853-1857`），`force=True` 才全量
- `reset:618` 清空全部产物并删除画布 → 全量重跑
- OCR 结果按**截图 sha256 缓存**（`3604-3616`，`OCR_CACHE_DIR`），同一张截图重跑不再调用模型
- 读取阶段有 checkpoint 续读（`637`）
- 只改测试点后重跑：只重跑第 8 步 writer 与第 9 步冒烟

## 七、配置缺失会怎样

| 缺什么 | 表现 | 判断位置 |
| --- | --- | --- |
| analyzer | 回退复用 writer；两者都缺则抛异常中断 | `555-556`、`_llm:568` |
| writer | 直接用，无回退（仅步骤自愈回退 analyzer） | `3200`、`3110` |
| writer_vision | **降级跳过**（只有双路融合模式会阻断置 failed） | `1970`、`672`、`834-838` |
| embedder | **降级不去重** | `_embed:600` |

## 八、常见报错对照

| 现象 | 原因 | 怎么处理 |
| --- | --- | --- |
| 解析直接失败 | analyzer 与 writer 都没配 | 至少配一个，analyzer 会回退复用 writer |
| 页面内容解析为空 | DOM 文本少但视觉模型没配，跳过 OCR | 配 `writer_vision`（OCR 可共用） |
| 测试点重复多 | embedder 未配或失效，向量去重被跳过 | 检查 embedder 配置的连接测试 |
| 卡在澄清阶段过不去 | 有未填的澄清项 | 前端逐条补完，闸门 `904` 会拦截 |
| 长画布 OCR 慢 | 分段截图多、并发上限 8 | 属正常，可先看已完成的画布 |
