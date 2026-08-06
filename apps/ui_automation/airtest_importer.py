"""
Airtest / Poco 录制脚本 → 统一步骤格式解析器

职责：
1. 把 Airtest IDE 录制的 .air 脚本（Python）解析成项目统一的「归一化步骤」格式
2. 归一化步骤与 apps/ui_automation/views.py 中 generate_recording_case 使用的 step dict 完全一致，
   因此可直接交给 _build_test_case_from_steps 落库成 TestCase。

支持的常见 Airtest / Poco 语句：
  poco("com.pkg:id/btn").click()              -> click (id 定位)
  poco("确认").click()                         -> click (xpath 文本定位)
  poco("x").double_click()                     -> double_tap
  poco("x").long_click()                       -> long_press
  poco("x").set_text("你好")                    -> fill
  poco("x").clear_text()                       -> clear
  poco("x").swipe("up") / swipe([0,-50])       -> swipe
  poco("x").wait_for_appearance()              -> waitFor
  poco("x").get_text()                         -> getText
  touch(Template(r"tpl.png"))                  -> click (图像定位)
  touch((500, 1000))                           -> tap  (坐标点击)
  swipe((x1,y1),(x2,y2))                       -> swipe (坐标)
  text("你好")                                  -> fill (键盘输入)
  sleep(2)                                      -> wait
  keyevent("BACK") / keyevent("HOME")          -> back / home
  assert_exists(Template(...), "描述")          -> assert

本模块只依赖标准库 ast / re，不依赖 Django，可独立测试。
"""
import ast
import re


# ---- 资源 ID 识别：形如 com.xxx:id/y ----
_RES_ID_RE = re.compile(r'^[a-zA-Z][\w.]*:[a-zA-Z][\w./-]*$')

# poco 方法 -> 统一 action_type
POCO_METHOD_MAP = {
    'click': 'click',
    'double_click': 'double_tap',
    'long_click': 'long_press',
    'set_text': 'fill',
    'clear_text': 'clear',
    'swipe': 'swipe',
    'wait_for_appearance': 'waitFor',
    'wait': 'waitFor',
    'get_text': 'getText',
    'exists': 'assert',
    'attr': 'getText',
}

# 顶层函数 -> 处理
FUNC_HANDLERS = {'touch', 'swipe', 'sleep', 'keyevent', 'assert_exists',
                 'assert_not_exists', 'text', 'snapshot', 'home', 'wake'}


def _const_str(node):
    """提取 ast 常量字符串"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _const_int_tuple(node):
    """提取 (x, y) 元组为整数元组"""
    if isinstance(node, ast.Tuple) and len(node.elts) == 2:
        a, b = node.elts
        if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
            try:
                return (int(a.value), int(b.value))
            except (TypeError, ValueError):
                return None
    return None


def _template_path(node):
    """Template(r"tpl.png") -> 文件名；否则 None"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Template':
        if node.args:
            return _const_str(node.args[0])
    return None


def _first_str_arg(call):
    """取调用第一个字符串位置参数 / 名为 text 的关键字参数"""
    for a in call.args:
        s = _const_str(a)
        if s is not None:
            return s
    for kw in call.keywords:
        if kw.arg in ('text', 'name') and _const_str(kw.value) is not None:
            return _const_str(kw.value)
    return None


def _first_tuple_arg(call):
    for a in call.args:
        t = _const_int_tuple(a)
        if t is not None:
            return t
    return None


def _descend_to_name(node, name):
    """沿 .value 链向下找到 func 为 Name(name) 的 Call 节点"""
    cur = node
    while isinstance(cur, ast.Call):
        f = cur.func
        if isinstance(f, ast.Name) and f.id == name:
            return cur
        if isinstance(f, ast.Attribute):
            cur = f.value
        else:
            return None
    return None


def _poco_selector(poco_call):
    """从 poco("x") 调用中提取选择器字符串（优先位置参数，其次 text= 关键字）"""
    sel = _first_str_arg(poco_call)
    if sel is None:
        # 退而求其次：任意字符串参数（如 resourceId=...）
        for kw in poco_call.keywords:
            if _const_str(kw.value) is not None:
                return _const_str(kw.value)
    return sel


def _build_element(selector):
    """根据选择器字符串构造统一 element dict（与 generate_recording_case 同构）"""
    if selector is None:
        return None
    name = selector
    if _RES_ID_RE.match(selector):
        strategy = 'id'
        name = selector.split(':id/')[-1] if ':id/' in selector else selector.split('/')[-1]
    else:
        strategy = 'xpath'
        # 文本类选择器，构造与 dump_page_elements 一致的 xpath
        selector = "//*[@text='{}']".format(selector.replace("'", "\\'"))
    return {
        'locator_strategy': strategy,
        'value': selector,
        'name': name,
        'center_x': None,
        'center_y': None,
    }


def _desc_for(action_type, element, extra=''):
    label = element.get('name') if element else ''
    if action_type == 'click':
        return f"点击{label or '元素'}"
    if action_type == 'double_tap':
        return f"双击{label or '元素'}"
    if action_type == 'long_press':
        return f"长按{label or '元素'}"
    if action_type == 'fill':
        return f"在{label or '输入框'}输入「{extra}」"
    if action_type == 'clear':
        return f"清空{label or '输入框'}"
    if action_type == 'swipe':
        return f"滑动{label or '屏幕'}{(' ' + extra) if extra else ''}"
    if action_type == 'waitFor':
        return f"等待{label or '元素'}出现"
    if action_type == 'getText':
        return f"获取{label or '元素'}文本"
    if action_type == 'assert':
        return f"断言{label or '元素'}{extra}"
    if action_type == 'tap':
        return f"坐标点击 ({extra})"
    if action_type == 'wait':
        return f"等待{extra or '1'}秒"
    if action_type == 'back':
        return "返回上一页"
    if action_type == 'home':
        return "回到主页"
    if action_type == 'screenshot':
        return "截图"
    return action_type


