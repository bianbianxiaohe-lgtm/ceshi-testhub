"""
Appium 工具执行器 —— Dify Agent 工具调用的后端胶水层

职责：
1. 封装 AppiumTestEngine 提供面向 Agent 的工具 API
2. 管理控件定位器知识库（当前为万年历）
3. 解析 Dify tool_calls → 真机执行 → 返回结构化结果
"""
import time
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ==================== 控件定位器知识库 ====================

WANNIANLI_ELEMENTS = {
    "月份标题": {"strategy": "id", "value": "com.youloft.calendar:id/title_click"},
    "年份标题": {"strategy": "id", "value": "com.youloft.calendar:id/title_click"},
    "月视图标题": {"strategy": "id", "value": "com.youloft.calendar:id/title"},
    "年视图标题": {"strategy": "id", "value": "com.youloft.calendar:id/title"},
    "确认按钮": {"strategy": "id", "value": "com.youloft.calendar:id/dc_sureBtn"},
    "取消按钮": {"strategy": "id", "value": "com.youloft.calendar:id/dc_cancelBtn"},
    "年滚轮": {"strategy": "id", "value": "com.youloft.calendar:id/year"},
    "月滚轮": {"strategy": "id", "value": "com.youloft.calendar:id/month"},
    "日滚轮": {"strategy": "id", "value": "com.youloft.calendar:id/day"},
    "公历按钮": {"strategy": "id", "value": "com.youloft.calendar:id/dc_dialog_solarRbtn"},
    "农历按钮": {"strategy": "id", "value": "com.youloft.calendar:id/dc_dialog_lunarRbtn"},
    # 月份滚轮区域坐标（用于精确 swipe 选月）
    "月滚轮区域": {
        "strategy": "bounds",
        "x_range": [428, 742],
        "y_range": [1928, 2528],
        "center_x": 585,
        "center_y": 2228,
        "item_height": 50,
    },
    # 年滚轮区域坐标
    "年滚轮区域": {
        "strategy": "bounds",
        "x_range": [0, 428],
        "y_range": [1928, 2528],
        "center_x": 214,
        "center_y": 2228,
        "item_height": 50,
    },
}


# ==================== Dify 工具定义 Schema ====================

DIFY_TOOL_SCHEMAS = [
    {
        "name": "appium_click",
        "description": "在 Android 应用中点击指定控件",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "控件的中文名称，如 月份标题、确认按钮、取消按钮、公历按钮 等",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "appium_input",
        "description": "在输入框中输入文本",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "输入框控件中文名称"},
                "text": {"type": "string", "description": "要输入的文本内容"},
            },
            "required": ["target", "text"],
        },
    },
    {
        "name": "appium_swipe",
        "description": "在指定滚轮上滑动选择项。常用于年月日选择器中滚动到目标值",
        "parameters": {
            "type": "object",
            "properties": {
                "wheel": {
                    "type": "string",
                    "enum": ["年滚轮", "月滚轮", "日滚轮"],
                    "description": "要在哪个滚轮上滑动",
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "滑动方向：up=向上滑（选择更大的值），down=向下滑（选择更小的值）",
                },
                "times": {
                    "type": "integer",
                    "description": "滑动次数（每滑动1次约滚动1个单位，如1个月）",
                    "default": 1,
                },
            },
            "required": ["wheel", "direction", "times"],
        },
    },
    {
        "name": "appium_assert",
        "description": "断言指定控件的文本内容是否符合预期",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "要断言的控件中文名称"},
                "expect": {"type": "string", "description": "期望包含的文本内容（如 10月）"},
            },
            "required": ["target", "expect"],
        },
    },
    {
        "name": "appium_screenshot",
        "description": "对当前界面截图，用于让用户查看执行结果",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "appium_wait",
        "description": "等待指定秒数",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "等待秒数", "default": 1},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "appium_launch_app",
        "description": "启动/唤起指定应用（当前为万年历）",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


# ==================== Appium 工具执行器 ====================

@dataclass
class ToolCallResult:
    """工具调用结果"""
    name: str
    success: bool
    message: str
    data: Optional[Dict] = None


