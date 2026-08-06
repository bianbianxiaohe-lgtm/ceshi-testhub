# 阶段 3：用例设计（V1.1 增强版）

> **目标**：分模块设计测试用例 + 冒烟用例，输出 Markdown + Excel
> **输入**：阶段1 摘要 + 阶段2 澄清记录
> **输出**：
> - `output/module_split.md`
> - `output/testcases/{module}.md` × N
> - `output/testcases/smoke_testcases.md`
> - `output/testcases_all.xlsx`
> - `output/quality_report.json`（新增）
>
> **V1.1 增强**：在 p2 → p3 → p4 基础上，新增 p5（风险识别）/ p6（PCI 识别）/ p7（三路合并去重）/ p8（质量自检）四个增强能力

---

## 🔴 阶段3 强制规则

1. **必须按模块拆分**：1 个模块 = 1 个独立用例文件 / 1 个 Excel sheet
2. **冒烟用例必须独立**：从全量用例中按"入口可达性 + 核心展示"原则抽取
3. **P0 占比 ≤ 15%**：所有 P0 优先级用例数应控制在总用例数的 15% 以内
4. **冒烟数不能为 0**：若生成的冒烟用例数为 0，必须阻断并提示用户
5. **Excel 优先，Markdown 兜底**：openpyxl 可用时输出 Excel，否则降级为 Markdown
6. **🔴 增强能力必须执行**：p5/p6/p7/p8 是核心能力，不得跳过

---

## 📋 执行步骤

### Step 3.1：模块拆分

读取 `prompts/p1_module_split.md`，对需求摘要进行模块拆分：

输出模块列表（每个模块应独立可测）：

```yaml
modules:
  - name: <模块名>
    sub_pages: [<子页面/子模块>]
    priority: P0/P1/P2
    features: [<核心功能点>]
    entry_path: <APP 内入口路径>
    core_data: <核心数据>
    risks: [<风险点>]
```

填充 `templates/module_split.md` → `output/module_split.md`。

### Step 3.2：⏸️ 模块拆分确认

输出格式：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 阶段3.1 完成：模块拆分已生成
📄 产物：output/module_split.md

📌 拆分概览：
- 总模块数：{N}
- P0 模块：{p0_count} 个
- P1 模块：{p1_count} 个
- P2 模块：{p2_count} 个

模块列表：
1. {module_1}（P0，{feature_count} 个核心功能）
2. {module_2}（P1，{feature_count} 个核心功能）
3. ...

💡 请确认模块拆分是否合理？
确认后回复「确认」，将开始为每个模块生成测试用例。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 3.3：基础测试点生成（p2）

对每个模块，读取 `prompts/p2_testpoint_gen.md`，生成基础测试点清单（draft）：

```yaml
module: {module_name}
test_points:
  - id: TP_{module}_001
    title: <测试点标题>
    type: 功能/边界/异常/UI/兼容
    priority: P0/P1/P2
    description: <详细描述>
    is_smoke_candidate: true/false
```

**is_smoke_candidate 判定标准**：

| 满足以下任一条件 → true | 满足以下任一条件 → false |
|------|------|
| 涉及页面入口 | 涉及异常场景（无权限/为空/超时） |
| 涉及核心数据加载 | 涉及删除/禁用操作 |
| 涉及核心操作（提交/查询/导出） | 涉及次要字段验证 |
| 涉及主流程关键节点 | 涉及 UI 细节 |
| | 涉及边界值 |

### Step 3.3.5：🆕 风险点识别（p5 增强能力）

> **目的**：在基础测试点之上，从 5 大类风险角度扩展出补充测试点

读取 `prompts/p5_risk_identify.md`，对每个模块的 draft 测试点，识别 5 类风险（APP 端适配版）：

- **R1 需求风险**：需求描述模糊、规则覆盖不完整
- **R2 逻辑风险**：状态流转、并发、计算边界
- **R3 边界风险**：数值/字符/数量/时间边界
- **R4 集成风险**：外部服务/接口/跨端一致性
- **R5 数据风险**：数据准备/隔离/缓存/脱敏/大数据量