def _step(action_type, element=None, input_value='', wait_time=1000,
          assert_type='', assert_value='', description='', center_x=None, center_y=None):
    if not description:
        description = _desc_for(action_type, element)
    return {
        'action_type': action_type,
        'element': element,
        'input_value': input_value,
        'wait_time': wait_time,
        'assert_type': assert_type,
        'assert_value': assert_value,
        'description': description,
        'center_x': center_x,
        'center_y': center_y,
    }


def _handle_poco(method, poco_call, outer_call):
    """处理 poco("x").method(...) 形式"""
    selector = _poco_selector(poco_call)
    if method == 'exists':
        # poco("x").exists() 作为断言存在
        return [_step('assert', _build_element(selector), assert_type='exists',
                      description=f"断言{selector or '元素'}存在")]
    if method == 'set_text':
        text = ''
        if outer_call.args:
            text = _const_str(outer_call.args[0]) or ''
        return [_step('fill', _build_element(selector), input_value=text)]
    if method == 'swipe':
        # 方向字符串 或 向量
        direction = ''
        if outer_call.args:
            direction = _const_str(outer_call.args[0]) or ''
            if not direction and isinstance(outer_call.args[0], ast.List):
                direction = ast.unparse(outer_call.args[0]) if hasattr(ast, 'unparse') else ''
        return [_step('swipe', _build_element(selector), input_value=direction,
                      description=_desc_for('swipe', _build_element(selector), direction))]
    action = POCO_METHOD_MAP.get(method)
    if not action:
        return None
    return [_step(action, _build_element(selector))]


def _handle_func(name, call):
    """处理顶层函数 touch/swipe/sleep/keyevent/assert_exists/text/snapshot/home/wake"""
    if name == 'touch':
        if not call.args:
            return None
        img = _template_path(call.args[0])
        if img:
            return [_step('click', {
                'locator_strategy': 'image', 'value': img,
                'name': f'图像:{img.split("/")[-1]}',
                'center_x': None, 'center_y': None})]
        t = _const_int_tuple(call.args[0])
        if t:
            return [_step('tap', None, center_x=t[0], center_y=t[1],
                          description=f"坐标点击 ({t[0]}, {t[1]})")]
        return None
    if name == 'swipe':
        if len(call.args) >= 2:
            t1 = _const_int_tuple(call.args[0])
            t2 = _const_int_tuple(call.args[1])
            if t1 and t2:
                val = f"{t1[0]},{t1[1]},{t2[0]},{t2[1]}"
                return [_step('swipe', None, input_value=val,
                              description=f"滑动 ({val})")]
        return None
    if name == 'sleep':
        secs = 1
        if call.args:
            try:
                secs = float(call.args[0].value)
            except (AttributeError, TypeError, ValueError):
                secs = 1
        return [_step('wait', None, wait_time=int(secs * 1000),
                      description=f"等待{secs}秒")]
    if name == 'keyevent':
        evt = ''
        if call.args:
            evt = (_const_str(call.args[0]) or '').upper()
        if evt == 'BACK':
            return [_step('back', None)]
        if evt == 'HOME':
            return [_step('home', None)]
        return None
    if name in ('assert_exists', 'assert_not_exists'):
        desc = ''
        if len(call.args) >= 2:
            desc = _const_str(call.args[1]) or ''
        img = _template_path(call.args[0]) if call.args else None
        el = {'locator_strategy': 'image', 'value': img or '',
              'name': f'图像:{(img or "").split("/")[-1]}',
              'center_x': None, 'center_y': None} if img else None
        return [_step('assert', el, assert_type='exists', assert_value='',
                      description=f"断言存在: {desc or (img or '')}")]
    if name == 'text':
        txt = ''
        if call.args:
            txt = _const_str(call.args[0]) or ''
        return [_step('fill', None, input_value=txt, description=f"键盘输入「{txt}」")]
    if name == 'snapshot':
        return [_step('screenshot', None)]
    if name == 'home':
        return [_step('home', None)]
    if name == 'wake':
        return [_step('launch_app', None, description='唤醒设备')]
    return None


def _parse_call(node):
    """解析单个 ast.Call 节点，返回 step 列表或 None"""
    f = node.func
    # poco("x").method() 形式：func 为 Attribute，且其链根基是 poco
    if isinstance(f, ast.Attribute):
        poco_call = _descend_to_name(node, 'poco')
        if poco_call is not None:
            return _handle_poco(f.attr, poco_call, node)
    # 顶层函数形式：touch / swipe / sleep / ...
    if isinstance(f, ast.Name) and f.id in FUNC_HANDLERS:
        return _handle_func(f.id, node)
    return None


def parse_airtest_script(script):
    """
    解析 Airtest / Poco 录制脚本，返回归一化步骤列表。
    每个步骤字段与 generate_recording_case 中录制的步骤完全一致。
    """
    if not script or not script.strip():
        return []
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        raise ValueError(f"脚本语法错误: {e}")
    steps = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            try:
                parsed = _parse_call(node)
            except Exception:
                parsed = None
            if parsed:
                steps.extend(parsed)
    return steps


def parse_airtest_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return parse_airtest_script(f.read())
