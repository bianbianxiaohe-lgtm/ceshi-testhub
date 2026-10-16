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

## 八、待验证：新提示词对覆盖率的实际提升（用户决定延后，2026-10-13）

> 现在跑覆盖率**只能验证判定侧**（输入 600 字 + 温度 0），**验证不了生成质量**——
> 提示词只影响「新生成的用例」，对 report#29 那 266 条已有用例无效。
> 故等下一个版本用新提示词生成用例、测试执行完成后再跑。到期按本节清单执行。

### 触发条件（满足才跑）
1. 新版本用例**确实由新提示词生成**（见下方「前置确认」）；
2. 该版本测试执行完成，禅道已有对应 bug 数据。

### 前置确认：这批用例是不是新提示词生成的

```powershell
docker cp scripts\_verify_prompt_sync.py <容器>:/tmp/
docker exec <容器> python /tmp/_verify_prompt_sync.py
docker exec <容器> cat /tmp/_verify_prompt_sync.txt
```

判据：末尾必须是 **`RESULT=SYNCED`**，且

| 类型 | 期望 |
|---|---|
| writer | `SYNCED`，text-md5=`B929122F`、bin-md5=`ABFDD854`、len=3089，**5 个 feature 全 OK** |
| reviewer | `SYNCED`，text-md5=`49A6BD79`、bin-md5=`FAF9D37D`、len=1012，**5 个 feature 全 OK** |
| analyzer | `CUSTOM`（1466 字符定制版，与文件不同属**预期**），**不是** MISMATCH |

⚠️ **不要用 `updated_at` 判断同步时间**：`update_prompt_configs.py` 用
`obj.save(update_fields=['content'])`，`auto_now` 的 `updated_at` **不会被刷新**
（实测 writer 仍显示 `2026-08-10`）。同步与否**只能看 md5**。

⚠️ **长度对 ≠ 内容对**：判同步必须比 md5（本脚本同时给 text-md5 与 bin-md5；
两者可能不同，因为 Python 文本模式读会把 `\r\n` 归一为 `\n`，
两侧同口径比对即可；bin-md5 用于和镜像固化期望值交叉核对）。

### 执行
1. 前端/接口对新版本执行一次 `run_coverage_analysis`；
2. 导出该报告的判定明细（`_cov_check.py` 同款脚本），统计下列指标。

### 判据（⚠️ 跨版本不要只比覆盖率数字）
> bug 集不同、功能范围不同 ⇒ 21.9% → 30% 这种直接对比**没有意义**。看下面三个归一化指标：

| 指标 | report#29 基线 | 期望 |
|---|---|---|
| 假覆盖剔除率（LLM 初判覆盖 → 复核剔除） | 18/34 ≈ **53%** | **明显下降**（对应 4.4「预期结果必须可判伪」生效） |
| 未覆盖 bug 归因分布：功能域缺失 + 同域变体 的占比 | 约 40/57 ≈ **70%** | **下降**（对应 4.1/4.2/4.3 生效） |
| 判定稳定性：同一批用例连跑两次覆盖率差值 | 28.8% ↔ 21.9% = **6.9 个百分点** | **< 3 个百分点**（对应温度 0 + 600 字输入生效） |

### 结论记录
跑完把三项指标回填到本节，并同步 `.codebuddy/memory/` 当日日志；
若指标未改善，回到第一/二节按「根因 → prompt 章节」重新定位，不要在数字上反复纠结。

## 九、提示词同步验证（2026-10-13，内容级比对，prod 实测）

> 第七节只证明了「提示词文件进了镜像」。本节回答另一个问题：
> **运行期实际读的是 DB 的 `PromptConfig`（FK `writer_prompt_config` / `reviewer_prompt_config`），
> 那 DB 里的内容是不是也是新的？**

- 方法：`scripts/_verify_prompt_sync.py`（容器内执行，结果自写 `/tmp/_verify_prompt_sync.txt`）
  —— 逐类型比对「提示词文件 md5」vs「DB content md5」，并校验 2026-10-13 新增章节锚点串是否真在 DB content 里。
- 实测：**`RESULT=SYNCED`**