每个风险点必须：
1. 关联到具体测试点 ID（`related_testpoints`）
2. 扩展出至少 1 个补充测试点（`extended_test_points`）

输出：`output/risks/{module}_risks.json`

### Step 3.3.6：🆕 PCI 待确认问题识别（p6 增强能力）

> **目的**：在测试前识别需求中的模糊点，标记阻塞场景，提供恢复条件

读取 `prompts/p6_pci_identify.md`，对每个模块识别 5 类 PCI（与 stage2 互补）：

- **Q1 定义歧义**：同一概念多种解释
- **Q2 信息缺失**：需求中未提及
- **Q3 规则冲突**：两条规则矛盾
- **Q4 边界未定**：边界条件无明确数值
- **Q5 依赖不明**：外部依赖未确认

每个 PCI 必须：
1. 阻塞标记（`blocked_scenarios`：阻塞哪些测试点）
2. 恢复条件（`resolution_condition`：确认什么后解除阻塞）
3. 影响级别（`blocker` / `high` / `medium` / `low`）

**关键规则**：必须合并 stage2 已识别的模糊/缺失/边界问题，不得遗漏。

输出：`output/pci/{module}_pci.json`

### Step 3.3.7：🆕 三路合并去重（p7 增强能力）

> **目的**：将 draft（p2）+ risk（p5）+ pci（p6）三路测试点合并去重，输出最终带优先级的测试点

读取 `prompts/p7_merge_dedup.md`：

1. **合并三路输入**（source 字段标记来源）
2. **去重**（D1 完全相同 / D2 标点空白差异 / D3 同源同类）
3. **优先级继承**（风险上调 / PCI 阻塞 / P0 不可下调）
4. **P0 占比约束**（≤ 15%）
5. **description 丰富化**（≥ 80 字，含入口+操作+验证目标）

输出：`output/testpoints/{module}_final_testpoints.json`

### Step 3.4：测试用例生成（p3）

对合并去重后的每个最终测试点，读取 `prompts/p3_case_gen.md`，生成完整测试用例：

```yaml
testcase:
  id: TC_{module}_{seq}
  module: {module}
  title: <用例标题>
  precondition: <前置条件>
  steps:
    - <步骤1>
    - <步骤2>
  expected: <预期结果>
  priority: P0/P1/P2
  type: 功能/边界/异常/UI/兼容
  requirement_ref: <关联需求点>
  is_smoke: true/false
  notes: <备注>
```

填充 `templates/testcase_module.md` → `output/testcases/{module_name}.md`。

### Step 3.5：冒烟用例提取（p4）

读取 `prompts/p4_smoke_extract.md`，从全量测试点中筛选冒烟用例：

筛选规则：
- `is_smoke_candidate == true`
- 优先级 P0 或 P1
- 同一入口路径最多保留 1-2 个代表性用例
- 总数控制在 P0 的 10-15%

填充 `templates/smoke_testcase.md` → `output/testcases/smoke_testcases.md`。

**阻断检查**：若 `smoke_count == 0`：
```
❌ 阻断：未识别出任何冒烟用例
可能原因：
1. 需求文档质量极差，未识别出 P0 功能
2. 拆分模块过多，每个模块都太细

请人工补充冒烟用例，或调整模块拆分粒度。
```

### Step 3.6：🆕 质量自检（p8 增强能力）

> **目的**：对生成的测试用例进行 6 项质量门禁检查

读取 `prompts/p8_quality_check.md`，执行 C1-C6 检查：

| 检查项 | 类型 | 失败时动作 |
|------|------|------|
| **C1 字段完整性** | 🔴 阻断 | 返回 p3 修复缺失字段 |
| **C2 冒烟比例合规** | 🔴 阻断 | 返回 p4 重新提取 |
| **C3 P0 主流程覆盖** | 🔴 阻断 | 返回 p3 补充 main_flow |
| **C4 用例步骤具体性** | 🟡 WARNING | 记录但不阻断 |
| **C5 优先级分布合理性** | 🟡 WARNING | 记录但不阻断 |
| **C6 description 字数** | 🟡 WARNING | 记录但不阻断 |

输出：`output/quality_report.json`

