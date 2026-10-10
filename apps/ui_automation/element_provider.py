"""
平台无关的「元素拾取」抽象层。

背景（2026-09-21）：
  项目里 Android 早就有一套 dump 能力（`smart_locator.dump_page_elements`，
  读 Appium 的 page_source），但 **iOS 完全没有** —— iOS 用例只能靠 Midscene
  让视觉模型"看图猜坐标"，密集图标条上必然点偏，而且每套用例都要重新试错。

  本模块把"从设备抓取当前页面元素"抽成一个**协议**，各平台各自实现，
  对外只暴露一个 `dump_elements(device, app_config)`：
    - Android : Appium/UiAutomator2 的 page_source（复用已有实现思路）
    - iOS     : WDA 的 /source（accessibility 树，带精确 x/y/width/height）
    - Harmony : 预留（鸿蒙的 uitest/hidumper 后续接入）
  返回**统一的元素结构**，前端拾取器只认这一种格式，因此加平台不用改前端。

统一元素结构（与 `smart_locator.dump_page_elements` 保持兼容）：
    {
        'name':        展示名（优先取元素文案，取不到用 id 末段）
        'strategy':    'id' | 'accessibility_id' | 'xpath' | 'text' | 'coordinate'
        'value':       定位表达式（可直接喂给 find_element）
        'text':        元素上显示的文字
        'class_name':  控件类型
        'clickable':   是否可点
        'bounds':      页码范围字符串（如 '[0,769][79,818]'）
        'center_x':    中心坐标
        'center_y':    中心坐标
        'platform':    来源平台
    }
"""
import logging
import re
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

#: Appium 的 LOCATOR_MAP 能直接吃这些策略名（见 appium_engine.LOCATOR_MAP）
ANDROID_LOCATOR_STRATEGIES = ('id', 'xpath', 'accessibility_id', 'class_name')

#: 这些控件类型是"容器"，不适合作为点击目标（与 iOS 侧 CONTAINER_TYPES 保持一致）
ANDROID_CONTAINER_CLASSES = (
    'android.widget.FrameLayout',
    'android.widget.LinearLayout',
    'android.widget.RelativeLayout',
    'android.widget.ScrollView',
    'androidx.recyclerview.widget.RecyclerView',
    'android.widget.ListView',
)


def _platform_of(device) -> str:
    return (getattr(device, 'platform', '') or '').strip().lower()


def dump_elements(device, app_config=None, retries=2) -> dict:
    """从设备抓取当前页面的可交互元素（平台无关入口）。

    Args:
        device:     AppDevice 实例
        app_config: AppConfig（iOS 需要 bundle id / 包名做兜底，Android 可空）
        retries:    抓取失败重试次数（UiAutomator2/WDA 偶发崩溃可自恢复）

    Returns:
        {'platform': str, 'count': int, 'elements': [...], 'error': str|None}
        **不抛异常**：失败时返回 error 字段，前端能展示可读原因。
    """
    platform = _platform_of(device)
    try:
        if platform == 'ios':
            elements = _dump_ios(device, app_config, retries=retries)
        elif platform == 'android':
            elements = _dump_android(device, app_config, retries=retries)
        elif platform == 'harmony':
            elements = _dump_harmony(device, app_config, retries=retries)
        else:
            return {'platform': platform, 'count': 0, 'elements': [],
                    'error': '暂不支持的平台: %s' % (platform or '(空)')}
    except Exception as exc:  # noqa: BLE001
        logger.warning('[ElementProvider] dump 失败 platform=%s: %s', platform, exc)
        return {'platform': platform, 'count': 0, 'elements': [],
                'error': str(exc)[:500]}

    for e in elements:
        e['platform'] = platform
    return {'platform': platform, 'count': len(elements),
            'elements': elements, 'error': None}