| 类型 | 结果 | 文件 text-md5 | 文件 bin-md5 | DB md5 | len | 锚点串 |
|---|---|---|---|---|---|---|
| writer | **SYNCED** | B929122F | ABFDD854 | B929122F | 3089 | 4.1/4.2/4.3/4.4/4.5 **全 OK** |
| reviewer | **SYNCED** | 49A6BD79 | FAF9D37D | 49A6BD79 | 1012 | 5 项**全 OK** |
| analyzer | **CUSTOM**（预期差异） | ED8D7DE0 | 6B066165 | 6DD95D9B | DB 1466 / 文件 1959 | — |

- 交叉印证：`writer bin-md5=ABFDD854`、`reviewer bin-md5=FAF9D37D`
  **与第七节 STEP5 镜像固化期望值完全一致** ⇒ 「镜像内文件」与「DB 内容」两条链对上了同一个字节内容。
- 生成任务实际引用：`TestCaseGenerationTask` 最近 5 条（id=179/180/181/184/185）
  `writer_fk=1`、`reviewer_fk=2` ⇒ 指向的正是上面这两条 SYNCED 记录，**运行链路打通**。

### 本次踩到的两个坑（已写进脚本注释 / 第八节判据）
1. ⚠️ **`updated_at` 不能当同步判据**：`update_prompt_configs.py` 用 `save(update_fields=['content'])`，
   `auto_now` 的 `updated_at` 不刷新 ⇒ writer 至今显示 `2026-08-10`。
   第八节原写「`updated_at > 2026-10-13`」是**错误判据**（会误判没同步），已改为 md5 判据。
2. ⚠️ **锚点串必须抄自文件真实文本**：第一版凭印象写了「同域变体」，
   而提示词里 4.1 实际叫「同一操作的**重复 / 再进入**变体」、4.3 叫「**状态迁移与权益边界**」
   ⇒ 误报 MISSING。属于未验证假设，改取文件原文后 5/5 全 OK。

### 结论
**提示词同步已确认**：文件 → 镜像 → DB → 生成任务 FK，四环一致。
剩下唯一未验证的是「新提示词生成的用例，覆盖率是否真的提升」（第八节，挂起中）。

## 十、墨刀线纳入覆盖率提升（2026-10-13，用户要求「酌情调整」）

### 三条线边界（代码级核查，勿凭印象）
| 能力 | 独立线(AI生产线) | 墨刀线 | 共用 |
|---|---|---|---|
| 生成提示词 | `independent_skill/prompts/tester*.md` → **PromptConfig(DB)** | `modao_skill/prompts/p0~p8_*.md`，**不读 PromptConfig** | ❌ 分离 |
| 知识库 RAG | `ai_model_service.py:2150` | `modao_workflow.py:1766/1770` `_kb_suffix()` | ✅ |
| 禅道覆盖率判定 | `zentao/services.py:1928`；用例取 **`apps.testcases.TestCase`（用例库）**，`_get_case_pool()` 按 version/project，**不区分来源** | 同左 | ✅ |

### 实证：墨刀线**同样存在**断言不可判伪问题
- report#29 用例池 266 条，**63 条（23.7%）**命中「页面展示正常 / 显示正确 / 恢复正常状态」等不可判伪断言。
- 抽样 5 条里出现「各选项图标与文案展示正确，**无白屏/破图/资源缺失**」——
  与墨刀线 `p3_case_gen.md:24` / `p2_testpoint_gen.md:26` 的原文**逐字一致** ⇒ 该批用例受墨刀线提示词影响（强提示，非铁证，见下）。
- 根因是提示词**允许**把视觉兜底句当完整预期结果，与独立线 4.4 的教训同源。

### 已改（墨刀线提示词，仅本地文件，未同步容器）
- `p3_case_gen.md`
  - 硬约束 6「视觉细节收敛」：保留"不做像素/取色比对"，新增 **「兜底句不得单独成条」**，要求每条至少 1 个功能级可观测断言。
  - 预期结果编写规范：新增 ❌ 禁止项（页面展示正常 / 恢复正常状态 / 展示正确）。
  - 新增硬约束 8「历史缺陷高发维度」：① 再次执行 ② 刷新与回撤 ③ 权益边界。
- `p2_testpoint_gen.md`
  - 硬约束 7「视觉细节收敛」：同步加兜底句限制，并要求 `pass_criteria` 给出功能级判据。
  - 新增硬约束 9「历史缺陷高发维度」：① 再次执行（**扩展到非交易类功能**）② 刷新与回撤 ③ 权益边界 ④ 中断恢复。

