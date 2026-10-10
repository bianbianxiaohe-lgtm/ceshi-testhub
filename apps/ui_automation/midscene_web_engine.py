"""
Midscene Web UI 自动化执行引擎。

基于 midscene Python 包（实测环境为 0.1.5）驱动 Web 页面，执行 AICase
(execution_mode='midscene_web') 的结构化 steps，也支持由传统 TestCaseStep
转换而来的语义化步骤（见 test_executor._convert_to_midscene_steps）。

实测结论（2026-09-09，dev/prod 容器均为 midscene 0.1.5）：
- 0.1.5 **没有** MidscenePage，Web 端正确入口是
  ``MidsceneWebAgent(url=None, driver=PuppeteerDriver(headless=...), config=MidsceneConfig(...))``
  （底层走 puppeteer，不是 playwright）。
- ``ai_assert()`` 通过时返回 None，失败时抛 AssertionError（带 Reason），
  **不能用返回值判断是否通过**。
- ``get_screenshot()`` 直接返回 base64 PNG 字符串（不含 data: 前缀）。
- ``MidsceneConfig.model_family`` 缺省会 fallback 成 'openai'，dashscope 的
  qwen 系列必须显式指定 family，否则调用失败。

模型配置统一取自 ``AIModelConfig(role='midscene_vision', is_active=True)``
（apps.requirement_analysis），不再使用不存在的 AIIntelligentModeConfig。
"""
import glob
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

CONTEXT_VAR_PATTERN = re.compile(r"\$\{\{(\s*[\w.-]+\s*)\}\}")

#: AIModelConfig 中承载 Midscene 视觉模型的角色
MODEL_ROLE = 'midscene_vision'

DEFAULT_VIEWPORT = {'width': 1920, 'height': 1080}

#: midscene 0.1.5 支持的 model_family（用于按模型名/网关推断，避免退化成 openai）
_FAMILY_BY_KEYWORD = (
    (('qwen3-vl', 'qwen2.5-vl', 'qwen-vl'), 'qwen3-vl'),
    (('glm-v', 'glm-4v'), 'glm-v'),
    (('doubao',), 'doubao-vision'),
    (('gemini',), 'gemini'),
)

_FAMILY_BY_HOST = (
    ('dashscope', 'qwen3-vl'),
    ('deepseek', ''),
)


def _resolve_model_family(cfg) -> str:
    """推断 midscene 需要的 model_family。

    优先级：模型配置上的 model_family 字段（若将来加上）> 环境变量
    MIDSCENE_MODEL_FAMILY > 按模型名关键词 > 按网关域名。
    返回空字符串表示让 midscene 走默认（openai），通常不适用于国产多模态模型。
    """
    fam = (getattr(cfg, 'model_family', '') or '').strip()
    if fam:
        return fam
    fam = (os.environ.get('MIDSCENE_MODEL_FAMILY') or '').strip()
    if fam:
        return fam

    model_name = (getattr(cfg, 'model_name', '') or '').lower()
    for keywords, family in _FAMILY_BY_KEYWORD:
        if any(k in model_name for k in keywords):
            return family

    base_url = (getattr(cfg, 'base_url', '') or '').lower()
    for host, family in _FAMILY_BY_HOST:
        if host in base_url:
            return family
    return ''


def load_midscene_model_config(role: str = MODEL_ROLE) -> Dict[str, str]:
    """读取 Midscene 视觉模型配置。

    返回 ``{'base_url', 'api_key', 'model_name', 'model_family'}``；
    未配置时返回空 dict（调用方应据此给出明确报错，不要静默继续）。
    """
    try:
        from apps.requirement_analysis.models import AIModelConfig
    except Exception as e:  # noqa: BLE001
        logger.warning("[MidsceneWeb] 无法导入 AIModelConfig: %s", e)
        return {}

    cfg = AIModelConfig.objects.filter(role=role, is_active=True).first()
    if not cfg:
        logger.warning("[MidsceneWeb] 未找到 role=%s 且已启用的模型配置", role)
        return {}

    family = _resolve_model_family(cfg)
    if family:
        # midscene 的 Node 服务从环境变量读取 family，必须显式写入才能被子进��继承
        os.environ['MIDSCENE_MODEL_FAMILY'] = family
    else:
        logger.warning(
            "[MidsceneWeb] 模型 %s 未能推断出 model_family，midscene 将回退为 openai，"
            "国产多模态模型会调用失败", getattr(cfg, 'model_name', ''),
        )

    return {
        'base_url': cfg.base_url or '',
        'api_key': cfg.api_key or '',
        'model_name': cfg.model_name or '',
        'model_family': family,
    }