# ============================================================
# iOS：WDA /source 的 accessibility 树
# ============================================================
def _dump_ios(device, app_config=None, retries=2) -> list:
    """iOS 走 `MidsceneIOSEngine` 已经打通的 WDA `/source` 通道。

    复用点：`midscene_ios_node/service.js` 里有 `parseElementTree` + `dumpTree`，
    这里通过引擎的 `_rpc('dumpTree')` 取，避免重复实现 XML 解析。
    """
    from .midscene_ios_engine import MidsceneIOSEngine

    wda_host = (getattr(device, 'wda_host', '') or '').strip()
    wda_port = getattr(device, 'wda_port', None) or 8100
    if not wda_host:
        raise ValueError(
            '设备「%s」未配置 WDA 地址：请在「设备管理」填写 WDA主机'
            '（手机USB所在电脑的 IP）' % getattr(device, 'name', '')
        )

    bundle_id = ''
    if app_config is not None:
        bundle_id = (getattr(app_config, 'package_name', '') or '').strip()

    engine = MidsceneIOSEngine(wda_host=wda_host, wda_port=wda_port,
                              default_bundle_id=bundle_id)
    try:
        engine.start()
        res = engine._rpc(
            'dumpTree',
            {'sessionId': engine._session_id, 'onlyNamed': True},
            timeout=120)
    finally:
        try:
            engine.close()
        except Exception:  # noqa: BLE001
            pass

    out = []
    for n in (res.get('nodes') or []):
        node_type = n.get('type') or ''
        name_txt = (n.get('name') or '').strip()
        label = (n.get('label') or '').strip()
        value = (n.get('value') or '').strip()
        text = name_txt or label or value
        rect = n.get('rect') or [0, 0, 0, 0]
        center = n.get('center') or [0, 0]

        # strategy 选型：
        #   WDA 用 accessibility id 查元素时，匹配的是 name/label，
        #   所以有文案就用 accessibility_id（跨版本最稳），否则退回坐标。
        if text:
            strategy, loc_value = 'accessibility_id', text
        else:
            strategy, loc_value = 'coordinate', '%s,%s' % (center[0], center[1])

        out.append({
            'name': text or node_type.replace('XCUIElementType', ''),
            'strategy': strategy,
            'value': loc_value,
            'text': text,
            'class_name': node_type,
            'clickable': node_type in (
                'XCUIElementTypeButton', 'XCUIElementTypeCell',
                'XCUIElementTypeTextField', 'XCUIElementTypeSecureTextField',
            ) or bool(text),
            'bounds': '[%d,%d][%d,%d]' % (
                rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]),
            'center_x': center[0],
            'center_y': center[1],
            'rect': rect,
        })
    return out


# ============================================================
# Android：Appium page_source（复用 smart_locator 已有的解析思路）
# ============================================================
def _dump_android(device, app_config=None, retries=2) -> list:
    """Android 走 Appium 会话的 `page_source`。

    这里**不自己建 Appium 会话**（建会话依赖 appium_server_url / capabilities，
    且要和录制器共享），而是复用 `smart_locator.dump_page_elements(engine)` ——
    它已经处理了 Airtest/Poco 的分支与重试。
    """
    from .smart_locator import dump_page_elements as _dump

    engine = _open_appium_engine(device, app_config)
    try:
        raw = _dump(engine, retries=retries)
    finally:
        try:
            engine.quit()
        except Exception:  # noqa: BLE001
            pass

    out = []
    for el in raw:
        cls = el.get('class_name') or ''
        # 容器类不参与拾取（点它们等于点空白）
        if cls in ANDROID_CONTAINER_CLASSES and not el.get('text'):
            continue
        bounds = el.get('bounds') or ''
        out.append({
            'name': el.get('chinese_name') or el.get('text') or '',
            'strategy': el.get('strategy') or 'xpath',
            'value': el.get('value') or '',
            'text': el.get('text') or '',
            'class_name': cls,
            'clickable': bool(el.get('clickable')),
            'bounds': bounds,
            'center_x': el.get('center_x'),
            'center_y': el.get('center_y'),
            'rect': _parse_android_bounds(bounds),
        })
    return out


def _parse_android_bounds(bounds):
    """'[x1,y1][x2,y2]' -> [x, y, w, h]；解析不了返回 None。"""
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds or '')
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return [x1, y1, x2 - x1, y2 - y1]


def _open_appium_engine(device, app_config):
    """建一个临时 Appium 会话用于 dump。

    ⚠️ 构造参数与 `views.start_recording` 保持一致（见 views.py 约 L7063-7074）——
    否则会出现"录制能用、拾取连不上"的不一致，那种问题极难排查。
    """
    import time as _time
    from .appium_engine import AppiumTestEngine

    package = (getattr(app_config, 'package_name', '') or '') if app_config else ''
    engine = AppiumTestEngine(
        appium_server_url=device.appium_server_url,
        platform=device.platform,
        device_udid=device.udid,
        app_package=package,
        app_activity=getattr(app_config, 'app_activity', '') or '' if app_config else '',
        bundle_id=package if device.platform == 'ios' else None,
        app_path=(getattr(app_config, 'app_path', '') or None) if app_config else None,
        no_reset=True,
        new_command_timeout=600,
    )
    engine.connect()
    if package:
        try:
            engine.driver.activate_app(package)
        except Exception:  # noqa: BLE001
            pass
    _time.sleep(1)
    return engine


# ============================================================
# HarmonyOS：预留
# ============================================================
def _dump_harmony(device, app_config=None, retries=2) -> list:
    """鸿蒙尚未接入。

    预留此函数是为了让"加平台"只改这一处 —— 前端拾取器无需改动。
    接入时的候选手段：hdc + uitest dumpLayout / hidumper。
    """
    raise NotImplementedError(
        'HarmonyOS 元素拾取尚未接入（已在架构上预留，接入时只需实现本函数）'
    )
