"""禅道同步与覆盖率分析服务。"""

import asyncio
import hashlib
import html as html_mod
import logging
import math
import os
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from django.db import transaction
from django.utils import timezone

from apps.projects.models import Project
from apps.testcases.models import TestCase
from apps.versions.models import Version

from .models import CoverageItem, CoverageReport, ZentaoBug, ZentaoConfig, ZentaoSyncLog

logger = logging.getLogger(__name__)


class _CoverageCancelled(Exception):
    """内部信号：用户取消覆盖率分析时由 cancel_event 触发，except 块捕获后写 cancelled 状态。"""

# 覆盖率分析参数：高置信自动覆盖 / 低置信自动未覆盖 / 中间模糊区走 LLM
COVER_HIGH_SIM = 0.90
UNCOVER_LOW_SIM = 0.40
JUDGE_BATCH_SIZE = 6
CANDIDATE_TOP_K = 5
RERANK_RECALL_TOP_K = 15
RERANK_FINAL_TOP_K = 5
RERANK_COVER_THRESHOLD = 0.7
SUGGESTION_MAX_BUGS = 30

# LLM 判定/复核的输入预算与温度（均可用环境变量覆盖，默认值为 2026-10-12 report#29 实证调优结果）。
# 背景：此前 LLM 判定只拿到「用例标题 + 预期结果」截断到 240 字，看不到操作步骤，
# 「执行该用例是否会经过 Bug 所在功能」缺乏判定依据，未覆盖结论与假覆盖剔除抖动偏大
# （用例库未变的两轮报告覆盖率 28.8% ↔ 21.9%）。故：
#   1) 用例侧补入前置条件/操作步骤，预算放开到 600 字；
#   2) Bug 侧复现步骤预算由 260 字放开到 600 字；
#   3) 分类任务温度取 0，抑制同一 Bug 跨轮次判定翻转。
JUDGE_CASE_CHARS = int(os.getenv('ZENTAO_COVER_JUDGE_CASE_CHARS', '600') or 600)
JUDGE_BUG_CHARS = int(os.getenv('ZENTAO_COVER_JUDGE_BUG_CHARS', '600') or 600)
JUDGE_TEMPERATURE = float(os.getenv('ZENTAO_COVER_JUDGE_TEMPERATURE', '0') or 0)

_BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
    ),
    'Accept-Language': 'zh-CN,zh;q=0.9',
}