class AppiumToolExecutor:
    """
    Appium 工具执行器（单例模式，复用 Appium 连接）

    用法：
        executor = AppiumToolExecutor.get_instance()
        result = executor.execute("appium_click", {"target": "月份标题"})
    """

    _instance = None
    _engine = None

    # 默认连接参数（与当前项目环境一致）
    SERVER_URL = "http://host.docker.internal:4723"
    PACKAGE = "com.youloft.calendar"
    ACTIVITY = "com.youloft.LauncherActivity"
    UDID = "20a1ae2d"

    def __init__(self):
        self._knowledge: Dict = dict(WANNIANLI_ELEMENTS)

    def _get_engine(self):
        """懒初始化 Appium 引擎（单例连接）"""
        if self._engine is None or self._engine.driver is None:
            from apps.ui_automation.appium_engine import AppiumTestEngine

            engine = AppiumTestEngine(
                appium_server_url=self.SERVER_URL,
                platform="android",
                device_udid=self.UDID,
                app_package=self.PACKAGE,
                app_activity=self.ACTIVITY,
                no_reset=True,
                new_command_timeout=300,
            )
            engine.connect()
            # 显式唤起 app（HyperOS 需要 skipDeviceInitialization 后手动唤起）
            try:
                engine.driver.activate_app(self.PACKAGE)
            except Exception:
                pass
            self._engine = engine
        return self._engine

    def _find_locator(self, target_name: str) -> Optional[dict]:
        """从知识库中查找控件的定位信息"""
        info = self._knowledge.get(target_name)
        if not info:
            # 模糊匹配
            for key, val in self._knowledge.items():
                if target_name in key or key in target_name:
                    return val
        return info

    def _lookup_wheel_bounds(self, wheel_name: str) -> Optional[dict]:
        """获取滚轮坐标信息"""
        key = f"{wheel_name}区域"
        info = self._knowledge.get(key)
        if not info:
            # 直接用 wheel 名找
            info = self._knowledge.get(f"{wheel_name}区域")
        return info if info and info.get("strategy") == "bounds" else None

    # ---- 工具执行 ----

    def execute(self, tool_name: str, params: dict) -> ToolCallResult:
        """执行单个工具调用"""
        try:
            if tool_name == "appium_click":
                return self._click(params)
            elif tool_name == "appium_input":
                return self._input(params)
            elif tool_name == "appium_swipe":
                return self._swipe(params)
            elif tool_name == "appium_assert":
                return self._assert(params)
            elif tool_name == "appium_screenshot":
                return self._screenshot()
            elif tool_name == "appium_wait":
                return self._wait(params)
            elif tool_name == "appium_launch_app":
                return self._launch_app()
            else:
                return ToolCallResult(tool_name, False, f"未知工具: {tool_name}")
        except Exception as e:
            logger.exception(f"工具 {tool_name} 执行异常")
            return ToolCallResult(tool_name, False, str(e))

    def execute_batch(self, tool_calls: List[dict]) -> List[ToolCallResult]:
        """批量执行工具调用序列"""
        results = []
        engine = self._get_engine()
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", "unknown")
            params = tc.get("function", {}).get("arguments", {})
            # 参数可能是字符串 JSON
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    params = {}
            result = self.execute(name, params)
            results.append(result)
            # 任何步骤失败则停止
            if not result.success:
                break
        return results

    # ---- 各工具实现 ----

    def _click(self, params: dict) -> ToolCallResult:
        target = params.get("target", "")
        loc = self._find_locator(target)
        if not loc:
            return ToolCallResult("appium_click", False,
                                  f"找不到控件「{target}」，知识库中已注册的控件：{list(self._knowledge.keys())}")

        engine = self._get_engine()
        step = {
            "action_type": "click",
            "description": f"点击 {target}",
        }
        element = {"locator_strategy": loc["strategy"], "locator_value": loc["value"], "name": target}
        result = engine.execute_step({
            **step,
            "element": element,
            "input_value": "",
            "wait_time": 500,
            "assert_type": "",
            "assert_value": "",
        })
        return ToolCallResult(
            "appium_click",
            result.get("success", False),
            result.get("description", "") + (" - 成功" if result.get("success") else f" - 失败: {result.get('error', '')}"),
        )

    def _input(self, params: dict) -> ToolCallResult:
        target = params.get("target", "")
        text = params.get("text", "")
        loc = self._find_locator(target)
        if not loc:
            return ToolCallResult("appium_input", False, f"找不到控件「{target}」")

        engine = self._get_engine()
        result = engine.execute_step({
            "action_type": "fill",
            "description": f"在 {target} 输入 {text}",
            "element": {"locator_strategy": loc["strategy"], "locator_value": loc["value"], "name": target},
            "input_value": text,
            "wait_time": 500,
            "assert_type": "",
            "assert_value": "",
        })
        return ToolCallResult(
            "appium_input",
            result.get("success", False),
            result.get("description", "") + (" - 成功" if result.get("success") else f" - 失败: {result.get('error', '')}"),
        )

    def _swipe(self, params: dict) -> ToolCallResult:
        wheel = params.get("wheel", "月滚轮")
        direction = params.get("direction", "up")
        times = int(params.get("times", 1))

        bounds = self._lookup_wheel_bounds(wheel)
        if not bounds:
            return ToolCallResult("appium_swipe", False, f"找不到滚轮坐标: {wheel}")

        engine = self._get_engine()
        cx = bounds["center_x"]
        cy = bounds["center_y"]
        step = 150  # 每次滑动 150px ≈ 1个刻度
        y1 = cy + step if direction == "up" else cy - step
        y2 = cy - step if direction == "up" else cy + step
        if direction == "up":
            y1, y2 = cy, cy - step
        else:
            y1, y2 = cy, cy + step

        results = []
        for i in range(times):
            r = engine.execute_step({
                "action_type": "swipe",
                "description": f"在 {wheel} 上 {direction} 滑动 ({i + 1}/{times})",
                "input_value": f"{cx},{y1},{cx},{y2}",
                "wait_time": 500,
                "element": None,
                "assert_type": "",
                "assert_value": "",
            })
            results.append(r)
            if not r.get("success"):
                return ToolCallResult("appium_swipe", False,
                                      f"滑动第 {i + 1}/{times} 次失败: {r.get('error', '')}")

        return ToolCallResult("appium_swipe", True,
                              f"在 {wheel} 上 {direction} 滑动 {times} 次完成")

    def _assert(self, params: dict) -> ToolCallResult:
        target = params.get("target", "")
        expect = params.get("expect", "")
        loc = self._find_locator(target)
        if not loc:
            return ToolCallResult("appium_assert", False, f"找不到控件「{target}」")

        engine = self._get_engine()
        result = engine.execute_step({
            "action_type": "assert",
            "description": f"断言 {target} 包含 '{expect}'",
            "element": {"locator_strategy": loc["strategy"], "locator_value": loc["value"], "name": target},
            "input_value": "",
            "wait_time": 500,
            "assert_type": "textContains",
            "assert_value": expect,
        })
        return ToolCallResult(
            "appium_assert",
            result.get("success", False),
            result.get("description", "") + (" - 通过" if result.get("success") else f" - 失败: {result.get('error', '')}"),
        )

    def _screenshot(self) -> ToolCallResult:
        engine = self._get_engine()
        try:
            b64 = engine.driver.get_screenshot_as_base64()
            return ToolCallResult("appium_screenshot", True, "截图成功",
                                  data={"screenshot": f"data:image/png;base64,{b64}"})
        except Exception as e:
            return ToolCallResult("appium_screenshot", False, str(e))

    def _wait(self, params: dict) -> ToolCallResult:
        sec = float(params.get("seconds", 1))
        time.sleep(sec)
        return ToolCallResult("appium_wait", True, f"等待 {sec} 秒完成")

    def _launch_app(self) -> ToolCallResult:
        engine = self._get_engine()
        try:
            engine.driver.activate_app(self.PACKAGE)
            time.sleep(3)
            return ToolCallResult("appium_launch_app", True, "万年历已启动")
        except Exception as e:
            return ToolCallResult("appium_launch_app", False, str(e))

    @classmethod
    def close(cls):
        """关闭 Appium 连接"""
        if cls._engine and cls._engine.driver:
            try:
                cls._engine.driver.quit()
            except Exception:
                pass
        cls._engine = None
