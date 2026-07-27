# -*- coding: utf-8 -*-
"""
墨刀技能 - 原型读取器（浏览器自动逐页提取需求内容，含注释/标注）

核心能力：
  1. 通过 Playwright 打开墨刀原型 URL（支持 cookie 回填绕过登录墙）。
  2. 枚举原型页面（页面树），逐页点击进入。
  3. 每页提取：可见文本 + 注释/标注（批注浮层）+ 截图。
  4. 对图片型/视觉型内容，调视觉模型（browser_use_vision）做 OCR 补充。
  5. 首次登录：可见浏览器扫码，导出 cookie 回填（用户决策 1）。

注意：墨刀是 SPA，页面结构可能随版本变化；提取规则做了防御性 try/except，
单页失败不影响整体，并在结果中标记 extraction_warnings。
"""
import os
import re
import json
import html
import uuid
import base64
import hashlib
import logging
import asyncio
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, quote

logger = logging.getLogger(__name__)

# 页面树常见选择器（按优先级尝试；命中其一即认为找到页面列表）。
# 既兼容墨刀，也尽量覆盖 webshare / 通用原型 SPA 的左侧页面树（best-effort）。
PAGE_TREE_SELECTORS = [
    # 墨刀当前分享视图：真正可点击的页面行带 data-cid；不要命中其内部
    # `.screen-item-icon`，否则 click() 只会选中图标而不会切换画布。
    '.rn-list-item.page[data-cid][data-interactive-target-type="6"]',
    '[data-cid][data-interactive-target-type="6"][class*="StyledScreenItem"]',
    # 墨刀
    '.page-list .page-item',
    '.page-panel .page-item',
    '[class*="pageList"] [class*="pageItem"]',
    '[class*="page-list"] [class*="page-item"]',
    '[class*="PageList"] [class*="PageItem"]',
    'ul.pages li',
    '.modao-page-item',
    # 通用 SPA / webshare 类左侧页面树（命中即认为找到页面列表）
    '[class*="pageTree"] [class*="pageItem"]',
    '[class*="page-tree"] [class*="page-item"]',
    '[class*="outline"] [class*="item"]',
    '[class*="catalog"] [class*="item"]',
    '[class*="sidebar"] [class*="page"]',
    '[class*="navPage"]',
    '[class*="tree"] li',
    '[class*="menu"] li',
]

# webshare 专用页面树选择器（hash 路由原型：目录页左侧通常列出带 #id= / &p= 的子页面链接）。
# 命中其一即认为找到页面列表；识别不到时回退到通用 PAGE_TREE_SELECTORS。
WEBSHARE_PAGE_TREE_SELECTORS = [
    '[class*="pageTree"] [class*="pageItem"]',
    '[class*="page-tree"] [class*="page-item"]',
    '[class*="pageList"] [class*="pageItem"]',
    '[class*="outline"] [class*="item"]',
    '[class*="catalog"] [class*="item"]',
    '[class*="sidebar"] [class*="page"]',
    '[class*="navPage"]',
    '[class*="tree"] li',
    '[class*="menu"] li',
    # webshare 用 hash 区分页面，目录里通常是带 #id= / &p= 的链接
    'a[href*="#id="]',
    'a[href*="&p="]',
    'a[href*="?p="]',
]

# ---------- webshare / Axure 原型：纯 HTTP 解析页面树（无需浏览器）----------
# Axure 生成的原型把页面树放在 data/document.js（不在 DOM），每个页面是服务端静态
# 渲染的 HTML（文本在 <div id="uN_text"> 容器内）。因此 webshare 走 HTTP 抓取 + 解析，
# 比 Playwright 渲染更稳更快，且能一次自动发现目录下所有子页面。
_AXURE_DOC_URL = 'data/document.js'
_AXURE_VAR_RE = re.compile(r'([\w$]+)\s*=\s*"((?:[^"\\]|\\.)*)"')
_AXURE_PAGE_RE = re.compile(
    r'_\(\s*s\s*,\s*([\w$]+|"[^"]*")\s*,\s*u\s*,\s*([\w$]+|"[^"]*")\s*,\s*w\s*,\s*([\w$]+|"[^"]*")\s*,\s*y\s*,\s*([\w$]+|"[^"]*")'
)
_AXURE_TEXT_DIV_RE = re.compile(r'id="u\d+_text"[^>]*>(.*?)</div>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')
_UA_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'),
}


def _axure_resolve(token: str, var_map: Dict[str, str]) -> str:
    token = (token or '').strip()
    if token.startswith('"') and token.endswith('"'):
        return html.unescape(token[1:-1])
    return var_map.get(token, '')


def parse_axure_document(js_text: str) -> List[Dict[str, str]]:
    """从 Axure 的 data/document.js 解析页面树，返回 [{id, pageName, url}]（过滤文件夹节点）。"""
    var_map = {m.group(1): m.group(2) for m in _AXURE_VAR_RE.finditer(js_text)}
    pages: List[Dict[str, str]] = []
    for m in _AXURE_PAGE_RE.finditer(js_text):
        ptype = _axure_resolve(m.group(3), var_map)
        if ptype and ptype != 'Wireframe':
            continue  # 跳过文件夹等非页面节点
        pid = _axure_resolve(m.group(1), var_map)
        name = _axure_resolve(m.group(2), var_map)
        url = _axure_resolve(m.group(4), var_map)
        if pid and url:
            pages.append({'id': pid, 'pageName': name or pid, 'url': url})
    return pages


def extract_axure_text(html_text: str) -> str:
    """从 Axure 页面 HTML 提取可见文本（仅取 _text 容器内的 p/span 文本，保留段落结构）。"""
    texts: List[str] = []
    for block in _AXURE_TEXT_DIV_RE.findall(html_text):
        # 在块级/换行标签处断行，保留段落结构
        block = re.sub(r'</(p|div|br\s*/?)>', '\n', block, flags=re.I)
        block = _TAG_RE.sub('', block)
        block = html.unescape(block)
        block = re.sub(r'[ \t]+', ' ', block)
        block = re.sub(r'\n\s*\n+', '\n', block).strip()
        if block:
            texts.append(block)
    return '\n'.join(texts)

# 注释/标注相关选择器（批注气泡、评论浮层）
ANNOTATION_SELECTORS = [
    '[class*="comment"]',
    '[class*="note"]',
    '[class*="annotation"]',
    '[class*="批注"]',
    '[class*="remark"]',
    '.comment-bubble',
    '.note-item',
]

MEDIA_ROOT = os.environ.get('MEDIA_ROOT', 'media')


