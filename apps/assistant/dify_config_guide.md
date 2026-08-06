# Dify Agent + Appium 工具配置指南

## 一、在 Dify 平台创建 HTTP 工具

进入 Dify → 工具 → 创建自定义工具 → 选择 `HTTP 工具`。

### 通用设置

| 参数 | 值 |
|------|-----|
| 请求地址 | `http://testhub-backend:8000/api/assistant/appium-tool/` |
| 请求方法 | `POST` |
| 请求头 | `Content-Type: application/json` |
| 认证 Header | `X-Internal-Key: testhub-appium-2026` |

### 工具列表（每个工具单独配置）

---

#### 工具 1: appium_click

**请求体（JSON）**:
```json
{
  "tool_name": "appium_click",
  "parameters": {
    "target": "{{target}}"
  }
}
```

**输入参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| target | string | 是 | 控件名称，如：月份标题、确认按钮、取消按钮、公历按钮 |

---

#### 工具 2: appium_swipe

**请求体**:
```json
{
  "tool_name": "appium_swipe",
  "parameters": {
    "wheel": "{{wheel}}",
    "direction": "{{direction}}",
    "times": {{times}}
  }
}
```

**输入参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| wheel | string | 是 | 滚轮名称：年滚轮 / 月滚轮 / 日滚轮 |
| direction | string | 是 | 滑动方向：up=向上（选更大值）、down=向下（选更小值） |
| times | integer | 是 | 滑动次数，1次≈1个月/年/日 |

---

#### 工具 3: appium_assert

**请求体**:
```json
{
  "tool_name": "appium_assert",
  "parameters": {
    "target": "{{target}}",
    "expect": "{{expect}}"
  }
}
```

**输入参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| target | string | 是 | 控件名称，如：月视图标题 |
| expect | string | 是 | 期望包含的文本，如：10月 |

---

#### 工具 4: appium_wait

**请求体**:
```json
{
  "tool_name": "appium_wait",
  "parameters": {
    "seconds": {{seconds}}
  }
}
```

**输入参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| seconds | number | 是 | 等待秒数 |

---

#### 工具 5: appium_screenshot

**请求体**:
```json
{
  "tool_name": "appium_screenshot",
  "parameters": {}
}
```

---

#### 工具 6: appium_launch_app

**请求体**:
```json
{
  "tool_name": "appium_launch_app",
  "parameters": {}
}
```

---

## 二、创建 Dify Agent 工作流

### Workflow 结构

```
[开始] → [LLM Agent 节点] → [结束]
```

### Agent 节点 Prompt（复制到 Dify Agent 指令中）

```
你是一个 Android App 自动化测试助手。你可以通过工具直接控制用户手机上的"万年历"应用。

## 可用工具
- appium_click：点击屏幕上的控件
- appium_swipe：在年/月/日滚轮上滑动选择
- appium_assert：断言控件文本是否符合预期
- appium_wait：等待指定秒数
- appium_screenshot：截图当前界面
- appium_launch_app：启动万年历应用

## 可用控件（中文名称）
- 月份标题 / 年份标题 → 点击打开年月日选择器
- 月视图标题 / 年视图标题 → 用于断言当前显示的年月
- 确认按钮 → 确认选择并关闭选择器
- 取消按钮 → 取消选择
- 年滚轮 → 在年份选择时滑动
- 月滚轮 → 在月份选择时滑动
- 日滚轮 → 在日期选择时滑动
- 公历按钮 / 农历按钮 → 切换公历/农历

## 工作规则
1. 收到用户发来的测试用例描述，先提取出操作步骤和预期结果。
2. 操作步骤通常格式："1. 点击XX 2. 在XX中选择XX"——按顺序执行。
3. "选择N个月/年后的月份/年份" → 用 appium_swipe 在对应滚轮上滑动 N 次。
4. "月份滚轮每次向上滑动1次约增加1个月；年份滚轮向上滑动1次约增加1年"
5. 预期结果 → 用 appium_assert 验证。
6. 所有步骤完成后，截图并生成简洁的测试报告。

## 示例
用户输入："测试月视图切换：1.点击月份标题 2.选3个月后的月份 3.确认 4.断言标题为10月"
你的执行：
1. appium_launch_app → 确保万年历在前台
2. appium_click(target="月份标题") → 打开选择器
3. appium_swipe(wheel="月滚轮", direction="up", times=3) → 从7月滑到10月
4. appium_click(target="确认按钮") → 确认选择
5. appium_assert(target="月视图标题", expect="10月") → 验证
6. 报告结果
```

### Agent 模式设置
- **模型**：任意支持 Function Calling 的模型（如 DeepSeek-V3、GPT-4）
- **最大迭代次数**：20
- **输出格式**：文本

---

## 三、万年历控件定位器参考

| 中文名 | 定位策略 | 定位值 |
|--------|---------|--------|
| 月份标题 / 年份标题 | id | `com.youloft.calendar:id/title_click` |
| 月视图标题 / 年视图标题 | id | `com.youloft.calendar:id/title` |
| 确认按钮 | id | `com.youloft.calendar:id/dc_sureBtn` |
| 取消按钮 | id | `com.youloft.calendar:id/dc_cancelBtn` |
| 年滚轮 | id | `com.youloft.calendar:id/year` |
| 月滚轮 | id | `com.youloft.calendar:id/month` |
| 日滚轮 | id | `com.youloft.calendar:id/day` |
| 公历按钮 | id | `com.youloft.calendar:id/dc_dialog_solarRbtn` |
| 农历按钮 | id | `com.youloft.calendar:id/dc_dialog_lunarRbtn` |

| 区域 | 说明 | 坐标信息 |
|------|------|---------|
| 月滚轮区域 | 日期选择器中的月份列 | center_x=585, center_y=2228, item_h≈50px |
| 年滚轮区域 | 日期选择器中的年份列 | center_x=214, center_y=2228, item_h≈50px |
| 日滚轮区域 | 日期选择器中的日期列 | center_x=957, center_y=2228, item_h≈50px |
