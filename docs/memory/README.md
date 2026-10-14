# TestHub 项目持久化记忆库 (Project Memory Bank)

> **创建日期**：2026-10-12  
> **维护目的**：记录 TestHub 平台的架构演进、技术决策、每日代码变更日志与踩坑经验，确保跨会话、跨成员开发时上下文不丢失，实现“变更可追溯、逻辑有关联、雷区有预警”。

---

## 🗂️ 记忆库目录导航

| 文件名 | 定位与用途 | 何时阅读 / 何时更新 |
|---|---|---|
| [project_profile.md](file:///D:/code/my-project/docs/memory/project_profile.md) | **平台全景档案**：架构拓扑、技术栈事实源、端口拓扑与容器编排 | 接手新模块、配置环境、理解架构时必读 |
| [change_log.md](file:///D:/code/my-project/docs/memory/change_log.md) | **变更流水与逻辑关联日志**：详细记录每一次改动原因、改动文件与前后关联 | **每次完成代码修改后必须追加更新** |
| [architecture_decisions.md](file:///D:/code/my-project/docs/memory/architecture_decisions.md) | **架构决策记录 (ADR)**：记录重大设计方案的背景、利弊权衡与替代方案 | 涉及架构改造、公共基础设施变更时维护 |
| [pitfalls_and_rules.md](file:///D:/code/my-project/docs/memory/pitfalls_and_rules.md) | **避坑指南与团队铁律**：高频 Bug 复盘、反模式与防踩雷策略 | 调试排障、写代码自检时查阅；排查出深坑时沉淀 |
| [roadmap_and_tasks.md](file:///D:/code/my-project/docs/memory/roadmap_and_tasks.md) | **改造规划与任务清单**：平台后续重构计划、任务拆解与推进状态 | 开启新需求规划、梳理下一步行动时更新 |

---

## 📝 每次修改代码后的“记忆更新标准流程”

为了保证后续任何开发人员或 AI 接手时都能秒级恢复上下文，**每次完成功能改造或缺陷修复后，请遵循以下流程**：

### 1. 更新 `change_log.md`
在 `change_log.md` 顶部追加新的变更记录，包含：
* **变更时间与负责人/分支**
* **变更类型**（`feat` / `fix` / `refactor` / `perf` / `config`）
* **背景与原因**（解决了什么问题？为什么这么改？）
* **涉及的核心文件与代码修改点**
* **前后逻辑关联与连带影响**（改动了哪个接口？是否影响其他 View/前端组件？是否影响数据库/Docker？）
* **验证结果**（接口状态码、页面表现、自测结论）

### 2. 检查是否有新雷区需沉淀到 `pitfalls_and_rules.md`
若本次修改解决了一个隐蔽的 Bug（如配置冲突、框架异常、并发问题），将其提炼为条目记录到 `pitfalls_and_rules.md` 中，避免团队再犯。

### 3. 同步 `roadmap_and_tasks.md`
若本次变更推进了某个规划中的任务，将对应项标记为 `[x] 已完成`，并记录下一步关联任务。