def _find_chrome_executable() -> str:
    """定位可用的 Chrome/Chromium 可执行文件。

    midscene 0.1.5 的 Web 端底层是 puppeteer，默认使用 **puppeteer 自己下载的
    Chrome**（``~/.cache/puppeteer``）。该目录是运行期产物，容器重建就会丢失，
    表现为 ``Could not find Chrome (ver. xxx)``。而镜像里本来就装了 playwright
    的 chromium（Dockerfile 里 ``playwright install chromium``），这里显式指定
    executable_path 复用它，从而去掉对 puppeteer 下载的依赖。

    优先级：环境变量 MIDSCENE_CHROME_PATH > playwright chromium > 系统 Chrome。
    找不到时返回空串，由调用方回退到 puppeteer 默认行为。
    """
    override = (os.environ.get('MIDSCENE_CHROME_PATH') or '').strip()
    if override and os.path.exists(override):
        return override

    bases = [
        (os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or '').strip(),
        os.path.expanduser('~/.cache/ms-playwright'),
        '/root/.cache/ms-playwright',
        '/ms-playwright',
    ]
    patterns = (
        'chromium-*/chrome-linux/chrome',
        'chromium-*/chrome-linux64/chrome',
        'chromium_headless_shell-*/chrome-linux/headless_shell',
    )
    for pat in patterns:
        for base in bases:
            if not base or not os.path.isdir(base):
                continue
            hits = sorted(glob.glob(os.path.join(base, pat)))
            hits = [h for h in hits if os.path.exists(h)]
            if hits:
                return hits[-1]

    for p in ('/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'):
        if os.path.exists(p):
            return p
    return ''


def _resolve_template(text, context):
    if not text or not isinstance(text, str):
        return text

    def _sub(m):
        key = m.group(1).strip()
        if key in context:
            val = context[key]
            return str(val) if not isinstance(val, str) else val
        logger.warning("[MidsceneWeb] context var %s not found, keeping placeholder", key)
        return m.group(0)

    return CONTEXT_VAR_PATTERN.sub(_sub, text)


def _to_data_url(b64: str) -> str:
    """统一成前端 <img :src> 可直接用的 data URL。"""
    if not b64:
        return ''
    if b64.startswith('data:'):
        return b64
    return 'data:image/png;base64,%s' % b64


