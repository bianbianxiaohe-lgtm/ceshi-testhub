"""
Midscene iOS UI 自动化执行引擎（WebDriverAgent）。

背景（2026-09-10 实测）：
- Python 包 ``midscene`` 的最新版就是 **0.1.5**，只有 ``agent_android`` / ``agent_web``
  两个子模块，**没有 iOS**。PyPI 上也没有更高版本，所以 iOS 不能走 Python SDK。
- 但官方 JS SDK ``@midscene/ios``（npm 上 1.12.6）是支持 iOS 的，底层同样走
  WebDriverAgent。容器里已经有 Node 22.12（midscene 0.1.5 自带的 node_runtime），
  且 npm registry 可访问。
- 因此本引擎的做法：**自己起一个 @midscene/ios 的 Node JSON-RPC 服务**
  （见同目录 ``midscene_ios_node/service.js``），Python 侧通过 HTTP JSON-RPC 调用它。
  不改动第三方 midscene 包，服务代码随本仓库部署。

模型配置统一取自 ``AIModelConfig(role='midscene_vision', is_active=True)``
（apps.requirement_analysis），与 Web / Android 引擎共用一份配置；
通过环境变量 ``MIDSCENE_MODEL_*`` 传给 Node 服务。

连接参数：``wda_host`` / ``wda_port``（默认 8100），对应 WDA 的 HTTP 端点，
例如 iPhone 插在 192.168.8.71 上并已做端口转发时填 host=192.168.8.71, port=8100。
"""
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime

from .midscene_web_engine import (
    MODEL_ROLE,
    load_midscene_model_config,
    _resolve_model_family,
    _to_data_url,
)
from .popup_handler import dismiss_popups, PopupAdapter

logger = logging.getLogger(__name__)

# 随机弹窗的自动处理，与 Android 引擎共用 popup_handler。
# 设 POPUP_AUTO_DISMISS=0 可关闭（专门测弹窗的用例需要）。
POPUP_AUTO_DISMISS = os.environ.get('POPUP_AUTO_DISMISS', '1') not in ('0', 'false', 'False', '')
POPUP_RETRY_LIMIT = int(os.environ.get('POPUP_RETRY_LIMIT', '2') or 2)

#: Node 服务目录（容器内路径，/root/.midscene 已挂卷持久化）
SERVICE_DIR = os.environ.get(
    'MIDSCENE_IOS_SERVICE_DIR', '/root/.midscene/ios/node_service')

#: 服务端口信息文件（由 Node 服务写入）
PORT_FILE = '/root/.midscene/ios/service.json'

SERVICE_SCRIPT = 'service.js'
NPM_INSTALL_TIMEOUT = 900  # 首次 npm install 最多等 15 分钟
SERVICE_START_TIMEOUT = 120


class MidsceneIOSServiceError(RuntimeError):
    """Node 服务不可用（未安装 / 启动失败 / 端口不通）。"""


