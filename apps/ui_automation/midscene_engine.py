"""
Midscene APP UI 自动化执行引擎

基于 Midscene（Python 包 midscene，底层桥接 @midscene/android）驱动 Android 真机，
执行 AICase（execution_mode='midscene'）的结构化 steps。设计原则（详见 docs/midscene_app_automation_design.md）：

- 步骤业务无关：action/prompt/value/extract/assert 全由用例设计者定义，框架不预置业务语义。
- 业务锚点（上下文传递）：步骤 extract 提取任意结构化数据存入 context，后续步骤用 ${{key}} 引用。
- 确定性操作优先 Instant Action（aiTap/aiInput），需理解页面语义才用 aiAct/aiQuery。
- 视觉模型取自 AIModelConfig(role='midscene_vision')，不写死 Key。

注意：midscene 相关第三方包在运行时（容器）才安装；本模块使用 lazy import，
保证在没有 midscene 包的环境（如本机 py_compile / 部分测试）下仍可导入与静态校验。
"""
import os
import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

from .popup_handler import dismiss_popups, PopupAdapter

logger = logging.getLogger(__name__)

# ${{key}} 模板占位符正则
CONTEXT_VAR_PATTERN = re.compile(r"\$\{\{(\s*[\w.-]+\s*)\}\}")

# 随机弹窗（权限请求 / 隐私协议 / 开屏广告 ……）的自动处理。
# 开关：设 POPUP_AUTO_DISMISS=0 可关闭，方便那些"专门测弹窗"的用例。
POPUP_AUTO_DISMISS = os.environ.get('POPUP_AUTO_DISMISS', '1') not in ('0', 'false', 'False', '')
# 某一步失败后，最多"关弹窗 + 重试"几次
POPUP_RETRY_LIMIT = int(os.environ.get('POPUP_RETRY_LIMIT', '2') or 2)
#: 断言步骤的弹窗重试次数放宽一些（见 run() 中的说明）。
ASSERT_POPUP_RETRY_LIMIT = int(
    os.environ.get('ASSERT_POPUP_RETRY_LIMIT', '3') or 3)

# 坐标/像素写法护栏：用例必须用语义描述，禁止写死坐标，否则换机型必错位
# 命中规则（兼顾 midscene bbox=[x,y,x,y] 与单点 [x,y]，但尽量不误伤业务数字）：
#   1) 四个数字（bbox）：\d,\d,\d,\d
#   2) 括号包裹的两数（单点坐标）：(x, y) / （x，y）
#   3) 显式坐标键：x= / y: / 坐标: / coord= 等
_COORD_HINT = re.compile(
    r'('
    r'\d{1,5}\s*[,，]\s*\d{1,5}\s*[,，]\s*\d{1,5}\s*[,，]\s*\d{1,5}'  # 四数 bbox
    r'|[\(\（]\s*\d{1,5}\s*[,， ]\s*\d{1,5}\s*[\)\）]'              # 括号包裹的两数单点
    r'|(坐标|coord|point|点击|点|tap|click)\D{0,10}\d{2,5}\s*[,，]\s*\d{2,5}'  # 坐标/点击动词后紧跟 数字,数字
    r')'
    r'|(坐标|coord|point)\s*[:=]'
    r'|(?<![A-Za-z0-9_])(x|y)\s*[:=]',                              # x= / y: 等显式坐标键（避免误伤英文单词）
    re.I,
)


def _guard_semantic_prompt(prompt: str, where: str = '') -> None:
    """拦截疑似写死坐标的 prompt，强制用语义描述以保证跨机型兼容性。

    仅对「自然语言操作类」prompt 生效；纯业务数据（如提取金额、手机号）不含坐标形状，
    不会被误伤。命中时抛 ValueError，由调用方转成 failed/错误提示。
    """
    if not prompt or not isinstance(prompt, str):
        return
    m = _COORD_HINT.search(prompt)
    if m:
        hit = m.group(0)
        raise ValueError(
            "【%s】检测到疑似坐标写法「%s」。Midscene 为语义定位引擎，请改用语义描述"
            "（如「点右下角的我的 Tab」「在搜索框输入天气」），不要写死像素/坐标，"
            "否则换机型会失效。" % (where or 'prompt', hit)
        )


