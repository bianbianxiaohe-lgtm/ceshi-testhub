# 独立线提示词攒批优化清单（TODO）

> 创建：2026-09-03。用途：供**下次改提示词时对照**执行，避免遗漏。
> 原则：提示词改动落地成本固定较高（本地双副本 + prod/dev 容器 + 两库 DB 记录 + 冒烟回归），
> **必须攒批一次改、一次同步**，不要改一条同步一条。同步策略与落点见 CODEBUDDY.md 注册表行及下文「落地须知」。

## 一、攒批候选（提示词级，下次动提示词时对照）

| # | 目标文件 | 改动 | 现状依据 | 状态 |
|---|---------|------|---------|------|
| 1 | tester.md | 增加**输入需求格式模板**约定（如：功能模块 + 用户角色 + 业务流程 + 约束条件），约束输入质量 | 当前无输入格式要求，AI 可能收到"帮我测一下登录"这类模糊输入 | 待办 |
| 2 | tester.md | 增加 **few-shot 示例**（好用例 vs 差用例对比 2~3 条） | 当前仅表格 1 行示意，无对比 | 待办 |
| 3 | tester.md | 增加**"一正一反"配对原则**：每个正向测试点必须配对 ≥1 个异常/边界用例 | 当前仅要求覆盖异常/边界，无显式配对 | 待办 |
| 4 | tester.md | 组织原则 1 "禁止按 UI 卡片逐个罗列" 评估改为"优先按业务场景组织，UI 卡片可作子维度"（表单等 UI 密集型场景按卡片反而清晰）。**改前需拍板**：与按测试维度横向组织的关系 | 当前第 1 条组织原则为硬性禁止 | 待拍板 |
| 5 | tester_analyzer.md | 增加**精简模式**：简单需求只输出需求概述/功能拆解/异常清单，复杂需求才全量 6 大输出项 | 6 大项+插接矩阵逐行展开，单次调用易超长/截断 | 待办 |
| 6 | tester_analyzer.md | 待确认事项限制**最多 5 条** | 已有表格+阻塞风险(高/中/低)列，无条数上限 | 待办 |
| 7 | tester_pro.md | **评分权重公开化**：0-100 分打分维度与权重写进 prompt（如覆盖率 40% + 逻辑性 35% + 规范性 25%，数字需拍板），让评审可解释可追溯 | 当前只要求 0-100 分，无维度权重 | 待拍板 |
| 8 | tester.md | 新增「**历史缺陷高发维度**」4.1~4.5：①操作的重复/再进入变体（再次执行/中断恢复/刷新回撤/防抖）②交互时序与并发 ③状态迁移与权益边界（会员过期/生成失败/跨端跨账号）④预期结果必须可判伪（禁"展示正常"类断言，须落到颜色/位置/尺寸/文案/接口字段）⑤交付自检清单 | 依据 2026-10-12 禅道覆盖率 report#29（mini2 V1.0.1）：未覆盖 57 条归因中，断言粒度粗 17 条（假覆盖剔除 18/34，假阳率 53%）、异常时序功能域缺失约 20 条、同域变体缺失约 20 条 | 本地已改，**待同步** |
| 9 | tester_pro.md | 评审维度增加「历史缺陷高发维度」三类逐项判定 + 「预期结果是否可判伪」；输出要求新增第 4 项「高发维度缺失清单」（通过也必给） | 同上；Reviewer 是最后一道守门，必须能点名缺失维度 | 本地已改，**待同步** |

> 说明：analyzer 功能拆解表已含「优先级」列（勿再加）；角色分组去重已由 tester.md「先通用后角色差异」覆盖；优先级 P0~P3 定义已在 tester.md（勿再加）。

## 二、代码级待办（单独排期，不走提示词攒批）

| 项 | 说明 | 落点 |
|----|------|------|
| Analyzer 超时降级 | `analyze`（views.py:1376）为同步调用，AI 超时会直接 500；需加超时控制/降级（如失败提示走 Writer） | views.py / ai_model_service.py |
| Reviewer 低分自动二次评审 | 当前低分只能人工触发 `rerun_review`（views.py:3451）；可评估低分自动拉起二次评审 | ai_model_service.py / views.py |

## 三、明确不做（记录原因，防重复提议）

- ❌ tester_new.md 相关优化：文件已于 2026-09-03 删除并并入 tester.md（当前 tester.md 即增强版）。
- ❌ Reviewer 强制输出"修正后用例"：与现有「评审反馈 → 人工确认 → 可选 rerun_review(Writer 重生成)」闭环相悖；强制修正版让 Reviewer 承担 Writer 职责，违背"质量守门员"定位。
- ❌ 每份 prompt 头部加 Version/Changelog：git 即版本管理；头部又增双副本同步负担。
- ❌ SKILL.md 增加"质量指标"章节：当前无埋点数据，指标会是空文；待有数据再补。

## 四、落地须知（每次改提示词必读）

> **本次（2026-10-13，条目 8/9）同步已完成**：dev + prod 两端文件 MD5 对齐、PromptConfig 的 writer/reviewer 已更新、
> 知识闭环（report#29）已写入并升级 16 条为跨版本通用、两端重启后 `/api/` 均 404 健康。
> ⚠️ 收尾：验收脚本 `scripts/_verify_sync.py` 因执行通道卡死未跑完，下次优先执行，见第六节。

