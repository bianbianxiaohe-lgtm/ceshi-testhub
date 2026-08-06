# 阶段 1：需求通读

> **目标**：把需求文档结构化为「需求摘要」，作为后续所有阶段的事实基础
> **输入**：用户提供的需求正文 / 文档
> **输出**：`output/requirement_summary.md`

---

## 🔴 阶段1 强制规则

1. **必须通读完整需求**：禁止只读部分需求就生成摘要
2. **禁止猜测**：原文中没有的内容，必须标注"原文未提及"或归入"待澄清"
3. **保留原文术语**：术语表必须使用需求文档中的原词
4. **等待用户确认**：摘要生成后必须 ⏸️ 等待用户回复「确认」才能进入阶段2

---

## 📋 执行步骤

### Step 1.1：载入需求

读取用户提供的需求正文 / 文档内容。

- 若是粘贴文本 → 直接处理
- 若是文件附件 → 读取文件内容
- 若是 .docx → 提示用户「请将 .docx 内容复制粘贴为文本」

### Step 1.2：调 prompt 结构化

读取并执行 `prompts/p0_requirement_struct.md`，将需求转换为以下结构：

```yaml
version: <版本号>
source: <需求来源>
modules:
  - name: <模块名>
    priority: <P0/P1/P2>
    change_type: <新增/修改/优化>
    description: <一句话描述>
business_flow: <关键业务流程>
risks: <风险点>
glossary:
  - term: <术语>
    definition: <解释>
```

### Step 1.3：填充模板

读取 `templates/requirement_summary.md`，将 Step 1.2 的结构化结果填入模板，生成 `output/requirement_summary.md`。

### Step 1.4：保存并更新状态

执行 `tools/state_manager.py save --stage 1 --output output/requirement_summary.md`：

```python
# state/workflow_state.json 更新内容
{
  "current_stage": 1,
  "stages_completed": [],
  "stage_outputs": {
    "stage1": "output/requirement_summary.md"
  },
  "user_confirmations": {
    "stage1_confirmed": false
  }
}
```

### Step 1.5：⏸️ 引导用户确认

输出格式：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 阶段1 完成：需求摘要已生成
📄 产物：output/requirement_summary.md

📌 核心发现：
- 涉及 {N} 个模块：{module_list}
- 优先级分布：P0={p0_count} / P1={p1_count} / P2={p2_count}
- 识别出 {N} 个潜在模糊点

💡 请确认：
1. 摘要是否覆盖完整需求？
2. 模块划分是否合理？
3. 是否有遗漏的内容？

确认无误后请回复「确认」，将进入阶段2：需求澄清。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## ⛔ 阶段1 终止锚点

**Agent 必须在输出 Step 1.5 引导语后立即停止，等待用户回复。**

❌ 禁止：
- 在用户未确认时直接进入阶段2
- 自行判断"摘要看起来 OK"就推进
- 修改 / 优化 / 补充摘要内容而未告知用户