**阻断逻辑**：
- C1/C2/C3 任一 FAIL → 必须修复后重跑，**禁止进入 Excel 导出**
- C4/C5/C6 WARNING → 可继续，但建议优化

### Step 3.7：Excel 导出

执行 `tools/module_exporter.py`：

```bash
python tools/module_exporter.py \
  --input output/testcases/ \
  --output output/testcases_all.xlsx \
  --smoke-file output/testcases/smoke_testcases.md
```

**Excel 结构**：
- Sheet 1：`总览` — 模块汇总、用例总数、P0/P1/P2 分布
- Sheet 2..N+1：每个模块一个 sheet，列：ID / 标题 / 前置 / 步骤 / 预期 / 优先级 / 类型 / 关联需求 / 冒烟
- Sheet N+2：`冒烟用例` — 冒烟用例清单
- Sheet N+3：`统计` — 数字

**降级处理**：
- 若 openpyxl 不可用 → 输出 `output/testcases_all.md`（合并所有模块）
- 降级时输出警告：`⚠️ openpyxl 不可用，已降级为 Markdown 输出`

### Step 3.8：⏸️ 阶段3 完成确认

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 阶段3 完成：用例设计已完成（V1.1 增强版）

📄 产物清单：
- output/module_split.md
- output/risks/{module}_risks.json  🆕
- output/pci/{module}_pci.json  🆕
- output/testpoints/{module}_final_testpoints.json  🆕
- output/testcases/{module1}.md
- output/testcases/{module2}.md
- ...
- output/testcases/smoke_testcases.md
- output/quality_report.json  🆕
- output/testcases_all.xlsx

📌 统计：
- 模块数：{N}
- draft 测试点：{draft_count}
- risk 扩展测试点：{risk_count}  🆕
- PCI 阻塞场景：{pci_count}  🆕
- 合并去重后测试点：{final_count}  🆕
- 用例总数：{total}
- P0：{p0}（占比 {p0_ratio}%）/ P1：{p1} / P2：{p2}
- 冒烟用例数：{smoke_count}（占 P0: {smoke_ratio}%）

🔍 质量门禁结果：  🆕
- C1 字段完整性：PASS/FAIL
- C2 冒烟比例：PASS/FAIL
- C3 P0 主流程覆盖：PASS/FAIL
- C4 步骤具体性：PASS/WARNING
- C5 优先级分布：PASS/WARNING
- C6 description 字数：PASS/WARNING
- 整体：{PASS/FAIL}

💡 请确认：
1. 各模块用例是否完整覆盖了需求？
2. 风险扩展测试点是否有遗漏场景？
3. PCI 阻塞场景是否需要先与产品确认？
4. 质量门禁是否通过？
5. Excel 文件是否可以正常打开？

确认后回复「确认」，将进入阶段4：冒烟执行。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## ⛔ 阶段3 终止锚点

**Agent 必须在输出 Step 3.8 引导语后立即停止，等待用户回复。**

❌ 禁止：
- 在用户未确认时进入阶段4
- 冒烟用例数为 0 仍继续
- C1/C2/C3 FAIL 时仍继续到阶段4
- Excel 失败时静默降级而不提示用户
- **跳过 p5/p6/p7/p8 任何一项增强能力**

---

## 📌 V1.1 增强能力说明

| 能力 | 来源 | 价值 | 工作量 |
|------|------|------|------|
| **p5 风险识别** | 原 P3 风险点识别（7类）→ 简化为 5 类（APP 端适配） | 提升用例覆盖率 30-50% | 每个模块 +1 轮 LLM |
| **p6 PCI 识别** | 原 P4 待确认问题（5类）→ 完整保留 | 减少与产品澄清的遗漏 | 每个模块 +1 轮 LLM |
| **p7 合并去重** | 原 P5 三路合并去重 → 完整保留 | 消除重复用例、规范优先级 | +1 轮 LLM |
| **p8 质量自检** | 原 P7 11 项 → 简化为 6 项 | 输出质量保障 | +1 轮 LLM |

**总工作量增加**：每模块 +4 轮 LLM（可并行）
**质量提升**：覆盖率 ↑30-50%，优先级一致性 ↑，输出稳定性 ↑↑
