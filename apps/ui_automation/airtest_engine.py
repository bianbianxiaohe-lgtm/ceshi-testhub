"""
纯 Airtest 录制引擎（直连设备 ADB，无需 Appium Server）

与 AppiumTestEngine 保持相同接口，使现有录制视图（start_recording / recording_page /
record_action / generate_recording_case）可以无缝切换到 Airtest 驱动：

  - connect()                      建立设备连接
  - activate_app(pkg)              唤起 App
  - disconnect()                   断开
  - dump_page_elements()           返回与 smart_locator.dump_page_elements 同 schema 的控件列表
  - get_screenshot_base64()        返回截图 base64，供 _get_screenshot_base64 复用
  - execute_step(step_data)        在真机真实执行某一步，返回 {success, error}

连接地址：
  - Android: Android://{adb_host}:{adb_port}/{serial}
            默认 adb_host=host.docker.internal，adb_port=5037（宿主机 adb server 需对容器可达）。
  - iOS    : iOS:///{wda_url}
            其中 wda_url 为设备端 WDA(WebDriverAgent) 经 iproxy/tidevice/wdaproxy 代理后的
            HTTP 地址，如 http://host.docker.internal:8100 或 http://192.168.1.10:8100。
            iOS 真机无需 adb，不依赖宿主 adb server。
"""
import base64
import time

import cv2
import numpy as np
from django.conf import settings