⚠️ **刻意保留的差异（勿跨线统一）**：墨刀线**仍禁止**像素尺寸/取色比对类用例（原型驱动无法得知精确色值，此约束合理）。
只要求"兜底句不能单独成条"，**不是**照抄独立线 4.4 的"颜色/位置/尺寸"断言。

### ⚠️ P0 未决：无法按线拆分统计覆盖率
- `TestCase.source` 仅 `ai/manual/unknown`；两条线入库**都写 `source='ai'`**
  （`modao_views.py:407/518/1350`、`views.py:2511/2661/2771`）。
- `feature_modules`、`tags`、作者**均无法区分线**（两条线都会关联 feature_modules；墨刀 tags 只有「冒烟」）。
- ⇒ **第八节的三个基线（53% / 70% / 6.9pp）实为两条线混合口径**。
  同口径纵向对比仍然有效，但**改任一条线都无法归因**。
- 若要分线度量：给 `TestCase` 加 `generated_by`（independent/modao/manual）字段 + 迁移 + `docker_start.py` 幂等 DDL + 两处入库写值。
  代价：**历史用例无法回填**，只能对新生成的用例生效。
- ⇒ 需用户决策是否做（涉及 DB schema 变更，未擅自执行）。

### 落地待办
1. ~~同步到 dev 容器~~ ✅ 2026-10-13 完成，运行期校验 `RESULT=SYNCED`（详见下节）。
   ⏸ 待人工：跑一次墨刀线生成，看新用例断言是否具体化。
2. ⏸ 确认有效后再同步 prod 并 `rebuild_prod_backend.ps1` 固化
   （墨刀提示词是**文件**、不进 PromptConfig，只需文件进镜像；**prod 非 bind mount，必须 rebuild 否则重建容器即回退**）。
3. 第八节验证时注明「混合口径」，若做了 P0 字段则按线分别统计。

## 十一、墨刀线提示词同步 dev 验证（2026-10-13 实测）

### ⭐⭐ 本次发现的关键坑：墨刀线提示词有**模块级内存缓存**，改文件必须 restart
`apps/requirement_analysis/modao_prompts.py:14` 有一个 `_CACHE = {}`，
`get_prompt()` 命中后**不再读盘**：

```python
_CACHE = {}
def get_prompt(name):
    if name not in _CACHE:
        with open(path, 'r', encoding='utf-8') as f:
            _CACHE[name] = f.read()      # ← 只在首次读，之后一直用旧的
    return _CACHE[name]
```

⇒ **只更新文件不 restart = 静默用旧提示词，且不报错**（典型"改了没生效"陷阱）。
墨刀线提示词不进 `PromptConfig`，所以 §九 的 `_verify_prompt_sync.py` **管不到这条线**，
必须用本节的脚本单独验。

### 验证脚本（可复用）
`scripts/_verify_modao_prompts.py`（dev 的 `apps`/`scripts` 已 bind mount，可直接跑）：

```powershell
docker exec testhub-dev-backend-1 python /app/scripts/_verify_modao_prompts.py
docker exec testhub-dev-backend-1 cat /tmp/_verify_modao_prompts.txt
```

判据：末尾 `RESULT=SYNCED`，且
- `file bin-md5` 命中期望值（p2 `C3F0F278…` / p3 `4D600982…`）
- `cache text-md5 == file text-md5` ⇒ 标 `OK(缓存已刷新)`；若显示 `STALE` 说明**忘了 restart**
- 两个文件的 feature 锚点全 OK，旧兜底句 `无白屏/破图/资源缺失即可` 为 `REMOVED`

⚠️ 脚本刻意**调用 `get_prompt()` 而非直接读盘**——只有这样才能证明"跑生成时读到的就是新提示词"。

### 实测结果（`RESULT=SYNCED`）
| 文件 | 文件 bin-md5 | 缓存 text-md5 vs 文件 text-md5 | 锚点 | 旧句 |
|---|---|---|---|---|
| p2_testpoint_gen | `C3F0F278…` OK | `6E6AF46F…` 一致 ⇒ OK(缓存已刷新) | 7 项全 OK | REMOVED |
| p3_case_gen | `4D600982…` OK | `FE26202F…` 一致 ⇒ OK(缓存已刷新) | 6 项全 OK | REMOVED |

