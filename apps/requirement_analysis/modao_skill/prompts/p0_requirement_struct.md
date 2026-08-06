# Prompt P0: 忠实需求结构化（阶段1）

> **使用位置**：阶段1（通读需求并形成可追溯摘要）
> **输入**：原始需求文档
> **输出**：YAML 格式的结构化需求

---

## 🎯 角色

你是一名资深的 APP 端测试工程师，正在评审一份新版本的需求文档。

## 📋 任务

将以下需求文档，**结构化**为以下 YAML 输出。

## 🛡️ 硬约束

1. **事实优先，禁止虚构**：只把原文或页面标注明确表达的内容写成确定事实
2. **保留原文术语**：所有专有名词、模块名、字段名必须使用原文用词
3. **完整覆盖**：必须读完整个文档，禁止只读部分
4. **区分事实与建议**：原文未明确的信息必须标为 原文未提及，不得把常识或历史经验写成需求
5. **可追溯**：每个模块必须列出来源页面/章节；有原文时给出简短原文证据
6. **优先级不伪装成事实**：未明示时可建议 P0/P1/P2，但 priority_source 必须写 模型建议
7. **允许确实为空**：没有可靠证据时，问题清单输出空数组，不得为了凑数编造
8. **跨页面合并模块**：同一业务主题即使分布在多个页面，也只能输出一个模块，并合并来源页面与功能点
9. **页面不是模块**：不得因为页面标题不同就重复建模块；例如“限免修订”和“限免开关补充逻辑”应合并为一个限免模块
10. **证据必须逐字引用**：source_evidence 只能复制原始页面中连续出现的短句，不得改写、总结或拼接不连续内容
11. **逐条证据**：多条证据必须分别输出 page 和 quote，不得合成为一个看似原文的长句
12. **视觉结构优先**：输入包含visual_artifacts时，其rows/columns优先于打平OCR文本
13. **决策表不得概括替代**：必须逐行保留decision_table的全部原始组合，再单独归纳规则
14. **视觉可追溯**：decision_tables必须保留source_artifact_id、source_page、截图哈希和原始行号
15. **禁止修改单元格**：不得改变visual_artifacts中的条件、结果、行号和validation
16. **通用视觉结构不得丢失**：为每个结构输出visual_structure_links关联；完整结构由系统按source_artifact_id权威回填，禁止在模型输出中重复大段原文
17. **状态卡片按状态归并**：同一功能的多张状态卡片必须形成state_matrix，逐状态保留标题、副标题、计时、文案、展示条件和点击行为
18. **多标签允许**：同一区域可以同时形成互补结构，例如订阅页同时具有ui_screen、pricing_matrix和interaction_flow
19. **未知内容保留**：无法确认类型时保留unknown、raw_text、source_elements和截图证据，不得静默删除

## 📝 输出格式（YAML）

```yaml
version: <版本号，如 "V2.3.0"；若原文未提及则填 "未指定">
source: <需求来源，如 "产品PRD邮件"/"禅道 #123">；若原文未提及则填 "未指定"
requirement_overview: |
  <用 2-5 句话概括本版本的核心目标，必须来自原文>
version_goals:
  - <目标1，来自原文>
  - <目标2>
modules:
  - name: <模块名，使用原文用词>
    priority: P0  # P0=核心必测/P1=重要/P2=次要
    priority_source: 原文明示/模型建议
    source_locations:
      - <来源页面/章节/标注编号>
    source_evidence:
      - page: <第N页>
        quote: <从该页逐字复制的连续原文短句>
    priority_reason: <引用原文；若为模型建议，明确写出建议依据>
    change_type: 新增/修改/优化
    description: <一句话描述该模块的改动>
    key_features:
      - <核心功能1，来自原文>
      - <核心功能2>
decision_tables:
  - name: <决策表标题>
    related_module: <所属模块名>
    source_artifact_id: <visual_artifacts中的artifact_id>
    source_page: <第N页>
    preconditions: {}
    dimensions:
      - name: <输入维度字段>
        values: [<允许值>]
    result_fields: [<结果字段>]
    rows:
      - row_no: 1
        <维度字段>: <截图单元格原值>
        <结果字段>: <截图单元格原值>
    derived_rules:
      - condition: <仅基于rows归纳>
        result: <结果>
        source_rows: [1]
    validation: <原样复制visual_artifact.validation>
    visual_evidence: <原样复制visual_artifact.visual_evidence>
visual_structure_links:
  - source_artifact_id: <artifact_id>
    artifact_type: <通用视觉类型>
    name: <简短结构名称>
    related_module: <所属模块名>
    source_page: <第N页>
business_flow: |
  <描述关键业务流程，必须来自原文，包括流程节点>
risks:
  - <风险点1；必须明确标为原文风险或测试分析建议>
  - <风险点2>
glossary:
  - term: <术语原文>
    definition: <来自原文的解释>
ambiguous_points:
  - location: <原文位置，如 "第3页/标注2">
    evidence: <触发问题的原文；无直接原文则填 "未找到直接原文">
    issue: <问题描述>
    suggested_question: <建议向产品确认的具体问题>
    priority: 高/中/低
missing_points:
  - scenario: <完成当前明确流程所缺少的信息>
    basis: <为什么该信息是当前流程必需的>
    impact: <影响哪些模块>
boundary_points:
  - issue: <与现有功能的边界问题>
    evidence: <相关原文或 "未找到直接原文">
    impact: <影响范围>
```

## 🔍 P0/P1/P2 判定规则

- **P0（核心）**：核心业务主流程、关键入口、影响营收/合规
- **P1（重要）**：常用功能、影响体验但不阻塞主流程
- **P2（次要）**：UI 优化、提示文案、边角功能

## 🚫 禁止

- ❌ 编造原文没有的需求点
- ❌ 把推断、常识或知识库历史规则写成“本次原文明确要求”
- ❌ 同一业务主题按页面拆成多个重复模块
- ❌ 将多个页面的句子重新拼接后放进一对引号冒充原文
- ❌ source_evidence 使用模型总结、同义改写或原文中不存在的文字
- ❌ 为满足格式或数量要求强行生成问题
- ❌ 业务流写"详见原文"
- ❌ 原文没有优先级时伪造原文依据；此时必须标记 priority_source: 模型建议

## 📥 输入

{requirement_text}

## 📤 输出（直接输出 YAML，不要有其他解释）
