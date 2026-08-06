# 测试用例 - {module_name}

> **所属版本**：{version}
> **所属模块**：{module_name}
> **编写日期**：{date}
> **编写人**：{tester}

---

## 用例元数据

| 项目 | 内容 |
|------|------|
| 模块优先级 | {P0/P1/P2} |
| 用例总数 | {total_count} |
| P0 用例数 | {p0_count} |
| P1 用例数 | {p1_count} |
| P2 用例数 | {p2_count} |
| 是否含冒烟用例 | 是/否 |

---

## 一、功能测试用例

| 用例ID | 模块 | 标题 | 前置条件 | 步骤 | 预期结果 | 优先级 | 关联需求 | 用例类型 | 备注 |
|:--:|------|------|--------|------|--------|:--:|--------|:--:|------|
| TC_{module}_001 | {module} | {title} | {precondition} | 1.{step1}<br>2.{step2}<br>3.{step3} | {expected} | P0 | {req_id} | 功能 | |
| TC_{module}_002 | {module} | {title} | {precondition} | 1.{step1}<br>2.{step2} | {expected} | P1 | {req_id} | 功能 | |

## 二、边界与异常用例

| 用例ID | 标题 | 前置条件 | 步骤 | 预期结果 | 优先级 | 备注 |
|:--:|------|--------|------|--------|:--:|------|
| TC_{module}_E01 | {title} | {precondition} | 1.{step1}<br>2.{step2} | {expected} | P1 | 边界 |

## 三、UI/交互用例

| 用例ID | 标题 | 前置条件 | 步骤 | 预期结果 | 优先级 | 备注 |
|:--:|------|--------|------|--------|:--:|------|
| TC_{module}_U01 | {title} | {precondition} | 1.{step1} | {expected} | P2 | UI |

## 四、兼容性用例

| 用例ID | 标题 | 测试机型 | 步骤 | 预期结果 | 优先级 | 备注 |
|:--:|------|--------|------|--------|:--:|------|
| TC_{module}_C01 | {title} | {device} | 1.{step1} | {expected} | P2 | 兼容性 |

## 五、回归用例（适用时）

| 用例ID | 标题 | 关联历史版本 | 步骤 | 预期结果 | 优先级 |
|:--:|------|:--:|------|--------|:--:|
| TC_{module}_R01 | {title} | {history_version} | 1.{step1} | {expected} | P1 |

---

## 备注

{module_notes}