### 双口径 md5 坑（第二次踩，已写进脚本注释）
（见上节末；本节的对比实验在其之后进行）
`EXPECT` 用 `Get-FileHash`（**原始字节**口径），而 `get_prompt()` 走 Python 文本模式会把
`\r\n` 归一为 `\n` ⇒ 两个口径**必然不同**，拿错口径比对会 100% 误报 MISMATCH。
**正确做法**：文件按 bin 口径比对期望值；缓存按 text 口径与「文件 text 口径」比对。
（与 §九 `_verify_prompt_sync.py` 同一个坑，凡"文本 md5 vs 文件 md5"都要先想口径。）

## 十二、墨刀线新旧提示词对比实验（2026-10-13，dev 实测）

### 实验设计（关键：同输入、可归因）
- 对象：`proto=65`（Boddi2.3.0）/ `page=722`（P6 升级付费-Android），画布级。
- 手法：`modao_design` + `modao_generate_cases` **都传 `page_ids=[722]`**。
  画布级独立运行会**放宽人工确认闸门**且产物写在 **page 级**（`page_testpoints_json` /
  `page_testcases_json`），不覆盖 proto 级其他数据 ⇒ 可与旧产物并存对比。
- **基准成立的依据**（不是拍脑袋）：
  `p2_testpoint_gen.md` / `p3_case_gen.md` 最近一次提交是 **`cbcf4f8`（2026-08-26 15:30）**，
  之后未改（本次改动仍在工作区）；而 proto65 的产物时间是 **2026-09-07**
  ⇒ 旧产物用的正是 2026-08-26 那一版提示词，**归因干净**。
- 备份：BEFORE/AFTER 两份快照在 `tmp/modao_rerun_20261013/_dump_modao_{before,after}.json`，可回滚。

### 结果
| 指标 | 旧提示词 | 新提示词 | 变化 |
|---|---|---|---|
| 用例条数 | 8 | 11 | +3 |
| **不可判伪断言占比** | **62.5%** | **18.2%** | **−44.3 个百分点** ✅ |
| 含功能级可观测断言 | 75.0%（6/8） | 72.7%（**8/11**） | 比例略降、**绝对数 +2** |
| ① 再次执行 | 3 | 3 | 持平（但质量提升，见下） |
| ② 刷新与回撤 | 2 | 3 | +1 |
| ③ 权益边界 | 3 | 5 | +2 |
| ④ 中断恢复 | 0 | 1 | +1 |

**核心目标达成**：本次改的首要目的（断言不可判伪 ⇒ Bug 存在时也通过）从 62.5% 降到 18.2%。

⚠️ **①「再次执行」持平不是没生效**：旧版是「连续快速充值两次仅展示一个弹窗」，
新版是「支付回调延迟与**重复回调**时弹窗触发次数正确」——更贴近真实幂等缺陷，**质量提升而非数量增加**。

新增场景（旧版没有）：弱网支付超时后客户端/服务器状态一致、多设备同时登录数据同步、
价格滚动动画未结束时的用户交互。这些正是历史高发维度。

### 本次踩到的三个坑（都已写进脚本注释）
1. ⚠️ **`call_openai_compatible_api` 是 async**：不 await 直接调用只得到协程对象，
   `str()` 出来是 `'<coroutine object ...>'` ⇒ 会把「根本没测」误报成「调用成功」。
   预检脚本已改为 `inspect.iscoroutine()` + `asyncio.run()`，并对 `coroutine object` 字样兜底判无效。
2. ⚠️ **轮询不能用 `page.stage_status` 判断本轮是否跑完**：画布级 `current_stage/stage_status`
   是**上一轮遗留**的（这里仍是 9-07 那轮的 stage=4/done），新一轮启动后不会立刻变
   ⇒ 一进循环就误判 FINISHED。正确判据：**`proto.status` 离开 `designing`**
   **且 `page.work_log` 长度发生变化**（work_log 每步追加时间戳，是最可靠的信号）。
