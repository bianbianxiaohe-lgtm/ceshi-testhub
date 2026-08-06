# 阶段 0：墨刀需求读取

> **目标**：通过浏览器 MCP 工具打开墨刀原型链接，逐页提取需求内容，整理为结构化需求文档
> **输入**：用户提供的墨刀在线链接（`modao.cc/proto/...`）
> **输出**：`output/requirement_from_modao.md`
> **前置条件**：浏览器 MCP 连接器已启用

---

## 🔴 阶段0 强制规则

1. **必须使用 javascript_tool**：墨刀基于 Canvas 渲染，`read_page` 的 accessibility tree 无法获取内容，**必须**通过 `javascript_tool` 执行 `document.body.innerText` 提取文本
2. **每次切换页面后等待 2 秒**：点击侧边栏导航后，必须 `wait 2秒` 再读取内容，否则可能读到旧页面
3. **区分导航与内容**：提取的文本包含侧边栏导航和主内容区，需区分并整理
4. **遍历所有页面**：必须逐个点击侧边栏中的功能页面，确保不遗漏需求
5. **提取注释/标注**：墨刀原型中的数字标注（如"1"、"2"）对应页面底部的需求说明/注释，必须一并提取
6. **等待用户确认**：需求文档生成后必须 ⏸️ 等待用户确认才进入阶段1

---

## 📋 执行步骤

### Step 0.1：获取浏览器标签页

调用 `qw_mcp_get` 获取工具 schema，然后调用 `tabs_context` 获取当前浏览器标签页列表：

```
工具：mcp__builtin_browser__tabs_context
参数：{}
```

检查返回结果中是否已有墨刀链接对应的标签页：
- **已存在**：记录该 tabId，跳到 Step 0.3
- **不存在**：创建新标签页并导航，进入 Step 0.2

### Step 0.2：打开墨刀链接（如需要）

调用 `tabs_create_mcp` 创建新标签页，然后调用 `navigate` 导航到墨刀链接：

```
工具：mcp__builtin_browser__navigate
参数：{ "url": "<墨刀链接>", "tabId": <tabId> }
```

等待页面加载完成（wait 3秒）。

### Step 0.3：获取工具 schema

在首次使用前，获取需要用到的浏览器工具的 schema：

```
工具：qw_mcp_get
参数：{ "toolName": "mcp__builtin_browser__javascript_tool" }
工具：qw_mcp_get
参数：{ "toolName": "mcp__builtin_browser__find" }
工具：qw_mcp_get
参数：{ "toolName": "mcp__builtin_browser__computer" }
```

### Step 0.4：提取当前页面内容

使用 `javascript_tool` 提取当前页面的全部文本内容：

```
工具：mcp__builtin_browser__javascript_tool
参数：{ "tabId": <tabId>, "text": "document.body.innerText" }
```

**关键说明**：
- 返回的文本包含：顶部工具栏 + 左侧导航列表 + 主内容区（原型画布）+ 底部注释/标注
- 主内容区的文本是原型中各个屏幕的 UI 文字（按钮、标题、提示语等）
- 底部标注（数字1、2、3...）对应具体的需求说明，**这些是最重要的需求信息**

### Step 0.5：识别侧边栏页面列表

使用 `find` 工具搜索侧边栏中的功能页面名称：

```
工具：mcp__builtin_browser__find
参数：{ "tabId": <tabId>, "query": "<功能关键词>" }
```

或使用 `read_page` 的 interactive 模式查看侧边栏可点击元素：

```
工具：mcp__builtin_browser__read_page
参数：{ "tabId": <tabId>, "filter": "interactive" }
```

从返回结果中识别侧边栏的页面列表（通常在一个 `<ul>` 列表中，每个 `<li>` 是一个页面）。

### Step 0.6：逐页提取内容

**核心循环**：对侧边栏中的每个功能页面，执行以下操作：

```
循环：对每个页面 P
  1. 使用 find 工具定位页面 P 在侧边栏中的元素
  2. 使用 computer 工具 left_click 点击该元素
  3. 使用 computer 工具 wait 2秒（等待页面切换完成）
  4. 使用 javascript_tool 执行 document.body.innerText 提取文本
  5. 记录提取的内容，标注来源页面名称
结束循环
```

