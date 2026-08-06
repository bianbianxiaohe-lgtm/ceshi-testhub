"""
智能步骤拆分 + 控件知识库（JSON 文件驱动，支持一键学习扩展）

知识库文件：knowledge/element_knowledge.json（自动创建）
"""
import re
import json
import os
import time
import xml.etree.ElementTree as ET

KB_DIR = os.path.join(os.path.dirname(__file__), "knowledge")
KB_FILE = os.path.join(KB_DIR, "element_knowledge.json")

# 内置默认知识库
DEFAULT = {
    "万年历": {
        "elements": {
            "月份标题": "com.youloft.calendar:id/title_click",
            "年份标题": "com.youloft.calendar:id/title_click",
            "标题": "com.youloft.calendar:id/title_click",
            "万年历": "com.youloft.calendar:id/title",
            "万年历tab": "com.youloft.calendar:id/title_click",
            "月视图标题": "com.youloft.calendar:id/title",
            "年视图标题": "com.youloft.calendar:id/title",
            "视图标题": "com.youloft.calendar:id/title",
            "确认按钮": "com.youloft.calendar:id/dc_sureBtn",
            "确认": "com.youloft.calendar:id/dc_sureBtn",
            "取消按钮": "com.youloft.calendar:id/dc_cancelBtn",
            "取消": "com.youloft.calendar:id/dc_cancelBtn",
            "年滚轮": "com.youloft.calendar:id/year",
            "月滚轮": "com.youloft.calendar:id/month",
            "日滚轮": "com.youloft.calendar:id/day",
            "公历": "com.youloft.calendar:id/dc_dialog_solarRbtn",
            "农历": "com.youloft.calendar:id/dc_dialog_lunarRbtn",
            "写日记": "com.youloft.calendar:id/item_1",
            "新建提醒": "com.youloft.calendar:id/item_2",
            "皮肤壁纸": "com.youloft.calendar:id/item_3",
            "定制首页": "com.youloft.calendar:id/item_4",
            "日期换算": "com.youloft.calendar:id/item_5",
            "提醒列表": "com.youloft.calendar:id/item_6",
            "新建提醒": "com.youloft.calendar:id/item_2",
            "提醒列表": "com.youloft.calendar:id/item_6",
            "tab": "com.youloft.calendar:id/title_click",
            "写日记": "com.youloft.calendar:id/item_1",
            "皮肤壁纸": "com.youloft.calendar:id/item_3",
            "定制首页": "com.youloft.calendar:id/item_4",
            "日期换算": "com.youloft.calendar:id/item_5",
            "日历": "com.youloft.calendar:id/title",
        },
        "wheels": {
            "month": "585,2228,585,2078",
            "year": "214,2228,214,2078",
            "day": "957,2228,957,2078",
        }
    }
}