class AirtestRecordingEngine:
    """Airtest 移动端录制引擎（Android）"""

    # 标记，供 smart_locator.dump_page_elements 分派
    engine_type = 'airtest'

    def __init__(self, serial=None, platform='android', app_package='',
                 adb_host=None, adb_port=None, wda_url=None, new_command_timeout=600):
        self.serial = serial
        self.platform = (platform or 'android').lower()
        self.app_package = app_package or ''
        self.adb_host = adb_host or getattr(settings, 'AIRTEST_ADB_HOST', 'host.docker.internal')
        self.adb_port = int(adb_port or getattr(settings, 'AIRTEST_ADB_PORT', 5037))
        # iOS WDA 地址（http://host:port），Airtest 模式连 iOS 时使用
        self.wda_url = wda_url or getattr(settings, 'AIRTEST_IOS_WDA_URL', 'http://127.0.0.1:8100')
        self.new_command_timeout = new_command_timeout
        self.device = None
        self.poco = None
        self.display_size = (1080, 2400)  # 兜底，connect 后会被真实值覆盖
        # 兼容现有录制辅助函数对 engine.driver.get_screenshot_base64 的调用
        self.driver = self

    # ==================== 连接管理 ====================

    def _build_uri(self):
        if self.platform == 'ios':
            # Airtest iOS URI 形如 iOS:///http://host:port（三段斜杠）。
            # 支持直接传入 iOS:// 开头或纯 http:// 开头的 wda_url。
            wda = (self.wda_url or '').strip()
            if wda.startswith('iOS://'):
                return wda
            if wda.startswith('http'):
                return f"iOS:///{wda}"
            # 兜底：当作 host:port
            return f"iOS:///{wda}"
        base = f"Android://{self.adb_host}:{self.adb_port}"
        return f"{base}/{self.serial}" if self.serial else f"{base}/"

    def connect(self):
        """连接设备（Android 直连宿主机 adb；iOS 连 WDA HTTP 地址）"""
        from airtest.core.api import connect_device

        self.device = connect_device(self._build_uri())

        try:
            di = self.device.display_info
            w = int(di.get('width') or 0)
            h = int(di.get('height') or 0)
            if w and h:
                self.display_size = (w, h)
        except Exception:
            pass

        # 初始化 Poco（best-effort，失败则退化为坐标操作）
        try:
            if self.platform == 'ios':
                from poco.drivers.ios import iosPoco
                self.poco = iosPoco()
            else:
                from poco.drivers.android.uiautomation import AndroidUiautomationPoco
                self.poco = AndroidUiautomationPoco(
                    self.device, use_airtest_input=True, screenshot_each_action=False
                )
        except Exception:
            self.poco = None

        if self.app_package:
            try:
                self.device.start_app(self.app_package)
            except Exception:
                pass
        return True

    def activate_app(self, package_name):
        """唤起 App（与 Appium 引擎同名方法，供 start_recording 统一调用）"""
        if package_name:
            try:
                self.device.start_app(package_name)
            except Exception:
                pass

    def disconnect(self):
        """断开（Airtest 会话无需显式 quit，置空即可）"""
        self.device = None
        self.poco = None

    # ==================== 截图 / 层级 ====================

    def get_screenshot_base64(self):
        """Airtest snapshot() 返回 numpy 数组，用 cv2 编码为 PNG base64。
        
        fallback: 若 snapshot() 失败则走 adb shell screencap -p 确保一定能拿到截图。
        """
        # 方案A: Airtest 原生 snapshot()
        try:
            img = self.device.snapshot()
            if isinstance(img, np.ndarray):
                ok, buf = cv2.imencode('.png', img)
                if ok:
                    return base64.b64encode(buf).decode('utf-8')
            # 部分版本返回 PIL Image
            import io
            b = io.BytesIO()
            img.save(b, 'PNG')
            return base64.b64encode(b.getvalue()).decode('utf-8')
        except Exception:
            pass
        
        # 方案B fallback: adb shell screencap -p（兼容性最好）
        try:
            out = self.device.shell('screencap -p')
            if out and len(out) > 100:
                return base64.b64encode(out).decode('utf-8')
        except Exception:
            pass
        
        raise RuntimeError('截图失败:snapshot()与adb screencap均不可用')

    def dump_page_elements(self):
        """用 Poco dump 生成与 smart_locator.dump_page_elements 同 schema 的控件列表

        返回字段：chinese_name, strategy('id'|'xpath'), value, text, class_name,
                 clickable, bounds("[x1,y1][x2,y2]"), center_x, center_y
        Poco 的 pos/size 为屏幕归一化坐标，乘以 display_size 得到像素坐标。
        """
        if self.poco is None:
            return []
        tree = self.poco.dump()
        root = tree.get('root', tree) if isinstance(tree, dict) else tree
        w, h = self.display_size
        out = []
        seen = set()

        def walk(node):
            if not isinstance(node, dict):
                return
            payload = node.get('payload', {}) or {}
            # iOS Poco 无 resourceId，用 name(accessibility identifier) 作为定位值；
            # Android 既有 resourceId 也有 name，优先 resourceId。
            rid = (payload.get('resourceId') or payload.get('name') or '').strip()
            text = (payload.get('text') or '').strip()
            typ = payload.get('type') or payload.get('name') or ''
            visible = payload.get('visible', True)
            touchable = payload.get('touchable', False)
            pos = payload.get('pos')
            size = payload.get('size')

            cx = cy = x1 = y1 = x2 = y2 = None
            bstr = ''
            if pos and size and w and h:
                sw, sh = size[0], size[1]
                cx = int((pos[0] - sw / 2) * w)
                cy = int((pos[1] - sh / 2) * h)
                x1, y1 = cx, cy
                x2 = int((pos[0] + sw / 2) * w)
                y2 = int((pos[1] + sh / 2) * h)
                bstr = f"[{x1},{y1}][{x2},{y2}]"

            if rid:
                strategy = 'id'
                value = rid
                label = text or rid.split(':id/')[-1]
            elif text and visible:
                strategy = 'xpath'
                value = f"//*[@text='{text}']"
                label = text
            else:
                strategy = None

            if strategy and visible:
                # 按 (策略, 值, 位置) 去重：RecyclerView 内多个子项常共用同一
                # resourceId/文本，仅按前两者去重会把子项全部折叠成容器本身，
                # 导致点选坐标反查命中容器而非具体子项。加入 bounds 区分位置。
                key = (strategy, value, bstr)
                if key not in seen:
                    seen.add(key)
                    out.append({
                        'chinese_name': label,
                        'strategy': strategy,
                        'value': value,
                        'text': text,
                        'class_name': typ,
                        'clickable': bool(touchable),
                        'bounds': bstr,
                        'center_x': cx,
                        'center_y': cy,
                    })

            for child in node.get('children', []) or []:
                walk(child)

        walk(root)
        return out

    # ==================== 步骤执行 ====================

    def execute_step(self, step_data: dict) -> dict:
        """在真机真实执行一步，返回 {success, error}"""
        result = {'success': False, 'error': None, 'screenshot': None}
        try:
            action_type = (step_data.get('action_type') or '').lower()
            element = step_data.get('element') or {}
            input_value = step_data.get('input_value', '') or ''
            wait_time = step_data.get('wait_time', 0) or 0

            if wait_time > 0:
                time.sleep(wait_time / 1000.0)

            if action_type in ('click', 'tap'):
                self._do_click(element)
            elif action_type == 'double_tap':
                self._do_double_tap(element)
            elif action_type == 'long_press':
                self._do_long_press(element)
            elif action_type in ('fill', 'input'):
                self._do_input(element, input_value)
            elif action_type == 'clear':
                self._do_clear(element)
            elif action_type == 'swipe':
                self._do_swipe(element, input_value)
            elif action_type == 'scroll':
                self._do_scroll(element, input_value)
            elif action_type == 'screenshot':
                self.device.snapshot()
            elif action_type == 'wait':
                time.sleep(float(input_value or 1))
            elif action_type == 'back':
                self.device.shell('input keyevent 4')
            elif action_type == 'home':
                self.device.shell('input keyevent 3')
            elif action_type == 'launch_app':
                if self.app_package:
                    self.device.start_app(self.app_package)
            elif action_type == 'close_app':
                if self.app_package:
                    self.device.stop_app(self.app_package)
            elif action_type in ('assert', 'getText'):
                rid = element.get('value') if element.get('locator_strategy') == 'id' else None
                if rid and self.poco is not None:
                    exists = bool(self.poco(rid).exists())
                    if action_type == 'assert' and not exists:
                        raise AssertionError(f"断言元素不存在: {rid}")
            else:
                raise ValueError(f"不支持的操作类型: {action_type}")

            result['success'] = True
            # 每步成功后自动截屏，返回 base64 供前端逐步查看
            try:
                b64 = self.get_screenshot_base64()
                result['screenshot'] = f'data:image/png;base64,{b64}' if b64 else None
            except Exception:
                result['screenshot'] = None
        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            # 失败时自动截屏，返回 base64 供前端展示
            try:
                b64 = self.get_screenshot_base64()
                result['screenshot'] = f'data:image/png;base64,{b64}' if b64 else None
            except Exception:
                result['screenshot'] = None
        return result

    # ---- 具体操作（坐标走 input tap/swipe，与 uiautomator 同坐标系；rid 优先用 Poco） ----

    def _resource_id(self, element):
        if not element:
            return None
        return element.get('value') if element.get('locator_strategy') == 'id' else None

    def _do_click(self, element):
        rid = self._resource_id(element)
        cx, cy = element.get('center_x'), element.get('center_y')
        # 镜像点选录制场景：坐标精确命中用户点击的真实控件。RecyclerView 内
        # 多个子项常共用同一 resourceId，poco(rid).click() 会点到第一个而非用户
        # 实际点的那个，因此优先用坐标（input tap）。
        if cx is not None and cy is not None:
            self.device.shell(f'input tap {int(cx)} {int(cy)}')
        elif rid and self.poco is not None:
            self.poco(rid).click()
        else:
            raise ValueError('点击操作缺少目标元素或坐标')

    def _do_double_tap(self, element):
        rid = self._resource_id(element)
        cx, cy = element.get('center_x'), element.get('center_y')
        if cx is not None and cy is not None:
            self.device.shell(f'input tap {int(cx)} {int(cy)}')
            time.sleep(0.08)
            self.device.shell(f'input tap {int(cx)} {int(cy)}')
        elif rid and self.poco is not None:
            self.poco(rid).double_click()
        else:
            raise ValueError('双击操作缺少目标元素或坐标')

    def _do_long_press(self, element):
        rid = self._resource_id(element)
        cx, cy = element.get('center_x'), element.get('center_y')
        if cx is not None and cy is not None:
            self.device.shell(f'input swipe {int(cx)} {int(cy)} {int(cx)} {int(cy)} 800')
        elif rid and self.poco is not None:
            self.poco(rid).long_click()
        else:
            raise ValueError('长按操作缺少目标元素或坐标')

    def _do_input(self, element, text):
        rid = self._resource_id(element)
        cx, cy = element.get('center_x'), element.get('center_y')
        if rid and self.poco is not None:
            self.poco(rid).set_text(text)
        else:
            if cx is not None and cy is not None:
                self.device.shell(f'input tap {int(cx)} {int(cy)}')
            self.device.text(text, enter=False)

    def _do_clear(self, element):
        rid = self._resource_id(element)
        cx, cy = element.get('center_x'), element.get('center_y')
        if rid and self.poco is not None:
            self.poco(rid).set_text('')
            return
        if cx is not None and cy is not None:
            self.device.shell(f'input tap {int(cx)} {int(cy)}')
        for _ in range(50):
            self.device.shell('input keyevent 67')

    def _swipe_points(self, element, direction, ratio):
        # 优先把 direction(即 record_action 传入的 input_value) 解析为坐标 "x1,y1,x2,y2"。
        # 录制时前端两点滑动传的就是 "sx,sy,ex,ey"，必须按坐标滑动而非忽略。
        if direction:
            parts = str(direction).split(',')
            if len(parts) == 4:
                try:
                    return (int(parts[0]), int(parts[1])), (int(parts[2]), int(parts[3]))
                except ValueError:
                    pass
        w, h = self.display_size
        cx = element.get('center_x') or (w // 2)
        cy = element.get('center_y') or (h // 2)
        offset = int(min(w, h) * ratio)
        direction = (direction or 'up').lower()
        start = (cx, cy)
        if direction == 'up':
            end = (cx, cy - offset)
        elif direction == 'down':
            end = (cx, cy + offset)
        elif direction == 'left':
            end = (cx - offset, cy)
        elif direction == 'right':
            end = (cx + offset, cy)
        else:
            end = (cx, cy - offset)
        return start, end

    def _do_swipe(self, element, direction):
        (x1, y1), (x2, y2) = self._swipe_points(element, direction, 0.3)
        self.device.shell(f'input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} 400')

    def _do_scroll(self, element, direction):
        (x1, y1), (x2, y2) = self._swipe_points(element, direction, 0.6)
        self.device.shell(f'input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} 400')

    # ==================== 自动捕获（镜像点击 + 焦点辅助） ====================
    #
    # 重要：无 root 的 Android 10+ 因 SELinux 限制，adb 无法读取 /dev/input/event*，
    # 无法"被动监听真机触摸"。这正是 Airtest IDE 录制也不是靠监听手机触摸，
    # 而是靠在 IDE 的**设备镜像窗口上用鼠标点击**来录制。
    #
    # 因此本平台采用与 Airtest IDE 完全一致的方案：
    #   主路径 —— 前端"手机镜像截图"上点击控件即自动记录一步（见 TestCaseManager.vue 的
    #            onScreenshotClick：点击坐标 → 反查 Poco 控件 → 自动 record_action）。
    #   辅助   —— 后台线程仅做"焦点/输入"辅助检测（捕获用户在真机输入框打字等
    #            镜像点击覆盖不到的场景），普通点击交由前端镜像点击负责，避免重复记录。

    def start_auto_capture(self, callback):
        """启动后台多信号轮询线程。callback(step_dict) 在检测到用户操作时调用。

        兼容无 root 的 Android 10+ 设备，无需读取 /dev/input/event*。
        """
        import threading, time as _time, hashlib, re
        print(f"[AUTO-CAP] ====== start_auto_capture 被调用 (poco={'OK' if self.poco else 'None'}) ======", flush=True)

        if self.poco is None:
            return False

        self._auto_stop = False
        self._getevent_active = False
        self._getevent_proc = None
        self._getevent_thread = None
        COOLDOWN = 2.0        # 同一操作最小间隔(秒)
        POLL_INTERVAL = 0.8   # 轮询间隔(秒)

        # ===================== 信号采集器 =====================

        def _get_focused_node():
            """返回当前 focusable && focused 的叶子节点，或 None"""
            try:
                root = self.poco()
                stack = list(root.children())
                while stack:
                    node = stack.pop(0)
                    try:
                        a = node.attr or {}
                    except Exception:
                        continue
                    try:
                        ch = node.children()
                        if ch:
                            stack.extend(ch)
                    except Exception:
                        pass
                    if not a.get('focusable'):
                        continue
                    if a.get('focused'):
                        pos = None
                        try:
                            p = a.get('pos')
                            if p and len(p) == 2:
                                w2, h2 = self.display_size
                                pos = (int(p[0] * w2), int(p[1] * h2))
                        except Exception:
                            pass
                        return {
                            'text': str(a.get('text') or ''),
                            'name': str(a.get('name') or a.get('text') or a.get('type', '?')),
                            'type': str(a.get('type') or ''),
                            'pos': pos,
                        }
            except Exception:
                pass
            return None

        def _get_current_activity():
            """获取当前前台 Activity 名，或 None"""
            try:
                out = self.device.shell('dumpsys activity activities | grep mResumedActivity')
                if out:
                    m = re.search(r'(\S+/\S+)\s', out.strip())
                    if m:
                        return m.group(1)
            except Exception:
                pass
            return None

        def _build_ui_fingerprint():
            """构建当前 UI 树的轻量指纹：可见控件的 (resourceId前缀, text前20字, 可见区域) 集合 hash"""
            try:
                dump = self.poco.dump()
                root = dump.get('root', dump) if isinstance(dump, dict) else dump
                parts = []
                _collect_fp_parts(root, parts, depth=0)
                raw = '|'.join(parts)
                if raw:
                    return hashlib.md5(raw.encode('utf-8', errors='ignore')).hexdigest()[:16]
            except Exception:
                pass
            return None

        def _get_all_texts():
            """收集所有有 text 的控件的 text 拼接，用于检测全局文本变化"""
            try:
                dump = self.poco.dump()
                root = dump.get('root', dump) if isinstance(dump, dict) else dump
                texts = []
                _collect_texts(root, texts)
                return '||'.join(texts)
            except Exception:
                return ''

        def _collect_fp_parts(node, parts, depth=0):
            if not isinstance(node, dict):
                return
            p = node.get('payload') or {}
            if p.get('visible') and depth < 20:
                rid = (p.get('resourceId') or '')[:40]
                txt = str(p.get('text') or '')[:20]
                bnd = p.get('bounds') or ()
                parts.append(f'{rid}:{txt}:{bnd}')
            for c in (node.get('children') or []):
                _collect_fp_parts(c, parts, depth + 1)

        def _collect_texts(node, texts):
            if not isinstance(node, dict):
                return
            p = node.get('payload') or ''
            if isinstance(p, dict):
                t = (p.get('text') or '').strip()
                if t and p.get('visible'):
                    texts.append(t)
            for c in (node.get('children') or []):
                _collect_texts(c, texts)

        # ===================== 步骤发射器 =====================

        def _emit(action_type, description, el_info=None, input_value=''):
            """构造并发射步骤字典"""
            el = el_info or {
                'locator_strategy': 'coordinate',
                'value': '0,0',
                'name': '',
                'center_x': None,
                'center_y': None,
            }
            step = {
                'step_number': 1,
                'action_type': action_type,
                'element': el,
                'input_value': input_value,
                'wait_time': 0,
                'assert_type': '',
                'assert_value': '',
                'description': f'自动捕获: {description}',
                'center_x': el.get('center_x'),
                'center_y': el.get('center_y'),
            }
            try:
                callback(step)
            except Exception:
                pass

        # ===================== 状态机 & 主循环 =====================

        state = {
            'focus_name': '', 'focus_text': '', 'last_emit': 0.0,
        }

        def _loop():
            while not self._auto_stop:
                _time.sleep(POLL_INTERVAL)
                if self._auto_stop:
                    break

                try:
                    now = _time.time()
                    cooled = now - state['last_emit'] > COOLDOWN
                    if not cooled:
                        continue

                    # ---- 采集焦点信号（仅用于捕获输入框等可聚焦控件的操作）----
                    # 注意：普通点击(按钮/列表项)由前端"镜像点击即录制"覆盖，
                    # 后台线程不做被动触摸监听（无 root Android 10+ 不可行）。
                    cur_focus = _get_focused_node()
                    emitted = False

                    # ====== 信号A: 焦点切换 → 点击到可聚焦控件（如输入框获焦）======
                    # 注：若真机被动监听(getevent)已启用，点击由 getevent 记录，
                    # 此处仅同步焦点状态供信号B(输入)判断，避免重复记录 click。
                    focus_name = cur_focus['name'] if cur_focus else ''
                    focus_changed = bool(focus_name and focus_name != state.get('focus_name', ''))
                    if focus_changed and not self._getevent_active:
                        cx, cy = cur_focus['pos'] or (None, None)
                        desc = focus_name
                        if len(desc) > 42:
                            desc = desc[:40] + '..'
                        _emit('click', f'点击 [{desc}]', {
                            'locator_strategy': 'poco_text',
                            'value': focus_name,
                            'name': focus_name,
                            'center_x': cx,
                            'center_y': cy,
                        })
                        state['last_emit'] = now
                        emitted = True
                    if focus_changed:
                        state['focus_name'] = focus_name
                        state['focus_text'] = cur_focus['text'] if cur_focus else ''

                    # ====== 信号B: 焦点不变但文本增长 → 输入 ======
                    if cur_focus and focus_name == state.get('focus_name', '') \
                            and not emitted:
                        cur_txt = cur_focus['text']
                        prev_txt = state.get('focus_text', '')
                        if cur_txt and cur_txt != prev_txt \
                                and len(cur_txt) > len(prev_txt):
                            new_part = cur_txt[len(prev_txt):]
                            cx, cy = cur_focus['pos'] or (None, None)
                            _emit('input', f'输入 [{focus_name}] → "{new_part}"', {
                                'locator_strategy': 'poco_text',
                                'value': focus_name,
                                'name': focus_name,
                                'center_x': cx,
                                'center_y': cy,
                            }, input_value=new_part)
                            state['focus_text'] = cur_txt
                            state['last_emit'] = now
                            emitted = True

                    # ---- 更新状态快照 ----
                    if cur_focus:
                        state['focus_text'] = cur_focus['text']

                except Exception as e:
                    try:
                        self._auto_error = str(e)
                    except Exception:
                        pass
                    _time.sleep(1.0)

        # ===================== 真机被动触摸监听（adb getevent，仅 Android）=====================
        # 无 root Android 10+ 多数设备仍可用 `adb shell getevent` 读取触摸屏事件
        # （本机已验证小米 houji 可读 /dev/input/event7），实现"真机点击→自动记录"。
        # iOS 无 adb，不走 getevent，自动捕获依赖前端镜像点击 + Poco 焦点轮询。
        print("[AUTO-CAP] start_auto_capture: 准备启动 _getevent_loop 线程...", flush=True)
        getevent_started = False
        if self.platform != 'ios':
            try:
                gt = threading.Thread(target=self._getevent_loop, args=(callback,), daemon=True)
                gt.start()
                self._getevent_thread = gt
                getevent_started = True
                print("[AUTO-CAP] start_auto_capture: _getevent_loop 线程已启动", flush=True)
            except Exception as e:
                print(f"[AUTO-CAP] start_auto_capture: 启动 _getevent_loop 失败: {e}", flush=True)
                getevent_started = False
        else:
            print("[AUTO-CAP] iOS 设备跳过 getevent（无 adb），自动捕获仅依赖镜像点击+焦点轮询", flush=True)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        self._auto_thread = t
        return True if (getevent_started or self.poco is not None) else False

    def stop_auto_capture(self):
        """停止轮询监听与真机触摸监听"""
        self._auto_stop = True
        try:
            if getattr(self, '_getevent_proc', None) is not None:
                self._getevent_proc.terminate()
        except Exception:
            pass
        self._getevent_active = False
        self._getevent_thread = None
        self._auto_thread = None

    # ==================== 真机被动触摸监听（adb getevent）====================

    def _detect_touch_node(self):
        """通过 `adb shell getevent -p` 找出触摸屏节点与坐标轴最大值。

        返回 (node_path, max_x, max_y)；找不到返回 (None, 0, 0)。
        """
        import subprocess, re
        print("[AUTO-CAP] _detect_touch_node: 开始执行 getevent -p...", flush=True)
        try:
            out = subprocess.run(
                ['adb', '-H', self.adb_host, '-P', str(self.adb_port), '-s', self.serial,
                 'shell', 'getevent', '-p'],
                capture_output=True, text=True, timeout=10,
            ).stdout or ''
        except Exception:
            return None, 0, 0
        blocks = re.split(r'(?=add device )', out)
        for blk in blocks:
            # 触摸屏特征：含 ABS_MT 位置轴(0035=ABS_MT_POSITION_X 的 EV_ABS 代码) 且标记为 INPUT_PROP_DIRECT。
            # 注意 getevent -p 输出的是轴代码 0035/0036，而非符号名 ABS_MT_POSITION_X。
            if '0035' not in blk or 'INPUT_PROP_DIRECT' not in blk:
                continue
            m_node = re.search(r'add device \d+:\s*(\S+)', blk)
            mx = re.search(r'0035\s*:\s*value\s*\d+.*?max\s*(\d+)', blk)
            my = re.search(r'0036\s*:\s*value\s*\d+.*?max\s*(\d+)', blk)
            if m_node and mx and my:
                return m_node.group(1), int(mx.group(1)), int(my.group(1))
        return None, 0, 0

    def _parse_getevent_line(self, line):
        """解析 `getevent -lt` 一行，提取 ABS_MT 事件名/值/时间戳。

        仅关注 ABS_MT_TRACKING_ID / ABS_MT_POSITION_X / ABS_MT_POSITION_Y。
        TRACKING_ID 抬起时为 0xffffffff，转成有符号 -1 供 TouchEventParser 判定 UP。
        """
        import re
        m = re.match(r'\[\s*([\d.]+)\]\s+\S+:\s+\S+\s+(ABS_MT_\w+)\s+([0-9a-fA-F]+)', line)
        if not m:
            return None
        name = m.group(2)
        if name not in ('ABS_MT_TRACKING_ID', 'ABS_MT_POSITION_X', 'ABS_MT_POSITION_Y'):
            return None
        val = int(m.group(3), 16)
        if name == 'ABS_MT_TRACKING_ID' and val > 0x7fffffff:
            val -= 0x100000000
        return {'name': name, 'value': val, 'ts': float(m.group(1))}

    def _getevent_loop(self, callback):
        """后台线程：被动监听真机触摸，识别手势后回调记录步骤。

        实现：用 `adb shell cat <touch_node>` 以**二进制**方式直读 /dev/input/event* 节点。
        `cat` 走 read/write 系统调用、无 stdio 缓冲，事件逐字节即时送达，规避了
        `getevent -lt` 经 adb shell（非 PTY）时 stdout 全缓冲、触摸事件卡住不输出的问题。
        解析 Linux `struct input_event`（64-bit 小端：timeval 16B + type 2B + code 2B + value 4B）。
        """
        import subprocess, struct, sys, time as _t
        print("[AUTO-CAP] ====== _getevent_loop 开始 ======", flush=True)
        node, max_x, max_y = self._detect_touch_node()
        if not node:
            print("[AUTO-CAP] 未找到触摸屏节点，自动捕获不可用!", flush=True)
            return
        print(f"[AUTO-CAP] 触摸节点: {node}, max={max_x}x{max_y}", flush=True)
        sw, sh = self.display_size
        parser = TouchEventParser(sw, sh, max_x or 4095, max_y or 4095)

        # 64-bit ARM 小端 input_event 布局
        EVENT_FMT = '<qqHHl'          # tv_sec(8) tv_usec(8) type(2) code(2) value(4)
        EVENT_SIZE = struct.calcsize(EVENT_FMT)   # = 24
        # ABS 轴代码 → TouchEventParser 期望的事件名
        CODE_NAME = {
            57: 'ABS_MT_TRACKING_ID',   # 0x39
            53: 'ABS_MT_POSITION_X',     # 0x35
            54: 'ABS_MT_POSITION_Y',     # 0x36
        }
        try:
            proc = subprocess.Popen(
                ['adb', '-H', self.adb_host, '-P', str(self.adb_port), '-s', self.serial,
                 'shell', 'cat', node],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as e:
            print(f"[AUTO-CAP] 启动 cat {node} 失败: {e}", flush=True)
            return
        self._getevent_proc = proc
        self._getevent_active = True
        print(f"[AUTO-CAP] 触摸监听已启动(二进制): node={node}, max={max_x}x{max_y}, event_size={EVENT_SIZE}", flush=True)
        buf = b''
        bytes_read = 0
        ev_count = 0
        try:
            while not self._auto_stop:
                try:
                    chunk = proc.stdout.read(4096)
                except Exception as e:
                    print(f"[AUTO-CAP] read exception: {e}", flush=True)
                    break
                if not chunk:
                    break  # EOF / 进程退出
                buf += chunk
                bytes_read += len(chunk)
                while len(buf) >= EVENT_SIZE:
                    tv_sec, tv_usec, etype, ecode, evalue = struct.unpack(EVENT_FMT, buf[:EVENT_SIZE])
                    buf = buf[EVENT_SIZE:]
                    if etype != 3:        # 仅处理 EV_ABS
                        continue
                    name = CODE_NAME.get(ecode)
                    if not name:
                        continue
                    ts = tv_sec + tv_usec / 1e6
                    ev_count += 1
                    g = parser.feed(name, evalue, ts)
                    if g:
                        print(f"[AUTO-CAP] *** 手势检测: type={g['type']} pos=({g.get('x1')},{g.get('y1')}) dur={g.get('duration_ms')}ms ***", flush=True)
                        step = self._gesture_to_step(g)
                        if step:
                            print(f"[AUTO-CAP] *** 步骤生成: action={step.get('action_type')} desc={str(step.get('description',''))[:60]} ***", flush=True)
                            try:
                                callback(step)
                                print(f"[AUTO-CAP] *** callback 成功 ***", flush=True)
                            except Exception as cb_err:
                                print(f"[AUTO-CAP] callback 异常: {cb_err}", flush=True)
                        else:
                            print(f"[AUTO-CAP] _gesture_to_step 返回 None (手势被丢弃)", flush=True)
            if ev_count > 0:
                print(f"[AUTO-CAP] 解析循环结束: 共解析 {ev_count} 个 EV_ABS MT 事件, {bytes_read} 字节", flush=True)
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
            self._getevent_active = False
            print(f"[AUTO-CAP] 触摸监听已停止 (共读取 {bytes_read} 字节)", flush=True)

    def _gesture_to_step(self, g):
        """手势 dict → record_action 同构的 step dict"""
        gtype = g['type']
        x1, y1 = int(g['x1']), int(g['y1'])
        el = self._find_element_at(x1, y1)

        if gtype == 'tap':
            action_type = 'click'
            desc = (el.get('chinese_name') or el.get('text', '')
                    ) if el else f'自动捕获: 点击 ({x1},{y1})'
        elif gtype == 'long_press':
            action_type = 'long_press'
            desc = (el.get('chinese_name') or el.get('text', '')
                    ) if el else f'自动捕获: 长按 ({x1},{y1})'
        elif gtype == 'swipe':
            action_type = 'swipe'
            x2, y2 = int(g['x2']), int(g['y2'])
            desc = f'自动捕获: 滑动 ({x1},{y1})->({x2},{y2})'
        else:
            return None

        if not desc:
            desc = f'自动捕获: {gtype} ({x1},{y1})'

        element = el or {'center_x': x1, 'center_y': y1,
                         'locator_strategy': 'coordinate',
                         'value': f'{x1},{y1}',
                         'name': f'坐标({x1},{y1})'}

        return {
            'step_number': 1,
            'action_type': action_type,
            'element': element,
            'input_value': '',
            'wait_time': 0,
            'assert_type': '',
            'assert_value': '',
            'description': desc,
            'center_x': x1,
            'center_y': y1,
        }

    def _find_element_at(self, px, py):
        """在像素坐标处用 Poco dump 反查最匹配的控件"""
        if self.poco is None:
            return None
        try:
            elements = self.dump_page_elements()
            best = None
            best_area = float('inf')
            import re
            for el in elements:
                ex, ey = el.get('center_x'), el.get('center_y')
                if ex is None or ey is None:
                    continue
                b = el.get('bounds', '')
                if not b:
                    continue
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
                if not m:
                    continue
                x1i, y1i, x2i, y2i = [int(m.group(i)) for i in range(1, 5)]
                if x1i <= px <= x2i and y1i <= py <= y2i:
                    area = (x2i - x1i) * (y2i - y1i)
                    if area < best_area:
                        best_area = area
                        best = {
                            'locator_strategy': el.get('strategy'),
                            'value': el.get('value'),
                            'name': el.get('chinese_name') or el.get('text', ''),
                            'center_x': ex,
                            'center_y': ey,
                        }
            return best
        except Exception:
            return None


def build_airtest_script(steps, app_package='', serial='', adb_host='host.docker.internal',
                         adb_port=5037, platform='android', wda_url='http://127.0.0.1:8100',
                         display_size=None):
    """把录制步骤生成为可直接 `airtest run` 的 Python 脚本

    坐标为设备像素（与录制时一致），resource-id 用 poco 定位，文本元素用坐标 touch。
    支持 Android（adb）与 iOS（WDA）两种连接方式。
    """
    platform = (platform or 'android').lower()
    w, h = display_size or (1080, 2400)
    if platform == 'ios':
        wda = (wda_url or '').strip()
        if wda.startswith('iOS://'):
            uri = wda
        elif wda.startswith('http'):
            uri = f"iOS:///{wda}"
        else:
            uri = f"iOS:///{wda}"
    else:
        uri = f"Android://{adb_host}:{adb_port}/{serial}" if serial else f"Android://{adb_host}:{adb_port}/"

    L = []
    L.append("# -*- encoding=utf-8 -*-")
    L.append("from airtest.core.api import *")
    if platform == 'ios':
        L.append("from poco.drivers.ios import iosPoco")
    else:
        L.append("from poco.drivers.android.uiautomation import AndroidUiautomationPoco")
    L.append("")
    L.append("auto_setup(__file__)")
    L.append(f'dev = connect_device("{uri}")')
    if platform == 'ios':
        L.append("poco = iosPoco()")
    else:
        L.append("poco = AndroidUiautomationPoco(dev, use_airtest_input=True, screenshot_each_action=False)")
    L.append("")
    if app_package:
        L.append(f'dev.start_app("{app_package}")')
        L.append("sleep(1.5)")
        L.append("")

    def esc(s):
        return str(s).replace('\\', '\\\\').replace('"', '\\"')

    def rid_of(el):
        if not el:
            return None
        return el.get('value') if el.get('locator_strategy') == 'id' else None

    for st in steps:
        at = (st.get('action_type') or '').lower()
        el = st.get('element') or {}
        iv = st.get('input_value', '') or ''
        rid = rid_of(el)
        cx, cy = el.get('center_x'), el.get('center_y')
        desc = st.get('description', '') or at

        if at == 'launch_app':
            continue
        elif at in ('click', 'tap'):
            if rid:
                L.append(f'poco("{esc(rid)}").click()  # {desc}')
            elif cx is not None and cy is not None:
                L.append(f'touch(({cx}, {cy}))  # {desc}')
        elif at == 'double_tap':
            if rid:
                L.append(f'poco("{esc(rid)}").double_click()  # {desc}')
            elif cx is not None and cy is not None:
                L.append(f'touch(({cx}, {cy})); touch(({cx}, {cy}))  # {desc}')
        elif at == 'long_press':
            if rid:
                L.append(f'poco("{esc(rid)}").long_click()  # {desc}')
            elif cx is not None and cy is not None:
                L.append(f'dev.long_click(({cx}, {cy}), duration=1.0)  # {desc}')
        elif at in ('fill', 'input'):
            if rid:
                L.append(f'poco("{esc(rid)}").set_text("{esc(iv)}")  # {desc}')
            elif cx is not None and cy is not None:
                L.append(f'touch(({cx}, {cy}))  # {desc}')
                L.append(f'text("{esc(iv)}", enter=False)')
        elif at == 'clear':
            if rid:
                L.append(f'poco("{esc(rid)}").set_text("")  # {desc}')
            else:
                L.append(f'# {desc}（请手动清空输入框）')
        elif at == 'swipe':
            start, end = _script_swipe(el, iv, w, h, 0.3)
            L.append(f'swipe({start}, {end})  # {desc}')
        elif at == 'scroll':
            start, end = _script_swipe(el, iv, w, h, 0.6)
            L.append(f'swipe({start}, {end})  # {desc}')
        elif at == 'wait':
            L.append(f'sleep({int((st.get("wait_time") or 1000) / 1000)}  # {desc})')
        elif at == 'screenshot':
            L.append(f'snapshot(msg="{esc(desc)}")')
        elif at == 'back':
            L.append('keyevent("BACK")')
        elif at == 'home':
            L.append('keyevent("HOME")')
        elif at in ('assert', 'getText'):
            if rid:
                L.append(f'# {at}: poco("{esc(rid)}").exists()  # {desc}')
            else:
                L.append(f'# {at}: {desc}')
        else:
            L.append(f'# 未处理操作: {at} ({desc})')

    return "\n".join(L)


def _script_swipe(el, input_value, w, h, ratio):
    if input_value:
        parts = str(input_value).split(',')
        if len(parts) == 4:
            try:
                return (int(parts[0]), int(parts[1])), (int(parts[2]), int(parts[3]))
            except ValueError:
                pass
    cx = el.get('center_x') or (w // 2)
    cy = el.get('center_y') or (h // 2)
    offset = int(min(w, h) * ratio)
    direction = (input_value or 'up').lower()
    start = (cx, cy)
    if direction == 'up':
        end = (cx, cy - offset)
    elif direction == 'down':
        end = (cx, cy + offset)
    elif direction == 'left':
        end = (cx - offset, cy)
    elif direction == 'right':
        end = (cx + offset, cy)
    else:
        end = (cx, cy - offset)
    return start, end


# ==================== 自动捕获（adb getevent 触摸监听） ====================


class TouchEventParser:
    """解析 adb getevent -tl 输出，识别 tap / swipe / long_press 手势"""

    ABS_MT_TRACKING_ID = 'ABS_MT_TRACKING_ID'
    ABS_MT_POSITION_X = 'ABS_MT_POSITION_X'
    ABS_MT_POSITION_Y = 'ABS_MT_POSITION_Y'

    def __init__(self, screen_w, screen_h, max_x=4095, max_y=4095):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.max_x = max_x
        self.max_y = max_y
        self.reset()

    def reset(self):
        self.touching = False
        self.start_x = self.start_y = None
        self.last_x = self.last_y = None
        self.down_time = None
        self.positions = []

    def _scale_x(self, raw):
        return int(raw * self.screen_w / self.max_x)

    def _scale_y(self, raw):
        return int(raw * self.screen_h / self.max_y)

    def feed(self, event_name, value, ts=None):
        """喂入一行 getevent -tl 解析结果。返回手势 dict 或 None。"""
        now = ts or time.monotonic()
        gesture = None

        if event_name == self.ABS_MT_TRACKING_ID:
            if value >= 0:
                self.touching = True
                self.down_time = now
                self.positions = []
            else:
                if self.touching and self.start_x is not None:
                    dur = int((now - (self.down_time or now)) * 1000)
                    dx = abs((self.last_x or 0) - (self.start_x or 0))
                    dy = abs((self.last_y or 0) - (self.start_y or 0))
                    dist = (dx ** 2 + dy ** 2) ** 0.5

                    if dist < 30 and dur < 300:
                        gtype = 'tap'
                    elif dur >= 500 and dist < 30:
                        gtype = 'long_press'
                    else:
                        gtype = 'swipe'

                    gesture = {
                        'type': gtype,
                        'x1': self.start_x,
                        'y1': self.start_y,
                        'x2': self.last_x or self.start_x,
                        'y2': self.last_y or self.start_y,
                        'duration_ms': dur,
                    }
                self.reset()
                return gesture

        elif not self.touching:
            return None
        elif event_name == self.ABS_MT_POSITION_X:
            x = self._scale_x(value)
            if self.start_x is None:
                self.start_x = x
            self.last_x = x
            if self.down_time is not None:
                self.positions.append((now, x, self.last_y or 0))
        elif event_name == self.ABS_MT_POSITION_Y:
            y = self._scale_y(value)
            if self.start_y is None:
                self.start_y = y
            self.last_y = y
            if self.down_time is not None:
                self.positions.append((now, self.last_x or 0, y))

        return gesture