**具体操作示例**：

```
# 1. 查找目标页面元素
工具：mcp__builtin_browser__find
参数：{ "tabId": <tabId>, "query": "功能介绍页" }

# 2. 点击页面（使用返回的 ref）
工具：mcp__builtin_browser__computer
参数：{ "action": "left_click", "ref": "<ref_id>", "tabId": <tabId> }

# 3. 等待加载
工具：mcp__builtin_browser__computer
参数：{ "action": "wait", "duration": 2, "tabId": <tabId> }

# 4. 提取内容
工具：mcp__builtin_browser__javascript_tool
参数：{ "tabId": <tabId>, "text": "document.body.innerText" }
```

**注意事项**：
- 侧边栏页面可能有层级关系（父页面→子页面），需按层级顺序遍历
- 部分页面可能是同一功能的不同状态展示（如"定时解锁"vs"答题解锁"），都需读取
- 如果点击后内容未变化，可能是父级分组而非实际页面，跳过即可

### Step 0.7：内容整理与去重

将所有页面提取的内容整理为结构化需求文档：

1. **去除重复内容**：侧边栏导航文本在每次提取中都会出现，只需保留一份
2. **区分 UI 文字与需求说明**：
   - UI 文字：原型中显示的按钮文案、标题、提示语等
   - 需求说明：页面底部带数字标注的注释（如"1、逻辑和以前一样..."），这些是产品经理写的具体需求规则
3. **按功能模块组织**：将各页面内容按功能模块归类

### Step 0.8：生成需求文档

将整理后的内容写入 `output/requirement_from_modao.md`，格式如下：

```markdown
# {原型名称} - 需求文档

> **来源**：墨刀原型 {链接}
> **提取日期**：{日期}
> **页面总数**：{N} 个页面

---

## 一、页面结构概览

{列出所有页面名称及层级关系}

## 二、各页面需求内容

### 2.1 {页面名称1}

**UI 内容**：
{该页面原型中显示的 UI 文字}

**需求说明/标注**：
{该页面底部的数字标注对应的需求说明}

### 2.2 {页面名称2}
...

## 三、后台配置需求（如有）

{后台管理页面的配置项说明}

## 四、关键业务规则汇总

{从各页面标注中提取的核心业务规则}
```

### Step 0.9：保存状态

```json
{
  "current_stage": 0,
  "stages_completed": [],
  "stage_outputs": {
    "stage0": "output/requirement_from_modao.md"
  },
  "user_confirmations": {
    "stage0_confirmed": false
  }
}
```

### Step 0.10：⏸️ 引导用户确认

输出格式：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 阶段0 完成：墨刀需求已提取
📄 产物：output/requirement_from_modao.md

📌 提取概览：
- 原型名称：{name}
- 总页面数：{N} 个
- 功能模块：{module_list}
- 含后台配置：是/否

📝 主要功能模块：
1. {module_1}（{page_count} 个页面）
2. {module_2}（{page_count} 个页面）
3. ...

💡 请确认：
1. 需求内容是否提取完整？
2. 是否有遗漏的页面或功能？
3. 标注/注释内容是否清晰可读？

确认无误后请回复「确认」，将进入阶段1：需求通读。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🔧 常见问题处理

### 页面内容提取为空
- 原因：页面可能基于 Canvas 渲染且 `innerText` 无法获取
- 处理：尝试 `document.querySelector('canvas').parentElement.innerText`，或使用 `get_page_text` 工具

### 侧边栏点击无响应
- 原因：某些页面项可能需要先展开父级
- 处理：先点击父级展开，再点击子页面

### 页面加载缓慢
- 原因：墨刀原型资源较大
- 处理：增加 wait 时间到 3-5 秒

### 需要登录
- 原因：墨刀链接非公开分享
- 处理：提示用户先在浏览器中登录墨刀账号

---

## ⛔ 阶段0 终止锚点

**Agent 必须在输出 Step 0.10 引导语后立即停止，等待用户回复。**

❌ 禁止：
- 在用户未确认时直接进入阶段1
- 自行补充墨刀中没有的需求内容
- 跳过任何页面的提取
- 修改/优化提取到的原始需求内容
