# AI + Midscene APP UI 自动化测试方案（设计说明）

> 范围：在 TestHub 的 `ui_automation` 模块新增 Midscene 驱动引擎，打通「AI 生成用例 → Midscene 真机执行」。
> 本文只定义**数据模型与执行契约**，不绑定任何具体业务（电商仅为可选示例，不作为默认语义）。

## 1. 设计原则（来自落地实战，已抽象为通用规则）

1. **代码负责流程控制，Prompt 负责业务动作**：用例由多个「业务动作步骤」组成，步骤顺序由代码编排，单个步骤内的页面理解交给视觉模型。
2. **不把整条链路一次性交给一个 Prompt**：每条用例拆成多个 `steps`，每步只完成一个明确业务动作，便于失败定位与复用。
3. **业务锚点（上下文传递）**：步骤可通过 `extract` 从页面提取任意结构化业务数据，存入执行上下文，后续步骤用 `${{key}}` 引用。**key 是调用方自定义的占位符，框架不预置任何业务语义**（不叫"商品锚点"）。
4. **确定性操作走 Instant Action**：目标明确时优先 `aiTap` / `aiInput`，需理解页面语义时才用 `aiAct` / `aiQuery`。
5. **模型配置不写死在代码**：视觉模型统一走 `AIModelConfig`（role=`midscene_vision`），Key/Endpoint 来自库配置或环境变量，不进仓库。
6. **可观测**：每步记录「识别到的页面 / 执行的操作 / 失败时的真实状态」，复用 Allure + 执行日志记录。

## 2. 步骤模型（核心契约，业务无关）

`AICase.steps` 为 JSON 数组，每步结构：

```json
{
  "name": "步骤的人类可读名称（任意业务，如『进入列表页』『提交表单』）",
  "action": "aiAct | aiQuery | aiTap | aiInput | assert | wait | launch | back",
  "prompt": "自然语言业务动作描述（给视觉模型的指令）",
  "value": "当 action=aiInput 时的输入文本，支持 ${{key}} 模板替换",
  "selector_hint": "可选：确定性操作的弱提示（如『确认按钮』），用于 Instant Action",
  "extract": [
    {
      "key": "调用方自定义的上下文变量名",
      "prompt": "从当前页面提取该数据的自然语言指令",
      "type": "string | number | boolean | json",
      "required": true
    }
  ],
  "assert": {
    "prompt": "校验当前页面状态的指令（可选）",
    "expect": "期望结论的自然语言描述"
  },
  "wait_ms": 0
}
```

### 上下文变量规则

- 执行期内维护一个 `context: dict`，`extract[].key` 全局唯一。
- 后续步骤的 `prompt` / `value` / `assert.prompt` 中出现 `${{key}}` 时，执行引擎在调用模型前替换为上下文中的实际值。
- `extract` 执行时机：本步 `action` 完成后、进入 `assert` 前，调用一次 `aiQuery` 提取并写入 `context`。
- `required=true` 且提取失败时，该步标记为失败并记录原始页面状态。

### 为什么不会误导其他应用

`extract` 的 `key` / `prompt` / `type` 全部由用例设计者填写，框架只做「调用 aiQuery → 按 type 解析 → 存 context → 模板替换」。
框架层不出现"商品/订单/购物车"等任何业务词；电商主链路仅作为 `docs` 中的**可选示例用例 JSON**，不作为模型默认或代码语义。

## 3. 模型扩展

### AICase
- 新增 `execution_mode` 字段：`text`（原 browser-use）| `midscene`（新增）。
- 新增 `steps` JSONField：Midscene 模式下的结构化步骤；`text` 模式可留空（沿用 `task_description`）。
- 新增 `app_config` / `device` 外键（midscene 模式必填，指向 `AppConfig` / `AppDevice`）。

### AIExecutionRecord
- `execution_mode` choices 增加 `midscene`。
- `steps_completed` 记录每步的 `action` / `prompt` / `extract_result` / `assert_result` / 截图，支撑可观测。

### AIModelConfig
- `role` choices 增加 `midscene_vision`（视觉驱动模型）。
- 字段复用现有 `base_url` / `api_key` / `model_name` / `model_family` / `temperature`。

## 4. 执行引擎（midscene_engine.py）

- 输入：`AICase`（midscene 模式）+ `AppConfig`（包名/activity）+ `AppDevice`（udid / adb_host）。
- 设备连接：Android 走 ADB（`adb_host` 指向手机所在电脑的 `IP:5037`，如 `192.168.8.71:5037`），经 `@midscene/android` 驱动真机。
- 每步：解析 `${{key}}` → 调对应 Midscene API（`aiAct`/`aiTap`/`aiInput`/`aiQuery`）→ 执行 `extract` → 执行 `assert` → 写日志/截图。
- 输出：`AIExecutionRecord` + Allure 报告。

## 5. 阶段划分

- **阶段 1（本期）**：模型扩展 + `midscene_engine` 核心链路 + 中性示例用例跑通真机。
- **阶段 2**：Midscene Playground 前端调试面板；scrcpy 模糊补丁脚本（可脚本化，不污染 node_modules）。
- **阶段 3**：每步可观测报告增强。

## 6. 可选示例用例（电商，仅作 demo，非默认）

见 `docs/midscene_example_ecommerce.json`（独立文件，不在代码语义中）。证明业务锚点在电商链路可用，但不代表框架只支持电商。