def _load_kb():
    """加载知识库 JSON 文件，不存在则用默认值初始化"""
    if not os.path.exists(KB_DIR):
        os.makedirs(KB_DIR)
    if os.path.exists(KB_FILE):
        try:
            with open(KB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 初始化
    with open(KB_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT, f, ensure_ascii=False, indent=2)
    return DEFAULT


def _save_kb(data):
    if not os.path.exists(KB_DIR):
        os.makedirs(KB_DIR)
    with open(KB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def smart_match_locator(step_text, app_name="万年历"):
    """从步骤文字匹配控件定位器（id 策略）"""
    kb = _load_kb()
    app = kb.get(app_name, {})
    elements = app.get("elements", {})
    text = (step_text or "").lower()
    for name, value in elements.items():
        if name.lower() in text:
            return "id", value
    return None, None


def parse_swipe_pattern(text):
    """解析"选中N个月后"模式。返回 (wheel_type, times) 或 None"""
    t = (text or "").lower()
    m = re.search(r"(\d+)\s*(个)?\s*(月|年|日)(后|的)?", t)
    if m:
        times = int(m.group(1))
        unit = m.group(3)
        wheel = {"月": "month", "年": "year", "日": "day"}.get(unit, "month")
        return wheel, times
    cn_map = {"一":1, "两":2, "二":2, "三":3, "四":4, "五":5, "六":6, "七":7, "八":8, "九":9, "十":10}
    m2 = re.search(r"([一二两三四五六七八九十])\s*(个)?\s*(月|年|日)(后|的)?", t)
    if m2:
        times = cn_map.get(m2.group(1), 1)
        unit = m2.group(3)
        wheel = {"月": "month", "年": "year", "日": "day"}.get(unit, "month")
        return wheel, times
    return None


def get_wheel_coords(app_name="万年历"):
    """获取滚轮坐标"""
    kb = _load_kb()
    app = kb.get(app_name, {})
    wheels_raw = app.get("wheels", {})
    wheels = {}
    for k, v in wheels_raw.items():
        parts = [int(x) for x in str(v).split(",")]
        wheels[k] = tuple(parts)
    return wheels


def dump_page_elements(engine, retries=2) -> list:
    """Dump 当前页面层级，返回可交互控件列表

    参数:
        retries: page_source 获取失败时的重试次数（UiAutomator2 崩溃通常可自恢复）
    """
    # Airtest 录制引擎：走 Poco dump（其 device 无 page_source）
    if getattr(engine, 'engine_type', None) == 'airtest':
        return engine.dump_page_elements()
    last_exc = None
    for attempt in range(retries + 1):
        try:
            xml_str = engine.driver.page_source
            break
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(1.5)
    else:
        raise last_exc
    root = ET.fromstring(xml_str)
    results = []
    seen = set()

    # ---- 第一遍：有 resource-id 的元素 ----
    for el in root.iter():
        rid = el.attrib.get("resource-id", "")
        text = el.attrib.get("text", "").strip()
        cls = el.attrib.get("class", "")
        clickable = el.attrib.get("clickable", "false") == "true"
        bounds = el.attrib.get("bounds", "")
        if rid and rid not in seen:
            seen.add(rid)
            name = text if text else rid.split(":id/")[-1] if ":id/" in rid else rid.split("/")[-1]
            center_x = center_y = None
            if bounds:
                try:
                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                    if m:
                        x1, y1, x2, y2 = map(int, m.groups())
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2
                except Exception:
                    pass
            results.append({
                "chinese_name": name,
                "strategy": "id",
                "value": rid,
                "text": text,
                "class_name": cls,
                "clickable": clickable,
                "bounds": bounds,
                "center_x": center_x,
                "center_y": center_y,
            })

    # ---- 第二遍：无 resource-id 但有意义的文本元素 ----
    # 过滤：文字>=2字符、非纯数字、非单字星期、非日期格式
    skip_texts = {'日', '一', '二', '三', '四', '五', '六',
                  '宜', '忌', '出', '行', '交', '易', '祭', '祀',
                  '结', '婚', '搬', '家'}
    seen_text = set()
    for el in root.iter():
        rid = el.attrib.get("resource-id", "")
        if rid:  # 已在第一遍处理
            continue
        text = el.attrib.get("text", "").strip()
        cls = el.attrib.get("class", "")
        clickable = el.attrib.get("clickable", "false") == "true"
        content_desc = el.attrib.get("content-desc", "").strip()
        desc_or_text = text or content_desc

        if len(desc_or_text) < 2 or desc_or_text.isdigit():
            continue
        if desc_or_text in skip_texts:
            continue
        if re.match(r'^[\d.]+[a-zA-Z]*$', desc_or_text):
            continue

        key = f"{cls}:{desc_or_text}"
        if key in seen_text:
            continue
        seen_text.add(key)

        bounds = el.attrib.get("bounds", "")
        center_x = center_y = None
        if bounds:
            try:
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if m:
                    x1, y1, x2, y2 = map(int, m.groups())
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
            except Exception:
                pass

        # 构造 xpath 定位器
        if text and cls:
            xpath_val = "//{}[@text='{}']".format(cls, text)
        elif content_desc and cls:
            xpath_val = "//{}[@content-desc='{}']".format(cls, content_desc)
        elif text:
            xpath_val = "*[@text='{}']".format(text)
        else:
            xpath_val = "*[@content-desc='{}']".format(content_desc)

        results.append({
            "chinese_name": desc_or_text,
            "strategy": "xpath",
            "value": xpath_val,
            "text": text,
            "class_name": cls,
            "clickable": clickable,
            "bounds": bounds,
            "center_x": center_x,
            "center_y": center_y,
        })

    return results


def add_knowledge(app_name, chinese_name, locator_value, strategy="id"):
    """添加一条知识到 JSON 文件"""
    kb = _load_kb()
    kb.setdefault(app_name, {}).setdefault("elements", {})[chinese_name] = locator_value
    _save_kb(kb)
    return True
