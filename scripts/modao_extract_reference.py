#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨刀原型需求自动识别与提取系统（参考实现 + 实测修正版）
==========================================================

说明：
  这是基于用户技术方案实现的独立参考脚本，用于验证「四路自适应抓取」在真实
  墨刀 sharing 链接上的可行性。它**不进生产主链路**（主链路是 apps/requirement_analysis
  下的 async 实现），仅作为对照/验证工具。

  与用户原始方案的关键差异（均来自 dev 容器对
  https://modao.cc/proto/xChvVjCKthsv1uVUfFWkCD/sharing?view_mode=inspect
  的实测，见下方注释）：

  [修正1] 文本图层判定：用户方案依赖「T 」前缀 + text-icon 子节点。但实测墨刀
          sharing 态的图层树里，文本图层就是**普通图层名**（如「365天会员」「免费领」），
          既无「T 」前缀、也无独立 text-icon 子节点。因此改为：
            - 优先：name 以「T 」开头（兼容编辑态）
            - 兜底：name 非空且非形状/图标/装饰类（md-/矩形/底栏/状态栏/空名则跳过）
  [修正2] 展开逻辑：墨刀 sharing 态的 expander 是**同一 DOM 节点的 toggle**（展开后
          还是同一个 expander，只是状态变了）。用户方案用 collapsed.first.click() 循环
          会反复横跳折叠。改为：收集当前所有 expander，**逐个点不同节点且点过即标记**，
          直到没有新的未展开分组为止。
  [修正3] 长文本「内容」字段：分享态下属性面板「内容」字段待验证；短文本图层名已够用，
          长文本暂时保留图层名（不强行点取，避免误触）。后续验证后再启用。