def _resolve_template(text: str, context: Dict[str, Any]) -> str:
    """把字符串中的 ${{key}} 替换为上下文变量值。"""
    if not text or not isinstance(text, str):
        return text

    def _sub(m):
        key = m.group(1).strip()
        if key in context:
            val = context[key]
            return str(val) if not isinstance(val, str) else val
        # 未找到时不替换，保留占位符以便排查
        logger.warning("[Midscene] 上下文变量 ${{%s}} 未找到，保留原样", key)
        return m.group(0)

    return CONTEXT_VAR_PATTERN.sub(_sub, text)


class MidsceneAppEngine:
    """Midscene 移动端执行引擎（Android 真机 / 模拟器）"""

    # 支持的步骤 action
    SUPPORTED_ACTIONS = {
        'aiAct', 'aiQuery', 'aiTap', 'aiInput', 'assert', 'wait',
        'launch', 'back', 'home', 'screenshot', 'aiWaitFor',
    }

    #: 条件等待的默认超时（毫秒）。aiWaitFor 语义是"等到条件成立"，
    #: 不像其他动作那样立刻返回，所以必须有个上限，否则页面一直
    #: 不出现目标元素时会一直卡住（默认 15 秒，可用步骤的
    #: timeout_ms 字段按步骤覆盖）。
    DEFAULT_WAIT_FOR_TIMEOUT_MS = 15000

    def __init__(self, app_config, device, model_config: Optional[dict] = None,
                 launch_wait_ms: int = 6000, workspace: Optional[str] = None,
                 auto_dismiss_popup: Optional[bool] = None,
                 replay_mode: bool = False):
        """
        Args:
            app_config: AppConfig 实例（含 package_name / app_activity）
            device: AppDevice 实例（含 udid / adb_host）
            model_config: {'api_key','base_url','model_name','model_family'}，
                          为空时从 AIModelConfig(role='midscene_vision') 读取
            launch_wait_ms: 启动 APP 后等待毫秒
            workspace: 截图/日志工作目录
            auto_dismiss_popup: 弹窗自动处理。None=用全局默认（环境变量），
                                True/False=用例配置优先
            replay_mode: 纯坐标回放。用例已固化时开启，每步直接按坐标点，
                         不调用视觉模型。
        """
        self.app_config = app_config
        self.device = device
        self.launch_wait_ms = launch_wait_ms
        self.workspace = workspace or os.path.join('media', 'midscene')
        os.makedirs(self.workspace, exist_ok=True)

        self.auto_dismiss_popup = (
            POPUP_AUTO_DISMISS if auto_dismiss_popup is None else bool(auto_dismiss_popup)
        )
        self.replay_mode = bool(replay_mode)
        self.model_config = model_config or self._load_model_config()
        # 运行期对象（lazy init）
        self._page = None  # Midscene AndroidPage 实例
        self._agent = None  # Midscene agent（若使用）
        self.context: Dict[str, Any] = {}  # 跨步骤业务上下文（业务锚点）
        self.logs: List[str] = []

    # ---------------- 模型配置 ----------------
    def _load_model_config(self) -> dict:
        try:
            from apps.requirement_analysis.models import AIModelConfig
        except Exception as e:  # noqa
            logger.warning("[Midscene] 无法导入 AIModelConfig: %s", e)
            return {}
        cfg = AIModelConfig.objects.filter(role='midscene_vision', is_active=True).first()
        if not cfg:
            return {}
        return {
            'api_key': cfg.api_key,
            'base_url': cfg.base_url,
            'model_name': cfg.model_name,
            'model_family': getattr(cfg, 'model_family', '') or '',
        }

    # ---------------- 设备连接 ----------------
    def connect(self):
        """建立 Midscene 与真机的连接（lazy import midscene）。

        midscene 的 Python 包入口为 MidsceneAndroidAgent（非 midscene.android.AndroidPage）。
        远程手机架构：手机 USB 插用户电脑，后端经该机 ADB server 控制。
        若 device.adb_host 形如 '192.168.8.71:5037'，则设置 ADB_SERVER_SOCKET 让
        @midscene/android 走该 adb server；device_id 仍用 udid。
        """
        try:
            from midscene import MidsceneAndroidAgent, MidsceneConfig
        except Exception as e:
            raise RuntimeError(
                "未安装 midscene，无法连接真机（%s）。请在后端容器执行 "
                "pip install midscene 后重试。" % e
            )

        adb_host = (self.device.adb_host or '').strip() or ''
        device_id = self.device.udid
        if adb_host:
            # 远程 adb server（如 192.168.8.71:5037）。
            # @midscene/android v0.1.5 读取的环境变量是 MIDSCENE_ADB_REMOTE_HOST /
            # MIDSCENE_ADB_REMOTE_PORT（代码核实：dist/lib/index.js 读
            # getEnvConfigValue(MIDSCENE_ADB_REMOTE_HOST) 而非 ANDROID_ADB_SERVER_HOST），
            # 故必须设这两个变量，midscene 才会把 adb 命令发往用户电脑的 adb server。
            # 该环境变量会被 midscene 的 Node 服务进程继承。
            host = adb_host
            port = '5037'
            if ':' in adb_host:
                host, _, port = adb_host.rpartition(':')
            os.environ['MIDSCENE_ADB_REMOTE_HOST'] = host
            os.environ['MIDSCENE_ADB_REMOTE_PORT'] = port
            # 兼容保留：部分 appium-adb 版本仍读 ANDROID_ADB_SERVER_HOST/PORT
            os.environ['ANDROID_ADB_SERVER_HOST'] = host
            os.environ['ANDROID_ADB_SERVER_PORT'] = port
            logger.info("[Midscene] 设置 MIDSCENE_ADB_REMOTE_HOST=%s PORT=%s", host, port)
        logger.info("[Midscene] 连接设备 udid=%s", device_id)

        # 模型配置（视觉模型，OpenAI 兼容）
        cfg = self.model_config or {}
        model_config = None
        if cfg.get('api_key'):
            family = cfg.get('model_family') or ''
            # midscene v1.x 的 Node 服务从 MIDSCENE_MODEL_FAMILY 环境变量读取
            # model family，Python 端 MidsceneConfig(model_family=...) 不会自动
            # 映射到该环境变量，必须显式写入 os.environ 才能被子进程继承。
            if family:
                os.environ['MIDSCENE_MODEL_FAMILY'] = family
                logger.info("[Midscene] 设置 MIDSCENE_MODEL_FAMILY=%s", family)
            model_config = MidsceneConfig(
                base_url=cfg.get('base_url') or '',
                api_key=cfg['api_key'],
                model_name=cfg.get('model_name') or '',
                model_family=family,
            )
        self._agent = MidsceneAndroidAgent(device_id, model_config)
        self._page = self._agent  # 兼容下方 step/playground 逻辑，统一用 self._page
        self._log("已连接设备 %s", device_id)
        return self._page

    def launch_app(self):
        if self._page is None:
            self.connect()
        pkg = self.app_config.package_name
        activity = self.app_config.app_activity or ''
        if activity:
            self._page.run_adb_shell("am start -n %s/%s" % (pkg, activity))
        else:
            self._page.run_adb_shell("monkey -p %s -c android.intent.category.LAUNCHER 1" % pkg)
        if self.launch_wait_ms:
            time.sleep(self.launch_wait_ms / 1000.0)
        self._log("已启动应用 %s / %s", pkg, activity)

    def reset_to_home(self):
        """把 App 复位到一致起点（探索与回放都用，保证"采样起点 == 回放起点"）。

        目的：回放按**固化时采到的绝对坐标**点击，隐含假设
          「执行起点页面 == 固化采样时的起点页面」。
          若两边起点不同 → 坐标整体偏掉 → 回放失败 → 降级烧 token
          → 用户以为"固化从没生效"。
          所以**探索和回放都必须先复位到同一起点**。

        ⚠️⚠️ **只做 `am start`，绝不 `am force-stop`**
        （2026-09-22 iOS 实测踩坑后定型，Android 同步该结论）：
          最初实现是"杀进程 + 冷启动"，以为能拿到"最干净的首启状态"。
          但实测该 App 冷启动会落到一个**没有主导航、也没有返回按钮的死路页**
          （iOS 侧是「日记本」页：`back` 手势连点两次元素树完全不变），
          首步固化坐标在此页会落到别的控件上 → 后续必然连锁失败。
          **杀进程恰恰会落到那个死路页，等于把 App 推进更糟的地方。**

          改为只用 `am start`/`monkey`：App 已在前台时通常只是"唤到前台"、
          保留原 Activity 栈，不在前台则冷启动。两种情况**都不由我们决定落在哪一页**，
          起点一致性交给用例自身保证（用例应从它期望的页面开始）。

        失败不抛异常：复位失败只是"起点可能不一致"，
        不能因为复位本身报错把用例直接搞挂。
        """
        if self._page is None:
            self.connect()
        pkg = self.app_config.package_name
        if not pkg:
            self._log('[复位] 未配置应用包名，跳过复位（起点可能不一致）')
            return
        try:
            activity = self.app_config.app_activity or ''
            if activity:
                self._page.run_adb_shell("am start -n %s/%s" % (pkg, activity))
            else:
                self._page.run_adb_shell(
                    "monkey -p %s -c android.intent.category.LAUNCHER 1" % pkg)
            # 等界面稳定，否则紧接着的坐标点击会落在启动过渡画面上
            wait_ms = self.launch_wait_ms or 3000
            time.sleep(max(wait_ms, 3000) / 1000.0)
            self._log('[复位] 已拉起 %s（不清 Activity 栈，起点由用例自身保证）', pkg)
        except Exception as exc:  # noqa: BLE001
            self._log('[复位] 复位失败（不影响执行，起点可能不一致）: %s',
                      str(exc)[:160])

    # ---------------- Playground（自然语言调试） ----------------
    def playground_run(self, prompt: str, action: str = 'aiAct',
                       launch_app: bool = True) -> Dict[str, Any]:
        """
        Playground 单条自然语言调试：连真机执行一条自然语言操作并返回截图(base64)。
        用于验证 Midscene 自然语言操作方式，确认稳定后再沉淀为正式步骤。
        """
        # 坐标护栏放最前：纯文本校验，不连设备即可拦截写死坐标的 prompt（避免无意义真机连接）
        _guard_semantic_prompt(prompt, 'Playground')
        if self._page is None:
            self.connect()
        if launch_app:
            try:
                self.launch_app()
            except Exception as e:
                return {
                    'status': 'failed',
                    'error': '启动应用失败: %s' % e,
                    'logs': list(self.logs),
                    'screenshot_base64': None,
                }

        result = {
            'status': 'passed',
            'action': action,
            'prompt': prompt,
            'logs': [],
            'screenshot_base64': None,
            'error': None,
        }
        try:
            self._log("[Playground] action=%s | prompt=%s", action, prompt)
            if action == 'aiTap':
                self._page.ai_tap(prompt)
            elif action == 'aiInput':
                self._page.ai_input(prompt, '')
            elif action == 'aiQuery':
                data = self._page.ai_query(prompt)
                result['query_result'] = data
                self._log("[Playground] ai_query 返回: %s", data)
            elif action == 'aiAct':
                self._page.ai_action(prompt)
            else:
                raise ValueError("Playground 暂不支持 action: %s（仅 aiAct/aiTap/aiInput/aiQuery）" % action)

            # 执行后截图并转 base64 回传（绕开静态 media 服务，直接走 api 通道）
            # midscene v0.1.5 的 get_screenshot() 不接受路径参数，直接返回 base64 字符串
            import base64
            result['screenshot_base64'] = self._page.get_screenshot()
            self._log("[Playground] 已截图（base64 len=%d）", len(result['screenshot_base64'] or ''))
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            self._log("[Playground] 执行出错: %s", e)
            try:
                result['screenshot_base64'] = self._page.get_screenshot()
            except Exception:
                pass

        result['logs'] = list(self.logs)
        return result

    # ---------------- 步骤执行 ----------------
    def _resolve_business_refs(self, steps: List[dict]) -> List[dict]:
        """把 steps 里的 {ref: 动作名} 展开成完整 step dict（从 BusinessAction 加载）。

        兼容两种写法：
        - {ref: 'login'}：纯引用业务动作
        - {ref: 'login', value: 'xxx'}：引用并覆盖部分字段（如覆盖 value）
        无 ref 的内联 step（含 action/prompt）原样保留，向后兼容。
        """
        from apps.ui_automation.models import BusinessAction

        resolved: List[dict] = []
        for s in steps or []:
            if not isinstance(s, dict):
                resolved.append(s)
                continue
            # A step carrying "ref" is a REFERENCE and gets expanded.
            # The old condition also required "action" to be absent, which
            # silently kept a half-filled step (ref + leftover action) as-is
            # and executed nothing at all - hard to notice, harder to debug.
            ref = (s.get('ref') or '').strip() if isinstance(s.get('ref'), str) else s.get('ref')
            if ref:
                try:
                    action_obj = BusinessAction.objects.get(name=ref)
                except BusinessAction.DoesNotExist:
                    self._log("[警告] 公共步骤「%s」不存在，该步已跳过", ref)
                    resolved.append({
                        'name': '引用公共步骤 %s' % ref,
                        'action': 'screenshot',
                        'prompt': ref,
                        '_ref_missing': ref,
                        '_status': 'failed',
                        '_error': '公共步骤「%s」不存在' % ref,
                    })
                    continue

                merged = action_obj.to_step()
                # 允许内联覆盖（ref 之外传入的字段）
                overrides = [k for k in s.keys() if k not in ('ref',)]
                merged.update({k: v for k, v in s.items() if k not in ('ref',)})
                # 日志里展开引用内容，否则失败时不知道是哪个公共步骤的问题
                self._log("引用公共步骤「%s」-> %s: %s",
                          ref, merged.get('action'),
                          (merged.get('prompt') or '')[:120])
                if overrides:
                    self._log("  覆盖字段: %s", ', '.join(overrides))
                merged['_ref'] = ref
                merged['name'] = merged.get('name') or ref
                resolved.append(merged)
            else:
                resolved.append(s)
        return resolved

    def run(self, steps: List[dict]) -> Dict[str, Any]:
        """执行整条用例的 steps，返回执行结果摘要。"""
        if self._page is None:
            self.connect()
        # 展开业务动作引用（Prompt 与代码分离）
        steps = self._resolve_business_refs(steps)
        # 空步骤必须显式失败：以前 action 会兜底成 aiAct、prompt 兜底成空串，
        # 拿着空提示词问视觉模型，模型随便点一下也返回成功 ——
        # 用例其实什么都没配，执行却显示「通过」。
        empty = [i for i, s in enumerate(steps)
                 if isinstance(s, dict) and not self._step_has_content(s)]
        if empty:
            bad = empty[0]
            msg = ('第 %d 个步骤是空的：既没有 action 也没有 prompt。'
                   '请到「用例编辑」里补全该步骤（或删除它）' % (bad + 1))
            self._log('%s', msg)
            return {
                'status': 'failed',
                'steps': [{'index': bad, 'name': '步骤%d' % (bad + 1),
                           'action': '', 'status': 'failed', 'error': msg}],
                'context': self.context,
                'error': msg,
            }
        result = {
            'status': 'passed',
            'steps': [],
            'context': {},
            'error': None,
        }
        try:
            # ⭐⭐ **两种模式都必须先复位到统一起点**（2026-09-22 与 iOS 侧对齐）。
            #
            # 为什么探索也要复位：固化采到的是**绝对坐标**，隐含假设
            # 「本次起点页面 == 固化采样时的起点页面」。
            # 若探索时从"任意状态"（App 停在上次留下的深层页面）开始采样，
            # 而回放从冷启动首页开始，两边起点不同 → 坐标整体偏掉
            # → 回放必失败 → 降级烧 token → 用户以为固化没用。
            # 规则简化为：**每次执行（探索/回放）都从同一个干净起点开始**。
            #
            # ⚠️ Android 必须 `am force-stop`：monkey/am start 对已在运行的 App
            #    只是"唤到前台"，不会重置 Activity 栈。
            self.reset_to_home()
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = '启动应用失败: %s' % e
            self._log("启动应用失败: %s", e)
            return result

        for idx, step in enumerate(steps):
            step_result = self._run_step(step, idx)

            # 随机弹窗（权限请求 / 隐私协议 / 开屏广告 ……）随时可能冒出来，
            # 一旦挡住目标元素这一步就会失败。这里做「关弹窗 + 重试」，
            # 正常路径（没弹窗）零额外开销。
            # 断言步骤上限单独放宽，理由同 iOS 引擎（弹窗检测与断言各自调模型、
            # 结论可能矛盾，多试几次能让广告页自愈）。
            limit = (ASSERT_POPUP_RETRY_LIMIT
                     if step.get('action') == 'assert' else POPUP_RETRY_LIMIT)
            try_count = 0
            while (step_result.get('status') == 'failed'
                   and self.auto_dismiss_popup
                   and try_count < limit):
                try_count += 1
                self._log('[步骤 %d] 失败，检测是否为弹窗干扰（第 %d/%d 次重试）...',
                          idx + 1, try_count, limit)
                if dismiss_popups(self._popup_adapter()) == 0:
                    self._log('[步骤 %d] 未发现弹窗，不再重试', idx + 1)
                    break
                step_result = self._run_step(step, idx)
                if step_result.get('status') != 'failed':
                    self._log('[步骤 %d] 关闭弹窗后重试成功', idx + 1)
                    break

            result['steps'].append(step_result)
            if step_result.get('status') == 'failed':
                result['status'] = 'failed'
                result['error'] = step_result.get('error')
                break

        result['context'] = self.context
        return result

    def _popup_adapter(self):
        """把本引擎的能力包成 popup_handler 需要的接口。"""
        page = self._page
        return _AndroidPopupAdapter(page, self._log)

    @staticmethod
    def _step_has_content(step: dict) -> bool:
        """步骤是否可执行：引用步骤看 ref，内联步骤看 action/prompt。"""
        if str(step.get('ref') or '').strip():
            return True
        if str(step.get('action') or '').strip():
            return True
        return bool(str(step.get('prompt') or '').strip())

    def _run_step(self, step: dict, idx: int) -> Dict[str, Any]:
        action = step.get('action', 'aiAct')
        name = step.get('name', '步骤%d' % (idx + 1))
        raw_prompt = step.get('prompt', '')
        prompt = _resolve_template(raw_prompt, self.context)
        value = _resolve_template(step.get('value', ''), self.context)
        wait_ms = int(step.get('wait_ms', 0) or 0)

        # 坐标护栏：自然语言操作/定位类步骤禁止写死坐标（launch/back/home/screenshot/wait 无 prompt 不受影响）
        _guard_semantic_prompt(prompt, '步骤%d' % (idx + 1))
        # selector_hint 也用于定位，同样拦截坐标写法（aiTap/aiInput 优先用 selector_hint）
        if step.get('selector_hint'):
            _guard_semantic_prompt(step.get('selector_hint'), '步骤%d.selector_hint' % (idx + 1))
        self._log("[步骤 %d] %s | action=%s | prompt=%s", idx + 1, name, action, prompt)
        step_result = {
            'index': idx,
            'name': name,
            'action': action,
            'prompt': prompt,
            'status': 'passed',
            'extract': {},
            'assert': None,
            'error': None,
        }

        try:
            if action == 'launch':
                self.launch_app()
            elif action == 'back':
                self._page.ai_action("返回上一页")
            elif action == 'home':
                self._page.run_adb_shell("input keyevent KEYCODE_HOME")
            elif action == 'screenshot':
                # midscene v0.1.5 的 get_screenshot() 不接受路径参数，直接返回 base64 字符串
                step_result['screenshot'] = self._page.get_screenshot()
            elif action == 'wait':
                time.sleep(wait_ms / 1000.0)
            elif action == 'aiTap':
                # 纯坐标回放：直接用固化坐标点，不调模型
                if self.replay_mode and self._step_has_coords(step):
                    self._replay_tap(step)
                else:
                    # 确定性点击：target 来自 selector_hint 或 prompt
                    target = step.get('selector_hint') or prompt
                    self._page.ai_tap(target)
                    self._count_model_use(prompt)
            elif action == 'aiInput':
                if self.replay_mode and self._step_has_coords(step):
                    self._replay_input(step, value)
                else:
                    self._page.ai_input(step.get('selector_hint') or prompt, value)
                    self._count_model_use(prompt)
            elif action == 'aiAct':
                if self.replay_mode and self._step_has_coords(step):
                    self._replay_tap(step)
                else:
                    self._page.ai_action(prompt)
                    self._count_model_use(prompt)
            elif action == 'aiQuery':
                # 纯查询（不改动页面），结果存入 extract 或返回
                data = self._page.ai_query(prompt)
                self._count_model_use(prompt)
                step_result['extract']['_query'] = data
            elif action == 'aiWaitFor':
                # 条件等待：等目标元素/文案出现再继续。解决"页面加载慢、
                # 元素还没渲染出来"导致的偶发失败（比固定 sleep 更省时间，
                # 条件一成立立刻返回）。
                self._wait_for(prompt, step.get('timeout_ms'))
                self._count_model_use(prompt)
            elif action == 'assert':
                ok = self._do_assert(step)
                step_result['assert'] = {'pass': ok}
                if not ok:
                    raise AssertionError(step.get('assert', {}).get('expect', '断言未通过'))
            else:
                raise ValueError("不支持的 action: %s" % action)

            # extract：从页面提取业务数据（业务锚点），写入 context
            if step.get('extract'):
                extracted = self._do_extract(step['extract'])
                step_result['extract'].update(extracted)
                self.context.update(extracted)

            # assert（独立字段，非 action=assert 时）
            if step.get('assert') and action != 'assert':
                ok = self._do_assert(step)
                step_result['assert'] = {'pass': ok}
                if not ok:
                    raise AssertionError(step['assert'].get('expect', '断言未通过'))

            if wait_ms and action not in ('wait',):
                time.sleep(wait_ms / 1000.0)

            # 每步都留一张实拍截图，报告里才能"步骤 ↔ 画面"一一对应。
            # 之前只有显式 screenshot 动作才截、失败才截，成功用例报告里一张图都没有。
            if action != 'screenshot':
                try:
                    step_result['screenshot'] = self._page.get_screenshot()
                except Exception as exc:  # noqa: BLE001
                    self._log("[步骤 %d] 截图失败: %s", idx + 1, exc)

        except Exception as e:
            step_result['status'] = 'failed'
            step_result['error'] = str(e)
            self._log("[步骤 %d] 失败: %s", idx + 1, e)
            # 失败时截图留存现场
            try:
                step_result['fail_screenshot'] = self._page.get_screenshot()
            except Exception:  # noqa
                pass

        return step_result

    @staticmethod
    def _step_has_coords(step: dict) -> bool:
        """该步是否已经固化过坐标。"""
        if not isinstance(step, dict):
            return False
        cx, cy = step.get('center_x'), step.get('center_y')
        if cx is None or cy is None:
            return False
        try:
            int(cx), int(cy)
            return True
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _count_model_use(prompt: str = ''):
        """估算并累加一次模型调用的 token。

        真实 usage 由 LLM 代理记录；这里只是兜底，保证即使代理没生效，
        "这次执行花了多少"也有个可比的数字。
        """
        try:
            from .llm_usage import record_step_estimate
            record_step_estimate(prompt=prompt)
        except Exception:  # noqa: BLE001
            pass

    def _replay_tap(self, step: dict):
        """纯坐标点击：不经过视觉模型。"""
        cx = int(step['center_x'])
        cy = int(step['center_y'])
        self._log('[回放] tap -> (%d, %d)  [零模型]', cx, cy)
        page = self._page
        # midscene 的 page 对象暴露的坐标点击入口随版本略有差异，按优先级尝试
        for name in ('tap', 'click', 'tap_point', 'click_point'):
            fn = getattr(page, name, None)
            if callable(fn):
                fn(cx, cy)
                return
        # 兜底：走 adb 的 input tap（完全绕开模型）
        self._page.run_adb_shell('input tap %d %d' % (cx, cy))

    def _replay_input(self, step: dict, value: str):
        """点输入框（坐标）后输入文本，不经过视觉模型。"""
        self._replay_tap(step)
        time.sleep(0.4)
        page = self._page
        for name in ('input_text', 'inputText'):
            fn = getattr(page, name, None)
            if callable(fn):
                fn(value or '')
                return
        # 兜底：adb 文本输入（注意 adb input text 不支持中文/空格，需要时由
        # 使用者改用 aiInput 的 AI 路径）
        safe = (value or '').replace(' ', '%s')
        self._page.run_adb_shell('input text "%s"' % safe)

    def _do_extract(self, extract_list: List[dict]) -> Dict[str, Any]:
        """调用 ai_query 提取结构化业务数据，按 type 解析后返回 {key: value}。"""
        out: Dict[str, Any] = {}
        for item in extract_list:
            key = item.get('key')
            prompt = _resolve_template(item.get('prompt', ''), self.context)
            typ = item.get('type', 'string')
            required = item.get('required', False)
            if not key:
                continue
            try:
                raw = self._page.ai_query(prompt)
                out[key] = self._coerce(raw, typ)
                self._log("extract %s(%s) = %s", key, typ, out[key])
            except Exception as e:
                self._log("extract %s 失败: %s", key, e)
                if required:
                    raise
        return out

    def _wait_for(self, prompt: str, timeout_ms=None):
        """等到 prompt 描述的元素/条件出现，超时则抛错。

        为什么需要它：很多失败不是用例写错，而是"页面还没渲染完就去点"。
        固定 sleep（wait 动作）要么等太久浪费时间，要么等太短仍然失败；
        条件等待是"条件一成立立刻继续，最多等 timeout_ms"。

        实现上优先用底层 SDK 的 waitFor 能力；若当前版本没有该方法，
        退化成"轮询 ai_query 直到答案命中"的通用实现，保证多环境可用。
        """
        try:
            timeout_ms = int(timeout_ms or 0) or self.DEFAULT_WAIT_FOR_TIMEOUT_MS
        except (TypeError, ValueError):
            timeout_ms = self.DEFAULT_WAIT_FOR_TIMEOUT_MS
        timeout_ms = max(1000, timeout_ms)
        timeout_s = timeout_ms / 1000.0

        # ---- 路径 1：SDK 原生条件等待 ----
        for name in ('ai_wait_for', 'ai_waitfor', 'aiWaitFor'):
            fn = getattr(self._page, name, None)
            if callable(fn):
                self._log('[等待元素] 等待「%s」出现（超时 %ds）',
                          prompt, int(timeout_s))
                try:
                    fn(prompt, timeout_ms)
                except TypeError:
                    # 有些实现只接受 prompt，超时走内部默认值
                    fn(prompt)
                return

        # ---- 路径 2：轮询通用实现 ----
        self._log('[等待元素] SDK 无原生 waitFor，改用轮询等待「%s」（超时 %ds）',
                  prompt, int(timeout_s))
        deadline = time.time() + timeout_s
        ask = ('回答 true 或 false：当前屏幕是否满足下面这个条件？\n%s' % prompt)
        last = ''
        while time.time() < deadline:
            try:
                res = self._page.ai_query(ask)
                last = str(res).strip()
            except Exception as exc:  # noqa: BLE001
                self._log('[等待元素] 查询失败（继续重试）: %s', exc)
                last = ''
            if last.lower().startswith('true'):
                self._log('[等待元素] 条件已成立，继续执行', )
                return
            time.sleep(1)
        raise AssertionError(
            '等待超时（%ds）：元素/条件未出现 —— %s。最后一次判断结果：%s'
            % (int(timeout_s), prompt, last or '(无返回)')
        )

    def _do_assert(self, step: dict) -> bool:
        prompt = _resolve_template(step.get('assert', {}).get('prompt', ''), self.context)
        expect = step.get('assert', {}).get('expect', '')
        if not prompt:
            return True
        try:
            res = self._page.ai_assert(prompt)
            if isinstance(res, bool):
                return res
            return str(res).strip().lower().startswith('true')
        except Exception as e:
            self._log("assert 异常: %s", e)
            return False

    @staticmethod
    def _coerce(val: Any, typ: str) -> Any:
        if typ == 'number':
            try:
                return float(val)
            except (TypeError, ValueError):
                return val
        if typ == 'boolean':
            return str(val).strip().lower() in ('true', '1', '是', 'yes')
        if typ == 'json':
            try:
                return json.loads(val) if isinstance(val, str) else val
            except (TypeError, ValueError):
                return val
        return val

    # ---------------- 日志 ----------------
    def _log(self, fmt: str, *args):
        msg = fmt % args if args else fmt
        ts = datetime.now().strftime('%H:%M:%S')
        line = "[%s] %s" % (ts, msg)
        self.logs.append(line)
        logger.info("[Midscene] %s", msg)


class _AndroidPopupAdapter(PopupAdapter):
    """把 midscene 的 page 对象适配成 popup_handler 的接口。"""

    def __init__(self, page, log_func):
        self._page = page
        self._log_func = log_func

    def query(self, prompt: str):
        return self._page.ai_query(prompt)

    def tap(self, target: str) -> None:
        self._page.ai_tap(target)

    def log(self, msg: str) -> None:
        self._log_func('%s', msg)