3. ⚠️ **维度覆盖关键词不能用固定短语**：第一版写「重新生成/再次提交/重复打开」，
   漏掉了真实存在的「**重复回调**」⇒ 误判 ①=0。改为「重复/再次/二次/连续/幂等」等字根后，
   ① 实际为 3。**自动化统计必须用标题列表人工交叉验证**（`_list_modao_titles.py`）。

### 局限（不要过度外推）
- 样本 = **1 个画布、8→11 条用例**，只证明「方向正确」，不能当总体结论。
- 未验证覆盖率是否提升（那要在禅道跑覆盖率分析，属第八节）。
- dev 上 proto65 的产物现已被新提示词覆盖；如需还原，用 BEFORE 快照回滚。

### 新增脚本（均在 `scripts/`，dev 可直接跑，`scripts` 已 bind mount）
`_find_modao_candidate.py`（挑候选画布）、`_precheck_modao_rerun.py`（跑前预检+LLM 连通）、
`_dump_modao_page.py`（BEFORE/AFTER 快照）、`_poll_modao_page.py`（进度轮询）、
`_compare_modao_cases.py`（质量对比）、`_list_modao_titles.py`（标题列表，人工交叉验证）、
`_modao_rerun.ps1`（触发；⚠️ 实际更推荐 curl + 文件传 body，见下）。

⚠️ **PowerShell 调 API 的两个坑**：① 内联 JSON body 的双引号会被 PS 转义破坏
（报 `JSON parse error ... column 2`）⇒ 改**写文件 + `--data-binary "@file"`**；
② `@file` 会被 PS 当 splatting 运算符 ⇒ 必须加引号写成 `"@file"`。
（另：`Invoke-RestMethod` 在本机单次执行卡到 300s 超时，改用 `curl.exe --max-time` 更稳。）

## 十三、墨刀线提示词同步生产（2026-10-14 固化完成）

### 结果：`RESULT=SYNCED`，生产镜像已固化
脚本 `scripts/rebuild_prod_backend.ps1` 全流程跑通（09:04:53 → 09:06:22，**仅 1.5 分钟**）：

| 步骤 | 结果 |
|---|---|
| STEP1 备份 | 容器内 `/tmp/rollback_20261014_0904/apps.tar.gz` + mysqldump → `_db_backup/testhub_20261014_0904.sql` |
| STEP2 build | exit=0，**7 秒**（base 镜像 `testhub-backend-base:20261010` 命中，只重跑 COPY 层） |
| STEP3 重建 | `rm -f` + `up -d` 成功 |
| STEP4 健康 | `/api/` = **404**（健康）；chromium 存在 |
| STEP5 md5 | **7 个文件全部 `MD5 OK`**（含新增的 p2/p3） |
| STEP6 运行期 | `RESULT=SYNCED`，`cache text-md5 == file text-md5` ⇒ `OK(缓存已刷新)` |

### 同步前后对照（生产容器）
| 判据 | 同步前 | 同步后 |
|---|---|---|
| p2 md5 | `a0967bbf…` | `c3f0f278…` ✅ |
| p3 md5 | `0a0c496a…` | `4d600982…` ✅ |
| `历史缺陷高发维度` 命中 | 0 / 0 | **1 / 1** ✅ |
| 旧兜底句 `无白屏/破图/资源缺失即可` | 1 / 1 | **0 / 0**（REMOVED）✅ |

### 本次顺带固化了两处（避免问题复现）
1. ⚠️ **`.dockerignore` 缺 `tmp/`**：只有 `tmp_*` 匹配不到 `tmp/` 目录
   ⇒ 本次 205KB 的 before/after 快照（**含真实用例内容**）本会被 `COPY . .` 打进生产镜像。
   已补 `tmp/` 与 `/_*.txt`（根目录诊断产物已累积 100+ 个，同样会进镜像）。
2. ⚠️ **rebuild 脚本结束语硬编码 "all 5 md5 match"**：把期望表扩到 7 条后数字就失真。
   已改为 `$($Expect.Count)` 动态推导，并写进注释。

### 提交
- `d010887` improve(modao)：提示词改动 + 端到端验证流水线
- `4308a87` fix(rebuild)：md5 结束语动态化

### 仍待人工
- 生产上跑一次墨刀生成，肉眼确认断言是否具体化（dev 已验证 62.5%→18.2%，
  生产模型/数据不同，结论**不可直接外推**）。