def _node_bin() -> str:
    """定位容器内的 node 可执行文件。

    midscene 0.1.5 会把 Node 22 装到 /root/.midscene/node_runtime，系统 PATH 里没有。
    """
    candidates = [
        os.environ.get('MIDSCENE_NODE_BIN', ''),
        '/root/.midscene/node_runtime/bin/node',
        '/usr/local/bin/node',
        '/usr/bin/node',
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return ''


def _npm_cli() -> str:
    """定位 npm 的 cli 入口（node_runtime 里的 npm 脚本没有执行权限，需用 node 调）。"""
    for p in (
        os.environ.get('MIDSCENE_NPM_CLI', ''),
        '/root/.midscene/node_runtime/npm/bin/npm-cli.js',
    ):
        if p and os.path.exists(p):
            return p
    return ''


class MidsceneIOSEngine:
    """iOS 真机 AI 自动化引擎（自然语言 aiAct / aiTap / aiInput / aiQuery / aiAssert）。

    接口对齐 :class:`~apps.ui_automation.midscene_web_engine.MidsceneWebEngine`，
    便于 views 层与测试执行器按同一套契约调用。
    """

    SUPPORTED_ACTIONS = {
        'aiAct', 'aiTap', 'aiInput', 'aiQuery', 'aiAssert', 'aiWaitFor',
        'launch', 'wait', 'screenshot',
    }

    #: 回放模式下能用纯坐标完成、不需要模型的动作。
    #: aiAssert / aiQuery 是有意排除的 —— 断言和取值本质上是语义判断，
    #: 坐标固化不了，必须继续调模型（这是刻意的取舍，不是遗漏）。
    REPLAY_ACTIONS = {'aiTap', 'aiAct', 'aiInput'}

    def __init__(self, wda_host='', wda_port=8100, model_config=None,
                 ai_action_context='', default_bundle_id='',
                 auto_dismiss_popup=None, replay_mode=False):
        self.wda_host = (wda_host or '').strip()
        self.wda_port = int(wda_port or 8100)
        self.model_config = model_config or load_midscene_model_config()
        self.ai_action_context = ai_action_context or (
            'If any location, permission, user agreement popup appears, click agree. '
            'If a login page appears, close it.'
        )
        # 用例绑定的被测应用 bundle id。步骤里写 "launch: 万年历" 这种人类可读
        # 名字时，WDA 会直接 400（它只认 bundle id 或 URL），所以需要有个兜底。
        self.default_bundle_id = (default_bundle_id or '').strip()
        # 弹窗自动处理。None = 用全局默认（环境变量），True/False = 用例配置优先。
        self.auto_dismiss_popup = (
            POPUP_AUTO_DISMISS if auto_dismiss_popup is None else bool(auto_dismiss_popup)
        )
        # 纯坐标回放：用例已固化过，每个 aiTap/aiAct/aiInput 都用上次采到的
        # 坐标直接点，不调模型。任何一步失败由调用方降级回 AI 模式重跑。
        self.replay_mode = bool(replay_mode)
        self.logs = []
        self._session_id = None
        self._port = None

    # ---------------- 基础设施：Node 服务 ----------------
    def _log(self, fmt, *args):
        msg = fmt % args if args else fmt
        ts = datetime.now().strftime('%H:%M:%S')
        self.logs.append('[%s] %s' % (ts, msg))
        logger.info('[MidsceneIOS] %s', msg)

    def _service_ready(self, port):
        try:
            req = urllib.request.Request(
                'http://127.0.0.1:%s/health' % port, method='GET')
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _read_port_file(self):
        try:
            with open(PORT_FILE, 'r', encoding='utf-8') as f:
                info = json.load(f)
            port = int(info.get('port') or 0)
            if port and self._service_ready(port):
                return port
        except Exception:
            return None
        return None

    def _ensure_service(self) -> int:
        """确保 @midscene/ios 的 Node 服务在跑，返回端口。"""
        port = self._read_port_file()
        if port:
            self._port = port
            return port

        node = _node_bin()
        if not node:
            raise MidsceneIOSServiceError(
                '未找到 Node 运行时（期望 /root/.midscene/node_runtime/bin/node）。'
                'iOS 引擎依赖 Node 侧的 @midscene/ios，请先跑一次 Midscene Web 让容器初始化 Node。'
            )

        os.makedirs(SERVICE_DIR, exist_ok=True)
        script = os.path.join(SERVICE_DIR, SERVICE_SCRIPT)
        if not os.path.exists(script):
            raise MidsceneIOSServiceError(
                'Node 服务脚本缺失: %s。请把 apps/ui_automation/midscene_ios_node/service.js '
                '复制到容器内该目录。' % script)

        if not os.path.isdir(os.path.join(SERVICE_DIR, 'node_modules')):
            self._log('首次使用，安装 @midscene/ios（约 1-3 分钟）...')
            npm_cli = _npm_cli()
            if not npm_cli:
                raise MidsceneIOSServiceError(
                    '未找到 npm-cli.js，无法安装 @midscene/ios。')
            try:
                proc = subprocess.run(
                    [node, npm_cli, 'install', '--no-audit', '--no-fund'],
                    cwd=SERVICE_DIR, capture_output=True, timeout=NPM_INSTALL_TIMEOUT)
            except subprocess.TimeoutExpired:
                raise MidsceneIOSServiceError('npm install @midscene/ios 超时')
            if proc.returncode != 0:
                raise MidsceneIOSServiceError(
                    'npm install @midscene/ios 失败: %s'
                    % (proc.stderr or b'').decode('utf-8', 'ignore')[-500:])
            self._log('@midscene/ios 安装完成')

        env = os.environ.copy()
        cfg = self.model_config or {}
        if not cfg.get('api_key') or not cfg.get('model_name'):
            raise MidsceneIOSServiceError(
                '未配置 Midscene 视觉模型：请在「AI 模型配置」中添加 role=%s 且已启用的多模态模型。'
                % MODEL_ROLE)
        base_url = cfg.get('base_url') or ''
        env['MIDSCENE_MODEL_BASE_URL'] = base_url
        env['MIDSCENE_MODEL_API_KEY'] = cfg.get('api_key') or ''
        env['MIDSCENE_MODEL_NAME'] = cfg.get('model_name') or ''
        env['MIDSCENE_MODEL_FAMILY'] = cfg.get('model_family') or _resolve_model_family(cfg) or ''
        # 让 Node 服务把每次 LLM 请求都带上真实上游地址，后端据此转发并统计
        # token（见 views.llm_proxy）。统计是旁路，拿不到也不影响调用。
        env['MIDSCENE_LLM_UPSTREAM'] = base_url
        # 代理地址由 Django 侧注入；为空表示直连，改用估算统计。
        proxy = os.environ.get('MIDSCENE_LLM_PROXY_URL', '').strip()
        if proxy:
            env['MIDSCENE_MODEL_BASE_URL'] = proxy
            self._log('LLM 走用量统计代理: %s -> %s', proxy, base_url)

        port = self._pick_free_port()
        log_path = '/tmp/midscene_ios_service.log'
        logf = open(log_path, 'ab')
        subprocess.Popen(
            [node, script, '--port=%d' % port],
            cwd=SERVICE_DIR, env=env, stdout=logf, stderr=logf, start_new_session=True)

        deadline = time.time() + SERVICE_START_TIMEOUT
        while time.time() < deadline:
            if self._service_ready(port):
                self._port = port
                self._log('iOS Node 服务已就绪 (port=%s)', port)
                return port
            time.sleep(1)
        raise MidsceneIOSServiceError(
            'iOS Node 服务启动超时，详见容器日志 %s' % log_path)

    @staticmethod
    def _pick_free_port():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _rpc(self, method, params=None, timeout=600):
        if not self._port:
            raise MidsceneIOSServiceError('Node 服务未启动')
        payload = json.dumps({
            'jsonrpc': '2.0',
            'id': int(time.time() * 1000),
            'method': method,
            'params': params or {},
        }).encode('utf-8')
        req = urllib.request.Request(
            'http://127.0.0.1:%s/rpc' % self._port,
            data=payload, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            raise MidsceneIOSServiceError('RPC %s 失败: HTTP %s' % (method, e.code))
        except Exception as e:
            raise MidsceneIOSServiceError('RPC %s 失败: %s' % (method, e))
        if data.get('error'):
            raise RuntimeError(data['error'].get('message') or str(data['error']))
        return data.get('result') or {}

    # ---------------- 生命周期 ----------------
    def start(self):
        if self._session_id:
            return self._session_id
        self._ensure_service()
        if not self.wda_host:
            raise ValueError('缺少 wda_host：请在设备配置中填写 WDA 地址（如 192.168.8.71）')
        self._log('连接 WDA: %s:%s', self.wda_host, self.wda_port)
        res = self._rpc('createSession', {
            'wdaHost': self.wda_host,
            'wdaPort': self.wda_port,
            'aiActionContext': self.ai_action_context,
        })
        self._session_id = res.get('sessionId')
        self._log('iOS 会话已建立: %s', self._session_id)
        return self._session_id

    def close(self):
        if not self._session_id:
            return
        try:
            self._rpc('destroySession', {'sessionId': self._session_id}, timeout=60)
            self._log('已断开 iOS 会话')
        except Exception as e:  # noqa: BLE001
            logger.warning('[MidsceneIOS] 断开会话失败: %s', e)
        finally:
            self._session_id = None

    _cleanup = close

    @staticmethod
    def _looks_like_bundle_id(text: str) -> bool:
        """粗略判断是不是 bundle id（com.xxx.yyy 这种反向域名）。"""
        t = (text or '').strip()
        if not t or ' ' in t:
            return False
        return bool(re.match(r'^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)+$', t))

    @staticmethod
    def _looks_like_url(text: str) -> bool:
        t = (text or '').strip().lower()
        return t.startswith('http://') or t.startswith('https://') or '://' in t

    def resolve_launch_target(self, raw_target: str) -> str:
        """把步骤里写的启动目标规范化成 WDA 能接受的 uri。

        WDA 的 /wda/apps/launch 只认真实 bundle id 或 URL。用例里常写
        「launch: 万年历」这种人类可读名字，直接透传会得到
        HTTP 400 (Failed to launch 万年历) —— 这是历史上真实踩过的坑。

        规则：
          1. 已经是 bundle id  -> 原样使用
          2. 是 URL            -> 原样使用
          3. 其他（中文名等）  -> 回退到用例绑定的被测应用 bundle id
        """
        t = (raw_target or '').strip()
        if t and (self._looks_like_bundle_id(t) or self._looks_like_url(t)):
            return t
        if self.default_bundle_id:
            if t:
                self._log('launch 目标「%s」不是 bundle id/URL，改用被测应用: %s',
                          t, self.default_bundle_id)
            return self.default_bundle_id
        raise ValueError(
            '无法启动「%s」：它既不是 bundle id / URL，用例也没有绑定被测应用'
            '（applicationId）。请在用例的「应用配置」里选好被测应用，'
            '或把该步骤的 prompt 改成真实 bundle id。' % (t or '(空)')
        )

    def launch_app(self, bundle_id=''):
        """启动 App（bundle id）或打开 URL。"""
        target = self.resolve_launch_target(bundle_id)
        if not target:
            return
        self._rpc('launch', {'sessionId': self._session_id, 'uri': target}, timeout=180)
        self._log('已启动: %s', target)

    def screenshot(self) -> str:
        res = self._rpc('screenshot', {'sessionId': self._session_id}, timeout=120)
        return _to_data_url(res.get('base64') or '')

    # ---------------- 执行 ----------------
    def execute_steps(self, steps):
        """串行执行一组步骤（与 Web 引擎同契约）。

        空步骤（既没有 action 也没有 prompt）直接**判失败并说明原因**：
        以前会给 action 兜底成 aiAct、prompt 兜底成空串，于是拿着空提示词去问
        视觉模型，模型随便点一下就返回 success —— 用例明明什么都没配，执行却显示
        「通过」，用户看到的就是"步骤没按我写的执行"。
        """
        steps = [s for s in (steps or []) if isinstance(s, dict)]
        # 空步骤不启动会话，省一次真机连接
        invalid = [i for i, s in enumerate(steps) if not self._step_has_content(s)]
        if invalid:
            bad = invalid[0]
            msg = ('第 %d 个步骤是空的：既没有 action 也没有 prompt。'
                   '请到「用例编辑」里补全该步骤（或删除它）' % (bad + 1))
            self._log('%s', msg)
            return {
                'status': 'failed',
                'steps': [{'index': bad, 'name': 'Step %d' % (bad + 1),
                           'action': '', 'status': 'failed', 'error': msg,
                           'extract': {}, 'assert': {}}],
                'error': msg,
            }

        started_here = self._session_id is None
        if started_here:
            self.start()
        result = {'status': 'success', 'steps': [], 'error': None}
        try:
            for idx, step in enumerate(steps):
                sr = self._execute_step(idx, step)

                # 随机弹窗（权限请求 / 隐私协议 / 开屏广告 ……）随时可能冒出来，
                # 挡住目标元素就会让这一步失败。这里做「关弹窗 + 重试」，
                # 正常路径（没弹窗）零额外开销。Android 侧同一套逻辑。
                try_count = 0
                while (sr['status'] == 'failed'
                       and self.auto_dismiss_popup
                       and try_count < POPUP_RETRY_LIMIT):
                    try_count += 1
                    self._log('[步骤 %d] 失败，检测是否为弹窗干扰（第 %d/%d 次重试）...',
                              idx + 1, try_count, POPUP_RETRY_LIMIT)
                    if dismiss_popups(self._popup_adapter()) == 0:
                        self._log('[步骤 %d] 未发现弹窗，不再重试', idx + 1)
                        break
                    sr = self._execute_step(idx, step)
                    if sr['status'] != 'failed':
                        self._log('[步骤 %d] 关闭弹窗后重试成功', idx + 1)
                        break

                result['steps'].append(sr)
                if sr['status'] == 'failed':
                    result['status'] = 'failed'
                    result['error'] = sr.get('error', '步骤执行失败')
                    break
        except Exception as e:  # noqa: BLE001
            result['status'] = 'failed'
            result['error'] = str(e)
            self._log('执行异常: %s', e)
        finally:
            if started_here:
                self.close()
        return result

    @staticmethod
    def _step_has_content(step):
        """步骤是否可执行：引用步骤看 ref，内联步骤看 action/prompt。"""
        if not isinstance(step, dict):
            return False
        if str(step.get('ref') or '').strip():
            return True
        if str(step.get('action') or '').strip():
            return True
        return bool(str(step.get('prompt') or '').strip())

    def _execute_step(self, idx, step):
        action = step.get('action', 'aiAct')
        prompt = step.get('prompt', '') or ''
        value = step.get('value', '') or ''
        name = step.get('name', 'Step %d' % (idx + 1))
        wait_ms = step.get('wait_ms', 0)
        sr = {'index': idx, 'name': name, 'action': action,
              'status': 'success', 'extract': {}, 'assert': {}}
        self._log('[步骤 %d] %s: %s', idx + 1, action, prompt or name)
        try:
            # 需要视觉模型的动作必须有 prompt，否则是在"盲操作"，
            # 必须报错而不是让模型瞎猜后返回成功。
            if action in ('aiAct', 'aiTap', 'aiInput', 'aiQuery', 'aiAssert', 'aiWaitFor') \
                    and not str(prompt).strip():
                raise ValueError(
                    '步骤 %d（%s）没有填写提示词 prompt，无法执行' % (idx + 1, action)
                )
            if action == 'launch':
                self.launch_app(prompt or value)
            elif action == 'screenshot':
                sr['screenshot'] = self.screenshot()
            elif action == 'wait':
                time.sleep(wait_ms / 1000.0 if wait_ms else 1)
            elif action in self.SUPPORTED_ACTIONS:
                # ---- 纯坐标回放 ----
                # steps_frozen_at 非空表示这条用例已经固化过，每步都带着
                # 上次成功执行时采到的坐标。用坐标直接点，完全不经过视觉
                # 模型（也不用跑定位采样），这是"重复跑零 token"的关键路径。
                if self.replay_mode and self._step_has_coords(step) and action in self.REPLAY_ACTIONS:
                    self._replay_step(action, step, prompt, value)
                    return sr

                rpc_params = {
                    'sessionId': self._session_id,
                    'prompt': prompt,
                    'value': value,
                    'locate': step.get('selector_hint') or '',
                }
                res = self._rpc(action, rpc_params)
                # 真实 usage 由 LLM 代理记录；代理没生效时按截图尺寸估算，
                # 保证"这次执行花了多少"永远有数字可看。
                try:
                    from .llm_usage import record_step_estimate
                    record_step_estimate(prompt=prompt)
                except Exception:  # noqa: BLE001
                    pass
                if action == 'aiQuery':
                    sr['extract']['_query'] = res.get('result')
                elif action in ('aiAssert',):
                    sr['assert'] = {'pass': True, 'reason': ''}

                # 采到的定位结果（坐标）留下来，供「固化为脚本」使用
                loc = res.get('location') or {}
                if loc.get('ok') and loc.get('center'):
                    sr['location'] = {
                        'center': loc.get('center'),
                        'rect': loc.get('rect'),
                        'dpr': loc.get('dpr'),
                        'target': loc.get('prompt') or prompt,
                    }
                elif loc.get('error'):
                    self._log('[步骤 %d] 定位采样未成功（不影响执行）: %s',
                              idx + 1, loc.get('error'))
            else:
                raise ValueError('不支持的 action: %s' % action)

            if action == 'aiAssert':
                sr['assert'] = {'pass': True, 'reason': ''}

            if wait_ms and action != 'wait':
                time.sleep(wait_ms / 1000.0)

            # 每步执行后都留一张实拍截图：报告里要能"步骤 ↔ 画面"一一对应。
            # 之前只有显式 screenshot 动作才截、失败才截，所以成功的用例
            # 报告里一张图都没有，用户无法确认这一步到底做成什么样。
            if action not in ('screenshot',):
                try:
                    sr['screenshot'] = self.screenshot()
                except Exception as exc:  # noqa: BLE001
                    # 截图失败不能影响用例结果，记一笔即可
                    self._log('[步骤 %d] 截图失败: %s', idx + 1, exc)
        except Exception as e:  # noqa: BLE001
            sr['status'] = 'failed'
            sr['error'] = str(e)
            self._log('[步骤 %d] 失败: %s', idx + 1, e)
            try:
                sr['fail_screenshot'] = self.screenshot()
            except Exception:  # noqa: BLE001
                pass
        return sr

    @staticmethod
    def _step_has_coords(step):
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

    def _replay_step(self, action, step, prompt, value):
        """纯坐标回放一步：直接按固化坐标点击，不调用任何视觉模型。

        失败就抛异常，由调用方（_run_midscene）决定是否降级回 AI 模式。
        """
        cx = int(step['center_x'])
        cy = int(step['center_y'])
        self._log('[回放] %s -> (%d, %d)  [零模型]', action, cx, cy)

        if action == 'aiInput':
            # 先点输入框获得焦点，再输入文本
            self._rpc('tapPoint', {'sessionId': self._session_id, 'x': cx, 'y': cy})
            time.sleep(0.4)
            self._rpc('inputText', {'sessionId': self._session_id, 'text': value or ''})
        else:
            # aiTap / aiAct 都退化成"点这个坐标"
            self._rpc('tapPoint', {'sessionId': self._session_id, 'x': cx, 'y': cy})

        wait_ms = int(step.get('wait_ms') or 0)
        if wait_ms:
            time.sleep(wait_ms / 1000.0)

    def _popup_adapter(self):
        """把本引擎的能力包成 popup_handler 需要的接口。"""
        return _IOSPopupAdapter(self)

    def playground_run(self, prompt, action='aiAct', value='', bundle_id='',
                       launch_first=True):
        """Playground 单条自然语言调试（iOS）。"""
        result = {
            'status': 'success', 'logs': [],
            'screenshot_base64': '', 'query_result': None, 'error': None,
        }
        started_here = self._session_id is None
        try:
            if started_here:
                self.start()
            if launch_first and bundle_id:
                self.launch_app(bundle_id)
                time.sleep(3)

            if action == 'aiAct':
                self._rpc('aiAct', {'sessionId': self._session_id, 'prompt': prompt})
            elif action == 'aiTap':
                self._rpc('aiTap', {'sessionId': self._session_id, 'prompt': prompt})
            elif action == 'aiInput':
                self._rpc('aiInput', {
                    'sessionId': self._session_id, 'prompt': prompt, 'value': value})
            elif action == 'aiQuery':
                res = self._rpc('aiQuery', {'sessionId': self._session_id, 'prompt': prompt})
                result['query_result'] = res.get('result')
                self._log('aiQuery 结果: %s', json.dumps(res.get('result'), ensure_ascii=False)[:500])
            elif action == 'aiAssert':
                self._rpc('aiAssert', {'sessionId': self._session_id, 'prompt': prompt})
                result['query_result'] = {'pass': True}
                self._log('AI 断言通过')
            elif action == 'aiWaitFor':
                self._rpc('aiWaitFor', {'sessionId': self._session_id, 'prompt': prompt})
            else:
                raise ValueError('Playground 不支持的 action: %s' % action)

            result['screenshot_base64'] = self.screenshot()
        except Exception as e:  # noqa: BLE001
            result['status'] = 'failed'
            result['error'] = str(e)
            self._log('执行失败: %s', e)
            try:
                result['screenshot_base64'] = self.screenshot()
            except Exception:  # noqa: BLE001
                pass
        finally:
            result['logs'] = list(self.logs)
            if started_here:
                self.close()
        return result


class _IOSPopupAdapter(PopupAdapter):
    """把 iOS 引擎的 JSON-RPC 调用适配成 popup_handler 的接口。"""

    def __init__(self, engine):
        self._engine = engine

    def query(self, prompt: str):
        res = self._engine._rpc('aiQuery', {
            'sessionId': self._engine._session_id,
            'prompt': prompt,
        })
        return res.get('result')

    def tap(self, target: str) -> None:
        self._engine._rpc('aiTap', {
            'sessionId': self._engine._session_id,
            'prompt': target,
        })

    def log(self, msg: str) -> None:
        self._engine._log('%s', msg)


__all__ = ['MidsceneIOSEngine', 'MidsceneIOSServiceError']