class ModaoExtractor:
    """墨刀原型逐页读取器。"""

    def __init__(self, run_id: Optional[str] = None, media_root: str = MEDIA_ROOT):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.media_root = media_root
        self.shot_dir = os.path.join(media_root, 'modao', self.run_id)
        os.makedirs(self.shot_dir, exist_ok=True)

    # ---------- 公共入口 ----------
    async def extract(
        self,
        url: str,
        cookies: Optional[str] = None,
        headless: bool = True,
        vision_config=None,
        max_pages: int = 200,
        enumerate_pages: bool = True,
        source_type: str = 'modao',
        dual_fusion: bool = False,
        fusion_config=None,
    ) -> Dict[str, Any]:
        """
        逐页提取墨刀原型需求内容。

        Returns:
            {
              'run_id': str,
              'url': str,
              'pages': [ {page_no, page_name, text, annotations:[...], screenshot, extraction_warnings:[...]} ],
              'warnings': [...]
            }
        """
        from playwright.async_api import async_playwright

        warnings: List[str] = []
        pages: List[Dict[str, Any]] = []

        cookie_list = self._parse_cookies(cookies)
        if cookies and not cookie_list:
            warnings.append('cookie 解析失败，将尝试匿名访问（可能遇到登录墙）')

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=['--no-sandbox', '--disable-dev-shm-usage'],
            )
            context = await browser.new_context(
                viewport={'width': 1440, 'height': 900},
                user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'),
            )
            if cookie_list:
                try:
                    await context.add_cookies(cookie_list)
                except Exception as e:
                    warnings.append(f'注入 cookie 失败: {e}')

            page = await context.new_page()
            try:
                await page.goto(url, wait_until='networkidle', timeout=60000)
            except Exception as e:
                warnings.append(f'页面加载超时/异常（继续尝试提取）: {e}')
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                except Exception as e2:
                    warnings.append(f'二次加载失败，终止: {e2}')
                    await browser.close()
                    return {'run_id': self.run_id, 'url': url, 'pages': pages, 'warnings': warnings}
            await page.wait_for_timeout(2000)

            # 枚举页面（多 URL 批量场景由调用方传 enumerate_pages=False，避免重复抓取）
            page_items = await self._enumerate_pages(page, source_type=source_type) if enumerate_pages else []
            if not page_items:
                warnings.append('未识别到页面树，将把当前单页作为唯一页面提取')
                page_items = [None]  # 单页模式

            for idx, item in enumerate(page_items[:max_pages], start=1):
                try:
                    extraction_warnings: List[str] = []
                    page_name = f'第{idx}页'
                    if item is not None:
                        try:
                            page_name = (await item.inner_text()).strip() or page_name
                        except Exception:
                            pass
                        switched = await self._activate_page_item(page, item)
                        if not switched:
                            msg = f'第{idx}页"{page_name}"点击后画布未发生变化'
                            warnings.append(msg)
                            extraction_warnings.append(msg)
                    else:
                        # 单页模式：确保回到原型根视图
                        pass

                    # Modao may show a welcome/login overlay on read-only shares.
                    # Escape closes the transient overlay without changing the canvas.
                    try:
                        await page.keyboard.press('Escape')
                        await page.wait_for_timeout(200)
                    except Exception:
                        pass

                    dom_text = await self._extract_visible_text(page, retry=dual_fusion)
                    annotations = await self._extract_annotations(page, warnings)
                    shot_path = os.path.join(self.shot_dir, f'page_{idx}.png')
                    try:
                        await page.screenshot(path=shot_path, full_page=False)
                    except Exception as e:
                        shot_path = ''
                        warnings.append(f'第{idx}页截图失败: {e}')

                    # 视觉 OCR 补充（按页面情况自动切换）：
                    # - 墨刀(modao)：画布用 canvas/SVG 渲染，文字/图片/表格根本不进入 DOM 文本，
                    #   也无法用 <img>/<table> 检测命中，原『文本少 / has_visual』判定对其完全失效。
                    #   因此墨刀页面只要有截图，就默认做一次视觉 OCR，把画布里的全部需求内容
                    #   （文字段落 + 图片 + 表格）都识别出来，与左侧导航 DOM 文本合并。
                    # - 其他源(webshare 等)：沿用『文本<30字 或 页面含图片/表格』判定，
                    #   纯文本无图无表的页面不触发，避免无谓的视觉模型开销。
                    vision_result = {'ocr_text': '', 'visual_summary': '', 'visual_artifacts': []}
                    if source_type == 'modao':
                        need_vision = bool(shot_path and os.path.exists(shot_path))
                    else:
                        has_visual = await self._page_has_visual(page)
                        need_vision = len((dom_text or '').strip()) < 30 or has_visual
                    vision_text = ''
                    vision_attempted = bool(
                        vision_config and shot_path and os.path.exists(shot_path) and need_vision
                    )
                    if vision_config and shot_path and os.path.exists(shot_path) and need_vision:
                        vision_result = await self._ocr_screenshot(vision_config, shot_path)
                        vision_text = vision_result.get('ocr_text', '')
                    vision_success = bool(
                        vision_text
                        or vision_result.get('visual_summary')
                        or vision_result.get('visual_artifacts')
                    )
                    if vision_attempted and not vision_success:
                        extraction_warnings.append('视觉识别未返回有效内容')
                    # 兼容字段：DOM 文本 + 视觉 OCR 合并，维持 run_struct 既有消费方式
                    text = (dom_text or '')
                    if vision_text:
                        text = text + '\n[视觉OCR补充]\n' + vision_text
                    # 双路融合策略：DOM 路径与视觉路径作为独立输入分开保留
                    page_vision_text = vision_text or ''
                    if vision_result.get('visual_summary'):
                        page_vision_text = (page_vision_text + '\n' + vision_result['visual_summary']).strip()

                    pages.append({
                        'page_no': idx,
                        'page_name': page_name,
                        'text': text,
                        'dom_text': dom_text,
                        'vision_text': page_vision_text,
                        'dom_text_len': len(dom_text or ''),
                        'vision_attempted': vision_attempted,
                        'vision_success': vision_success,
                        'annotations': annotations,
                        'screenshot': os.path.relpath(shot_path, self.media_root) if shot_path else '',
                        'visual_summary': vision_result.get('visual_summary', ''),
                        'visual_artifacts': vision_result.get('visual_artifacts', []),
                        'extraction_warnings': extraction_warnings,
                    })
                except Exception as e:
                    warnings.append(f'第{idx}页提取异常: {e}')
                    pages.append({
                        'page_no': idx,
                        'page_name': f'第{idx}页',
                        'text': '',
                        'annotations': [],
                        'screenshot': '',
                        'extraction_warnings': [str(e)],
                        'visual_summary': '',
                        'visual_artifacts': [],
                    })

            duplicate_groups = self._mark_duplicate_screenshots(pages)
            if duplicate_groups:
                duplicate_count = sum(len(group) - 1 for group in duplicate_groups)
                warnings.append(
                    f'检测到 {duplicate_count} 个重复画布截图，重复页不应视为读取成功：'
                    + '；'.join(','.join(str(no) for no in group) for group in duplicate_groups)
                )

            await browser.close()

        # 可选增强策略：双路 DOM + 视觉 交叉融合（仅 dual_fusion=True 且提供 fusion_config 时触发）
        fused_requirements: List[Dict[str, Any]] = []
        if dual_fusion and fusion_config:
            try:
                fused_requirements = await self.dual_fusion_requirements(pages, fusion_config)
            except Exception as e:
                logger.warning(f'双路融合失败（已跳过，保留分路径数据）: {e}')
                warnings.append(f'双路融合失败（已跳过）: {e}')

        result: Dict[str, Any] = {
            'run_id': self.run_id, 'url': url, 'pages': pages, 'warnings': warnings}
        if dual_fusion:
            result['dual_fusion'] = True
            result['fused_requirements'] = fused_requirements
        return result

    @staticmethod
    def _is_axure_url(url: str, cookies: Optional[str] = None) -> bool:
        """快速探测 URL 是否为 Axure/webshare 原型：尝试抓取 data/document.js 并解析页面树。
        命中则返回 True（说明该地址是 webshare 目录，应走多页 HTTP 解析而非单页浏览器抓取）。"""
        import requests
        try:
            base = url.split('#')[0]
            if not base.endswith('/'):
                last_seg = base.rsplit('/', 1)[-1]
                base = base.rsplit('/', 1)[0] + '/' if '.' in last_seg else base + '/'
            doc_url = urljoin(base, _AXURE_DOC_URL)
            resp = requests.get(doc_url, cookies=ModaoExtractor._cookie_dict(cookies),
                                timeout=15, headers=_UA_HEADERS)
            if resp.status_code != 200:
                return False
            if not resp.encoding or resp.encoding.lower() in ('iso-8859-1', 'ascii'):
                resp.encoding = 'utf-8'
            return bool(parse_axure_document(resp.text))
        except Exception:
            return False

    def extract_sync(self, *args, **kwargs) -> Dict[str, Any]:
        """同步包装（供 Django 视图在线程中调用）。
        webshare 走纯 HTTP 解析路径；墨刀来源若检测到实际是 Axure/webshare 原型，
        也自动路由到 webshare 多页解析（避免把 webshare 地址误粘到墨刀框时只读出单页）。"""
        kwargs.setdefault('dual_fusion', False)
        kwargs.setdefault('fusion_config', None)
        source_type = kwargs.get('source_type', 'modao')
        url = kwargs.get('url')
        # 自动识别：墨刀来源但 URL 实为 Axure/webshare 原型时，自动走多页解析
        if source_type != 'webshare' and url:
            import logging
            _logger = logging.getLogger('modao')
            _logger.info(f'[AUTO-DETECT] source_type={source_type}, url={url[:120]}')
            try:
                is_axure = self._is_axure_url(url, kwargs.get('cookies'))
                _logger.info(f'[AUTO-DETECT] _is_axure_url returned {is_axure}')
                if is_axure:
                    source_type = 'webshare'
                    _logger.info('[AUTO-DETECT] -> routing to webshare path')
            except Exception as detect_err:
                _logger.warning(f'[AUTO-DETECT] _is_axure_url raised {detect_err}')
        else:
            import logging
            logging.getLogger('modao').info(f'[AUTO-DETECT] skipped: source_type={source_type}, url={bool(url)}')
        if source_type == 'webshare':
            # webshare / Axure 原型：解析 data/document.js 拿页面树，逐个 HTTP 抓取页面 HTML，
            # 不需要启动浏览器，更稳更快，且一次自动发现目录下所有子页面。
            import logging
            logging.getLogger('modao').info(f'[extract_sync] calling extract_webshare_sync(url={url[:100]})')
            return self.extract_webshare_sync(
                url=url,
                cookies=kwargs.get('cookies'),
                vision_config=kwargs.get('vision_config'),
                dual_fusion=kwargs.get('dual_fusion'),
                fusion_config=kwargs.get('fusion_config'),
            )
        import logging
        logging.getLogger('modao').info(f'[extract_sync] falling through to Playwright path, source_type={source_type}')
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.extract(*args, **kwargs))

    # ---------- webshare / Axure：纯 HTTP 解析（无需浏览器）----------
    @staticmethod
    def _cookie_dict(cookies: Optional[str]) -> Dict[str, str]:
        """把 cookie 字符串（JSON 列表 / JSON 对象 / name=value;...）转成 requests 用的 dict。"""
        if not cookies:
            return {}
        try:
            data = json.loads(cookies)
            if isinstance(data, list):
                return {c.get('name'): c.get('value') for c in data if isinstance(c, dict)}
            if isinstance(data, dict):
                if isinstance(data.get('cookies'), list):
                    return {c.get('name'): c.get('value') for c in data['cookies'] if isinstance(c, dict)}
                return {k: v for k, v in data.items() if isinstance(v, str)}
        except Exception:
            pass
        d: Dict[str, str] = {}
        for part in cookies.split(';'):
            if '=' in part:
                k, v = part.split('=', 1)
                d[k.strip()] = v.strip()
        return d

    def extract_webshare_sync(self, url: str, cookies: Optional[str] = None, timeout: int = 30,
                              vision_config=None, dual_fusion: bool = False,
                              fusion_config=None) -> Dict[str, Any]:
        """webshare / Axure 原型读取：解析 data/document.js 拿页面树，逐个 HTTP 抓取页面 HTML 提取文本。

        返回结构与 extract() 一致：{'run_id','url','pages':[{page_no,page_name,text,annotations,screenshot,extraction_warnings}],'warnings'}
        """
        import requests
        warnings: List[str] = []
        pages: List[Dict[str, Any]] = []
        cookie_dict = self._cookie_dict(cookies)

        # 规范化目录地址：去掉 hash 片段，补尾部斜杠（兼容直接粘贴某页面 .html 链接）
        base = url.split('#')[0]
        if not base.endswith('/'):
            last_seg = base.rsplit('/', 1)[-1]
            if '.' in last_seg:
                base = base.rsplit('/', 1)[0] + '/'
            else:
                base = base + '/'

        try:
            doc_url = urljoin(base, _AXURE_DOC_URL)
            resp = requests.get(doc_url, cookies=cookie_dict, timeout=timeout, headers=_UA_HEADERS)
            if not resp.encoding or resp.encoding.lower() in ('iso-8859-1', 'ascii'):
                resp.encoding = 'utf-8'
            doc_js = resp.text
        except Exception as e:
            warnings.append(f'获取 {doc_url} 失败: {e}')
            return {'run_id': self.run_id, 'url': url, 'pages': pages, 'warnings': warnings}

        axure_pages = parse_axure_document(doc_js)
        if not axure_pages:
            warnings.append('未能从 data/document.js 解析出页面树，请确认链接为 Axure/webshare 原型目录')
            return {'run_id': self.run_id, 'url': url, 'pages': pages, 'warnings': warnings}

        for idx, ap in enumerate(axure_pages, 1):
            try:
                page_url = urljoin(base, quote(ap['url'], safe=''))
                r = requests.get(page_url, cookies=cookie_dict, timeout=timeout, headers=_UA_HEADERS)
                if not r.encoding or r.encoding.lower() in ('iso-8859-1', 'ascii'):
                    r.encoding = 'utf-8'
                dom_text = extract_axure_text(r.text)
                screenshot_path = ''
                vision_result = {'ocr_text': '', 'visual_summary': '', 'visual_artifacts': []}
                vision_text = ''
                vision_attempted = False
                # 视觉 OCR 补充（自动切换）。触发条件满足其一：
                #   1) 文本极少(<30字) → 纯图片/截图/表格页；
                #   2) HTML 含 <img> / <table> / 背景图 → 混合页（文字+图片+表格），
                #      需视觉补充图片/表格内容。纯文本页不受影响。
                if vision_config and (
                    dual_fusion or len(dom_text.strip()) < 30 or self._html_has_visual(r.text)
                ):
                    vision_attempted = True
                    try:
                        vision_result = asyncio.run(
                            self._ocr_webshare_page_async(page_url, cookie_dict, vision_config, idx)
                        )
                    except Exception as e:
                        vision_result = {'ocr_text': '', 'visual_summary': '', 'visual_artifacts': []}
                        logger.warning(f'webshare 页面[{ap.get("pageName")}]视觉OCR失败: {e}')
                    vision_text = vision_result.get('ocr_text', '')
                vision_success = bool(
                    vision_text
                    or vision_result.get('visual_summary')
                    or vision_result.get('visual_artifacts')
                )
                # 兼容字段：DOM 文本 + 视觉 OCR 合并，维持 run_struct 既有消费方式
                text = (dom_text or '')
                if vision_text:
                    text = text + '\n[视觉OCR补充]\n' + vision_text
                rendered_shot = os.path.join(self.shot_dir, f'ws_page_{idx}.png')
                if os.path.exists(rendered_shot):
                    screenshot_path = os.path.relpath(rendered_shot, self.media_root)
                page_vision_text = vision_text or ''
                if vision_result.get('visual_summary'):
                    page_vision_text = (page_vision_text + '\n' + vision_result['visual_summary']).strip()
                pages.append({
                    'page_no': idx,
                    'page_name': ap.get('pageName') or f'第{idx}页',
                    'text': text,
                    'dom_text': dom_text,
                    'vision_text': page_vision_text,
                    'dom_text_len': len(dom_text or ''),
                    'vision_attempted': vision_attempted,
                    'vision_success': vision_success,
                    'annotations': [],
                    'screenshot': screenshot_path,
                    'visual_summary': vision_result.get('visual_summary', ''),
                    'visual_artifacts': vision_result.get('visual_artifacts', []),
                    'extraction_warnings': (
                        ['视觉识别未返回有效内容']
                        if vision_attempted and not vision_success else []
                    ),
                })
            except Exception as e:
                warnings.append(f"页面[{ap.get('pageName')}]抓取失败: {e}")
                pages.append({
                    'page_no': idx,
                    'page_name': ap.get('pageName') or f'第{idx}页',
                    'text': '',
                    'annotations': [],
                    'screenshot': '',
                    'visual_summary': '',
                    'visual_artifacts': [],
                    'extraction_warnings': [str(e)],
                })

        fused_requirements: List[Dict[str, Any]] = []
        if dual_fusion and fusion_config:
            try:
                fused_requirements = asyncio.run(self.dual_fusion_requirements(pages, fusion_config))
            except Exception as e:
                logger.warning(f'webshare 双路融合失败（已跳过）: {e}')
                warnings.append(f'双路融合失败（已跳过）: {e}')
        result: Dict[str, Any] = {
            'run_id': self.run_id, 'url': url, 'pages': pages, 'warnings': warnings}
        if dual_fusion:
            result['dual_fusion'] = True
            result['fused_requirements'] = fused_requirements
        return result

    # ---------- webshare / Axure：纯图片页视觉 OCR 兜底 ----------
    async def _ocr_webshare_page_async(self, page_url: str, cookie_dict: Dict[str, str],
                                       vision_config, idx: int) -> Dict[str, Any]:
        """对 webshare 单个页面用 Playwright 渲染、截图，再调视觉模型 OCR（纯图片/截图/表格页兜底）。

        仅在 extract_webshare_sync 中『文本极少』时调用，纯文本页不会进入此分支。
        """
        from playwright.async_api import async_playwright
        if not vision_config:
            return {'ocr_text': '', 'visual_summary': '', 'visual_artifacts': []}
        shot_path = os.path.join(self.shot_dir, f'ws_page_{idx}.png')
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                context = await browser.new_context(
                    viewport={'width': 1440, 'height': 900},
                    user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                                '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'))
                if cookie_dict:
                    try:
                        await context.add_cookies(
                            [{'name': k, 'value': v, 'url': page_url} for k, v in cookie_dict.items()])
                    except Exception:
                        pass
                page = await context.new_page()
                await page.goto(page_url, wait_until='networkidle', timeout=60000)
                await page.wait_for_timeout(2000)
                await page.screenshot(path=shot_path, full_page=True)
                await browser.close()
            return await self._ocr_screenshot(vision_config, shot_path)
        except Exception as e:
            logger.warning(f'webshare 页面渲染/截图失败（跳过视觉OCR）: {e}')
            return {'ocr_text': '', 'visual_summary': '', 'visual_artifacts': []}

    # ---------- 首次登录：可见浏览器扫码导 cookie ----------
    async def login_and_export_cookie(self, url: str, wait_seconds: int = 120) -> str:
        """
        启动可见浏览器，用户扫码登录；等待 wait_seconds 秒（或检测到登录态）后导出 cookie。
        Returns: cookie JSON 字符串（供后续回填）。
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=['--no-sandbox'])
            context = await browser.new_context(viewport={'width': 1440, 'height': 900})
            page = await context.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            logger.info(f'请在打开的浏览器中扫码登录墨刀，将在 {wait_seconds}s 后自动导出 cookie…')
            await page.wait_for_timeout(wait_seconds * 1000)
            cookies = await context.cookies()
            await browser.close()
            return json.dumps(cookies, ensure_ascii=False)

    # ---------- 内部辅助 ----------
    @staticmethod
    def _parse_cookies(cookies: Optional[str]) -> List[Dict[str, Any]]:
        if not cookies:
            return []
        try:
            data = json.loads(cookies)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and 'cookies' in data:
                return data['cookies']
        except Exception:
            pass
        return []

    async def _enumerate_pages(self, page, source_type: str = None) -> List[Any]:
        """枚举页面树元素，返回可点击的页面项列表（为空表示未识别）。"""
        selectors = list(PAGE_TREE_SELECTORS)
        if source_type == 'webshare':
            # webshare 优先用专门的页面树选择器，再回退通用选择器
            selectors = list(WEBSHARE_PAGE_TREE_SELECTORS) + list(PAGE_TREE_SELECTORS)
        for sel in selectors:
            try:
                items = await page.query_selector_all(sel)
                if items:
                    logger.info(f'页面树命中选择器: {sel}，共 {len(items)} 页')
                    return items
            except Exception:
                continue
        return []

    @staticmethod
    async def _viewport_fingerprint(page) -> str:
        """返回当前稳定视口指纹，用于验证点击页面树后画布确实发生变化。"""
        try:
            payload = await page.screenshot(full_page=False)
            return hashlib.sha256(payload).hexdigest()
        except Exception:
            return ''

    async def _activate_page_item(self, page, item) -> bool:
        """点击页面树条目，并用视口指纹确认切换；普通点击失败时再强制点击一次。"""
        try:
            await page.keyboard.press('Escape')
            await page.wait_for_timeout(200)
        except Exception:
            pass
        before = await self._viewport_fingerprint(page)
        for force in (False, True):
            try:
                await item.scroll_into_view_if_needed()
                await item.click(force=force, timeout=5000)
                await page.wait_for_timeout(1500)
                try:
                    await page.keyboard.press('Escape')
                    await page.wait_for_timeout(200)
                except Exception:
                    pass
                after = await self._viewport_fingerprint(page)
                if before and after and before != after:
                    return True
            except Exception:
                continue
        return False

    def _mark_duplicate_screenshots(self, pages: List[Dict[str, Any]]) -> List[List[int]]:
        """标记字节完全相同的截图；保留页面供审计，但明确标为读取异常。"""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for page_data in pages:
            rel_path = page_data.get('screenshot') or ''
            abs_path = os.path.join(self.media_root, rel_path) if rel_path else ''
            if not abs_path or not os.path.exists(abs_path):
                continue
            with open(abs_path, 'rb') as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            page_data['screenshot_sha256'] = digest
            groups.setdefault(digest, []).append(page_data)

        duplicates = []
        for same_pages in groups.values():
            if len(same_pages) < 2:
                continue
            page_nos = [int(page_data.get('page_no') or 0) for page_data in same_pages]
            duplicates.append(page_nos)
            for page_data in same_pages[1:]:
                page_data.setdefault('extraction_warnings', []).append(
                    f'截图与第{page_nos[0]}页完全一致，未计为独立有效页面'
                )
                page_data['duplicate_of_page'] = page_nos[0]
        return duplicates

    async def _extract_visible_text(self, page, retry: bool = False,
                                    min_chars: int = 60, max_retries: int = 2) -> str:
        """提取页面可见文本。retry=True 时（墨刀 DOM 异步渲染）首抓偏短则等待重试，
        对抗偶发 0 字符 / 未就绪，返回最终文本。"""
        try:
            text = (await page.evaluate('() => document.body.innerText') or '').strip()
        except Exception as e:
            logger.warning(f'提取可见文本失败: {e}')
            return ''
        tries = 1
        while retry and len(text) < min_chars and tries <= max_retries:
            await page.wait_for_timeout(1500)
            try:
                text = (await page.evaluate('() => document.body.innerText') or '').strip()
            except Exception:
                break
            tries += 1
        return text

    async def _extract_annotations(self, page, warnings: List[str]) -> List[str]:
        """尽力提取注释/标注文本。"""
        results: List[str] = []
        for sel in ANNOTATION_SELECTORS:
            try:
                nodes = await page.query_selector_all(sel)
                for node in nodes:
                    try:
                        t = (await node.inner_text()).strip()
                        if t and t not in results:
                            results.append(t)
                    except Exception:
                        continue
            except Exception:
                continue
        # 若命中了批注切换按钮，尝试展开评论面板再抓一次
        try:
            toggle = await page.query_selector('[class*="comment-toggle"], [class*="note-toggle"], [aria-label*="评论"], [aria-label*="批注"]')
            if toggle:
                await toggle.click()
                await page.wait_for_timeout(800)
                panel_text = await self._extract_visible_text(page)
                if panel_text:
                    results.append('[评论面板] ' + panel_text[:1000])
        except Exception as e:
            warnings.append(f'展开评论面板失败（可忽略）: {e}')
        return results

    async def _page_has_visual(self, page) -> bool:
        """检测当前页面是否含实质图片或表格元素（用于判定『混合页』是否需要视觉补充）。

        - 图片：<img>（naturalWidth/Height > 60px，排除图标/占位）或有 background-image 的较大区块；
        - 表格：<table>，或墨刀/Axure 常见的多行多列网格结构。
        任一命中即返回 True。检测失败时保守返回 False（不影响主流程）。
        """
        try:
            return bool(await page.evaluate(
                """() => {
                    const bigImg = Array.from(document.images || [])
                        .some(im => (im.naturalWidth||im.width) > 60 && (im.naturalHeight||im.height) > 60);
                    if (bigImg) return true;
                    if (document.querySelector('table')) return true;
                    // 较大的背景图区块（排除极小图标）
                    const bgBlock = Array.from(document.querySelectorAll('*')).some(el => {
                        const bg = getComputedStyle(el).backgroundImage;
                        if (!bg || bg === 'none' || bg.indexOf('url(') === -1) return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 120 && r.height > 120;
                    });
                    return bgBlock;
                }"""
            ))
        except Exception as e:
            logger.warning(f'页面图片/表格检测失败（按无视觉处理）: {e}')
            return False

    @staticmethod
    def _html_has_visual(html: str) -> bool:
        """检测 webshare/Axure 页面 HTML 是否含图片或表格（用于『混合页』视觉补充判定）。"""
        if not html:
            return False
        low = html.lower()
        return ('<img' in low) or ('<table' in low) or ('background-image' in low)

    @staticmethod
    def _parse_visual_payload(content: str) -> Dict[str, Any]:
        text = (content or '').strip()
        match = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
        candidates = (text, text[text.find('{'):text.rfind('}') + 1])
        for candidate in candidates:
            try:
                value = json.loads(candidate)
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
        # Vision models occasionally omit quotes around an ASCII JSON key while
        # otherwise returning a complete payload (for example `,result_fields:`).
        # Repair keys only; never alter cell values or synthesize missing content.
        for candidate in candidates:
            repaired = re.sub(
                r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:',
                r'\1"\2":',
                candidate,
            )
            try:
                value = json.loads(repaired)
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
        # JSON is a YAML subset; SafeLoader also accepts harmless omissions
        # such as an unquoted mapping key that strict JSON rejects.
        try:
            import yaml
            for candidate in candidates:
                value = yaml.safe_load(candidate)
                if isinstance(value, dict):
                    return value
        except Exception:
            pass
        return {}

    @staticmethod
    def _validate_visual_artifact(artifact: Dict[str, Any]) -> Dict[str, Any]:
        rows = artifact.get('rows') if isinstance(artifact.get('rows'), list) else []
        columns = artifact.get('columns') if isinstance(artifact.get('columns'), list) else []
        result = {
            'row_count': len(rows),
            'column_count': len(columns),
            'shape_valid': bool(rows),
            'duplicate_combinations': [],
            'invalid_rule_references': [],
        }
        artifact_type = artifact.get('artifact_type')
        if artifact_type == 'state_matrix':
            states = artifact.get('states') if isinstance(artifact.get('states'), list) else []
            state_names = [str(item.get('state') or '').strip() for item in states if isinstance(item, dict)]
            transitions = artifact.get('transitions') if isinstance(artifact.get('transitions'), list) else []
            invalid_transitions = []
            known = set(state_names)
            for index, transition in enumerate(transitions, 1):
                if not isinstance(transition, dict):
                    invalid_transitions.append(index)
                    continue
                source = str(transition.get('from') or '').strip()
                target = str(transition.get('to') or '').strip()
                if (source and source not in known) or (target and target not in known):
                    invalid_transitions.append(index)
            result.update({
                'state_count': len(states),
                'state_names': state_names,
                'duplicate_states': sorted({name for name in state_names if state_names.count(name) > 1}),
                'invalid_transitions': invalid_transitions,
                'structure_valid': bool(states) and all(state_names),
                'transitions_traceable': not invalid_transitions,
            })
            result['shape_valid'] = result['structure_valid']
            return result
        if artifact_type == 'state_machine':
            states = artifact.get('states') if isinstance(artifact.get('states'), list) else []
            transitions = artifact.get('transitions') if isinstance(artifact.get('transitions'), list) else []
            result.update({'state_count': len(states), 'transition_count': len(transitions),
                           'structure_valid': bool(states) and bool(transitions)})
            result['shape_valid'] = result['structure_valid']
            return result
        if artifact_type != 'decision_table':
            if rows and columns and all(isinstance(row, list) for row in rows):
                result['shape_valid'] = all(len(row) == len(columns) for row in rows)
            elif artifact_type in {'ui_screen', 'interaction_flow', 'rule_list', 'timeline',
                                   'permission_matrix', 'pricing_matrix', 'form_schema',
                                   'list_spec', 'flowchart', 'annotation'}:
                result['shape_valid'] = bool(
                    artifact.get('elements') or artifact.get('rules') or artifact.get('nodes')
                    or artifact.get('steps') or rows or artifact.get('raw_text')
                )
            return result

        dimensions = artifact.get('dimensions') if isinstance(artifact.get('dimensions'), list) else []
        names = [x.get('name') if isinstance(x, dict) else str(x) for x in dimensions]
        names = [x for x in names if x]
        result_fields = artifact.get('result_fields') or ['user_a_result', 'user_b_result']
        seen = {}
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                result['shape_valid'] = False
                continue
            key = tuple(str(row.get(name, '')) for name in names)
            if key in seen:
                result['duplicate_combinations'].append([seen[key], index])
            seen[key] = index
            if names and any(not row.get(name) for name in names):
                result['shape_valid'] = False
            if any(field not in row for field in result_fields):
                result['shape_valid'] = False

        valid_rows = set(range(1, len(rows) + 1))
        for index, rule in enumerate(artifact.get('derived_rules') or [], 1):
            refs = rule.get('source_rows') if isinstance(rule, dict) else None
            if not isinstance(refs, list) or not refs or not set(refs).issubset(valid_rows):
                result['invalid_rule_references'].append(index)

        expanded = list(rows)
        pair_keys = {'user_a_platform', 'user_a_type', 'user_b_platform', 'user_b_type'}
        if pair_keys.issubset(set(names)) and all(isinstance(row, dict) for row in rows):
            existing = {tuple(str(row.get(name, '')) for name in names) for row in rows}
            for row in rows:
                swapped = dict(row)
                swapped['user_a_platform'], swapped['user_b_platform'] = row.get('user_b_platform'), row.get('user_a_platform')
                swapped['user_a_type'], swapped['user_b_type'] = row.get('user_b_type'), row.get('user_a_type')
                swapped['user_a_result'], swapped['user_b_result'] = row.get('user_b_result'), row.get('user_a_result')
                key = tuple(str(swapped.get(name, '')) for name in names)
                if key not in existing:
                    existing.add(key)
                    expanded.append(swapped)

        expected = 1
        for dimension in dimensions:
            values = dimension.get('values') if isinstance(dimension, dict) else None
            if not values:
                expected = None
                break
            expected *= len(values)
        result.update({
            'raw_combination_count': len(rows),
            'expanded_combination_count': len(expanded),
            'expected_combination_count': expected,
            'coverage_complete': len(expanded) >= expected if expected else None,
            'symmetry_expanded': len(expanded) > len(rows),
            'expanded_rows': expanded,
            'rules_traceable': not result['invalid_rule_references'],
        })
        return result

    @classmethod
    def _merge_decision_table_fragments(cls, raw_artifacts: List[Any]) -> List[Any]:
        """Merge adjacent 4-cell identity/result cards into one decision table."""
        fragments = []
        for index, artifact in enumerate(raw_artifacts):
            if not isinstance(artifact, dict) or artifact.get('artifact_type') != 'table':
                continue
            columns = artifact.get('columns') or []
            rows = artifact.get('rows') or []
            results = rows[0] if len(rows) == 1 and isinstance(rows[0], list) else []
            if len(columns) != 4 or len(results) != 4:
                continue
            identities = []
            for cell in columns:
                match = re.fullmatch(r'\s*(Android|iOS)\s*(新用户|老用户)\s*', str(cell), re.I)
                if not match:
                    identities = []
                    break
                platform = 'Android' if match.group(1).lower() == 'android' else 'iOS'
                identities.append((platform, match.group(2)))
            if identities and all(str(value).strip() in ('屏蔽', '不屏蔽') for value in results):
                fragments.append((index, artifact, identities, [str(x).strip() for x in results]))
        if len(fragments) < 2:
            return raw_artifacts

        combined_rows = []
        bboxes = []
        source_ids = []
        for index, artifact, identities, results in fragments:
            source_ids.append(artifact.get('artifact_id') or f'fragment-{index + 1}')
            if isinstance(artifact.get('bbox'), list) and len(artifact['bbox']) == 4:
                bboxes.append(artifact['bbox'])
            for offset in (0, 2):
                combined_rows.append({
                    'user_a_platform': identities[offset][0],
                    'user_a_type': identities[offset][1],
                    'user_b_platform': identities[offset + 1][0],
                    'user_b_type': identities[offset + 1][1],
                    'user_a_result': results[offset],
                    'user_b_result': results[offset + 1],
                    'source_fragment': source_ids[-1],
                })
        bbox = None
        if bboxes:
            bbox = [min(x[0] for x in bboxes), min(x[1] for x in bboxes),
                    max(x[2] for x in bboxes), max(x[3] for x in bboxes)]
        decision_table = {
            'artifact_type': 'decision_table',
            'title': next((item[1].get('title') for item in fragments if item[1].get('title')), '决策表'),
            'bbox': bbox,
            'confidence': min(float(item[1].get('confidence') or 0) for item in fragments),
            'preconditions': {'对新用户屏蔽': '是'},
            'dimensions': [
                {'name': 'user_a_platform', 'values': ['Android', 'iOS']},
                {'name': 'user_a_type', 'values': ['新用户', '老用户']},
                {'name': 'user_b_platform', 'values': ['Android', 'iOS']},
                {'name': 'user_b_type', 'values': ['新用户', '老用户']},
            ],
            'result_fields': ['user_a_result', 'user_b_result'],
            'rows': combined_rows,
            'derived_rules': [],
            'source_fragments': source_ids,
        }
        fragment_indexes = {item[0] for item in fragments}
        return [item for index, item in enumerate(raw_artifacts) if index not in fragment_indexes] + [decision_table]

    @classmethod
    def _promote_numbered_state_tables(cls, raw_artifacts: List[Any]) -> List[Any]:
        """Promote a numbered state specification table without rewriting its cells."""
        promoted = []
        for artifact in raw_artifacts:
            if not isinstance(artifact, dict) or artifact.get('artifact_type') != 'table':
                promoted.append(artifact)
                continue
            columns = [str(value).strip() for value in (artifact.get('columns') or [])]
            rows = artifact.get('rows') or []
            if len(columns) != 2 or columns[0] not in ('编号', '序号') or not rows:
                promoted.append(artifact)
                continue
            states = []
            rules = []
            for row_index, row in enumerate(rows, 1):
                if not isinstance(row, list) or len(row) != 2:
                    continue
                raw_spec = str(row[1] or '').strip()
                match = re.search(r'标题\s*[：:]\s*([^\n，。,；;]+)', raw_spec)
                if match:
                    states.append({
                        'state': match.group(1).strip(),
                        'raw_spec': raw_spec,
                        'source_row': row_index,
                    })
                else:
                    rules.append({'raw_rule': raw_spec, 'source_row': row_index})
            if len(states) < 2:
                promoted.append(artifact)
                continue
            upgraded = dict(artifact)
            upgraded.update({
                'artifact_type': 'state_matrix',
                'title': artifact.get('title') or '状态矩阵',
                'states': states,
                'rules': rules,
                'transitions': artifact.get('transitions') or [],
                'source_table': {'columns': artifact.get('columns'), 'rows': rows},
            })
            promoted.append(upgraded)
        return promoted

    @staticmethod
    def _state_matrix_from_text(text: str) -> Optional[Dict[str, Any]]:
        """Build a minimal traceable state matrix from repeated literal title specs."""
        content = str(text or '')
        matches = list(re.finditer(r'标题\s*[：:]\s*([^\\"\n，。,；;]+)', content))
        states = []
        seen = set()
        for index, match in enumerate(matches):
            state_name = match.group(1).strip()
            if not state_name or state_name in seen:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else min(len(content), match.end() + 500)
            raw_spec = content[match.start():end].strip(' ,]}')
            seen.add(state_name)
            states.append({'state': state_name, 'raw_spec': raw_spec, 'source': 'literal_text_fallback'})
        if len(states) < 2:
            return None
        return {
            'artifact_type': 'state_matrix',
            'title': '状态矩阵',
            'confidence': 0.6,
            'raw_text': content,
            'states': states,
            'transitions': [],
            'rules': [],
            'source_elements': [],
            'extraction_warning': '由视觉模型原始文字确定性恢复，字段待人工复核',
        }

    @classmethod
    def _prepare_visual_payload(cls, payload: Dict[str, Any], shot_path: str) -> Dict[str, Any]:
        with open(shot_path, 'rb') as image_file:
            digest = hashlib.sha256(image_file.read()).hexdigest()
        artifacts = []
        allowed = {
            'ui', 'ui_screen', 'table', 'data_table', 'decision_table', 'state_matrix',
            'state_machine', 'state_diagram', 'flowchart', 'interaction_flow', 'rule_list',
            'timeline', 'permission_matrix', 'pricing_matrix', 'form_schema', 'list_spec',
            'annotation', 'unknown',
        }
        raw_artifacts = cls._merge_decision_table_fragments(payload.get('visual_artifacts') or [])
        raw_artifacts = cls._promote_numbered_state_tables(raw_artifacts)
        for index, raw in enumerate(raw_artifacts, 1):
            if not isinstance(raw, dict):
                continue
            artifact = dict(raw)
            if artifact.get('artifact_type') not in allowed:
                artifact['artifact_type'] = 'unknown'
            artifact['artifact_id'] = artifact.get('artifact_id') or f'VA-{index:03d}'
            artifact['source_elements'] = artifact.get('source_elements') or []
            artifact['raw_text'] = str(artifact.get('raw_text') or '').strip()
            artifact['visual_evidence'] = {
                'screenshot': os.path.basename(shot_path),
                'image_sha256': digest,
                'bbox': artifact.get('bbox'),
            }
            artifact['validation'] = cls._validate_visual_artifact(artifact)
            artifacts.append(artifact)
        return {
            'ocr_text': str(payload.get('ocr_text') or '').strip(),
            'visual_summary': str(payload.get('visual_summary') or '').strip(),
            'visual_artifacts': artifacts,
        }

    async def _ocr_screenshot(self, vision_config, shot_path: str) -> Dict[str, Any]:
        empty = {'ocr_text': '', 'visual_summary': '', 'visual_artifacts': []}
        try:
            from apps.requirement_analysis.models import AIModelService
            with open(shot_path, 'rb') as image_file:
                b64 = base64.b64encode(image_file.read()).decode('utf-8')
            instruction = (
                '你是产品原型视觉结构提取器，只输出JSON，不得补写截图中不存在的内容。'
                '忽略浏览器工具栏、墨刀页面导航和登录提示。输出：'
                '{"ocr_text":"忠实文字","visual_summary":"可见布局",'
                '"visual_artifacts":[{"artifact_type":"ui_screen|data_table|decision_table|state_matrix|state_machine|flowchart|interaction_flow|rule_list|timeline|permission_matrix|pricing_matrix|form_schema|list_spec|annotation|unknown",'
                '"title":"","bbox":[x1,y1,x2,y2],"confidence":0.0,"raw_text":"","preconditions":{},'
                '"source_elements":[{"element_id":"E-001","text":"逐字文字","bbox":[x1,y1,x2,y2]}],'
                '"columns":[],"rows":[],"states":[],"transitions":[],"nodes":[],"steps":[],"rules":[],'
                '"dimensions":[{"name":"","values":[]}],"result_fields":[],"derived_rules":[]}]}。'
                '普通表格rows为与columns等长的二维数组。决策表rows必须为对象数组，'
                '每个小方框/原始组合对应一行，不得省略；dimensions列出所有输入维度和值域，'
                'result_fields列出结果字段。双用户矩阵使用user_a_platform、user_a_type、'
                'user_b_platform、user_b_type、user_a_result、user_b_result。'
                'derived_rules每条包含condition、result、source_rows（行号从1开始）。'
                '多张卡片展示同一功能的不同状态时必须输出state_matrix；states每项包含state、title、'
                'subtitle、timer_type、timer_source、fixed_text、display_condition、click_action、source_elements，'
                '无法识别的字段留空但必须保留raw_spec。状态之间有箭头或明确切换文字时同时填写transitions，'
                '每项包含from、trigger、to、source_elements。价格/周期/套餐卡片用pricing_matrix；'
                '角色或平台可见可用关系用permission_matrix；多页面或弹窗点击故事用interaction_flow；'
                '时间条件用timeline；表单用form_schema；列表字段规范用list_spec。一个区域可拆成多个互补产物，'
                '无法分类必须输出unknown并保存raw_text，不得静默丢弃。'
                '所有单元格必须逐字来自截图；无法确认关系时降低confidence，禁止猜测。'
            )
            messages = [{'role': 'user', 'content': [
                {'type': 'text', 'text': instruction},
                {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
            ]}]
            result = await AIModelService.call_openai_compatible_api(
                vision_config, messages, max_tokens=8000
            )
            raw = result['choices'][0]['message']['content'].strip()
            payload = self._parse_visual_payload(raw)
            if not payload:
                logger.warning('视觉模型未返回有效JSON，降级为普通OCR文本')
                payload = {'ocr_text': raw, 'visual_artifacts': []}
            artifacts = payload.get('visual_artifacts') or []
            has_decision_table = any(
                isinstance(item, dict) and item.get('artifact_type') == 'decision_table'
                for item in artifacts
            )
            matrix_hint = any(word in raw for word in ('屏蔽', '决策表', '新用户', '老用户'))
            if matrix_hint and not has_decision_table:
                retry_instruction = (
                    '上一次未将截图中由多个小方框组成的双用户屏蔽矩阵输出为decision_table。'
                    '请重新仅输出严格JSON：每个原始小方框是rows中一行，不得用derived_rules代替rows，'
                    '不得遗漏对称或重复布局中的原始组合。artifact_type必须是decision_table；'
                    'rows字段必须为对象数组，每行含user_a_platform、user_a_type、user_b_platform、'
                    'user_b_type、user_a_result、user_b_result。仅识别截图可见内容，禁止推测。'
                )
                retry_messages = [{'role': 'user', 'content': [
                    {'type': 'text', 'text': retry_instruction},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
                ]}]
                retry_result = await AIModelService.call_openai_compatible_api(
                    vision_config, retry_messages, max_tokens=8000
                )
                retry_raw = retry_result['choices'][0]['message']['content'].strip()
                retry_payload = self._parse_visual_payload(retry_raw)
                if any(
                    isinstance(item, dict) and item.get('artifact_type') == 'decision_table'
                    for item in (retry_payload.get('visual_artifacts') or [])
                ):
                    retry_payload.setdefault('ocr_text', payload.get('ocr_text') or raw)
                    payload = retry_payload
            current_artifacts = payload.get('visual_artifacts') or []
            has_state_matrix = any(
                isinstance(item, dict) and item.get('artifact_type') == 'state_matrix'
                for item in current_artifacts
            )
            state_hint = sum(word in raw for word in (
                '断食中', '饮食中', '待开始', '迟到', '状态', '实时活动', '小组件'
            )) >= 2
            if state_hint and not has_state_matrix:
                state_instruction = (
                    '识别截图中同一功能的所有状态卡片，只输出严格JSON且保持简洁。输出格式：'
                    '{"ocr_text":"逐字文字","visual_summary":"布局","visual_artifacts":['
                    '{"artifact_type":"state_matrix","title":"原文标题","bbox":[0,0,0,0],'
                    '"confidence":0.0,"raw_text":"相关原文","source_elements":[],'
                    '"states":[{"state":"状态原名","title":"","subtitle":"",'
                    '"timer_type":"","timer_source":"","fixed_text":"",'
                    '"display_condition":"","click_action":"","raw_spec":"逐字原文",'
                    '"source_elements":[]}],"transitions":[],"rules":[]}]}。'
                    '每种可见状态必须各一项；字段看不清则留空，禁止猜测；不要输出UI坐标细节以免截断。'
                )
                state_messages = [{'role': 'user', 'content': [
                    {'type': 'text', 'text': state_instruction},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
                ]}]
                state_result = await AIModelService.call_openai_compatible_api(
                    vision_config, state_messages, max_tokens=8000
                )
                state_raw = state_result['choices'][0]['message']['content'].strip()
                state_payload = self._parse_visual_payload(state_raw)
                if any(
                    isinstance(item, dict) and item.get('artifact_type') == 'state_matrix'
                    for item in (state_payload.get('visual_artifacts') or [])
                ):
                    state_payload.setdefault('ocr_text', payload.get('ocr_text') or raw)
                    payload = state_payload
            if state_hint and not any(
                isinstance(item, dict) and item.get('artifact_type') == 'state_matrix'
                for item in (payload.get('visual_artifacts') or [])
            ):
                recovered = self._state_matrix_from_text(raw)
                if recovered:
                    payload.setdefault('visual_artifacts', []).append(recovered)
            return self._prepare_visual_payload(payload, shot_path)
        except Exception as exc:
            logger.warning(f'视觉结构提取失败（可忽略）: {exc}')
            return empty

    # ---------- 可选增强策略：双路 DOM + 视觉 交叉融合 ----------
    # 背景：跨多原型验证（canvas 训练页 / 文本层设置页 / 排行榜活动页 / 测试+贴纸+日历页）表明，
    # 墨刀原型「DOM 文本路径」与「视觉截图路径」互补且不可互相替代：DOM 能抽到精确数值/次数/规则，
    # 视觉能理解布局/纯图/全局结构；纯 DOM 在墨刀上偶发 0 字符（异步渲染），需重试兜底。
    # 本策略把两路作为独立输入，分别抽需求后 LLM 交叉融合，标注
    # sources(dom/vision/both) / confidence(high/medium/low) / evidence(A/B/C/D)。
    # 作为可选策略：默认关闭（dual_fusion=False），保持既有行为不变；由调用方（如 modao_workflow）
    # 在采用 analyzer 配置时开启并传入 fusion_config。

    async def dual_fusion_requirements(self, pages, fusion_config):
        """对已被分别记录 dom_text / vision_text 的各页，做双路 LLM 交叉融合。

        pages: extract / extract_webshare_sync 在 dual_fusion=True 时产出的页面列表，
               每项含 'page_name' / 'dom_text' / 'vision_text' / 'dom_text_len'。
        fusion_config: 具备文本能力的 AIModelConfig（如 analyzer）。
        返回融合需求数组（含 sources/confidence/evidence）。失败返回空列表，不抛异常。
        """
        if not fusion_config:
            return []
        from apps.requirement_analysis.models import AIModelService
        dom_all, vis_all = [], []
        dom_total = 0
        for p in pages:
            name = p.get('page_name') or f"第{p.get('page_no', '?')}页"
            dom = (p.get('dom_text') or '').strip()
            vis = (p.get('vision_text') or '').strip()
            if dom:
                dom_all.append(f"### {name}\n{dom}")
                dom_total += len(dom)
            if vis:
                vis_all.append(f"### {name}\n{vis}")
        if not dom_all and not vis_all:
            return []
        dom_reqs = await self._dual_extract_one(
            AIModelService, fusion_config, dom_all) if dom_all else []
        vis_reqs = await self._dual_extract_one(
            AIModelService, fusion_config, vis_all) if vis_all else []
        return await self._dual_fuse(AIModelService, fusion_config, dom_reqs, vis_reqs, dom_total)

    async def _dual_extract_one(self, aim_service, fusion_config, blocks):
        """单路分批抽取；按完整页面分组，禁止整体截断导致尾部页面丢失。"""
        batches = []
        current = []
        current_len = 0
        for block in blocks:
            # 单页异常超长时按字符切片，但每片都保留原页面标题。
            pieces = [block[i:i + 10000] for i in range(0, len(block), 10000)] or ['']
            for piece in pieces:
                if current and current_len + len(piece) > 12000:
                    batches.append(current)
                    current, current_len = [], 0
                current.append(piece)
                current_len += len(piece)
        if current:
            batches.append(current)

        requirements = []
        for batch_no, batch in enumerate(batches, 1):
            messages = [
                {'role': 'system', 'content': DUAL_EXTRACT_PROMPT},
                {'role': 'user', 'content': f'批次 {batch_no}/{len(batches)} 页面内容:\n' + '\n\n'.join(batch)},
            ]
            try:
                result = await aim_service.call_openai_compatible_api(
                    fusion_config, messages, max_tokens=8000)
                parsed = _parse_llm_json_array(result['choices'][0]['message']['content'])
                requirements.extend(parsed)
            except Exception as e:
                raise RuntimeError(f'双路抽取第 {batch_no}/{len(batches)} 批失败: {e}') from e
        return requirements

    async def _dual_fuse(self, aim_service, fusion_config, dom_reqs, vis_reqs, dom_len):
        """交叉融合两路需求数组；任一失败降级为两路并集。"""
        if not dom_reqs and not vis_reqs:
            return []
        user = (
            f"DOM 可见文本长度 = {dom_len} 字符。\n\n"
            f"===== 方式A（DOM 文本）原始结果 =====\n{json.dumps(dom_reqs, ensure_ascii=False)}\n\n"
            f"===== 方式B（视觉截图）原始结果 =====\n{json.dumps(vis_reqs, ensure_ascii=False)}\n"
        )
        messages = [
            {'role': 'system', 'content': DUAL_FUSE_PROMPT},
            {'role': 'user', 'content': user},
        ]
        try:
            result = await aim_service.call_openai_compatible_api(
                fusion_config, messages, max_tokens=8000)
            return _parse_llm_json_array(result['choices'][0]['message']['content']) or []
        except Exception as e:
            raise RuntimeError(f'双路交叉融合失败: {e}') from e


# ---------- 模块级常量与工具（双路融合用） ----------
DUAL_EXTRACT_PROMPT = (
    "你是资深需求分析师。请根据提供的页面内容，提取其中的功能需求点。"
    "输出 JSON 数组，每条包含：source_pages(证据页面名称数组)、module(所属模块)、feature(功能点)、"
    "interaction(关键交互/边界/数值规则)、evidence(证据等级 A/B/C/D)。"
    "只输出 JSON 数组，不要解释。"
)
DUAL_FUSE_PROMPT = (
    "你是资深需求分析架构师。下面是对同一个产品原型，分别用两种方式提取的需求：\n"
    "- 方式A（DOM 文本）：基于页面 DOM 可见文本（含精确数值/次数/规则）\n"
    "- 方式B（视觉截图）：基于页面截图（含布局/纯图/全局结构）\n"
    "请融合两份结果，输出去重后的功能需求数组。每条包含：\n"
    "  source_pages(合并两路证据页面名称数组), module(所属模块), feature(功能点), interaction(关键交互/边界),\n"
    "  evidence(取两种方式中最严格的证据等级 A/B/C/D),\n"
    "  sources(数组，元素取自 'dom' 或 'vision'，表示该需求被哪种方式支持),\n"
    "  confidence('high' 若 dom 与 vision 都支持 / 'medium' 若仅一种且 evidence>=B / 'low' 若仅一种且 evidence 为 C 或 D)\n"
    "只输出 JSON 数组，不要解释。"
)


def _parse_llm_json_array(raw):
    """鲁棒解析 LLM 返回的 JSON 数组；失败返回空列表。"""
    if not raw:
        return []
    s = (raw or '').strip()
    try:
        val = json.loads(s)
        if isinstance(val, list):
            return val
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if m:
        try:
            val = json.loads(m.group(1).strip())
            if isinstance(val, list):
                return val
        except Exception:
            pass
    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1 and j > i:
        try:
            val = json.loads(s[i:j + 1])
            if isinstance(val, list):
                return val
        except Exception:
            pass
    return []
