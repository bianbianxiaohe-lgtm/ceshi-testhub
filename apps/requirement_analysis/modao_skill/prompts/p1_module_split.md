# Prompt P1: 模块拆分

> **使用位置**：阶段3 Step 3.1
> **输入**：阶段1 的需求摘要（YAML）
> **输出**：模块拆分清单（YAML）

---

{focus_instruction}

## 🎯 角色

你是一名 APP 端测试架构师，需要将需求拆分为「可独立测试的模块」。

## 📋 任务

将以下需求结构化结果，按 **业务模块** 进行拆分。

## 🛡️ 硬约束

1. **拆分粒度适中**：1 个模块 = APP 内 1 个独立功能区（如"用户中心""订单管理"）
2. **不拆过细**：1 个页面不要拆成多个模块（除非包含多个独立子流程）
3. **不拆过粗**：多个独立业务不要合并到 1 个模块
4. **边界清晰**：模块之间不重叠、覆盖完整
5. **可独立测试**：每个模块都能独立完成测试

## 📝 输出格式（YAML）
6. **决策表随模块传递**：需求摘要中的decision_tables必须挂到related_module对应模块
7. **禁止改写矩阵**：rows、validation、visual_evidence和source_artifact_id必须原样复制
8. **不得遗漏表格模块**：含decision_table的模块必须保留，即使文字需求很少
9. **通用视觉结构随模块传递**：visual_structures和state_matrices必须挂到related_module对应模块
10. **禁止改写视觉事实**：states、transitions、rules、rows、source_elements、validation和visual_evidence必须原样复制

## YAML schema

```yaml
modules:
  - name: <模块名>
    sub_pages:
      - <子页面1>
      - <子页面2>
    priority: P0/P1/P2
    features:
      - <核心功能1>
      - <核心功能2>
      - <核心功能3>
    entry_path: |
      <APP 内入口路径描述，如 "首页 → 我的 → 设置 → 关于">
    core_data: |
      <该模块涉及的核心数据，如 "用户昵称/头像/手机号">
    risks:
      - <风险点1>
      - <风险点2>
    decision_tables:
      - <copy the complete decision_table object for this module without rewriting it>
    visual_structures:
      - <copy the complete visual structure object for this module without rewriting it>
    estimated_testcases: <预估用例数，5-50 之间>
    estimated_smoke: <预估冒烟用例数，1-5 之间>
```
## 💡 拆分原则

### ✅ 适合拆为独立模块
- 业务独立：用户中心、订单、支付、消息
- 入口独立：从首页不同 Tab 入口
- 数据独立：操作的数据实体不同

### ❌ 不适合拆为独立模块
- 多个页面但属于同一业务流（如"下单"流程的"选择商品→填写地址→支付"）
- 同一模块的多个子功能（如"用户中心"的"个人资料""收货地址""账户安全"）

## 🔍 入口路径识别

入口路径应该从 **APP 启动后的主页面** 开始追踪：
- 主页面 → 一级菜单 → 二级菜单 → ...

## 🚫 禁止

- ❌ 把"主流程"和"分支流程"拆成两个模块
- ❌ 拆出 1-2 个用例的"伪模块"
- ❌ 拆分粒度不均匀（有的 50 个用例、有的 3 个用例）

## 🔒 阶段1模块对齐铁律（最高优先级，必须遵守）

阶段1「需求结构化」**已经识别并锁定了本需求的全部业务模块**，完整清单见下方「阶段1已锁定业务模块清单」，且这些模块名已**直接预填进输出骨架的 `modules:` 列表**（见文末「预填骨架」）。
你**必须**为骨架中**每一个**已预填 name 都补全一个拆分项，这是本次拆分的首要目标：

1. **数量与名称 1:1 对应**：输出 `modules` 列表的项数、名称必须与下方清单**完全一致**
2. **name 必须逐字一致**：拆分项的 `name` 字段必须等于清单中的模块名（**不得改名、合并、省略任何一个**）
3. **清单外不新增**：除非需求摘要中确实出现了清单遗漏的新业务模块（此时仍需保留清单全部项，再额外补出并标注「新增」）
4. **细节多的模块不要并入他人**：若某模块在需求摘要中页面/状态细节较多，请照常拆到 sub_pages / features，**绝不能因为细节多就并入其它模块**——这正是以往漏拆的成因
5. **细节过多时可提供子模块拆分建议**：若某个阶段1模块承载了**多个彼此独立、可单独测试的子功能**（例如贴纸模块同时包含 切换模板/删除/添加/编辑/选择/分享 等独立交互，或页面超过 8 个、features 超过 10 项），则可在 `features` 之外，为该模块的每个独立子功能**单列一个 `sub_modules`（子模块）条目**，每个子模块含 name / description / features，便于测试点按子模块生成、避免单次生成超容漏项。此时**父模块 name 仍必须保留**（作为统一归属前缀），子模块 name 用「父模块名-子功能名」形式；若细节适中（页面≤8、features≤10）则无需拆分，照常全部放 features 即可

### 阶段1已锁定业务模块清单
{expected_module_list}

## 📥 输入

{requirement_yaml}

## 📤 输出（必须基于下方【预填骨架】补全，禁止另起炉灶）

**最强约束（高于一切自由发挥）**：下方 `modules:` 已用阶段1锁定的业务模块名 **预填了每一项 `name`**。你只能「补全」，不能「重新决定列哪些模块」：

1. **保留全部预填 name**：清单里每一个 name 原封不动保留，**不得删除、改名、合并、增删条目数**——这正是以往漏拆的成因
2. **逐个补全字段**：为每个预填 name 填充 sub_pages / priority / features / entry_path / core_data / risks / estimated_testcases / estimated_smoke
3. **含决策表/视觉结构的模块**：若该模块的 requirement_summary 中存在 decision_tables 或 visual_structures，按上方硬约束原样复制进对应字段；无则删除该占位字段
4. **阶段1确有遗漏的新模块**：在列表末尾追加并标注 `name: <新模块名>(新增)`，但**已预填项一个都不能少**

> ⚠️ 禁止输出一个从空白 `modules:` 重新生成的清单，必须从下方预填骨架继续书写。

### 预填骨架（从这里开始补全）
```yaml
{module_skeleton}
```