依赖：pip install playwright；playwright install chromium
"""
import os
import re
import json
import time
import shutil
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout


# ============================================================
# 配置
# ============================================================
@dataclass
class Config:
    output_dir: str = "./modao_output"
    screenshot_dir: str = "./modao_output/screenshots"
    enable_ui_capture: bool = False
    max_canvases: int = 0  # 0 = 不限制
    ui_trigger_keywords: List[str] = field(default_factory=lambda: [
        "价格", "档位", "配置", "表格", "列表", "字段",
        "会员", "权益", "审核", "后台", "设置"
    ])
    viewport_width: int = 1920
    viewport_height: int = 1080
    nav_timeout: int = 30000
    wait_after_canvas_switch: float = 0.8
    wait_after_mode_switch: float = 1.0
    headless: bool = True
    scroll_overlap_ratio: float = 0.1


# ============================================================
# 数据结构
# ============================================================
@dataclass
class Annotation:
    number: str
    content: str
    author: str = ""
    requirement_points: List[str] = field(default_factory=list)


@dataclass
class PageScreenshot:
    page_num: int
    image_path: str
    extracted_content: str = ""


@dataclass
class CanvasResult:
    canvas_name: str
    group_path: str
    annotations: List[Annotation] = field(default_factory=list)
    canvas_text: str = ""
    page_screenshots: List[PageScreenshot] = field(default_factory=list)
    links: List[str] = field(default_factory=list)


# ============================================================
# 工具函数
# ============================================================
# 形状/图标/装饰类图层名关键词（无业务文本，应跳过）
_NON_TEXT_LAYER_HINTS = (
    '矩形', '圆形', '椭圆', '线条', '箭头', '图片', '图像', '图标', '底栏', '状态栏',
    '背景', '遮罩', '按钮', '图片', 'md-', 'shape', 'rect', 'icon', 'image', 'bg',
    'group', '分组', '画板', 'frame',
)


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


def extract_links(text: str) -> List[str]:
    if not text:
        return []
    pattern = r'https?://[^\s，。、）)】\]]+'
    raw_links = re.findall(pattern, text)
    cleaned = []
    for link in raw_links:
        link = re.sub(r'[，。、）)】]+$', '', link)
        if link and link not in cleaned:
            cleaned.append(link)
    return cleaned


def split_requirement_points(content: str) -> List[str]:
    if not content:
        return []
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    numbered = re.split(
        r'(?:^|\n)\s*(?:\d+[、.．]|[①②③④⑤⑥⑦⑧⑨⑩][、.．]?)\s*', content
    )
    numbered = [p.strip() for p in numbered if p.strip()]
    if len(numbered) > 1:
        return numbered
    listed = re.split(r'(?:^|\n)\s*[-•*]\s+', content)
    listed = [p.strip() for p in listed if p.strip()]
    if len(listed) > 1:
        return listed
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    if len(lines) > 1:
        return lines
    return [content.strip()] if content.strip() else []


def is_text_layer_name(name: str) -> bool:
    """[修正1] 判断图层名是否为业务文本图层（非形状/图标/空）。"""
    if not name:
        return False
    low = name.lower()
    for hint in _NON_TEXT_LAYER_HINTS:
        if hint in low:
            return False
    # 纯数字/纯符号图层名视为非文本
    if re.fullmatch(r'[\d\s\-_/]+', name):
        return False
    return True


def get_screenshot_path(config: Config, group_path: str, canvas_name: str,
                        page_num: int, suffix: str = "") -> str:
    parts = [safe_filename(p) for p in group_path.split(" > ") if p]
    dir_path = os.path.join(config.screenshot_dir, *parts, safe_filename(canvas_name))
    os.makedirs(dir_path, exist_ok=True)
    filename = f"page_{page_num}{suffix}.png"
    return os.path.join(dir_path, filename)


# ============================================================
# 墨刀提取器主类
# ============================================================
class ModaoRequirementExtractor:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page: Optional[Page] = None
        os.makedirs(self.config.output_dir, exist_ok=True)
        os.makedirs(self.config.screenshot_dir, exist_ok=True)

    def start(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.config.headless)
        self.context = self.browser.new_context(
            viewport={"width": self.config.viewport_width,
                      "height": self.config.view_height if hasattr(self.config, 'view_height') else self.config.viewport_height},
            locale="zh-CN"
        )
        self.page = self.context.new_page()
        self.page.set_default_navigation_timeout(self.config.nav_timeout)

    def close(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def _ensure_mode(self, mode: str):
        mode_map = {
            "read_only": "view_mode=read_only",
            "inspect": "view_mode=inspect",
            "device": "view_mode=device",
        }
        target_param = mode_map[mode]
        current_url = self.page.url
        if target_param not in current_url:
            base_url = current_url.split("?")[0]
            self.page.goto(f"{base_url}?{target_param}", wait_until="networkidle")
            time.sleep(self.config.wait_after_mode_switch)

    def _close_welcome_popup(self):
        try:
            close_selectors = [
                ".welcome-popup .close",
                "[class*='welcome'] [class*='close']",
                "text=立即登录 >> .. >> [class*='close']",
            ]
            for sel in close_selectors:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    time.sleep(0.3)
                    break
        except Exception:
            pass

    def open_proto(self, url: str) -> str:
        read_only_url = url.split("?")[0] + "?view_mode=read_only"
        self.page.goto(read_only_url, wait_until="networkidle")
        time.sleep(2)
        self._close_welcome_popup()
        title = self.page.title()
        print(f"[INFO] 已打开原型: {title}")
        return title

    # ----------------------------------------------------------
    # 第0路+遍历：画布树遍历（递归展开分组）
    # ----------------------------------------------------------
    def traverse_canvas_tree(self) -> List[Dict]:
        results = []

        def _expand_all_groups():
            for _ in range(30):
                collapsed = self.page.locator(
                    "[class*='canvas-tree'] [class*='expand']:not([class*='expanded']), "
                    "[class*='tree'] [class*='arrow']:not([class*='open']), "
                    "[class*='sidebar'] [class*='caret']:not([class*='expanded'])"
                )
                if collapsed.count() == 0:
                    break
                try:
                    collapsed.first.click()
                    time.sleep(0.3)
                except Exception:
                    break

        def _collect_leaves(parent_path: str = ""):
            items = self.page.locator(
                "[class*='canvas-tree'] [class*='tree-item'], "
                "[class*='sidebar'] [class*='item']"
            )
            count = items.count()
            for i in range(count):
                item = items.nth(i)
                try:
                    name = item.inner_text().strip()
                except Exception:
                    continue
                if not name:
                    continue
                has_expand = item.locator(
                    "[class*='expand'], [class*='arrow'], [class*='caret']"
                ).count() > 0
                if has_expand:
                    try:
                        item.locator("[class*='expand']:not([class*='expanded'])").first.click()
                        time.sleep(0.3)
                    except Exception:
                        pass
                    _collect_leaves(f"{parent_path} > {name}" if parent_path else name)
                else:
                    results.append({"name": name, "path": parent_path, "element": item})

        self._ensure_mode("read_only")
        _expand_all_groups()
        _collect_leaves()
        print(f"[INFO] 共发现 {len(results)} 个画布")
        return results

    # ----------------------------------------------------------
    # 第1路：批注面板抓取
    # ----------------------------------------------------------
    def extract_annotations(self) -> List[Annotation]:
        annotations = []
        empty_state = self.page.locator("text=暂无批注")
        if empty_state.is_visible(timeout=1000):
            return []
        try:
            expand_all = self.page.locator("text=展开全部").first
            if expand_all.is_visible(timeout=1000):
                expand_all.click()
                time.sleep(0.5)
        except Exception:
            pass
        self._scroll_annotation_panel()
        cards = self.page.locator(
            "[class*='annotation-item'], [class*='comment-card'], "
            "[class*='note-item'], [class*='annotation-card']"
        )
        count = cards.count()
        for i in range(count):
            card = cards.nth(i)
            try:
                num_elem = card.locator(
                    "[class*='number'], [class*='index'], [class*='seq']"
                ).first
                number = num_elem.inner_text().strip() if num_elem.count() > 0 else str(i + 1)
                content_elem = card.locator(
                    "[class*='content'], [class*='text'], [class*='body']"
                ).first
                content = content_elem.inner_text().strip() if content_elem.count() > 0 else ""
                author_elem = card.locator(
                    "[class*='author'], [class*='user'], [class*='name']"
                ).first
                author = author_elem.inner_text().strip() if author_elem.count() > 0 else ""
                if content:
                    points = split_requirement_points(content)
                    annotations.append(Annotation(
                        number=number, content=content, author=author,
                        requirement_points=points))
            except Exception as e:
                print(f"[WARN] 提取第 {i+1} 条批注失败: {e}")
                continue
        return annotations

    def _scroll_annotation_panel(self):
        try:
            panel = self.page.locator(
                "[class*='annotation-panel'], [class*='comment-list'], "
                "[class*='note-list'], [class*='sidebar-right']"
            ).first
            if panel.count() == 0:
                return
            for _ in range(10):
                prev = self.page.evaluate("el => el.scrollHeight", panel.element_handle())
                self.page.evaluate("el => el.scrollTop = el.scrollHeight", panel.element_handle())
                time.sleep(0.3)
                new = self.page.evaluate("el => el.scrollHeight", panel.element_handle())
                if new == prev:
                    break
        except Exception:
            pass

    # ----------------------------------------------------------
    # 第2路（修正）：标注模式图层树提取画布纯文本
    # ----------------------------------------------------------
    def extract_canvas_text_via_layers(self) -> str:
        """
        [修正2] 展开逻辑：墨刀 sharing 态的 expander 是同一 DOM 节点的 toggle，
        反复点同一个会横跳折叠。改为：逐个点不同分组，点过的标记，直到无新分组。
        """
        self._ensure_mode("inspect")
        try:
            layer_tab = self.page.locator("text=图层").first
            if layer_tab.is_visible(timeout=2000):
                layer_tab.click()
                time.sleep(0.3)
        except Exception:
            pass

        self._expand_all_layers()

        text_items = []
        layer_items = self.page.locator(
            "div[class*='layer-item'], [class*='layer-tree'] [class*='item'], "
            "[class*='tree-item']"
        )
        count = layer_items.count()
        for i in range(count):
            item = layer_items.nth(i)
            try:
                name = item.inner_text().strip().replace('\n', ' / ')
            except Exception:
                continue
            # 取图层名第一段（inner_text 可能含子节点名，例如「365天会员 / 文本」）
            name_first = name.split(' / ')[0].strip() if name else ''
            # [修正1] 文本图层判定：T 前缀 或 非形状/图标类业务文本
            has_t_icon = item.locator(
                "[class*='text-icon'], [class*='t-icon'], [class*='icon-text']"
            ).count() > 0
            if name.startswith("T "):
                text_content = name[2:].strip()
            elif has_t_icon or is_text_layer_name(name_first):
                text_content = name_first
            else:
                continue
            if text_content:
                text_items.append(text_content)
        return "\n".join(text_items)

    def _expand_all_layers(self):
        """[修正2] 逐个点不同未展开分组，避免 toggle 横跳。"""
        clicked_handles = set()
        for _ in range(40):
            expanders = self.page.locator("div[class*='layer-item'] [class*='expander']")
            ec = expanders.count()
            if ec == 0:
                break
            progressed = False
            for i in range(ec):
                try:
                    h = expanders.nth(i).element_handle()
                    if h is None:
                        continue
                    hid = h.evaluate("(el) => el.__exp_id || (el.__exp_id = Symbol('e'))") \
                        if False else id(h)
                except Exception:
                    hid = i
                if hid in clicked_handles:
                    continue
                before = self.page.locator("div[class*='layer-item']").count()
                try:
                    expanders.nth(i).click(force=True, timeout=3000)
                except Exception:
                    try:
                        expanders.nth(i).click(timeout=3000)
                    except Exception:
                        clicked_handles.add(hid)
                        continue
                time.sleep(0.35)
                after = self.page.locator("div[class*='layer-item']").count()
                clicked_handles.add(hid)
                if after > before:
                    progressed = True
            if not progressed:
                break

    # ----------------------------------------------------------
    # 第3路：UI 页面截图（演示模式，按需）
    # ----------------------------------------------------------
    def _need_ui_capture(self, canvas_result: CanvasResult) -> bool:
        if not self.config.enable_ui_capture:
            return False
        all_text = canvas_result.canvas_text + " " + \
                   " ".join(a.content for a in canvas_result.annotations)
        for keyword in self.config.ui_trigger_keywords:
            if keyword in all_text:
                return True
        return False

    def extract_ui_pages(self, canvas_name: str, group_path: str) -> List[PageScreenshot]:
        screenshots = []
        self._ensure_mode("device")
        time.sleep(1)
        total_pages = self._get_total_pages()
        for page_num in range(1, total_pages + 1):
            long_image = self._stitch_long_page()
            if long_image:
                save_path = get_screenshot_path(self.config, group_path, canvas_name, page_num)
                shutil.copy(long_image, save_path)
                extracted = self._multimodal_extract(save_path)
                screenshots.append(PageScreenshot(
                    page_num=page_num, image_path=save_path, extracted_content=extracted))
            if page_num < total_pages:
                self._goto_next_page()
        return screenshots

    def _get_total_pages(self) -> int:
        try:
            indicator = self.page.locator(
                "[class*='page-indicator'], text=/\\d+\\s*\\/\\s*\\d+/"
            ).first
            if indicator.is_visible(timeout=2000):
                text = indicator.inner_text()
                match = re.search(r'/\s*(\d+)', text)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        return 1

    def _stitch_long_page(self) -> Optional[str]:
        try:
            device_frame = self.page.locator(
                "[class*='device'], [class*='phone-frame'], "
                "[class*='screen'], [class*='app-frame']"
            ).first
            if device_frame.count() == 0:
                full_path = os.path.join(self.config.output_dir, "_temp_full.png")
                self.page.screenshot(path=full_path, full_page=False)
                return full_path
            scroll_container = device_frame.locator(
                "[class*='scroll'], [class*='content']"
            ).first
            images = []
            last_scroll_top = -1
            for _ in range(20):
                seg_path = os.path.join(self.config.output_dir, f"_temp_seg_{len(images)}.png")
                device_frame.screenshot(path=seg_path)
                images.append(seg_path)
                try:
                    new_scroll_top = self.page.evaluate(
                        "el => { el.scrollTop = el.scrollTop + el.clientHeight * 0.9; return el.scrollTop; }",
                        scroll_container.element_handle())
                except Exception:
                    break
                time.sleep(0.3)
                if new_scroll_top == last_scroll_top:
                    break
                last_scroll_top = new_scroll_top
            if len(images) == 1:
                return images[0]
            merged_path = os.path.join(self.config.output_dir, "_temp_merged.png")
            self._merge_images_vertical(images, merged_path, self.config.scroll_overlap_ratio)
            for img in images:
                try:
                    os.remove(img)
                except Exception:
                    pass
            return merged_path
        except Exception as e:
            print(f"[WARN] 长图拼接失败: {e}")
            return None

    def _merge_images_vertical(self, image_paths: List[str], output_path: str,
                                overlap_ratio: float = 0.1):
        try:
            from PIL import Image
        except ImportError:
            print("[WARN] 未安装 Pillow，返回最后一张")
            shutil.copy(image_paths[-1], output_path)
            return
        images = [Image.open(p) for p in image_paths]
        if not images:
            return
        width = images[0].width
        crop_height = int(images[0].height * overlap_ratio)
        parts = [images[0]] + [img.crop((0, crop_height, img.width, img.height)) for img in images[1:]]
        total_height = sum(p.height for p in parts)
        merged = Image.new("RGB", (width, total_height), "white")
        y_offset = 0
        for part in parts:
            merged.paste(part, (0, y_offset))
            y_offset += part.height
        merged.save(output_path)

    def _goto_next_page(self):
        try:
            next_btn = self.page.locator(
                "[class*='next'], [aria-label*='下一页'], [class*='pager'] [class*='right']"
            ).first
            if next_btn.is_visible(timeout=1000):
                next_btn.click()
                time.sleep(0.8)
        except Exception:
            pass

    def _multimodal_extract(self, image_path: str) -> str:
        # TODO: 接入多模态 API
        return ""

    # ----------------------------------------------------------
    # 单画布处理
    # ----------------------------------------------------------
    def process_canvas(self, canvas_info: Dict) -> CanvasResult:
        canvas_name = canvas_info["name"]
        group_path = canvas_info["path"]
        print(f"[PROCESS] 画布: {group_path} > {canvas_name}")
        result = CanvasResult(canvas_name=canvas_name, group_path=group_path)
        self._ensure_mode("read_only")
        canvas_info["element"].click()
        time.sleep(self.config.wait_after_canvas_switch)
        result.annotations = self.extract_annotations()
        print(f"  - 批注: {len(result.annotations)} 条")
        result.canvas_text = self.extract_canvas_text_via_layers()
        if result.canvas_text:
            print(f"  - 画布文本: {len(result.canvas_text)} 字符")
        if self._need_ui_capture(result):
            result.page_screenshots = self.extract_ui_pages(canvas_name, group_path)
            print(f"  - UI页面截图: {len(result.page_screenshots)} 张")
        all_text = result.canvas_text + " " + \
                   " ".join(a.content for a in result.annotations)
        result.links = extract_links(all_text)
        if result.links:
            print(f"  - 链接: {len(result.links)} 个")
        self._ensure_mode("read_only")
        return result

    # ----------------------------------------------------------
    # 主流程
    # ----------------------------------------------------------
    def run(self, proto_url: str) -> Dict:
        self.start()
        try:
            proto_title = self.open_proto(proto_url)
            canvases = self.traverse_canvas_tree()
            if self.config.max_canvases and self.config.max_canvases > 0:
                canvases = canvases[:self.config.max_canvases]
            results = []
            for idx, canvas_info in enumerate(canvases, 1):
                print(f"\n[{idx}/{len(canvases)}]", end=" ")
                try:
                    result = self.process_canvas(canvas_info)
                    results.append(result)
                except Exception as e:
                    print(f"[ERROR] 处理画布失败: {e}")
                    results.append(CanvasResult(
                        canvas_name=canvas_info["name"], group_path=canvas_info["path"]))
            output = {
                "proto_title": proto_title,
                "proto_url": proto_url,
                "total_canvases": len(results),
                "canvases": [asdict(r) for r in results],
            }
            json_path = os.path.join(self.config.output_dir, "modao_requirements.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            print(f"\n[DONE] JSON 已保存: {json_path}")
            md_path = os.path.join(self.config.output_dir, "modao_requirements.md")
            self._generate_markdown(output, md_path)
            print(f"[DONE] Markdown 已保存: {md_path}")
            return output
        finally:
            self.close()

    def _generate_markdown(self, data: Dict, output_path: str):
        md = f"# {data['proto_title']} — 需求清单\n\n"
        md += f"> 原型链接: {data['proto_url']}\n"
        md += f"> 共 {data['total_canvases']} 个画布\n\n---\n\n"
        groups = defaultdict(list)
        for c in data["canvases"]:
            groups[c["group_path"]].append(c)
        for group_path, canvases in groups.items():
            md += f"## {group_path if group_path else '未分组'}\n\n"
            for c in canvases:
                md += f"### {c['canvas_name']}\n\n"
                if c["annotations"]:
                    md += "**批注需求：**\n\n"
                    for a in c["annotations"]:
                        author = f"（{a['author']}）" if a.get("author") else ""
                        md += f"- **#{a['number']}**{author}: {a['content']}\n"
                        if a.get("requirement_points") and len(a["requirement_points"]) > 1:
                            md += "  - 拆分需求点：\n"
                            for pt in a["requirement_points"]:
                                md += f"    - {pt}\n"
                    md += "\n"
                if c.get("canvas_text"):
                    md += "**画布文本（图层树提取）：**\n\n"
                    md += f"```\n{c['canvas_text']}\n```\n\n"
                if c.get("links"):
                    md += "**关联链接：**\n\n"
                    for link in c["links"]:
                        md += f"- [{link}]({link})\n"
                    md += "\n"
                md += "---\n\n"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="墨刀原型需求自动提取工具（参考实现）")
    parser.add_argument("url", help="墨刀原型分享链接")
    parser.add_argument("--output", "-o", default="./modao_output", help="输出目录")
    parser.add_argument("--ui", action="store_true", help="启用第3路 UI页面截图")
    parser.add_argument("--headful", action="store_true", help="有头模式")
    args = parser.parse_args()
    config = Config(
        output_dir=args.output,
        screenshot_dir=os.path.join(args.output, "screenshots"),
        enable_ui_capture=args.ui,
        headless=not args.headful,
    )
    extractor = ModaoRequirementExtractor(config)
    result = extractor.run(args.url)
    print(f"\n{'='*50}\n提取完成！\n原型: {result['proto_title']}\n"
          f"画布数: {result['total_canvases']}\n输出目录: {config.output_dir}\n{'='*50}")


if __name__ == "__main__":
    main()