def _md5(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def _strip_html(value: str) -> str:
    """把禅道返回的 HTML 字段（如 steps）转成纯文本。"""
    if not value:
        return ''
    text = re.sub(r'<[^>]+>', '', value)
    text = html_mod.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _looks_garbled(value: str) -> bool:
    if not value:
        return False
    suspicious = sum(
        1 for ch in value
        if ('\u0080' <= ch <= '\u00ff') or ('\u0600' <= ch <= '\u06ff')
    )
    return suspicious > 0 and suspicious / max(len(value), 1) > 0.2


def fix_text(value: str) -> str:
    """尝试修复双重编码导致的乱码（禅道老数据常见）。"""
    if not value or not _looks_garbled(value):
        return value or ''
    candidates: List[str] = []
    for src_enc, dst_enc in (
        ('latin1', 'gbk'),
        ('latin1', 'gb18030'),
        ('cp1256', 'gbk'),
        ('cp1256', 'gb18030'),
        ('latin1', 'utf-8'),
    ):
        try:
            candidates.append(value.encode(src_enc).decode(dst_enc))
        except Exception:
            continue
    for cand in candidates:
        if any('\u4e00' <= ch <= '\u9fff' for ch in cand):
            return cand
    return value


def _parse_zentao_datetime(value):
    if not value or str(value).startswith('0000-00-00'):
        return None
    try:
        dt = datetime.strptime(str(value)[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        try:
            dt = datetime.strptime(str(value)[:10], '%Y-%m-%d')
        except ValueError:
            return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


class ZentaoClient:
    """基于禅道网页会话的轻量客户端（REST /api.php 在本环境未启用，走会话 JSON 接口）。"""

    def __init__(self, base_url: str, account: str, password: str, timeout: int = 30):
        self.base_url = self._normalize_base_url(base_url)
        self.account = account
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self._context_execution_id: Optional[str] = None
        self._login_headers = {
            **_BROWSER_HEADERS,
            'Referer': f'{self.base_url}/',
        }

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """清洗禅道地址：只保留 协议://主机[:端口]，去掉误粘贴的页面路径。"""
        text = (url or '').strip()
        match = re.match(r'(https?://[^/]+)', text)
        if match:
            return match.group(1).rstrip('/')
        return text.rstrip('/')

    # ---------- 登录 ----------
    def login(self, max_attempts: int = 3) -> None:
        """登录禅道；失败时用全新会话重试，避免会话随机串（verifyRand）失配。"""
        last_exc: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                self._login_once()
                return
            except Exception as exc:
                last_exc = exc
                logger.warning('禅道登录失败（第%d次）: %s', attempt + 1, exc)
                if attempt < max_attempts - 1:
                    import time

                    time.sleep(1.0 * (attempt + 1))
                    self.session = requests.Session()  # 全新会话，重置 cookies/rand
        raise RuntimeError(str(last_exc)[:200] if last_exc else '禅道登录失败')

    def _login_once(self) -> None:
        s = self.session
        base = self.base_url
        login_url = f'{base}/index.php?m=user&f=login'
        s.get(login_url, headers=self._login_headers, timeout=self.timeout)
        rnd_resp = s.get(
            f'{base}/index.php?m=user&f=refreshRandom',
            headers=self._login_headers,
            timeout=self.timeout,
        )
        rand = (rnd_resp.text or '').strip()
        if not rand:
            raise RuntimeError('禅道未返回随机串，请检查地址/网络')
        pwd = _md5(_md5(self.password) + rand)
        data = {
            'account': self.account,
            'password': pwd,
            'passwordStrength': '1',
            'referer': '/',
            'verifyRand': rand,
            'keepLogin': '1',
            'captcha': '',
        }
        resp = s.post(
            login_url,
            data=data,
            headers={
                **_BROWSER_HEADERS,
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': base,
                'Referer': login_url,
            },
            timeout=self.timeout,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(f'禅道登录响应异常（可能被验证码/风控拦截）: {resp.text[:200]}') from exc
        if payload.get('result') != 'success':
            raise RuntimeError(f'禅道登录失败: {payload.get("message") or payload}')

    # ---------- 通用请求 ----------
    def _get_json(self, path: str) -> dict:
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self.session.get(
                    f'{self.base_url}{path}',
                    headers=self._login_headers,
                    timeout=self.timeout,
                )
                if resp.status_code != 200 or not resp.text.strip():
                    raise RuntimeError(f'禅道接口请求失败 {resp.status_code}: {path}')
                outer = resp.json()
                return json_loads_outer(outer)
            except Exception as exc:
                last_exc = exc
                logger.warning('禅道接口请求异常(尝试%d): %s', attempt + 1, exc)
                try:
                    self.session = requests.Session()
                    self.login()
                    if self._context_execution_id:
                        # 重登后恢复执行上下文，避免分页请求因会话无上下文而返回空
                        self.session.get(
                            f'{self.base_url}/index.php?m=execution&f=view'
                            f'&executionID={self._context_execution_id}',
                            headers=self._login_headers,
                            timeout=self.timeout,
                        )
                except Exception:
                    pass
        raise RuntimeError(
            f'禅道接口请求失败: {path} | {str(last_exc)[:200]}'
        )

    # ---------- 数据 ----------
    def get_products(self) -> Dict[str, str]:
        data = self._get_json('/index.php?m=product&f=all&t=json')
        return {str(k): str(v) for k, v in (data.get('products') or {}).items()}

    def get_executions(self, product_id: str) -> List[Dict[str, str]]:
        """获取指定产品相关的执行（冲刺）列表。

        来源：① 该产品的测试单（m=testtask）携带 execution/build；② 产品 Bug 最新页
        的执行。名称用执行浏览的 executions 映射补齐。
        """
        execution_ids: set = set()
        builds: Dict[str, str] = {}
        try:
            data = self._get_json(
                f'/index.php?m=testtask&f=browse&productID={product_id}'
                f'&recPerPage=100&t=json'
            )
            for task in (data.get('tasks') or {}).values():
                if isinstance(task, dict) and task.get('execution'):
                    execution_ids.add(str(task['execution']))
                    if task.get('build'):
                        builds[str(task['build'])] = ''
        except Exception as exc:
            logger.warning('获取测试单执行列表失败: %s', exc)

        try:
            data = self._get_json(
                f'/index.php?m=bug&f=browse&productID={product_id}'
                f'&browseType=all&t=json'
            )
            for bug in _as_bug_list(data.get('bugs')):
                if isinstance(bug, dict) and bug.get('execution'):
                    execution_ids.add(str(bug['execution']))
        except Exception as exc:
            logger.warning('获取产品 Bug 页执行失败: %s', exc)

        names: Dict[str, str] = {}
        try:
            data = self._get_json('/index.php?m=execution&f=browse&t=json')
            names = {str(k): str(v) for k, v in (data.get('executions') or {}).items()}
        except Exception as exc:
            logger.warning('获取执行名称映射失败: %s', exc)

        result = []
        for eid in sorted(execution_ids, key=lambda x: int(x) if x.isdigit() else 0):
            if eid == '0':
                continue
            result.append({'id': eid, 'name': names.get(eid, eid)})
        return result

    def get_builds(self, execution_id: str) -> List[Dict[str, str]]:
        """获取执行对应的版本（build）列表（产品级）。"""
        builds: Dict[str, str] = {}
        try:
            data = self._get_json(
                f'/index.php?m=execution&f=bug&executionID={execution_id}'
                f'&type=all&t=json'
            )
            builds = {str(k): str(v) for k, v in (data.get('builds') or {}).items()}
        except Exception as exc:
            logger.warning('获取版本列表失败: %s', exc)
        return [
            {'id': bid, 'name': bname}
            for bid, bname in builds.items()
            if bid and bname and bid != 'trunk'
        ]

    def get_executions_by_product(self, product_id: str) -> List[Dict[str, str]]:
        """获取产品下的执行（用于定位 build 列表来源）。"""
        try:
            data = self._get_json(
                f'/index.php?m=execution&f=browse&productID={product_id}&t=json'
            )
            execs = data.get('executions') or {}
            return [
                {'id': str(k), 'name': str(v)}
                for k, v in execs.items()
                if str(k) != '0' and str(k) != 'product'
            ]
        except Exception as exc:
            logger.warning('获取产品执行列表失败: %s', exc)
            return []

    def get_builds_by_product(self, product_id: str) -> List[Dict[str, str]]:
        """获取产品下全部版本（build）列表。

        禅道 build 列表接口（m=build&f=all）返回非标准 JSON，无法直接解析；
        产品级 bug 浏览接口（m=bug&f=browse&productID=...）通常一次请求即可返回
        完整的 builds 映射，优先使用以显著降低耗时。仅当该接口未返回 builds
        时，才回退到遍历执行（并行）聚合 builds。
        """
        builds: Dict[str, str] = {}

        # 1) 优先一次请求产品级 bug 浏览页，拿到完整 builds
        try:
            data = self._get_json(
                f'/index.php?m=bug&f=browse&productID={product_id}&browseType=all&t=json'
            )
            for bid, bname in (data.get('builds') or {}).items():
                bid = str(bid)
                if bid and bid != 'trunk' and bid not in builds:
                    builds[bid] = str(bname)
        except Exception as exc:
            logger.warning('产品级 builds 获取失败: %s', exc)

        # 2) 若产品级接口没拿到，再并行遍历各执行补全
        if not builds:
            execs = self.get_executions_by_product(product_id)
            exec_ids = [e['id'] for e in execs if e.get('id')]

            def _fetch_exec_builds(eid: str):
                local_builds: Dict[str, str] = {}
                try:
                    data = self._get_json(
                        f'/index.php?m=execution&f=bug&executionID={eid}&type=all&t=json'
                    )
                    for bid, bname in (data.get('builds') or {}).items():
                        bid = str(bid)
                        if bid and bid != 'trunk':
                            local_builds[bid] = str(bname)
                except Exception as exc:
                    logger.warning('获取版本列表失败(exec=%s): %s', eid, exc)
                return local_builds

            # 并行加速，避免 execution 多时效低下
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(8, max(1, len(exec_ids)))) as pool:
                for future in as_completed([pool.submit(_fetch_exec_builds, eid) for eid in exec_ids]):
                    for bid, bname in future.result().items():
                        if bid not in builds:
                            builds[bid] = bname

        return [
            {'id': bid, 'name': bname}
            for bid, bname in sorted(builds.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0, reverse=True)
        ]

    def fetch_bugs(
        self,
        product_id: str,
        execution_id: str = '',
        build_id: str = '',
        opened_build_keyword: str = '',
        on_page: Optional[callable] = None,
    ) -> List[dict]:
        """拉取禅道 Bug。

        优先使用执行维度的精确接口（m=execution&f=bug），一次返回该执行下全部 Bug
        （该版本单页上限约 20 条）；超过单页时回退到“先访问执行页设置会话上下文 +
        产品分页浏览”的兜底方案。

        当配置了 build_id 时，会把 build 参数带入产品级浏览接口，让禅道按版本排序，
        使目标版本的 Bug 集中在前面，便于关键字过滤。
        """
        last_result: List[dict] = []
        for attempt in range(4):
            # 每次尝试都使用全新会话，避免旧 cookie（preProductID/分页状态）污染导致分页返回空
            self.session = requests.Session()
            self._context_execution_id = None
            try:
                self.login()
            except Exception as exc:
                logger.warning('重新登录失败: %s', exc)
                continue
            try:
                result = self._fetch_bugs_once(
                    product_id, execution_id, build_id, opened_build_keyword, on_page
                )
            except Exception as exc:
                logger.warning('拉取 Bug 第 %d 次失败: %s', attempt + 1, exc)
                continue
            if result:
                return result
            last_result = result
        return last_result

    def _fetch_bugs_once(
        self,
        product_id: str,
        execution_id: str = '',
        build_id: str = '',
        opened_build_keyword: str = '',
        on_page: Optional[callable] = None,
    ) -> List[dict]:
        # 方案一：执行维度精确列表
        exec_total = 0
        if execution_id:
            data = self._get_json(
                f'/index.php?m=execution&f=bug&executionID={execution_id}'
                f'&type=all&t=json'
            )
            page_bugs = _as_bug_list(data.get('bugs'))
            exec_total = int((data.get('pager') or {}).get('recTotal') or len(page_bugs))
            if page_bugs and exec_total <= len(page_bugs):
                normalized = [self._normalize_bug(b) for b in page_bugs]
                return self._filter_normalized(normalized, opened_build_keyword)

        # 方案二：产品分页浏览（需先访问执行页设置会话上下文）
        if execution_id:
            try:
                self.session.get(
                    f'{self.base_url}/index.php?m=execution&f=view&executionID={execution_id}',
                    headers=self._login_headers,
                    timeout=self.timeout,
                )
                self._context_execution_id = execution_id
            except Exception as exc:
                logger.warning('设置禅道会话上下文失败: %s', exc)

        # 注意：该禅道版本对参数顺序敏感，executionID 必须在 browseType 之前，
        # 否则产品浏览会返回空列表（recTotal=0）。
        base_path = f'/index.php?m=bug&f=browse&productID={product_id}'
        if execution_id:
            base_path += f'&executionID={execution_id}'
        # build 参数用于让禅道按目标版本排序，使目标版本 Bug 靠前，便于关键字过滤
        if build_id:
            base_path += f'&build={build_id}'
        base_path += '&browseType=all'
        page1 = self._get_json(base_path + '&t=json')
        raw_bugs = _as_bug_list(page1.get('bugs'))
        pager = page1.get('pager') or {}
        rec_total = int(pager.get('recTotal') or len(raw_bugs))
        page_total = max(1, math.ceil(rec_total / 20))

        collected: List[dict] = []
        seen_ids = set()
        empty_pages = 0
        keyword_empty_pages = 0
        kw = str(opened_build_keyword or '').strip()

        def _keyword_matched(bug: dict) -> bool:
            if not kw:
                return True
            title = str(bug.get('title') or '')
            opened_build = str(bug.get('openedBuild') or '')
            return kw in title or kw in fix_text(opened_build)

        def _collect(page_bugs_: List[dict]) -> Tuple[int, int]:
            nonlocal empty_pages, keyword_empty_pages
            added = 0
            kw_added = 0
            for bug in page_bugs_:
                if not isinstance(bug, dict):
                    continue
                bid = str(bug.get('id') or '')
                if not bid or bid in seen_ids:
                    continue
                if execution_id and str(bug.get('execution')) != str(execution_id):
                    continue
                seen_ids.add(bid)
                collected.append(bug)
                added += 1
                if _keyword_matched(bug):
                    kw_added += 1
            empty_pages = 0 if added else empty_pages + 1
            keyword_empty_pages = 0 if kw_added else keyword_empty_pages + 1
            return added, kw_added

        _collect(raw_bugs)
        # 存在关键字过滤时，多翻几页确保目标版本 Bug 不漏；否则按原兜底逻辑早停
        max_empty_pages = 5 if kw else 2
        for page in range(2, page_total + 1):
            path = (
                f'{base_path}&param=0&orderBy=id_desc&recTotal={rec_total}'
                f'&recPerPage=20&pageID={page}&t=json'
            )
            try:
                data = self._get_json(path)
                page_bugs = _as_bug_list(data.get('bugs'))
                if not page_bugs:
                    # 部分版本 param 需与分页值一致，兜底重试
                    path = (
                        f'{base_path}&param=100&orderBy=id_desc&recTotal={rec_total}'
                        f'&recPerPage=20&pageID={page}&t=json'
                    )
                    data = self._get_json(path)
                    page_bugs = _as_bug_list(data.get('bugs'))
            except Exception as exc:
                logger.warning('分页第%d页获取失败，跳过: %s', page, exc)
                page_bugs = []
            added, kw_added = _collect(page_bugs)
            if on_page:
                on_page(page, len(page_bugs), len(collected))
            # 执行维度已知总数时，收集够即可提前停止（当前执行的 Bug 通常是最新的，在前几页）
            if execution_id and exec_total and len(collected) >= exec_total:
                break
            # 设了关键字时，以「连续多页没有命中关键字的 Bug」为停止条件，避免扫完全产品
            if kw and keyword_empty_pages >= max_empty_pages:
                break
            # 无关键字时，连续两页没有该执行的 Bug，说明已收集完
            if not kw and empty_pages >= max_empty_pages:
                break
            # 安全上限，防止异常情况下无限翻页
            if page >= 200:
                logger.warning('Bug 分页达到安全上限 200 页，停止翻页')
                break

        normalized = [self._normalize_bug(b) for b in collected]
        return self._filter_normalized(normalized, opened_build_keyword)

    def fetch_bugs_by_build(
        self,
        product_id: str,
        build_id: str,
        build_name: str = '',
        on_page: Optional[callable] = None,
    ) -> List[dict]:
        """按产品 + 版本(build) 精确拉取 Bug。

        关键事实（实测）：禅道 bug 浏览接口的 ``build`` 参数并不会精确过滤 Bug，
        而是把该产品下全部 Bug（含历史版本）一并返回（recTotal 为产品总量），
        仅靠 build 参数无法只取目标版本。目标版本 Bug 的精确标识在每条 Bug 的
        ``openedBuild`` 字段（如「轻卡日常2.0」）。

        因此本方法：① 拉取该产品全部 Bug（分页）；② 按 ``openedBuild == build_name``
        精确过滤，得到该版本真实的 Bug 集合（如 2.0 共 62 条）。
        build_name 为空时退化为返回全部（不推荐，会污染覆盖率）。
        """
        # 带 build 参数取第一页，拿真实的产品级分页总量（build 参数不改变总量，只影响排序）
        probe = self._get_json(
            f'/index.php?m=bug&f=browse&productID={product_id}'
            f'&build={build_id}&browseType=all&t=json'
        )
        pager = probe.get('pager') or {}
        rec_total = int(pager.get('recTotal') or len(_as_bug_list(probe.get('bugs'))))
        page_total = max(1, math.ceil(rec_total / 20))

        # 全程带 build 参数逐页拉取（保持会话上下文，分页稳定），最后按 openedBuild 精确过滤
        collected: List[dict] = []
        seen_ids = set()
        for page in range(1, page_total + 1):
            if page == 1:
                data = probe
            else:
                path = (
                    f'/index.php?m=bug&f=browse&productID={product_id}'
                    f'&build={build_id}&browseType=all&param=0&orderBy=id_desc'
                    f'&recTotal={rec_total}&recPerPage=20&pageID={page}&t=json'
                )
                try:
                    data = self._get_json(path)
                except Exception as exc:
                    logger.warning('build 分页第%d页失败: %s', page, exc)
                    data = {}
            raw_bugs = _as_bug_list(data.get('bugs'))
            for bug in raw_bugs:
                if not isinstance(bug, dict):
                    continue
                bid = str(bug.get('id') or '')
                if not bid or bid in seen_ids:
                    continue
                seen_ids.add(bid)
                collected.append(bug)
            if on_page:
                on_page(page, len(raw_bugs), len(collected))
            if len(collected) >= rec_total:
                break

        normalized = [self._normalize_bug(b) for b in collected]
        if not build_name:
            return normalized
        # 精确匹配 openedBuild（去空白/HTML 实体），兼容 &amp; 这类转义
        target = fix_text(str(build_name)).strip()
        target = target.replace('&amp;', '&')
        filtered = [
            b for b in normalized
            if fix_text(str(b.get('opened_build') or '')).strip().replace('&amp;', '&') == target
        ]
        logger.info(
            '按版本精确过滤：产品%s 全部%d条，版本「%s」命中%d条',
            product_id, len(normalized), build_name, len(filtered),
        )
        return filtered

    @staticmethod
    def _filter_normalized(normalized: List[dict], opened_build_keyword: str) -> List[dict]:
        """按版本关键字过滤同步的 Bug。

        匹配范围：① openedBuild（发现版本）字段；② Bug 标题（禅道版本号常写在标题里，
        如「轻卡日常v2.2.0」）。两处任一命中即保留。

        注意：关键字非空时必须真正过滤，匹配失败返回空列表（不再退回全量），
        否则会误把其它版本的 Bug 全量拉入，污染覆盖率分析。
        """
        if not opened_build_keyword:
            return normalized
        kw = str(opened_build_keyword).strip()
        if not kw:
            return normalized
        filtered = [
            b for b in normalized
            if kw in (b['opened_build'] or '')
            or kw in fix_text(b['opened_build'] or '')
            or kw in (b['title'] or '')
            or kw in fix_text(b['title'] or '')
        ]
        return filtered

    @staticmethod
    def _normalize_bug(raw: dict) -> dict:
        if isinstance(raw, str):
            # 部分接口 bugs 是 dict{id: bug}，取 dict 值时可能是字符串键
            return {
                'zentao_id': raw,
                'title': '',
                'steps': '',
                'severity': '',
                'pri': '',
                'status': '',
                'bug_type': '',
                'execution': '',
                'product': '',
                'opened_build': '',
                'opened_by': '',
                'opened_date': None,
                'assigned_to': '',
                'resolved_by': '',
                'resolution': '',
                'resolved_date': None,
                'raw_data': {},
            }
        return {
            'zentao_id': str(raw.get('id', '')),
            'title': fix_text(str(raw.get('title') or '')).strip(),
            'steps': _strip_html(raw.get('steps') or ''),
            'severity': str(raw.get('severity') or ''),
            'pri': str(raw.get('pri') or ''),
            'status': str(raw.get('status') or ''),
            'bug_type': str(raw.get('type') or ''),
            'execution': str(raw.get('execution') or ''),
            'product': str(raw.get('product') or ''),
            'opened_build': str(raw.get('openedBuild') or ''),
            'opened_by': str(raw.get('openedBy') or ''),
            'opened_date': _parse_zentao_datetime(raw.get('openedDate')),
            'assigned_to': str(raw.get('assignedTo') or ''),
            'resolved_by': str(raw.get('resolvedBy') or ''),
            'resolution': str(raw.get('resolution') or ''),
            'resolved_date': _parse_zentao_datetime(raw.get('resolvedDate')),
            'raw_data': raw,
        }


def _as_bug_list(value) -> List[dict]:
    """禅道不同接口的 bugs 可能是 list 或 dict{id: bug}。"""
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    return []


def json_loads_outer(outer: dict) -> dict:
    """禅道 t=json 响应是 {'status':'success','data':'{...}'}，data 需要二次解析。"""
    data = outer.get('data')
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        import json

        return json.loads(data)
    return {}


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------
def sync_zentao_bugs(config: ZentaoConfig) -> ZentaoSyncLog:
    """幂等同步：按 (config, zentao_id) upsert，禅道已删除的标记 is_active=False。

    新版优先按 产品(product_id) + 版本(build_id) 精确拉取（无需填写执行/关键字）；
    若未配置 build_id 则回退到旧的 产品+执行+关键字 分页逻辑。
    """
    log = ZentaoSyncLog.objects.create(config=config, status='running')
    try:
        client = ZentaoClient(config.base_url, config.account, config.password)
        client.login()

        if config.product_id and config.build_id:
            raw_bugs = client.fetch_bugs_by_build(
                product_id=config.product_id,
                build_id=config.build_id,
                build_name=config.build_name or '',
            )
        else:
            raw_bugs = client.fetch_bugs(
                product_id=config.product_id or '0',
                execution_id=config.execution_id,
                build_id=config.build_id,
                opened_build_keyword=config.opened_build_keyword,
            )
        seen_ids = set()
        new_count = updated_count = 0
        now = timezone.now()
        with transaction.atomic():
            for item in raw_bugs:
                zid = item['zentao_id']
                if not zid:
                    continue
                seen_ids.add(zid)
                defaults = {k: v for k, v in item.items() if k != 'zentao_id'}
                defaults.update(
                    version=config.version,
                    is_active=True,
                    last_seen_at=now,
                )
                obj, created = ZentaoBug.objects.update_or_create(
                    config=config,
                    zentao_id=zid,
                    defaults=defaults,
                )
                if created:
                    new_count += 1
                else:
                    updated_count += 1

            deactivated_count = 0
            if seen_ids:
                # 只有真实拉到数据才做失效标记：禅道偶发空响应时不能把已有 Bug 误删
                deactivated = ZentaoBug.objects.filter(
                    config=config, is_active=True
                ).exclude(zentao_id__in=seen_ids)
                deactivated_count = deactivated.count()
                deactivated.update(is_active=False, last_seen_at=now)
            else:
                log.detail['skipped_deactivation'] = True
                log.detail['hint'] = '本次拉取为空，已跳过失效标记，避免误删已有 Bug'

        log.status = 'success'
        log.total_count = len(seen_ids)
        log.new_count = new_count
        log.updated_count = updated_count
        log.deactivated_count = deactivated_count
        log.finished_at = timezone.now()
        log.message = (
            f'同步完成：共 {len(seen_ids)} 条，新增 {new_count}，更新 {updated_count}，'
            f'失效 {deactivated_count}'
        )
        log.save(update_fields=[
            'status', 'total_count', 'new_count', 'updated_count',
            'deactivated_count', 'message', 'finished_at',
        ])
        return log
    except Exception as exc:
        logger.exception('禅道同步失败: config=%s', config.id)
        log.status = 'failed'
        log.message = str(exc)[:1000]
        log.finished_at = timezone.now()
        log.save(update_fields=['status', 'message', 'finished_at'])
        return log


# ---------------------------------------------------------------------------
# 覆盖率分析
# ---------------------------------------------------------------------------
def _get_case_pool(config: ZentaoConfig) -> List[TestCase]:
    """取参与比对的用例：优先按版本，其次按项目（均为已入库用例）。"""
    if config.version_id:
        qs = TestCase.objects.filter(versions=config.version).exclude(status='deprecated')
    elif config.project_id:
        qs = TestCase.objects.filter(project=config.project).exclude(status='deprecated')
    else:
        qs = TestCase.objects.none()
    return list(qs.order_by('id'))


def _cosine(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    na = math.sqrt(sum(x * x for x in vec_a))
    nb = math.sqrt(sum(y * y for y in vec_b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _pick_llm_config():
    from apps.requirement_analysis.models import AIModelConfig

    config = (
        AIModelConfig.objects.filter(role='reviewer', is_active=True)
        .exclude(model_type='embedder')
        .first()
    )
    if config:
        return config
    return (
        AIModelConfig.objects.filter(is_active=True)
        .exclude(role='embedder')
        .order_by('-id')
        .first()
    )


def _extract_llm_text(result) -> str:
    """从 OpenAI 兼容响应中提取正文（兼容 reasoning_content）。"""
    if not isinstance(result, dict):
        return ''
    try:
        message = (result.get('choices') or [{}])[0].get('message') or {}
    except Exception:
        message = {}
    text = message.get('content') or ''
    if not text:
        text = message.get('reasoning_content') or ''
    return str(text).strip()


def _extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出中解析 JSON，容忍 markdown 围栏与前后缀文本。"""
    if not text:
        return None
    text = re.sub(r'```(?:json)?', '', text).strip().strip('`').strip()
    import json

    try:
        return json.loads(text)
    except ValueError:
        pass
    # 提取首个 { 到最后一个 } 之间的片段
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            return None
    return None


def _case_text(testcase: TestCase) -> str:
    parts = [
        testcase.title or '',
        testcase.preconditions or '',
        testcase.steps or '',
        testcase.expected_result or '',
    ]
    return '\n'.join(p for p in parts if p).strip()


def _bug_text(bug: ZentaoBug) -> str:
    return '\n'.join(p for p in [bug.title or '', bug.steps or ''] if p).strip()


def _bug_text_compact(bug: ZentaoBug) -> str:
    """LLM 判定用的精简 Bug 文本：标题 + 复现步骤（按 JUDGE_BUG_CHARS 截断）。"""
    text = _bug_text(bug)
    if len(text) > JUDGE_BUG_CHARS:
        text = text[:JUDGE_BUG_CHARS] + '…'
    return text


def _case_text_compact(testcase: TestCase) -> str:
    """LLM 判定用的精简用例文本：标题 + 前置条件 + 操作步骤 + 预期结果（按 JUDGE_CASE_CHARS 截断）。

    2026-10-12 前只给「标题 + 预期结果」240 字，LLM 无法判断用例的操作路径是否
    经过 Bug 所在功能；补入前置条件与操作步骤后，才具备判定「执行即发现」的依据。
    """
    text = _case_text(testcase)
    if len(text) > JUDGE_CASE_CHARS:
        text = text[:JUDGE_CASE_CHARS] + '…'
    return text


def _count_cases_in_content(content: str) -> int:
    """统计生成任务 final_test_cases 中的用例条数（TC001 格式表格）。"""
    if not content:
        return 0
    return len(set(re.findall(r'TC\d{2,4}', content)))


def _bm25_tokenize(text: str) -> List[str]:
    """轻量中文分词：CJK 片段取重叠 2-gram + 英文/数字词，用于 BM25 检索。"""
    tokens: List[str] = []
    for seq in re.findall(r'[\u4e00-\u9fff]+', text or ''):
        if len(seq) >= 2:
            tokens.extend(seq[i:i + 2] for i in range(len(seq) - 1))
    tokens.extend(w.lower() for w in re.findall(r'[A-Za-z0-9]+', text or ''))
    return tokens


class _BM25Index:
    """纯 Python BM25 索引（k1=1.5, b=0.75），用于关键词通道召回。"""

    K1 = 1.5
    B = 0.75

    def __init__(self, docs: List[str]):
        self.doc_terms: List[List[str]] = [_bm25_tokenize(d) for d in docs]
        self.N = len(self.doc_terms)
        self.avgdl = (
            sum(len(t) for t in self.doc_terms) / self.N if self.N else 0.0
        )
        df = {}
        for terms in self.doc_terms:
            for t in set(terms):
                df[t] = df.get(t, 0) + 1
        self.df = df

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1.0)

    def rank(self, query: str, top_k: int = 15, docs: Optional[List[str]] = None):
        """返回 [(doc_index, score)] 按分数降序。"""
        q_terms = _bm25_tokenize(query)
        if not q_terms:
            return []
        scored = []
        for idx, terms in enumerate(self.doc_terms):
            if docs is not None and not docs[idx]:
                continue
            if not terms:
                continue
            dl = len(terms)
            tf = {}
            for t in terms:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for t in set(q_terms):
                if t in tf:
                    score += self._idf(t) * (
                        tf[t] * (self.K1 + 1)
                        / (tf[t] + self.K1 * (1 - self.B + self.B * dl / max(self.avgdl, 1)))
                    )
            if score > 0:
                scored.append((idx, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def _rrf_fuse(
    embed_ranked: List[Tuple[TestCase, float]],
    bm25_ranked: List[Tuple[TestCase, float]],
    cases: List[TestCase],
    top_n: int = RERANK_RECALL_TOP_K,
    k: int = 60,
) -> List[Tuple[TestCase, float]]:
    """RRF 融合：两路排序按 rank 倒数加权合并，附回 embedding 分数用于展示。"""
    fused: dict = {}
    for rank, (case, _) in enumerate(embed_ranked, start=1):
        fused[case.id] = fused.get(case.id, 0.0) + 1.0 / (k + rank)
    for rank, (case, _) in enumerate(bm25_ranked, start=1):
        fused[case.id] = fused.get(case.id, 0.0) + 1.0 / (k + rank)
    case_by_id = {c.id: c for c in cases}
    embed_score = {c.id: s for c, s in embed_ranked}
    order = sorted(fused, key=lambda cid: -fused[cid])[:top_n]
    return [(case_by_id[cid], embed_score.get(cid, 0.0)) for cid in order]


def _build_candidates(
    bug: ZentaoBug,
    cases: List[TestCase],
    bug_vec: Optional[List[float]],
    case_vecs: Optional[List[List[float]]],
    top_k: int = CANDIDATE_TOP_K,
    dedupe_threshold: float = 0.95,
) -> List[Tuple[TestCase, float]]:
    scored: List[Tuple[TestCase, float]] = []
    if bug_vec and case_vecs and len(case_vecs) == len(cases):
        scored = [
            (case, _cosine(bug_vec, vec))
            for case, vec in zip(cases, case_vecs)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # 无 embedding 时按关键词重合粗排
    bug_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+', _bug_text(bug)))
    scored = []
    for case in cases:
        words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+', _case_text(case)))
        if bug_words and words:
            score = len(bug_words & words) / max(len(bug_words | words), 1)
        else:
            score = 0.0
        scored.append((case, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    # 候选去重：与已选候选高度雷同（向量余弦 ≥ 阈值）的跳过，保证送审候选有区分度，
    # 避免雷同用例挤占候选位导致真正合适的那条进不来。
    selected: List[Tuple[TestCase, float]] = []
    selected_vecs: List[List[float]] = []
    for case, score in scored:
        if len(selected) >= top_k:
            break
        if case_vecs and len(case_vecs) == len(cases):
            vec = case_vecs[cases.index(case)]
            if any(_cosine(vec, sv) >= dedupe_threshold for sv in selected_vecs):
                continue
            selected_vecs.append(vec)
        selected.append((case, score))
    return selected


def _get_active_reranker():
    from apps.requirement_analysis.models import AIModelConfig

    return (
        AIModelConfig.objects.filter(role='reranker', is_active=True)
        .order_by('-id')
        .first()
    )


def _rerank_candidates(model_config, bug: ZentaoBug, candidates, top_n: int = RERANK_FINAL_TOP_K):
    """Reranker 精排：对候选重排序，返回 [(用例, embedding分数, rerank分数)] Top-N。

    兼容 OpenAI 风格的 /rerank 接口（如 SiliconFlow bge-reranker）；失败时返回 None，
    由调用方降级为 embedding 排序结果。
    """
    if not candidates:
        return None
    try:
        import requests as _requests

        base_url = (model_config.base_url or '').rstrip('/')
        if base_url.endswith('/rerank'):
            url = base_url
        elif base_url.endswith('/v1'):
            url = f'{base_url}/rerank'
        else:
            url = f'{base_url}/v1/rerank'
        documents = [_case_text(c) for c, _ in candidates]
        payload = {
            'model': model_config.model_name,
            'query': _bug_text_compact(bug),
            'documents': documents,
            'top_n': min(top_n, len(documents)),
        }
        resp = _requests.post(
            url,
            headers={'Authorization': f'Bearer {model_config.api_key}'},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get('results') or []
        if not results:
            return None
        ranked = []
        for item in sorted(results, key=lambda x: x.get('relevance_score', 0), reverse=True):
            idx = item.get('index')
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                case, embed_score = candidates[idx]
                ranked.append((case, embed_score, float(item.get('relevance_score', 0.0))))
            if len(ranked) >= top_n:
                break
        return ranked or None
    except Exception as exc:
        logger.warning('Reranker 精排失败（model=%s），降级 embedding 排序: %s',
                       getattr(model_config, 'model_name', '-'), exc)
        return None


def _keyword_recall(bug, selected, cases, bug_vec=None, case_vecs=None, max_extra=2):
    """关键词兜底召回：候选里没有与 Bug 共享专属词（3字中文片段）的用例时，
    强制补入最多 max_extra 条，解决“正确用例排在候选外”的漏召回。
    额外增强：抽取 Bug 与用例的「功能动作词」（点击/提交/保存/登录等），
    只要有动作词重叠就补入，覆盖「按钮点了没反应」这类字面相似度低但功能对应的漏召回。"""
    bug_text = _bug_text(bug)
    grams = set()
    for i in range(len(bug_text) - 2):
        gram = bug_text[i:i + 3]
        if re.match(r'^[\u4e00-\u9fff]+$', gram):
            grams.add(gram)
    # 功能动作词：字面相似度低但代表同一操作，是功能失效类 Bug 的核心锚点
    action_words = set(re.findall(r'[\u4e00-\u9fff]{2,4}', bug_text)) & _ACTION_VERBS
    if not grams and not action_words:
        return selected
    selected_ids = {c.id for c, _ in selected}
    extra = []
    for idx, case in enumerate(cases):
        if case.id in selected_ids:
            continue
        text = _case_text(case)
        shared = sum(1 for g in grams if g in text)
        if not shared and action_words:
            case_actions = set(re.findall(r'[\u4e00-\u9fff]{2,4}', text)) & _ACTION_VERBS
            shared = sum(1 for a in action_words if a in case_actions)
        if shared:
            score = 0.0
            if bug_vec and case_vecs and len(case_vecs) == len(cases):
                score = _cosine(bug_vec, case_vecs[idx])
            extra.append((case, score, shared))
    extra.sort(key=lambda x: (-x[2], -x[1]))
    for case, score, _ in extra[:max_extra]:
        selected.append((case, score))
    return selected


# 功能失效类 Bug 的特征词：字面相似度天然低（如「按钮没反应」vs「点击登录」），
# 但其表现（无响应/不生效/报错）说明只要执行对应功能操作用例即可发现。
# 命中这些词时不应被低相似度直接枪毙为 auto_uncover，应强制走 LLM 判定。
# 第二类（calculation/text/state）：计算错误、文案错误、状态流转错误——同样字面
# 相似度低但只要有对应功能步骤用例即可发现，也归为「可覆盖失效类」，不硬枪毙。
FAILURE_KEYWORDS = (
    # 原功能失效类（响应/报错/保存/跳转）
    '没反应', '无响应', '未响应', '不响应', '点了没', '无反应', '没生效', '不生效',
    '未生效', '失效', '报错', '异常', '崩溃', '闪退', '卡死', '未保存', '没保存',
    '保存失败', '提交失败', '无反应', '不动', '空白', '不显示', '未显示', '没显示',
    '不更新', '未更新', '没更新', '打不开', '无法', '不能', '未跳转', '没跳转',
    # 计算类：金额/数量/总数/比例/取值算错
    '算错', '计算错误', '金额错误', '金额不对', '数额', '总数不对', '总数错误',
    '合计错误', '统计错误', '数量不对', '数量错误', '比例不对', '取值错误', '显示值错误',
    # 文案类：提示语/文案/标签/默认值写错
    '文案', '提示语', '提示文案', '文字错误', '错别字', '标签错误', '默认值错误',
    '默认选中', '占位符', '单位错误', '格式错误',
    # 状态流转类：状态/流程/流转不对
    '状态不对', '状态错误', '状态未', '流程错误', '流转错误', '审批后', '状态没变',
    '状态不更新', '状态不正确', '未流转',
)

# 功能动作词表：用于动作词召回，覆盖「同功能不同表述」的漏召回
_ACTION_VERBS = {
    '点击', '单击', '双击', '长按', '拖拽', '拖动', '滑动', '滚动', '输入', '填写',
    '选择', '选中', '勾选', '提交', '保存', '登录', '退出', '注销', '注册', '查询',
    '搜索', '刷新', '加载', '上传', '下载', '删除', '编辑', '新增', '添加', '修改',
    '确认', '取消', '返回', '跳转', '切换', '筛选', '排序', '导出', '导入', '发送',
    '重置', '清空', '关闭', '打开', '查看', '预览', '支付', '下单', '审批', '审核',
}


def _bug_is_failure_type(bug: ZentaoBug) -> bool:
    """判断 Bug 是否为功能失效类（字面相似度低但执行对应用例可发现）。"""
    text = (_bug_text(bug) or '').lower()
    return any(kw in text for kw in FAILURE_KEYWORDS)


# 功能锚点词表：Bug 若与候选用例共享这些动作/功能词，说明用例库存在对应功能的步骤
# 用例，执行即可发现该 Bug，不应被低相似度硬枪毙。与 _ACTION_VERBS 互补，额外覆盖
# 计算/校验/状态类操作词（这些词的字面相似度同样低但功能对应明确）。
_FUNCTION_ANCHOR_VERBS = {
    '点击', '单击', '双击', '长按', '拖拽', '拖动', '滑动', '滚动', '输入', '填写',
    '选择', '选中', '勾选', '提交', '保存', '登录', '退出', '注销', '注册', '查询',
    '搜索', '刷新', '加载', '上传', '下载', '删除', '编辑', '新增', '添加', '修改',
    '确认', '取消', '返回', '跳转', '切换', '筛选', '排序', '导出', '导入', '发送',
    '重置', '清空', '关闭', '打开', '查看', '预览', '支付', '下单', '审批', '审核',
    '计算', '统计', '合计', '校验', '验证', '流转', '生成', '同步',
}


def _bug_has_function_anchor(bug: ZentaoBug, candidates) -> bool:
    """判断 Bug 是否与候选存在功能锚点（动作/功能词重叠）。

    仅在候选里挑出与 Bug 共享功能词的那条用例，避免「Bug 写了很多动作词但候选是无关
    用例」造成误判。只要有任一条候选与 Bug 共享功能锚点词，即视为存在对应功能步骤用例。
    """
    if not candidates:
        return False
    bug_text = _bug_text(bug) or ''
    bug_verbs = set(re.findall(r'[\u4e00-\u9fff]{2,4}', bug_text)) & _FUNCTION_ANCHOR_VERBS
    if not bug_verbs:
        return False
    for case, _ in candidates:
        case_verbs = set(re.findall(r'[\u4e00-\u9fff]{2,4}', _case_text(case))) & _FUNCTION_ANCHOR_VERBS
        if bug_verbs & case_verbs:
            return True
    return False


def _llm_judge(model_config, bug: ZentaoBug, candidates: List[Tuple[TestCase, float]]) -> dict:
    from apps.requirement_analysis.models import AIModelService

    candidate_lines = []
    for idx, (case, score) in enumerate(candidates, start=1):
        candidate_lines.append(
            f'{idx}. 用例ID={case.id}｜{_case_text_compact(case)}\n'
            f'   语义相似度：{round(score, 4)}'
        )
    bug_desc = _bug_text_compact(bug)
    messages = [
        {
            'role': 'system',
            'content': (
                '你是资深测试专家。请判断候选测试用例能否覆盖（发现）给定的Bug。\n'
                '覆盖标准（务必遵循）：\n'
                '1. 覆盖 ≠ 用例明确写出该Bug。只要执行候选用例的操作路径会经过 Bug 所在功能，'
                '且 Bug 的表现（如点击无响应、提交后无反应、页面报错、数据未保存、状态未更新）'
                '会导致用例预期结果不符，就算「能发现」→ covered=true，并给出 matched_case_id。\n'
                '2. 功能失效类 Bug（按钮无响应/提交无反应/页面报错/数据未落库/状态不刷新）'
                '尤其适用第1条：只要有对应该功能的操作步骤用例，就应判 covered=true。'
                '不要因「用例没写验证按钮有响应」而误判为未覆盖。\n'
                '3. 仅在以下情况判 covered=false：候选完全没有对应该功能的操作步骤；'
                '或该 Bug 属于性能/兼容性/偶发崩溃等非功能用例能稳定复现的问题。\n'
                '请选出最合适的一条候选；若存在歧义或只能部分覆盖，请降低 confidence。'
                '只输出JSON，格式：'
                '{"covered": true/false, "matched_case_id": 用例ID或null, '
                '"confidence": 0到1的小数, "reason": "一句话理由"}'
            ),
        },
        {
            'role': 'user',
            'content': f'Bug：\n{bug_desc}\n\n候选用例：\n' + '\n'.join(candidate_lines),
        },
    ]
    try:
        result = asyncio.run(AIModelService.call_openai_compatible_api(model_config, messages))
        judge = _extract_json(_extract_llm_text(result)) or {}
        if judge.get('confidence') is not None:
            try:
                judge['confidence'] = float(judge.get('confidence'))
            except (TypeError, ValueError):
                judge['confidence'] = None
        return judge
    except Exception as exc:
        logger.warning(
            'LLM 判定失败 bug=%s model=%s: %s',
            bug.zentao_id, model_config.model_name, exc,
        )
        return {}


def _extract_json_array(text: str) -> list:
    """从 LLM 输出中解析 JSON 数组，容忍围栏与前后缀。"""
    if not text:
        return []
    text = re.sub(r'```(?:json)?', '', text).strip().strip('`').strip()
    import json

    start = text.find('[')
    end = text.rfind(']')
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, list) else []
        except ValueError:
            return []
    return []


def _llm_judge_batch(model_config, items: List[Tuple[ZentaoBug, List[Tuple[TestCase, float]]]]) -> dict:
    """批量判定：多个 Bug 一次 LLM 调用，返回 {bug_id: judgment}。"""
    from apps.requirement_analysis.models import AIModelService

    blocks = []
    for idx, (bug, candidates) in enumerate(items):
        cand_lines = [
            f'{ci}. 用例ID={case.id}｜{_case_text_compact(case)}（相似度{round(score, 3)}）'
            for ci, (case, score) in enumerate(candidates, start=1)
        ]
        blocks.append(
            f'[{idx}] Bug#{bug.zentao_id}：{_bug_text_compact(bug)}\n候选：\n' + '\n'.join(cand_lines)
        )
    messages = [
        {
            'role': 'system',
            'content': (
                '你是资深测试专家。请逐条判断：执行候选测试用例能否覆盖（发现）该Bug。\n'
                '覆盖标准（务必遵循）：\n'
                '1. 覆盖 ≠ 用例明确写出该Bug。只要执行候选用例的操作路径会经过 Bug 所在功能，'
                '且 Bug 表现（如点击无响应、提交后无反应、页面报错、数据未保存）会导致用例预期不符，'
                '就算「能发现」→ covered=true。\n'
                '2. 功能失效类 Bug（按钮无响应/提交无反应/页面报错/数据未落库）'
                '只要有对应该功能的操作步骤用例，就应判 covered=true，'
                '不要因「用例没写验证按钮有响应」而误判为未覆盖。\n'
                '3. 仅当候选完全没有对应功能的操作步骤，或 Bug 属性能/兼容/偶发崩溃等非稳定复现问题时，'
                '才判 covered=false。\n'
                '请选出最合适的一条候选；若候选间存在歧义或只能部分覆盖，请降低 confidence。'
                '只输出JSON数组，每个元素对应一个Bug，格式：'
                '[{"bug_index": 序号, "covered": true/false, "matched_case_id": 用例ID或null, '
                '"confidence": 0到1的小数, "reason": "一句话理由"}, ...]。'
                '必须与输入序号一一对应，只输出JSON数组。'
            ),
        },
        {'role': 'user', 'content': '\n\n'.join(blocks)},
    ]
    result = asyncio.run(
        AIModelService.call_openai_compatible_api(model_config, messages, temperature=JUDGE_TEMPERATURE)
    )
    arr = _extract_json_array(_extract_llm_text(result))
    out = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        bidx = item.get('bug_index')
        if isinstance(bidx, int) and 0 <= bidx < len(items):
            bug = items[bidx][0]
            out[bug.zentao_id] = {
                'covered': bool(item.get('covered')),
                'matched_case_id': item.get('matched_case_id'),
                'reason': item.get('reason') or '',
                'confidence': item.get('confidence'),
            }
            if out[bug.zentao_id]['confidence'] is not None:
                try:
                    out[bug.zentao_id]['confidence'] = float(
                        out[bug.zentao_id]['confidence']
                    )
                except (TypeError, ValueError):
                    out[bug.zentao_id]['confidence'] = None
    return out


def _llm_precision_check(model_config, items) -> dict:
    """假断言复核：校验“已覆盖”的匹配用例，其断言是否真的能发现该 Bug。"""
    from apps.requirement_analysis.models import AIModelService

    if not items:
        return {}
    blocks = []
    for idx, item in enumerate(items):
        bug = item.bug
        case = item.matched_testcase
        case_desc = _case_text_compact(case) if case else '无匹配用例'
        blocks.append(
            f'[{idx}] Bug#{bug.zentao_id}：{_bug_text_compact(bug)}\n'
            f'匹配用例：{case_desc}'
        )
    messages = [
        {
            'role': 'system',
            'content': (
                '你是资深测试专家。请严格判断“匹配用例”的断言/预期结果是否真的能发现该Bug。\n'
                '判定为 precise=false（应剔除为假覆盖）的情形，包括但不限于：\n'
                '1. 用例预期写得笼统（如“显示正常”“功能正常”“操作成功”“结果正确”），'
                '没有可验证的具体断言，执行该用例也无法区分 Bug 是否存在；\n'
                '2. 用例验证路径与 Bug 场景无关（如 Bug 是边界值算错，用例只验证了正常输入）；\n'
                '3. 用例虽文字相似，但实际覆盖了不同字段/不同功能点，无法触发该 Bug；\n'
                '4. Bug 属于性能/兼容性/偶发崩溃等非功能用例能稳定复现的问题（本就不该算覆盖）。\n'
                '只有用例断言明确指向 Bug 所在的具体行为/数据/状态，且执行后预期不符能暴露该 Bug，'
                '才判 precise=true。宁可从严（判 false），不要放宽。'
                '只输出JSON数组，与输入序号一一对应：'
                '[{"bug_index": 序号, "precise": true/false, "reason": "一句话"}, ...]'
            ),
        },
        {'role': 'user', 'content': '\n\n'.join(blocks)},
    ]
    result = asyncio.run(
        AIModelService.call_openai_compatible_api(model_config, messages, temperature=JUDGE_TEMPERATURE)
    )
    arr = _extract_json_array(_extract_llm_text(result))
    out = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        bidx = item.get('bug_index')
        if isinstance(bidx, int) and 0 <= bidx < len(items):
            out[items[bidx].bug.zentao_id] = {
                'precise': bool(item.get('precise')),
                'reason': item.get('reason') or '',
            }
    return out


def _llm_suggestions(model_config, uncovered_bugs: List[ZentaoBug]) -> str:
    from apps.requirement_analysis.models import AIModelService

    if not uncovered_bugs:
        return ''
    # 分批处理：避免一次把大量未覆盖 Bug 塞进单次 LLM 调用导致上下文过大、长时间挂起
    SUGGESTION_BATCH = 15
    SUGGESTION_TIMEOUT = 120.0  # 建议生成是"锦上添花"的非关键调用，超时即跳过，不阻塞主流程
    parts: List[str] = []
    batch_bugs = uncovered_bugs[:SUGGESTION_MAX_BUGS]
    total = len(batch_bugs)
    for start in range(0, total, SUGGESTION_BATCH):
        chunk = batch_bugs[start:start + SUGGESTION_BATCH]
        end = start + len(chunk)
        logger.info(
            '覆盖率分析生成建议批次: report 进度 %d-%d/%d',
            start + 1, end, total,
        )
        lines = [
            f'{i}. [{bug.zentao_id}] {_bug_text_compact(bug)}'
            for i, bug in enumerate(chunk, start=1)
        ]
        messages = [
            {
                'role': 'system',
                'content': (
                    '你是测试策略专家。以下是在当前版本AI测试用例集中未被覆盖的禅道Bug。'
                    '请给出可落地的补漏建议：哪些测试场景/用例需要补充（按功能点归类），'
                    '以及如何把这些经验沉淀到知识库。请用中文分点输出，简洁实用。'
                ),
            },
            {'role': 'user', 'content': '未覆盖Bug列表：\n' + '\n'.join(lines)},
        ]
        try:
            # asyncio.wait_for 作为最外层硬超时护栏：无论 httpx 内部是否真实触发
            # read 超时，wait_for 都会在 SUGGESTION_TIMEOUT 秒后取消任务并抛 TimeoutError，
            # 由 except Exception 捕获，避免单次 LLM 调用无限挂起导致整个分析线程卡死。
            result = asyncio.run(
                asyncio.wait_for(
                    AIModelService.call_openai_compatible_api(
                        model_config, messages, timeout=SUGGESTION_TIMEOUT
                    ),
                    timeout=SUGGESTION_TIMEOUT,
                )
            )
            text = _extract_llm_text(result)
            if text:
                parts.append(text)
            logger.info(
                '覆盖率分析生成建议批次完成: %d-%d/%d',
                start + 1, end, total,
            )
        except Exception as exc:
            logger.warning(
                '生成覆盖建议批次 %d-%d 失败/超时（model=%s）: %s',
                start + 1, end, model_config.model_name, exc,
            )
    return '\n'.join(parts)


# 可沉淀为"强制覆盖场景"的异常场景类型枚举
ABNORMAL_SCENE_TYPES = ['边界值', '并发', '网络中断', '权限不足', '状态回显', '数据校验', '其他']


def _llm_abnormal_scene_summary(model_config, uncovered_bugs: List[ZentaoBug]) -> List[dict]:
    """把未覆盖缺陷归类到异常场景类型并统计高频场景，供生成用例时注入。

    只统计可转化为覆盖场景的缺陷（归因=用例覆盖缺失/AI需求误解），
    排除纯代码缺陷（产品本身 bug，无需用例覆盖），避免把该修的 bug 也塞进生成。
    返回 [{'type': str, 'count': int, 'examples': [str]}]，按 count 降序。

    分批调用 LLM：一次塞太多 Bug 会导致单次调用长时间挂起，分批 + 短超时可保证
    即使某批失败也只损失该批统计，不阻塞整个覆盖率分析。
    """
    from apps.requirement_analysis.models import AIModelService

    if not uncovered_bugs:
        return []
    SCENE_BATCH = 20
    SCENE_TIMEOUT = 120.0
    scene_type_enum = ' / '.join(ABNORMAL_SCENE_TYPES)
    system_prompt = (
        '你是资深测试专家。请分析每条未覆盖缺陷，输出三个判断：\n'
        '1. cause（缺陷归因，仅两类）：\n'
        '   - "case_design_gap"：用例设计遗漏/覆盖缺失，AI 没生成该场景；\n'
        '   - "ai_misunderstanding"：AI 对需求理解有误导致用例方向错误。\n'
        '   注意：功能失效类缺陷（按钮无响应/提交无反应/页面报错/数据未保存）'
        '只要有对应该功能的操作步骤用例即可发现，一律归为 case_design_gap，不要归其它类。\n'
        '2. scene_type（异常场景类型）：\n'
        f'   从以下类型中选择最贴切的一个：{scene_type_enum}\n'
        '3. relevant：未覆盖缺陷均可沉淀为"应覆盖场景"，统一为 true。\n'
        '只输出JSON数组，与输入序号一一对应，格式：\n'
        '[{"bug_index": 序号, "cause": "...", "scene_type": "...", '
        '"relevant": true/false}, ...]'
    )
    stats: Dict[str, dict] = {}
    for start in range(0, len(uncovered_bugs), SCENE_BATCH):
        chunk = uncovered_bugs[start:start + SCENE_BATCH]
        blocks = [
            f'[{idx}] Bug#{bug.zentao_id}：{_bug_text_compact(bug)}'
            for idx, bug in enumerate(chunk)
        ]
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': '\n'.join(blocks)},
        ]
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    AIModelService.call_openai_compatible_api(
                        model_config, messages, temperature=0, timeout=SCENE_TIMEOUT
                    ),
                    timeout=SCENE_TIMEOUT,
                )
            )
        except Exception as exc:
            logger.warning('异常场景统计批次 %d-%d 失败/超时（model=%s）: %s', start + 1, start + len(chunk), model_config.model_name, exc)
            continue
        arr = _extract_json_array(_extract_llm_text(result))
        for item in arr:
            if not isinstance(item, dict):
                continue
            # cause 仅接受两类；模型若返回旧 code_defect 等类别则跳过（不再单列纯代码缺陷）
            if str(item.get('cause') or '').strip() not in CAUSE_TYPES:
                continue
            st = str(item.get('scene_type') or '').strip()
            if not st or st not in ABNORMAL_SCENE_TYPES:
                continue
            example = ''
            bidx = item.get('bug_index')
            if isinstance(bidx, int) and 0 <= bidx < len(chunk):
                example = chunk[bidx].title
            bucket = stats.setdefault(st, {'count': 0, 'examples': []})
            bucket['count'] += 1
            if example and len(bucket['examples']) < 2:
                bucket['examples'].append(example)
    return sorted(
        [
            {'type': k, 'count': v['count'], 'examples': v['examples']}
            for k, v in stats.items()
        ],
        key=lambda x: -x['count'],
    )


# 有效真实 Bug 的判定：禅道 status∈{resolved,closed} 且 resolution=='fixed'。
# resolved 也排除非 fixed 的 resolution（如 willnotfix/notrepro/bydesign 等），
# 避免把「不予解决/设计如此」类关闭的 Bug 误算成 AI 用例能发现的真实缺陷。
VALID_BUG_RESOLUTIONS = {'fixed'}


def is_valid_bug(bug) -> bool:
    """判定禅道 Bug 是否为「有效真实 Bug」：开发真正修复并闭环的缺陷。"""
    return (
        bug.status in ('resolved', 'closed')
        and (bug.resolution or '') in VALID_BUG_RESOLUTIONS
    )


# 缺陷归因只分两类，不再设 "code_defect"：
# 经验证，像「按钮点了没反应」「提交无响应」这类功能失效类 Bug，只要用例库里有
# 对应该功能的操作步骤用例，跑用例就会发现（预期不符），本就属于生成/匹配可覆盖项。
# 把这类强行归为 code_defect 会稀释覆盖率、掩盖召回与判定问题。因此未覆盖的有效
# Bug 一律视为「生成该背的锅」，只区分是思路方向错还是场景遗漏。
CAUSE_TYPES = ('ai_misunderstanding', 'case_design_gap')


def _llm_cause_breakdown(model_config, bugs: List[ZentaoBug]) -> dict:
    """对给定 Bug 列表做缺陷归因，返回各 cause 的计数分布。

    用于「低覆盖诊断」：判断有效真实 Bug 中未覆盖的部分，是 AI 思路方向错
    （ai_misunderstanding）还是场景遗漏（case_design_gap）。
    不再设 code_defect 维度——功能失效类 Bug（按钮无响应/提交无反应等）只要有对应
    操作步骤用例即可发现，本就属于生成可优化范围，故一律计入可优化项。
    返回 {'ai_misunderstanding': N, 'case_design_gap': N, 'unknown': N, 'total': M}。
    LLM 失败/无输入时返回全 0。
    """
    from apps.requirement_analysis.models import AIModelService

    if not bugs:
        return {
            'ai_misunderstanding': 0,
            'case_design_gap': 0,
            'unknown': 0,
            'total': 0,
        }
    SCENE_BATCH = 20
    SCENE_TIMEOUT = 120.0
    system_prompt = (
        '你是资深测试专家。请分析每条缺陷，判断其 cause（缺陷归因），只可能是以下两类：\n'
        '   - "case_design_gap"：用例设计遗漏/覆盖缺失，AI 没生成该功能场景的用例；\n'
        '   - "ai_misunderstanding"：AI 对需求理解有误导致用例方向错误。\n'
        '注意：功能失效类缺陷（如按钮点了没反应、提交后无响应、页面报错、数据未保存）'
        '只要有对应该功能的操作步骤用例，执行用例就会触发/发现它，'
        '这类一律归为 case_design_gap（场景遗漏），不要归为其它类别。\n'
        '只输出JSON数组，与输入序号一一对应，格式：\n'
        '[{"bug_index": 序号, "cause": "..."}, ...]'
    )
    counts = {'ai_misunderstanding': 0, 'case_design_gap': 0, 'unknown': 0}
    for start in range(0, len(bugs), SCENE_BATCH):
        chunk = bugs[start:start + SCENE_BATCH]
        blocks = [
            f'[{idx}] Bug#{bug.zentao_id}：{_bug_text_compact(bug)}'
            for idx, bug in enumerate(chunk)
        ]
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': '\n'.join(blocks)},
        ]
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    AIModelService.call_openai_compatible_api(
                        model_config, messages, temperature=0, timeout=SCENE_TIMEOUT
                    ),
                    timeout=SCENE_TIMEOUT,
                )
            )
        except Exception as exc:
            logger.warning('缺陷归因批次 %d-%d 失败/超时（model=%s）: %s',
                           start + 1, start + len(chunk), model_config.model_name, exc)
            counts['unknown'] += len(chunk)
            continue
        arr = _extract_json_array(_extract_llm_text(result))
        for item in arr:
            if not isinstance(item, dict):
                counts['unknown'] += 1
                continue
            cause = str(item.get('cause') or '').strip()
            if cause not in CAUSE_TYPES:
                # 模型可能仍返回 code_defect 等旧类别，统一视为 unknown 不计入可优化
                counts['unknown'] += 1
                continue
            counts[cause] = counts.get(cause, 0) + 1
    counts['total'] = sum(v for k, v in counts.items() if k != 'total')
    return counts


def _build_coverage_diagnosis(
    missed_valid: List[ZentaoBug],
    cause_breakdown: dict,
    effective_coverage: float,
    coverage_target: float,
    abnormal_scenes: List[dict],
) -> dict:
    """基于有效真实 Bug 的未覆盖归因，生成结构化低覆盖诊断结论。

    结论区分两类可优化项（未覆盖有效 Bug 一律视为生成可优化，不再用 code_defect 稀释）：
      - ai_misunderstanding 占比高 → 思路有问题（生成方向偏）
      - case_design_gap 占比高     → 场景遗漏（方向对但没生成具体场景）
    unknown 为 LLM 归因失败/超时项，单独提示人工复核，不计入可优化判定。
    """
    total = cause_breakdown.get('total', 0) or 0
    ai_mis = cause_breakdown.get('ai_misunderstanding', 0)
    gap = cause_breakdown.get('case_design_gap', 0)
    unknown = cause_breakdown.get('unknown', 0)
    # 可优化项：所有已成功归因的未覆盖有效 Bug（ai_mis + gap）。
    # 不再排除 code_defect——功能失效类 Bug 有对应用例即可发现，属于生成可优化范围。
    optimizable = ai_mis + gap
    optimizable = max(optimizable, 0)

    below_target = effective_coverage < coverage_target
    # level: ok（达标）/ low（低于目标但可优化项占比不高）/ high（明显思路/遗漏问题）
    if not below_target:
        level = 'ok'
        conclusion = (
            f'有效真实 Bug 覆盖率 {effective_coverage:.1f}% 已达目标'
            f'（{coverage_target:.0f}%），AI 生成用例对有效缺陷的发现能力达标。'
        )
    else:
        if optimizable == 0:
            level = 'low'
            conclusion = (
                f'有效真实 Bug 覆盖率 {effective_coverage:.1f}% 低于目标'
                f'（{coverage_target:.0f}%），未覆盖项均无法归因（unknown {unknown} 项），'
                f'建议人工复核样本以确认是召回/判定问题还是真实遗漏。'
            )
        else:
            # 思路 vs 遗漏 占比
            if ai_mis >= gap and ai_mis > 0:
                direction = (
                    '「思考思路有问题」为主：AI 对需求/功能的理解方向存在偏差，'
                    '建议补充需求结构化输入与知识库注入，校准生成方向。'
                )
            elif gap > ai_mis and gap > 0:
                direction = (
                    '「场景遗漏」为主：生成方向基本正确，但具体异常/边界场景缺失，'
                    '建议补充异常场景、边界值与高频缺失场景的用例生成。'
                )
            else:
                direction = '未覆盖项归因不明确，建议人工复核样本。'
            level = 'high'
            conclusion = (
                f'有效真实 Bug 覆盖率 {effective_coverage:.1f}% 低于目标'
                f'（{coverage_target:.0f}%）。诊断显示未覆盖有效 Bug 中，'
                f'思路方向问题 {ai_mis} 项、场景遗漏 {gap} 项（另有无法归因 {unknown} 项）。'
                f'{direction}'
            )

    # 高频缺失场景 top3（来自现有 abnormal_scenes 聚合，作为证据）
    top_scenes = [
        {'scene_type': s.get('type'), 'count': s.get('count'), 'examples': s.get('examples', [])[:2]}
        for s in (abnormal_scenes or [])[:3]
    ]
    return {
        'level': level,
        'conclusion': conclusion,
        'below_target': below_target,
        'effective_coverage': effective_coverage,
        'coverage_target': coverage_target,
        'cause_breakdown': {
            'ai_misunderstanding': ai_mis,
            'case_design_gap': gap,
            'unknown': unknown,
            'total': total,
        },
        'optimizable_count': optimizable,
        'top_missing_scenes': top_scenes,
    }


def _llm_distill_knowledge_points(
    model_config, uncovered_bugs: List[ZentaoBug], version_name: str = ''
) -> List[dict]:
    """把未覆盖缺陷精炼归并成少量「覆盖缺失重点」，供写入知识库。

    与旧逻辑「每条 Bug 写一条」不同：这里用 LLM 把语义相近的缺失点合并成 N 条，
    所有未覆盖有效 Bug 均视为可沉淀的「缺失场景」（功能失效类如按钮无响应只要有对应用例
    即可发现，也属于生成可优化范围，不再单列 code_defect 剔除）。
    返回 [{'title': str, 'content': str, 'scope': 'version|global|legacy'}]。
    """
    from apps.requirement_analysis.models import AIModelService

    if not uncovered_bugs:
        return []
    blocks = [
        f'[{idx}] Bug#{bug.zentao_id}：{_bug_text_compact(bug)}'
        for idx, bug in enumerate(uncovered_bugs)
    ]
    messages = [
        {
            'role': 'system',
            'content': (
                '你是资深测试专家。现有某版本的未覆盖缺陷清单，请把它们**精炼归并**成少量'
                '「覆盖缺失重点」，供后续 AI 生成测试用例时注入提示词参考。要求：\n'
                '1. 所有未覆盖缺陷都是「该补的缺失场景」，不要剔除任何类别'
                '（包括功能失效类如按钮无响应/提交无反应——只要有对应操作步骤用例即可发现，'
                '属于场景遗漏，需沉淀）。\n'
                '2. 把语义相近/同属一个缺失点的缺陷**合并为一条**，避免重复。整体输出控制在 '
                '3~8 条精炼条目，宁少勿滥。\n'
                '3. 每条用「缺失场景 + 触发条件 + 建议覆盖的校验点」一句话说清，让 AI 知道下次该补什么，'
                '不要照抄 Bug 复现步骤。\n'
                '只输出 JSON 数组，格式：\n'
                '[{"title": "精炼标题(<=30字)", "content": "缺失场景描述(<=120字，含为什么没覆盖、'
                '建议覆盖的断言方向)", "scope": "version|global|legacy"}, ...]\n'
                'scope 含义：version=仅本版本新功能缺失；global=全局长期有效（平台差异/设计规范/通用交互）；'
                'legacy=老功能优化可跨版本参考。'
            ),
        },
        {'role': 'user', 'content': '\n'.join(blocks)},
    ]
    try:
        result = asyncio.run(
            AIModelService.call_openai_compatible_api(model_config, messages, temperature=0)
        )
    except Exception as exc:
        logger.warning('知识库覆盖重点精炼失败（model=%s）: %s', model_config.model_name, exc)
        return []
    arr = _extract_json_array(_extract_llm_text(result))
    points: List[dict] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        content = str(item.get('content') or '').strip()
        if not title or not content:
            continue
        scope = str(item.get('scope') or 'version')
        if scope not in ('version', 'global', 'legacy'):
            scope = 'version'
        # 归并内容里带上版本标识，便于溯源
        if version_name and f'{version_name}' not in content:
            content = f'（版本：{version_name}）{content}'
        points.append({'title': title, 'content': content, 'scope': scope})
    return points


def _llm_distill_misunderstanding_points(
    model_config, missed_valid_bugs: List[ZentaoBug],
    diagnosis: dict, version_name: str = '',
) -> List[dict]:
    """把「思路方向偏（ai_misunderstanding）」的未覆盖有效 Bug 蒸馏成「生成思路校准」知识。

    与 _llm_distill_knowledge_points（补缺失场景）互补：这里是针对「AI 对需求/功能的理解
    方向存在偏差」的 Bug，提炼成给未来生成用例的**方向性提示**（如「涉及金额计算的需求，
    应优先覆盖边界值与精度」，而非「缺了某条具体场景」），反向注入知识库，让模型下次
    生成同类需求时校准思路。

    返回 [{'title': str, 'content': str, 'scope': 'version|global|legacy'}]，空列表表示无需写。
    """
    from apps.requirement_analysis.models import AIModelService

    ai_mis = (diagnosis.get('cause_breakdown') or {}).get('ai_misunderstanding', 0) or 0
    if ai_mis <= 0 or not missed_valid_bugs:
        return []
    blocks = [
        f'[{idx}] Bug#{bug.zentao_id}：{_bug_text_compact(bug)}'
        for idx, bug in enumerate(missed_valid_bugs)
    ]
    conclusion = diagnosis.get('conclusion') or ''
    messages = [
        {
            'role': 'system',
            'content': (
                '你是资深测试专家。以下 Bug 经诊断属于「AI 对需求/功能的理解方向存在偏差」'
                '（ai_misunderstanding）：即 AI 生成用例的思路偏了，不是单纯漏了某条场景。\n'
                '请提炼成少量（2~5 条）**生成思路校准**知识，供后续 AI 生成同类需求用例时'
                '注入提示词、校准方向。要求：\n'
                '1. 聚焦「方向性教训」：例如「涉及金额/计算的需求，应优先覆盖边界值与精度校验」'
                '「涉及状态流转的需求，应覆盖异常流转与回滚」——是给生成模型的通用性方向提示，'
                '不是某条具体 Bug 的复现步骤。\n'
                '2. 每条一句话说清：适用场景 + 该往哪个方向校准 + 建议补充的验证维度。\n'
                '3. 整体 2~5 条，宁少勿滥。\n'
                '只输出 JSON 数组，格式：\n'
                '[{"title": "精炼标题(<=30字)", "content": "方向校准描述(<=120字，含适用场景与校准方向)", '
                '"scope": "version|global|legacy"}, ...]\n'
                'scope 含义：version=仅本版本需求；global=跨版本通用的生成方向（如通用交互/计算规范）；'
                'legacy=老功能可参考。'
            ),
        },
        {
            'role': 'user',
            'content': (
                f'诊断结论：{conclusion}\n\n思路偏差类未覆盖 Bug：\n' + '\n'.join(blocks)
            ),
        },
    ]
    try:
        result = asyncio.run(
            AIModelService.call_openai_compatible_api(model_config, messages, temperature=0)
        )
    except Exception as exc:
        logger.warning('生成思路校准蒸馏失败（model=%s）: %s', model_config.model_name, exc)
        return []
    arr = _extract_json_array(_extract_llm_text(result))
    points: List[dict] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        content = str(item.get('content') or '').strip()
        if not title or not content:
            continue
        scope = str(item.get('scope') or 'global')
        if scope not in ('version', 'global', 'legacy'):
            scope = 'global'
        if version_name and f'{version_name}' not in content:
            content = f'（版本：{version_name}）{content}'
        points.append({'title': title, 'content': content, 'scope': scope})
    return points


def _compute_learning_feedback(
    config: ZentaoConfig,
    current_report_id: int,
    valid_total: int,
    covered_valid: int,
    missed_valid: int,
    effective_coverage: float,
) -> dict:
    """B. 自学成效回测：与同一 config 上一轮成功报告对比，量化知识库沉淀后的改善。

    纯读历史报告（零额外 LLM 成本），对比有效覆盖率 / 已覆盖 / 未覆盖的变化，
    作为「闭环自学是否真的让下次生成更好」的可见指标，写进 report.detail。
    返回 {'has_previous': bool, 'prev_report_id', 'prev_effective_coverage_rate',
          'coverage_delta', 'covered_valid_delta', 'missed_valid_delta',
          'trend': 'improved'|'regressed'|'flat'|'first'}。
    """
    try:
        prev = (
            CoverageReport.objects
            .filter(config=config, status='success')
            .exclude(id=current_report_id)
            .order_by('-id')
            .first()
        )
        # 排除自身（本报告的 id 在调用时通常已写入，但用 finished_at 顺序兜底）
        if prev is None:
            return {'has_previous': False, 'trend': 'first'}
        prev_detail = prev.detail or {}
        prev_eff = prev_detail.get('effective_coverage_rate')
        prev_covered = prev_detail.get('covered_valid')
        prev_missed = prev_detail.get('missed_valid')
        if prev_eff is None:
            return {
                'has_previous': True,
                'prev_report_id': prev.id,
                'trend': 'first',
            }
        cov_delta = round(effective_coverage - float(prev_eff), 2)
        cv_delta = (covered_valid - int(prev_covered)) if prev_covered is not None else None
        mv_delta = (missed_valid - int(prev_missed)) if prev_missed is not None else None
        if cov_delta > 0.01:
            trend = 'improved'
        elif cov_delta < -0.01:
            trend = 'regressed'
        else:
            trend = 'flat'
        return {
            'has_previous': True,
            'prev_report_id': prev.id,
            'prev_effective_coverage_rate': prev_eff,
            'prev_covered_valid': prev_covered,
            'prev_missed_valid': prev_missed,
            'coverage_delta': cov_delta,
            'covered_valid_delta': cv_delta,
            'missed_valid_delta': mv_delta,
            'trend': trend,
        }
    except Exception as exc:
        logger.warning('自学成效回测计算失败: %s', exc)
        return {'has_previous': False, 'trend': 'first', 'error': str(exc)[:200]}


def _auto_push_kb(report: CoverageReport, user=None) -> None:
    """A. 自动沉淀：报告成功后自动把覆盖缺口 + 思路校准写入知识库（闭环自学）。

    默认开启（环境变量 ZENTAO_AUTO_KB 不为 '0' 即开启），失败仅告警不阻断主流程。
    直接复用 push_report_to_knowledge，保证与手动点击行为完全一致。
    """
    import os

    if os.environ.get('ZENTAO_AUTO_KB', '1') == '0':
        logger.info('自动沉淀知识库已通过 ZENTAO_AUTO_KB=0 关闭: report=%s', report.id)
        return
    try:
        logger.info('覆盖率报告自动沉淀知识库开始: report=%s', report.id)
        result = push_report_to_knowledge(report, user=user)
        logger.info('覆盖率报告自动沉淀知识库完成: report=%s %s', report.id, result.get('message', ''))
    except Exception as exc:
        logger.warning('覆盖率报告自动沉淀知识库失败（不影响主报告）: report=%s %s', report.id, exc)


def run_coverage_analysis(config: ZentaoConfig, user=None, report: Optional[CoverageReport] = None, build_name: Optional[str] = None, cancel_event: Optional[threading.Event] = None) -> CoverageReport:
    """对配置对应版本的 AI 用例与禅道 Bug 做覆盖率分析。

    build_name 为用户在界面选中的禅道 Build 显示名（如「轻卡日常2.0」）。
    禅道按 build 拉 Bug 的接口并不精确过滤，因此这里统一在应用层按
    ZentaoBug.opened_build 做精确等值匹配，避免把全产品历史 Bug 都算进来。

    cancel_event（threading.Event）用于"协作式取消"：用户删除报告时由 DELETE 接口
    set()，本函数在每个阶段/批次入口检查 is_set()，若取消则抛 CancelledError，
    由外层 except 标记 report.status='cancelled' 后退出。
    """
    if cancel_event is None:
        cancel_event = threading.Event()

    def _check_cancel():
        """协作式取消检查点。"""
        if cancel_event.is_set():
            from django.db import close_old_connections as _close
            _close()
            raise _CoverageCancelled(f'报告 {report.id} 已被用户取消')

    # 子线程可能复用主线程的数据库连接，先关闭旧连接确保 ORM 在新线程中正常工作
    from django.db import close_old_connections

    close_old_connections()

    # 优先用显式传入的 build_name，否则回退到 config 上保存的 build_name
    build_name = (build_name or config.build_name or '').strip()
    # 禅道 opened_build 字段里 & 被存成了 HTML 实体 &amp;，统一归一化后再匹配
    def _norm_build(value: str) -> str:
        return (value or '').replace('&amp;', '&').replace('&AMP;', '&').strip()

    if report is None:
        report = CoverageReport.objects.create(
            config=config,
            version=config.version,
            status='running',
            created_by=user,
        )
    _check_cancel()
    logger.info('覆盖率分析开始: report=%s config=%s build_name=%r', report.id, config.id, build_name)
    try:
        bug_qs = ZentaoBug.objects.filter(config=config, is_active=True)
        if build_name:
            # 应用层精确过滤：opened_build 可能含 &amp; 实体，做归一化比较
            target = _norm_build(build_name)
            matched_ids = [
                b.id for b in bug_qs
                if _norm_build(b.opened_build) == target
            ]
            bugs = list(ZentaoBug.objects.filter(id__in=matched_ids).order_by('id'))
            logger.info(
                '覆盖率分析按 build 精确过滤: report=%s build_name=%r 命中 %d/%d 条 Bug',
                report.id, build_name, len(bugs), bug_qs.count(),
            )
            if not bugs:
                report.status = 'failed'
                report.error_message = (
                    f'按版本「{build_name}」未匹配到任何 Bug（openedBuild 精确匹配为空）。'
                    '请确认同步 Bug 时已选中该版本，或重新点击「同步Bug」。'
                )
                report.finished_at = timezone.now()
                report.save(update_fields=['status', 'error_message', 'finished_at'])
                return report
        else:
            bugs = list(bug_qs.order_by('id'))
            logger.warning(
                '覆盖率分析未指定 build_name，将分析 config 下全部 %d 条 Bug（口径可能偏大）',
                len(bugs),
            )
        # 界面优化类 Bug（bug_type=interfaceoptimize）不参与覆盖率计算，单独计数写入报告展示
        ui_bugs = [b for b in bugs if (b.bug_type or '').strip().lower() == 'interfaceoptimize']
        if ui_bugs:
            ui_ids = {b.id for b in ui_bugs}
            bugs = [b for b in bugs if b.id not in ui_ids]
            logger.info(
                '覆盖率分析排除界面优化Bug: report=%s excluded=%d remaining=%d',
                report.id, len(ui_bugs), len(bugs),
            )

        cases = _get_case_pool(config)
        logger.info('覆盖率分析数据准备: report=%s bugs=%d cases=%d', report.id, len(bugs), len(cases))
        if not bugs:
            report.status = 'failed'
            if ui_bugs:
                report.error_message = (
                    f'该版本共 {len(ui_bugs)} 条 Bug，全部为界面优化类（不计入覆盖率），无参与计算的 Bug。'
                )
            else:
                report.error_message = '未找到已同步的禅道 Bug，请先点击“同步Bug”完成同步后再分析'
            report.finished_at = timezone.now()
            report.save(update_fields=['status', 'error_message', 'finished_at'])
            return report
        if not cases:
            raise RuntimeError('该版本下没有可比的测试用例，请先确认用例已入库（用例库）')

        model_config = _pick_llm_config()
        if not model_config:
            raise RuntimeError('未配置可用的 AI 模型（writer/reviewer），无法进行判定')
        logger.info('覆盖率分析模型: report=%s model=%s', report.id, model_config.model_name)

        from apps.requirement_analysis.models import AIModelConfig, AIModelService

        embedder = AIModelConfig.get_active_embedder()
        reranker = _get_active_reranker()
        bug_vecs = None
        case_vecs = None
        matched_by = 'llm'
        if embedder:
            logger.info('覆盖率分析开始 embedding: report=%s', report.id)
            bug_vecs = AIModelService.embed_texts_sync([_bug_text(b) for b in bugs], embedder)
            case_vecs = AIModelService.embed_texts_sync([_case_text(c) for c in cases], embedder)
            logger.info('覆盖率分析 embedding 完成: report=%s', report.id)
            if bug_vecs and case_vecs:
                matched_by = (
                    'embedding+bm25+rrf+rerank+llm' if reranker else 'embedding+bm25+rrf+llm'
                )
        bm25_index = _BM25Index([_case_text(c) for c in cases])

        report.case_count = len(cases)
        report.matched_by = matched_by
        report.total_bugs = len(bugs)
        report.save(update_fields=['case_count', 'matched_by', 'total_bugs'])
        logger.info('覆盖率分析进入判定阶段: report=%s bugs=%d cases=%d matched_by=%s', report.id, len(bugs), len(cases), matched_by)

        # 来源统计：AI 生成 / 人工编写 / 未标记（用于采纳率、真实覆盖率）
        ai_case_count = sum(1 for c in cases if c.source == 'ai')
        manual_case_count = sum(1 for c in cases if c.source == 'manual')
        unknown_case_count = len(cases) - ai_case_count - manual_case_count
        true_coverage_rate = round(ai_case_count / len(cases) * 100, 2) if cases else 0.0

        # 采纳率（版本口径）：库内 AI 用例数 / 该版本 AI 生成任务产出的用例总数
        adoption_rate = None
        if config.version_id:
            from apps.requirement_analysis.models import TestCaseGenerationTask

            generated_total = 0
            for task in TestCaseGenerationTask.objects.filter(
                version_id=config.version_id, status='completed'
            ):
                generated_total += _count_cases_in_content(task.final_test_cases)
            if generated_total:
                adoption_rate = round(ai_case_count / generated_total * 100, 2)

        # 需求使用率：用例覆盖的功能模块 / 该版本全部功能模块
        requirement_usage_rate = None
        try:
            from apps.feature_modules.models import FeatureModule

            modules_qs = FeatureModule.objects.filter(project_id=config.project_id)
            if config.version_id:
                modules_qs = modules_qs.filter(versions__id=config.version_id)
            total_modules = modules_qs.distinct().count()
            covered_modules = set()
            for case in cases:
                covered_modules.update(case.feature_modules.values_list('id', flat=True))
            if total_modules:
                requirement_usage_rate = round(len(covered_modules) / total_modules * 100, 2)
        except Exception as exc:
            logger.warning('需求使用率计算失败: %s', exc)

        # 第一轮：召回候选 + 置信度分级
        pending: List[Tuple[ZentaoBug, List[Tuple[TestCase, float]], Optional[str], Optional[float]]] = []
        fuzzy_items: List[Tuple[ZentaoBug, List[Tuple[TestCase, float]]]] = []
        for idx, bug in enumerate(bugs, start=1):
            if idx % 10 == 0 or idx == len(bugs):
                _check_cancel()
            embed_top = _build_candidates(
                bug, cases,
                bug_vecs[idx - 1] if bug_vecs else None,
                case_vecs,
                top_k=RERANK_RECALL_TOP_K,
            )
            bm25_hits = bm25_index.rank(_bug_text(bug), top_k=RERANK_RECALL_TOP_K)
            bm25_ranked = [(cases[i], s) for i, s in bm25_hits]
            candidates = _rrf_fuse(
                embed_top, bm25_ranked, cases, top_n=RERANK_RECALL_TOP_K
            )
            rerank_used = False
            rerank_top_score = None
            if reranker:
                reranked = _rerank_candidates(reranker, bug, candidates)
                if reranked:
                    rerank_used = True
                    candidates = [(c, s) for c, s, _ in reranked]
                    rerank_top_score = reranked[0][2] if reranked else None
                else:
                    candidates = candidates[:CANDIDATE_TOP_K]
            else:
                candidates = candidates[:CANDIDATE_TOP_K]
            # 关键词兜底召回：候选里没有与Bug共享专属词的用例时，补入最多2条
            candidates = _keyword_recall(
                bug, candidates, cases,
                bug_vecs[idx - 1] if bug_vecs else None,
                case_vecs,
            )
            top_score = candidates[0][1] if candidates else 0.0
            # 功能失效类 Bug（按钮无响应/提交失败等）字面相似度天然低，不应被低相似度
            # 直接枪毙为 auto_uncover——其对应功能的操作步骤用例即可发现它。强制走
            # LLM 判定（fuzzy），由 _llm_judge 依据「执行对应用例即可发现」判定 covered。
            is_failure = _bug_is_failure_type(bug)
            # 功能锚点：Bug 文本与候选用例共享动作词/功能词（点击/提交/保存/计算/状态等），
            # 说明用例库存在对应该功能的步骤用例，该类 Bug 执行用例即可发现，不应被低
            # 相似度硬枪毙，须转 fuzzy 走 LLM 判定。
            has_anchor = _bug_has_function_anchor(bug, candidates)
            # 功能失效类 / 功能锚点类 Bug 字面相似度天然低，只要用例库有对应功能步骤用例
            # 即可发现。因此两个硬枪毙分支（rerank 低分 / 低相似度）都必须豁免，强制走
            # LLM 判定（fuzzy），由 _llm_judge 依据「执行对应用例即可发现」判定 covered。
            if (
                candidates and rerank_used
                and rerank_top_score is not None
                and rerank_top_score < RERANK_COVER_THRESHOLD
                and not is_failure and not has_anchor
            ):
                tier = 'auto_uncover_rerank'
            elif candidates and top_score >= COVER_HIGH_SIM:
                tier = 'auto_cover'
            elif top_score <= UNCOVER_LOW_SIM and not is_failure and not has_anchor:
                tier = 'auto_uncover'
            else:
                tier = 'fuzzy'
                fuzzy_items.append((bug, candidates))
            pending.append((bug, candidates, tier, rerank_top_score))

        # 第二轮：模糊区间批量走 v4-pro（按批，减少调用次数）
        judgments: dict = {}
        if fuzzy_items:
            logger.info('覆盖率分析 LLM 批量判定开始: report=%s fuzzy=%d batch=%d', report.id, len(fuzzy_items), JUDGE_BATCH_SIZE)
            for start in range(0, len(fuzzy_items), JUDGE_BATCH_SIZE):
                _check_cancel()  # 协作式取消：每批 LLM 调用前检查
                batch = fuzzy_items[start:start + JUDGE_BATCH_SIZE]
                try:
                    logger.info('覆盖率分析 LLM 批量判定中: report=%s batch=%d-%d', report.id, start + 1, min(start + JUDGE_BATCH_SIZE, len(fuzzy_items)))
                    judgments.update(_llm_judge_batch(model_config, batch))
                except _CoverageCancelled:
                    raise  # 取消信号必须向外传递，不能被 except 吞掉
                except Exception as exc:
                    logger.warning(
                        '批量判定失败（model=%s），回退单条: %s',
                        model_config.model_name, exc,
                    )
                    for bug, cands in batch:
                        if cancel_event.is_set():
                            raise _CoverageCancelled(f'报告 {report.id} 已被用户取消')
                        try:
                            single = _llm_judge(model_config, bug, cands)
                            if single:
                                judgments[bug.zentao_id] = single
                        except _CoverageCancelled:
                            raise
                        except Exception as single_exc:
                            logger.warning(
                                '单条判定失败 bug=%s model=%s: %s',
                                bug.zentao_id, model_config.model_name, single_exc,
                            )

        # 第三轮：落库
        covered_count = 0
        uncovered_bugs: List[ZentaoBug] = []
        with transaction.atomic():
            for bug, candidates, tier, rerank_top_score in pending:
                judge: dict = {}
                if tier == 'auto_cover':
                    case = candidates[0][0]
                    judge = {
                        'covered': True,
                        'matched_case_id': case.id,
                        'reason': f'语义相似度 {round(candidates[0][1], 3)} ≥ {COVER_HIGH_SIM}，自动判定覆盖',
                    }
                elif tier == 'auto_uncover':
                    judge = {
                        'covered': False,
                        'reason': f'最高候选相似度仅 {round(candidates[0][1], 3)}（≤ {UNCOVER_LOW_SIM}），自动判定未覆盖',
                    }
                elif tier == 'auto_uncover_rerank':
                    judge = {
                        'covered': False,
                        'reason': (
                            f'精排最高分 {round(rerank_top_score or 0, 3)} < '
                            f'{RERANK_COVER_THRESHOLD}，自动判定未覆盖（未调用LLM）'
                        ),
                    }
                else:
                    judge = judgments.get(bug.zentao_id) or {}
                    if not judge:
                        judge = {
                            'covered': False,
                            'reason': f'LLM 判定失败（{model_config.model_name}），按未覆盖处理',
                        }

                covered = bool(judge.get('covered'))
                matched_id = judge.get('matched_case_id')
                matched_case = None
                if matched_id:
                    try:
                        matched_case = TestCase.objects.get(id=int(matched_id))
                    except (ValueError, TestCase.DoesNotExist):
                        matched_case = None
                matched_score = None
                if matched_case:
                    matched_score = next(
                        (s for c, s in candidates if c.id == matched_case.id),
                        None,
                    )
                if covered:
                    covered_count += 1
                else:
                    uncovered_bugs.append(bug)
                CoverageItem.objects.create(
                    report=report,
                    bug=bug,
                    covered=covered,
                    matched_testcase=matched_case,
                    matched_case_title=matched_case.title if matched_case else '',
                    match_score=candidates[0][1] if candidates else None,
                    matched_score=matched_score,
                    judge_confidence=judge.get('confidence') if tier == 'fuzzy' else 1.0,
                    candidates=[
                        {
                            'case_id': c.id,
                            'title': c.title,
                            'score': round(s, 4),
                        }
                        for c, s in candidates[:5]
                    ],
                    reason=judge.get('reason') or '',
                )

        # 假断言复核：剔除“断言无法发现Bug”的假覆盖，让覆盖率更接近真实
        fake_covered = 0
        covered_items = list(
            CoverageItem.objects.filter(report=report, covered=True).select_related(
                'bug', 'matched_testcase'
            )
        )
        if covered_items and model_config:
            _check_cancel()  # 协作式取消：进入 LLM 复核前检查
            logger.info('覆盖率分析假覆盖复核开始: report=%s covered=%d', report.id, len(covered_items))
            try:
                precision = _llm_precision_check(model_config, covered_items)
            except _CoverageCancelled:
                raise
            except Exception as exc:
                logger.warning(
                    '假断言复核失败（model=%s）: %s', model_config.model_name, exc
                )
                precision = {}
            for item in covered_items:
                res = precision.get(item.bug.zentao_id)
                if res and res.get('precise') is False:
                    item.covered = False
                    item.reason = f'假覆盖剔除：{res.get("reason") or "断言无法发现该Bug"}'
                    item.save(update_fields=['covered', 'reason'])
                    fake_covered += 1
                    covered_count -= 1
                    uncovered_bugs.append(item.bug)
            logger.info('覆盖率分析假覆盖复核完成: report=%s fake=%d', report.id, fake_covered)

        _check_cancel()  # 协作式取消：进入生成建议前检查
        logger.info('覆盖率分析生成建议: report=%s uncovered=%d', report.id, len(uncovered_bugs))
        suggestions = _llm_suggestions(model_config, uncovered_bugs)

        # 异常场景类型统计：把未覆盖缺陷归类到场景类型，取高频 top-N 供后续生成用例注入
        abnormal_scenes: List[dict] = []
        if uncovered_bugs:
            _check_cancel()  # 协作式取消：进入异常场景 LLM 总结前检查
            logger.info('覆盖率分析异常场景总结开始: report=%s uncovered=%d', report.id, len(uncovered_bugs))
            try:
                abnormal_scenes = _llm_abnormal_scene_summary(model_config, uncovered_bugs)
            except _CoverageCancelled:
                raise
            except Exception as exc:
                logger.warning('异常场景统计失败: %s', exc)

        # 有效真实 Bug 池分析：仅统计 status∈{resolved,closed} 且 resolution=='fixed' 的 Bug
        # （开发真正修复并闭环的缺陷），据此反推 AI 用例能发现的有效真实 Bug 数，
        # 并对未覆盖的有效 Bug 做归因诊断（思路方向错 vs 场景遗漏）。
        valid_bugs = [b for b in bugs if is_valid_bug(b)]
        valid_total = len(valid_bugs)
        covered_valid = 0
        missed_valid_bugs: List[ZentaoBug] = []
        for b in valid_bugs:
            item = CoverageItem.objects.filter(report=report, bug=b).first()
            if item and item.covered:
                covered_valid += 1
            else:
                missed_valid_bugs.append(b)
        missed_valid = len(missed_valid_bugs)
        effective_coverage = round(covered_valid / valid_total * 100,  # noqa: E501
                                   2) if valid_total else 0.0

        # 低覆盖诊断：对未覆盖的有效 Bug 做 cause 归因
        diagnosis = {
            'level': 'ok',
            'conclusion': (
                f'有效真实 Bug 覆盖率 {effective_coverage:.1f}%，'
                f'有效 Bug 池为空或已全部覆盖，AI 用例发现能力达标。'
            ),
            'below_target': effective_coverage < config.coverage_target,
            'effective_coverage': effective_coverage,
            'coverage_target': config.coverage_target,
            'cause_breakdown': {
                'ai_misunderstanding': 0,
                'case_design_gap': 0,
                'unknown': 0,
                'total': 0,
            },
            'optimizable_count': 0,
            'top_missing_scenes': [],
        }
        if missed_valid_bugs and model_config:
            _check_cancel()
            logger.info('覆盖率分析有效Bug归因诊断开始: report=%s missed_valid=%d',
                        report.id, missed_valid)
            try:
                cause_breakdown = _llm_cause_breakdown(model_config, missed_valid_bugs)
                diagnosis = _build_coverage_diagnosis(
                    missed_valid_bugs, cause_breakdown, effective_coverage,
                    config.coverage_target, abnormal_scenes,
                )
            except _CoverageCancelled:
                raise
            except Exception as exc:
                logger.warning('有效Bug归因诊断失败（model=%s）: %s',
                               model_config.model_name, exc)

        low_confidence_count = CoverageItem.objects.filter(
            report=report, judge_confidence__lt=0.7
        ).count()
        report.total_bugs = len(bugs)
        report.covered_bugs = covered_count
        report.uncovered_bugs = len(uncovered_bugs)
        report.coverage_rate = round(covered_count / len(bugs) * 100, 2)
        logger.info('覆盖率分析成功: report=%s covered=%d/%d', report.id, covered_count, len(bugs))
        report.status = 'success'
        report.finished_at = timezone.now()
        report.detail = {
            'improvement_suggestions': suggestions,
            'uncovered_bug_ids': [b.zentao_id for b in uncovered_bugs],
            'auto_judged': sum(
                1 for _, _, t, _ in pending
                if t in ('auto_cover', 'auto_uncover', 'auto_uncover_rerank')
            ),
            'llm_judged': len(fuzzy_items),
            'ai_case_count': ai_case_count,
            'manual_case_count': manual_case_count,
            'unknown_case_count': unknown_case_count,
            'true_coverage_rate': true_coverage_rate,
            'adoption_rate': adoption_rate,
            'requirement_usage_rate': requirement_usage_rate,
            'coverage_target': config.coverage_target,
            'fake_covered_count': fake_covered,
            'ui_optimization_bug_count': len(ui_bugs),
            'ui_optimization_bug_ids': [b.zentao_id for b in ui_bugs],
            'llm_model': model_config.model_name,
            'embedder_model': embedder.model_name if embedder else None,
            'reranker_model': reranker.model_name if reranker else None,
            'rerank_threshold': RERANK_COVER_THRESHOLD,
            'low_confidence_count': low_confidence_count,
            # LLM 判定输入预算与温度：留痕便于跨报告复现「两轮判定不一致」类问题
            'judge_case_chars': JUDGE_CASE_CHARS,
            'judge_bug_chars': JUDGE_BUG_CHARS,
            'judge_temperature': JUDGE_TEMPERATURE,
            'abnormal_scenes': abnormal_scenes,
            # 有效真实 Bug 反推与低覆盖诊断（status∈{resolved,closed} 且 resolution=='fixed'）
            'valid_bug_total': valid_total,
            'covered_valid': covered_valid,
            'missed_valid': missed_valid,
            'effective_discovered_bugs': covered_valid,
            'effective_coverage_rate': effective_coverage,
            'coverage_diagnosis': diagnosis,
            # B. 自学成效回测：与同一 config 上一轮成功报告对比，量化「知识库沉淀后
            # 生成是否真的变好」，作为闭环有效性的可见指标（零额外 LLM 成本）。
            'self_learning_feedback': _compute_learning_feedback(
                config, report.id, valid_total, covered_valid, missed_valid, effective_coverage,
            ),
        }
        report.save()
        # A. 自动沉淀：报告成功后自动把覆盖缺口 + 思路校准写入知识库（闭环自学，
        # 无需人工点「写入知识库」）。失败仅告警，不影响主报告。
        _auto_push_kb(report, user)
        return report
    except _CoverageCancelled as cancel_exc:
        logger.info('覆盖率分析被用户取消: report=%s', report.id)
        # 用户已通过 DELETE 发起取消；标记 cancelled（线程退出后 DELETE 会真删记录，
        # 此状态只是给轮询 / 日志面板一个清晰的最终态）
        try:
            report.status = 'failed'
            report.error_message = '用户删除报告：任务已取消'
            report.finished_at = timezone.now()
            report.save(update_fields=['status', 'error_message', 'finished_at'])
        except Exception:
            pass
        return report
    except BaseException as exc:
        # 捕获一切（含 asyncio.CancelledError 等 BaseException 子类），
        # 避免后台线程静默死亡导致报告永远停留在 running。
        logger.exception('覆盖率分析失败(含BaseException): report=%s', report.id)
        error_msg = (str(exc) or repr(exc))[:2000] or '未知异常'
        try:
            report.status = 'failed'
            report.error_message = error_msg
            report.finished_at = timezone.now()
            report.save(update_fields=['status', 'error_message', 'finished_at'])
        except Exception as save_exc:
            logger.exception('覆盖率分析失败后状态保存也失败: report=%s', report.id)
        return report


def push_report_to_knowledge(report: CoverageReport, user=None) -> dict:
    """把未覆盖缺陷与调优建议写入项目知识库（带向量索引，供后续生成用例参考）。"""
    from apps.projects.models import ProjectKnowledge
    from apps.requirement_analysis.models import AIModelService

    if report.status != 'success':
        raise RuntimeError('仅成功的覆盖率报告可写入知识库')
    if not report.config.project_id:
        raise RuntimeError('该配置未关联 TestHub 项目，无法写入知识库')

    project = report.config.project
    version_name = report.version.name if report.version_id else ''
    created_count = updated_count = 0
    scope_counts = {'version': 0, 'global': 0, 'legacy': 0}
    # 提前取模型配置：保证下方 C（归因反向注入）分支始终可用，避免 model_config 未定义
    model_config = _pick_llm_config()

    def _save_entry(title: str, content: str, sort_order: int, version=None, category='test_focus') -> bool:
        nonlocal created_count, updated_count
        entry, created = ProjectKnowledge.objects.update_or_create(
            project=project,
            title=title,
            defaults={
                'category': category,
                'content': content,
                'is_active': True,
                'sort_order': sort_order,
                'version': version,
                'source': 'zentao_coverage',
                'needs_review': True,  # 自动沉淀默认待复核，人工确认后才进向量召回
                'created_by': user,
            },
        )
        if created:
            created_count += 1
        else:
            updated_count += 1
        try:
            AIModelService.sync_kb_entry_to_vector(entry, 'upsert')
        except Exception as exc:
            logger.warning('知识库向量化失败 %s: %s', title, exc)
        return created

    items = list(report.items.select_related('bug').all())
    uncovered_items = [it for it in items if not it.covered]
    # 用于 C（归因反向注入）：未覆盖的有效真实 Bug 列表（诊断 cause 基于它）
    missed_valid_bugs_for_distill = [
        it.bug for it in uncovered_items if is_valid_bug(it.bug)
    ]

    # 精炼归并：把未覆盖缺陷蒸馏成少量「覆盖缺失重点」，而非逐条铺 Bug
    points: List[dict] = []
    scope_counts = {'version': 0, 'global': 0, 'legacy': 0}
    if uncovered_items:
        model_config = _pick_llm_config()
        if model_config:
            try:
                points = _llm_distill_knowledge_points(
                    model_config, [it.bug for it in uncovered_items], version_name
                )
            except Exception as exc:
                logger.warning('知识库覆盖重点精炼失败（model=%s）: %s', model_config.model_name, exc)
        if not points:
            # 精炼失败回退：按「未被覆盖原因」去重后每类写一条，避免堆全部 Bug
            seen_reason = set()
            for item in uncovered_items:
                reason_key = (item.reason or '未说明')[:40]
                if reason_key in seen_reason:
                    continue
                seen_reason.add(reason_key)
                bug = item.bug
                points.append({
                    'title': f'[覆盖缺失] {bug.title[:60]}',
                    'content': (
                        f'（版本：{version_name or "-"}）未覆盖原因：{item.reason or "无"}；'
                        f'复现：{bug.steps or "无"}'
                    ),
                    'scope': 'version',
                })

    for p in points:
        scope = p.get('scope') or 'version'
        scope_counts[scope] += 1
        title = f'[覆盖缺失重点] {p["title"][:60]}'
        _save_entry(
            title, p['content'], 10,
            version=(report.version if scope == 'version' else None),
        )

    suggestions = (report.detail or {}).get('improvement_suggestions') or ''
    if suggestions:
        _save_entry(
            f'[覆盖缺口调优建议] {version_name or report.config.name}',
            suggestions,
            5,
            version=report.version,
        )

    # C. 归因反向注入：把「思路方向偏（ai_misunderstanding）」也蒸馏成知识条目，
    # 反向写回知识库，让模型下次生成此类需求时校准方向，而不只是补缺失场景。
    # 诊断里 ai_mis>0 才值得写（纯场景遗漏 gap 已由上方的覆盖缺失重点覆盖）。
    diagnosis = (report.detail or {}).get('coverage_diagnosis') or {}
    ai_mis = (diagnosis.get('cause_breakdown') or {}).get('ai_misunderstanding', 0) or 0
    if ai_mis > 0:
        try:
            mis_points = _llm_distill_misunderstanding_points(
                model_config or _pick_llm_config(),
                missed_valid_bugs_for_distill or [],
                diagnosis,
                version_name,
            )
            for mp in mis_points:
                scope = mp.get('scope') or 'global'
                scope_counts[scope] = scope_counts.get(scope, 0) + 1
                _save_entry(
                    f'[生成思路校准] {mp["title"][:60]}',
                    mp['content'],
                    8,
                    version=(report.version if scope == 'version' else None),
                    category='generation_guidance',
                )
        except Exception as exc:
            logger.warning('生成思路校准知识蒸馏失败（model=%s）: %s',
                           (model_config.model_name if model_config else '-'), exc)

    return {
        'created': created_count,
        'updated': updated_count,
        'total_uncovered': sum(1 for it in items if not it.covered),
        'distilled_points': len(points),
        'scope': scope_counts,
        'message': (
            f'已写入知识库：新增 {created_count}，更新 {updated_count}；'
            f'未覆盖缺陷已精炼为 {len(points)} 条覆盖缺失重点（范围：'
            f'仅本版本 {scope_counts.get("version", 0)}，全局 {scope_counts.get("global", 0)}，'
            f'老功能优化 {scope_counts.get("legacy", 0)}）；'
            f'所有未覆盖有效 Bug 均视为可沉淀的缺失场景。'
        ),
    }


# 判定"覆盖缺失重点"是否属于跨版本通用的易漏点（而非本版本专属 Bug 场景）。
#
# 判定标准（经用户纠正）：不是看"是否提及边界/异常/权限等测试类型词"，而是看
# "这条坑换了版本/换了页面还会不会再犯"。只要做同类功能就必然复现的规律（如
# 文案完整性/跨端差异、弹窗点空白自动关闭、模式数据隔离、跨月数据归属、删除后
# 关联数据一致、切换不串布局）都应升级为跨版本通用；仅当"该版本实现了某个特定
# 接口/字段才可能踩"的纯实现细节才是版本专属、不升。
# 因此词表指向"会跨版本复现的固有行为规律"信号，而非具体功能名/版本号。
_UNIVERSAL_HINTS = (
    '文案', '跨端', 'iOS', 'Android', '完整', '缺失', '串', '隔离', '归属',
    '联动', '回显', '折叠', '关闭', '空白', '收起', '级联', '一致', '布局',
    '切换', '空状态', '占位', '兜底', '默认值', '竞态', '重复', '顺序', '弹窗',
    '自动', '刷新', '同步', '错乱', '残留', '未展示', '不覆盖', '不串',
)


def _is_universal_knowledge_point(title: str, content: str) -> bool:
    """粗略判定一条覆盖缺失重点是否跨版本通用（命中通用测试维度关键词）。"""
    text = f'{title or ""}\n{content or ""}'
    return any(hint in text for hint in _UNIVERSAL_HINTS)


def promote_report_knowledge_to_global(
    report: 'CoverageReport', user=None, only_universal: bool = True
) -> dict:
    """把本次覆盖率报告沉淀的、绑了本版本的知识升级为「跨版本通用」。

    背景：push_report_to_knowledge 写入时，scope=version 的条目会绑定 report.version，
    而生成用例的 RAG 召回（_rag_retrieve_kb）只会让"同版本"或"version 为空"的条目被召回。
    因此 V2.0.0 踩过的坑（覆盖缺失重点）默认不会被 V3.0.0 复用，思考点容易反复遗漏。

    本函数把该报告沉淀、且绑定本版本的条目：
      1. version=None（解除版本绑定，跨版本通用）；
      2. needs_review=False（确认进向量，否则 sync_kb_entry_to_vector 不写入）；
      3. 重新 upsert 向量，使新版本生成用例时能被语义召回。

    only_universal=True（默认）时只升级"命中通用测试维度关键词"的易漏点，
    避免把本版本专属 Bug 场景细节污染全局；传 False 则把本次沉淀全部升级。
    """
    from apps.projects.models import ProjectKnowledge
    from apps.requirement_analysis.models import AIModelService

    if report.status != 'success':
        raise RuntimeError('仅成功的覆盖率报告可升级知识')
    if not report.config.project_id:
        raise RuntimeError('该配置未关联 TestHub 项目，无法升级知识')

    qs = ProjectKnowledge.objects.filter(
        project=report.config.project,
        source='zentao_coverage',
        version=report.version,
    )
    promoted = skipped = 0
    promoted_titles: List[str] = []
    for entry in qs:
        if only_universal and not _is_universal_knowledge_point(entry.title, entry.content):
            skipped += 1
            continue
        entry.version = None
        entry.needs_review = False
        entry.save(update_fields=['version', 'needs_review', 'updated_at'])
        try:
            AIModelService.sync_kb_entry_to_vector(entry, 'upsert')
        except Exception as exc:
            logger.warning('升级知识向量化失败 %s: %s', entry.title, exc)
        promoted += 1
        promoted_titles.append(entry.title)

    return {
        'promoted': promoted,
        'skipped_version_only': skipped,
        'promoted_titles': promoted_titles,
        'only_universal': only_universal,
        'message': (
            f'已升级 {promoted} 条覆盖缺失重点为跨版本通用'
            + (f'（{skipped} 条本版本专属场景未升级）' if skipped else '')
            + '；新版本生成用例时将自动语义召回这些易漏点。'
        ),
    }