1. **本地双副本同步**：改包内 `independent_skill/prompts/tester*.md` 后，必须同步根目录同名文件（内容一致，MD5 对齐）。
2. **容器同步**：dev（新代码路径，读包内 `independent_skill/prompts/`）；prod（旧代码路径，读根目录 `/app/tester*.md`）。分别 `docker cp` 后校验 MD5。
3. **DB 记录同步**：`PromptConfig`（prompt_type=`writer`/`reviewer`/`analyzer`）active 记录内容取自容器内文件，需用容器内脚本更新，两环境都要。
   ⚠️ **必须显式指定类型（如 `writer reviewer`）**：DB 里 analyzer 是人工定制版（1466 字符「智能测试分析总控专家」，与 `prompts/tester_analyzer.md` 的 1959 字符不一致），跟着文件刷会被静默覆盖（2026-10-13 已在 dev 踩到并恢复）。
4. **回归验证**：冒烟 `pytest apps/requirement_analysis/tests/test_regression_smoke.py` + 走一遍 生成→评审→确认 流程。
5. 是否 rebuild：提示词改动要 rebuild 才固化镜像（`docker-compose build backend`）；紧急可 `docker cp` 热更（不固化）。

## 五、2026-10-12 条目 8/9 同步清单（待执行）

改动范围：`apps/requirement_analysis/independent_skill/prompts/tester.md`、`tester_pro.md`（本地双副本已同步到根目录 `tester.md`、`tester_pro.md`）。

```powershell
# 1) dev：打 tar 同步（Windows docker cp 目录会漏文件）
tar -cf _p.tar apps/requirement_analysis/independent_skill/prompts tester.md tester_pro.md
docker cp _p.tar testhub-dev-backend-1:/tmp/
docker exec testhub-dev-backend-1 sh -c "tar -xf /tmp/_p.tar -C / -o 2>/dev/null; echo ok"

# 2) prod：镜像内文件被占用，先 cp 再 mv
docker cp _p.tar testhub-backend:/tmp/
# 容器内把 tester.md / tester_pro.md 覆盖到 /app/，prompts/ 覆盖到 /app/apps/.../prompts/

# 3) 两端各跑一次 DB 同步脚本
docker cp scripts/update_prompt_configs.py <容器>:/tmp/
docker exec <容器> python /tmp/update_prompt_configs.py
docker exec <容器> cat /tmp/update_prompt_configs.txt

# 4) 重启并校验
docker restart <容器>
```

验收判据：① 两端容器内 `md5sum` 的包内文件与根目录同名文件一致；② `/tmp/update_prompt_configs.txt` 显示 writer/reviewer/analyzer 三条均已更新（`len=` 与本地文件一致）；③ 前端 `GET /api/requirement-analysis/prompts/load_defaults/` 返回的新文案包含「历史缺陷高发维度」。

## 六、本次同批 ── 禅道覆盖率判定侧代码改动（apps/zentao/services.py）

- LLM 判定输入：用例侧由「标题+预期结果 240 字」放开为「标题+前置+步骤+预期 600 字」；Bug 侧 260 字 → 600 字。
- 判定/复核温度 `0.1` → `0`（抑制同一 Bug 跨轮次判定翻转：report28/29 用例未变但覆盖 28.8%↔21.9%）。
- 三参数均可用环境变量覆盖：`ZENTAO_COVER_JUDGE_CASE_CHARS` / `ZENTAO_COVER_JUDGE_BUG_CHARS` / `ZENTAO_COVER_JUDGE_TEMPERATURE`。
- 报告 `detail` 新增 `judge_case_chars` / `judge_bug_chars` / `judge_temperature` 留痕，便于复现口径。
- 容器同步方式与第五节相同（`tar` → `docker cp` → 清 `__pycache__` → restart）。

## 七、固化记录（2026-10-13，prod 已重建镜像）

prod `/app/apps` 非 bind mount ⇒ 上面两节的热更**容器一重建就静默回退**。已按用户要求固化：

- 回滚点：`docker commit testhub-backend testhub-backend:20261013-hotfix-before-rebuild`（sha256:25866655091e…）。
- 固化：`powershell -ExecutionPolicy Bypass -File C:\TestHub\scripts\rebuild_prod_backend.ps1`
  （STEP1 容器内 `tar` 备份 + mysqldump → STEP2 `docker compose build backend` → STEP3 重建容器 → STEP4/5 自动 md5 比对）。
- 结果：新镜像 `sha256:c3a78aed4790…`，**STEP5 五个文件 md5 全部 OK**（与宿主一致），`/api/`=404 健康、chromium 存在、`/api/projects/roles/`=401。
- 脚本同步增强：`rebuild_prod_backend.ps1` 新增 STEP5（md5 期望值表自动比对，不符直接 Fail）+ 运行时 JUDGE_* 常量 / PromptConfig 长度 / ProjectKnowledge 计数。
  ⚠️ **坑**：脚本里 `docker exec python -c "..."` 的输出**不会**进日志（PS 只把 `Say` 的文本 Add-Content），运行时校验改用容器内 `scripts/_verify_img.py`（自写 `/tmp/_verify_img.txt` 再 `cat`）。
- ⚠️ `.ps1` 改完必须 `python scripts/fix_crlf.py <绝对路径>`（相对路径会被拼到 `scripts/scripts/` 报 MISSING）。
- ✅ **运行时验收（15:06，全部达标，脚本 `scripts/_run_verify_img.ps1` → 结果 `C:\TestHub\_verify_img_out.txt`）**：
  `JUDGE_CASE_CHARS=600 / JUDGE_BUG_CHARS=600 / JUDGE_TEMPERATURE=0.0`（**由镜像内代码读出**，非热更残留）；
  `analyzer len=1466`（定制版未被覆盖）/ `reviewer=1012` / `writer=3089`；
  知识库 `global(version null)=166`、`confirmed(needs_review=False)=167`、`pending=32`（≥16 达标，后续生成可被 RAG 召回）。
  ⇒ **至此本批改动在 prod 已「进镜像 + 生效」双确认。**