class MidsceneWebEngine:
    SUPPORTED_ACTIONS = {
        'aiAct', 'aiQuery', 'aiTap', 'aiInput', 'aiAssert', 'assert', 'wait',
        'navigate', 'screenshot', 'aiWaitFor',
    }

    #: 条件等待默认超时（毫秒）。页面加载/渲染慢时，"等元素出现"比固定 sleep
    #: 更省时间：条件一成立立刻继续，最多等到这个上限（可用步骤 timeout_ms 覆盖）。
    DEFAULT_WAIT_FOR_TIMEOUT_MS = 15000

    def __init__(self, base_url='', model_config=None, headless=True, workspace=None):
        self.base_url = base_url.rstrip('/') if base_url else ''
        self.model_config = model_config or load_midscene_model_config()
        self.headless = headless
        self.workspace = workspace or os.path.join(os.getcwd(), 'media', 'midscene_web')
        os.makedirs(self.workspace, exist_ok=True)
        self.logs = []
        self.context = {}
        self._agent = None

    # ---------------- 生命周期 ----------------
    def _build_config(self):
        from midscene import MidsceneConfig

        cfg = self.model_config or {}
        if not cfg.get('api_key') or not cfg.get('model_name'):
            raise RuntimeError(
                "未配置 Midscene 视觉模型：请在「AI 模型配置」中添加 role=%s 且已启用的"
                "多模态模型（当前 midscene_web 引擎取不到 api_key/model_name）。" % MODEL_ROLE
            )
        return MidsceneConfig(
            base_url=cfg.get('base_url') or '',
            api_key=cfg.get('api_key') or '',
            model_name=cfg.get('model_name') or '',
            model_family=cfg.get('model_family') or '',
        )

    def start(self):
        """显式启动浏览器与 midscene agent（套件执行可复用同一实例）。"""
        if self._agent is not None:
            return self._agent
        try:
            from midscene import MidsceneWebAgent, PuppeteerDriver
        except ImportError as e:
            raise ImportError(
                "未安装 midscene（当前环境需要 midscene>=0.1.5 的 MidsceneWebAgent / "
                "PuppeteerDriver）。请在后端容器执行 pip install midscene。原始错误: %s" % e
            ) from e

        self._log("启动浏览器 (headless=%s)...", self.headless)
        config = self._build_config()
        chrome = _find_chrome_executable()
        driver_kwargs = {'headless': self.headless, 'viewport': DEFAULT_VIEWPORT}
        if chrome:
            # 显式指定镜像自带的 chromium，避免依赖 puppeteer 的 ~/.cache/puppeteer
            driver_kwargs['executable_path'] = chrome
            self._log("使用浏览器: %s", chrome)
        else:
            self._log("未找到本地 Chrome，回退到 puppeteer 自带下载")
        driver = PuppeteerDriver(**driver_kwargs)
        self._agent = MidsceneWebAgent(driver=driver, config=config)
        self._log("Midscene Web 引擎初始化完成 (model=%s, family=%s)",
                  self.model_config.get('model_name'), self.model_config.get('model_family') or '(默认)')
        return self._agent

    def close(self):
        """释放浏览器与 Node 服务。"""
        if self._agent is None:
            return
        try:
            self._agent.destroy()
            self._log("已关闭浏览器")
        except Exception as e:  # noqa: BLE001
            logger.warning("[MidsceneWeb] 关闭浏览器失败: %s", e)
        finally:
            self._agent = None

    # 兼容旧调用名
    _cleanup = close

    def _screenshot(self) -> str:
        """取当前页面截图，返回 data URL（失败或引擎未启动时返回空串）。"""
        if self._agent is None:
            return ''
        try:
            return _to_data_url(self._agent.get_screenshot())
        except Exception as e:  # noqa: BLE001
            logger.warning("[MidsceneWeb] 截图失败: %s", e)
            return ''

    # ---------------- 执行 ----------------
    def execute_steps(self, steps):
        """执行一组步骤；若调用方未提前 start()，执行完自动 close()。"""
        started_here = self._agent is None
        if started_here:
            self.start()
        result = {'status': 'success', 'steps': [], 'context': {}, 'error': None}
        try:
            for idx, step in enumerate(steps or []):
                step_result = self._execute_step(idx, step)
                result['steps'].append(step_result)
                if step_result['status'] == 'failed':
                    result['status'] = 'failed'
                    result['error'] = step_result.get('error', '步骤执行失败')
                    break
            result['context'] = self.context.copy()
        except Exception as e:  # noqa: BLE001
            result['status'] = 'failed'
            result['error'] = str(e)
            self._log("执行异常: %s", e)
        finally:
            if started_here:
                self.close()
        return result

    def _execute_step(self, idx, step):
        action = step.get('action', 'aiAct')
        prompt = _resolve_template(step.get('prompt', ''), self.context)
        value = _resolve_template(step.get('value', ''), self.context)
        wait_ms = step.get('wait_ms', 0)
        name = step.get('name', 'Step %d' % (idx + 1))
        step_result = {
            'index': idx, 'name': name, 'action': action,
            'status': 'success', 'extract': {}, 'assert': {},
        }
        self._log("[步骤 %d] %s: %s", idx + 1, action, prompt or name)
        try:
            if action == 'navigate':
                url = prompt or value
                if url and not url.startswith(('http://', 'https://')):
                    url = self.base_url + '/' + url.lstrip('/')
                self._agent.goto(url)
                self._log("已导航到: %s", url)
            elif action == 'screenshot':
                step_result['screenshot'] = self._screenshot()
            elif action == 'wait':
                time.sleep(wait_ms / 1000.0 if wait_ms else 1)
            elif action == 'aiTap':
                self._agent.ai_tap(step.get('selector_hint') or prompt)
            elif action == 'aiInput':
                self._agent.ai_input(step.get('selector_hint') or prompt, value)
            elif action == 'aiAct':
                self._agent.ai_action(prompt)
            elif action == 'aiQuery':
                data = self._agent.ai_query(prompt)
                step_result['extract']['_query'] = data
                self._log("aiQuery 返回: %s", json.dumps(data, ensure_ascii=False)[:500])
            elif action in ('aiAssert', 'assert'):
                ok, reason = self._do_assert(step)
                step_result['assert'] = {'pass': ok, 'reason': reason}
                if not ok:
                    raise AssertionError(reason or step.get('assert', {}).get('expect', 'AI 断言未通过'))
            elif action == 'aiWaitFor':
                # 条件等待：等目标元素/文案出现再继续，解决"页面还没渲染出来
                # 就去点"导致的偶发失败（语义与真机侧一致）。
                self._wait_for(prompt, step.get('timeout_ms'))
            else:
                raise ValueError("不支持的 action: %s" % action)

            if step.get('extract'):
                extracted = self._do_extract(step['extract'])
                step_result['extract'].update(extracted)
                self.context.update(extracted)

            if step.get('assert') and action not in ('assert', 'aiAssert'):
                ok, reason = self._do_assert(step)
                step_result['assert'] = {'pass': ok, 'reason': reason}
                if not ok:
                    raise AssertionError(reason or step['assert'].get('expect', 'AI 断言未通过'))

            if wait_ms and action != 'wait':
                time.sleep(wait_ms / 1000.0)

        except Exception as e:  # noqa: BLE001
            step_result['status'] = 'failed'
            step_result['error'] = str(e)
            self._log("[步骤 %d] 失败: %s", idx + 1, e)
            step_result['fail_screenshot'] = self._screenshot()

        return step_result

    def _do_extract(self, extract_list):
        out = {}
        for item in extract_list or []:
            key = item.get('key')
            prompt = _resolve_template(item.get('prompt', ''), self.context)
            typ = item.get('type', 'string')
            required = item.get('required', False)
            if not key or not prompt:
                continue
            try:
                raw = self._agent.ai_query(prompt)
                out[key] = self._coerce(raw, typ)
                self._log("extract %s(%s) = %s", key, typ, out[key])
            except Exception as e:  # noqa: BLE001
                self._log("extract %s 失败: %s", key, e)
                if required:
                    raise
        return out

    def _wait_for(self, prompt, timeout_ms=None):
        """等到 prompt 描述的元素/条件出现，超时则抛错（与真机侧同语义）。

        优先用 SDK 原生 waitFor；没有该方法时退化成"轮询 ai_query"的通用实现。
        """
        try:
            timeout_ms = int(timeout_ms or 0) or self.DEFAULT_WAIT_FOR_TIMEOUT_MS
        except (TypeError, ValueError):
            timeout_ms = self.DEFAULT_WAIT_FOR_TIMEOUT_MS
        timeout_ms = max(1000, timeout_ms)
        timeout_s = timeout_ms / 1000.0

        for name in ('ai_wait_for', 'ai_waitfor', 'aiWaitFor'):
            fn = getattr(self._agent, name, None)
            if callable(fn):
                self._log("[等待元素] 等待「%s」出现（超时 %ds）", prompt, int(timeout_s))
                try:
                    fn(prompt, timeout_ms)
                except TypeError:
                    fn(prompt)
                return

        self._log("[等待元素] SDK 无原生 waitFor，改用轮询等待「%s」（超时 %ds）",
                  prompt, int(timeout_s))
        deadline = time.time() + timeout_s
        ask = '回答 true 或 false：当前页面是否满足下面这个条件？\n%s' % prompt
        last = ''
        while time.time() < deadline:
            try:
                last = str(self._agent.ai_query(ask)).strip()
            except Exception as exc:  # noqa: BLE001
                self._log("[等待元素] 查询失败（继续重试）: %s", exc)
                last = ''
            if last.lower().startswith('true'):
                self._log("[等待元素] 条件已成立，继续执行")
                return
            time.sleep(1)
        raise AssertionError(
            '等待超时（%ds）：元素/条件未出现 —— %s。最后一次判断结果：%s'
            % (int(timeout_s), prompt, last or '(无返回)')
        )

    def _do_assert(self, step):
        """执行 AI 断言，返回 (是否通过, 失败原因)。

        实测：midscene 0.1.5 的 ai_assert 通过时返回 None，失败时抛 AssertionError，
        因此**不能用返回值判断**，只能靠是否抛异常。
        """
        assert_cfg = step.get('assert') or {}
        prompt = _resolve_template(
            assert_cfg.get('prompt') or step.get('prompt') or '', self.context)
        if not prompt:
            return True, ''
        try:
            self._agent.ai_assert(prompt)
            return True, ''
        except Exception as e:  # noqa: BLE001
            reason = str(e)
            self._log("断言未通过: %s", reason[:300])
            return False, reason

    @staticmethod
    def _coerce(val, typ):
        if typ == 'number':
            try:
                return float(val)
            except (TypeError, ValueError):
                return val
        if typ == 'boolean':
            return str(val).strip().lower() in ('true', '1', 'yes')
        if typ == 'json':
            try:
                return json.loads(val) if isinstance(val, str) else val
            except (TypeError, ValueError):
                return val
        return val

    # ---------------- Playground ----------------
    def playground_run(self, url, prompt, action='aiAct', value='', selector_hint=''):
        """单条自然语言调试（Web Playground）。"""
        result = {
            'status': 'success', 'logs': [],
            'screenshot_base64': '', 'query_result': None, 'error': None,
        }
        started_here = self._agent is None
        try:
            if started_here:
                self.start()
            if url:
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                self._agent.goto(url)
                self._log("已导航到: %s", url)

            if action == 'aiTap':
                self._agent.ai_tap(selector_hint or prompt)
            elif action == 'aiInput':
                self._agent.ai_input(selector_hint or prompt, value)
            elif action == 'aiQuery':
                data = self._agent.ai_query(prompt)
                result['query_result'] = data
                self._log("aiQuery 结果: %s", json.dumps(data, ensure_ascii=False)[:500])
            elif action == 'aiAssert':
                self._agent.ai_assert(prompt)
                result['query_result'] = {'pass': True}
                self._log("AI 断言通过")
            elif action == 'aiAct':
                self._agent.ai_action(prompt)
            else:
                raise ValueError("Playground 不支持的 action: %s" % action)

            result['screenshot_base64'] = self._screenshot()
        except Exception as e:  # noqa: BLE001
            result['status'] = 'failed'
            result['error'] = str(e)
            self._log("执行失败: %s", e)
            result['screenshot_base64'] = self._screenshot()
        finally:
            result['logs'] = list(self.logs)
            if started_here:
                self.close()
        return result

    def _log(self, fmt, *args):
        msg = fmt % args if args else fmt
        ts = datetime.now().strftime('%H:%M:%S')
        line = "[%s] %s" % (ts, msg)
        self.logs.append(line)
        logger.info("[MidsceneWeb] %s", msg)


__all__ = ['MidsceneWebEngine', 'load_midscene_model_config', 'MODEL_ROLE']
