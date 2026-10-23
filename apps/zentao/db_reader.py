"""禅道 MySQL 只读取数（用于历史缺陷复盘）。

设计约束（务必遵守）：
1. **只读**：连接建立后立即 `SET SESSION TRANSACTION READ ONLY`；只执行 SELECT。
2. **字段探测**：不同禅道版本字段有差异，拼 SQL 前先用 information_schema 确认列存在，
   缺失则从 SELECT 列表剔除（而不是抛错），保证跨版本可用。
3. **白名单列**：不 SELECT *，避免把无关/敏感大字段拉进来。
4. **参数化**：所有外部输入走占位符，禁止字符串拼接。
5. 连接失败要给出**可区分的原因**（网络不通 / 认证失败 / 库不存在 / 只读被拒），
   前端据此提示，不能笼统报"读取失败"。

配置来源优先级：
  ZentaoConfig 上的 db_* 字段 > settings 中的 ZENTAO_DB_* 环境变量
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# 有效 Bug 判定（与 services.is_valid_bug 保持同一口径）
VALID_STATUSES = ('resolved', 'closed')
VALID_RESOLUTIONS = ('fixed',)

# 复盘可选的 resolution 口径（2026-10-22 用户要求口径可见且可配）：
#   fixed      —— 开发真正修复并闭环（默认，与覆盖率线一致）
#   bydesign   —— 设计如此：往往暴露"用户预期 vs 设计"的偏差，对写用例有价值
#   external   —— 外部原因：一般不是产品缺陷，默认不纳入
#   duplicate / notrepro / willnotfix / postponed / Legacy 亦可通过 include 扩展
RESOLUTION_FIXED = ('fixed',)
RESOLUTION_WITH_BYDESIGN = ('fixed', 'bydesign')
# 全口径：所有已闭环状态（供"我要看全部历史"的场景）
RESOLUTION_ALL_CLOSED = None  # None 表示不按 resolution 过滤

# 默认可排除的缺陷类型：界面优化类无法转化为功能测试点
DEFAULT_EXCLUDED_TYPES = ('interfaceoptimize',)

# 允许读取的列白名单
BUG_COLUMNS = (
    'id', 'product', 'module', 'project', 'title', 'steps', 'status', 'resolution',
    'type', 'severity', 'pri', 'openedBuild', 'resolvedBuild', 'openedBy',
    'openedDate', 'resolvedDate', 'closedDate', 'story', 'duplicateBug', 'deleted',
)
PRODUCT_COLUMNS = ('id', 'name', 'status', 'deleted')
MODULE_COLUMNS = ('id', 'root', 'branch', 'name', 'parent', 'path', 'type', 'deleted')


class ZentaoDBError(RuntimeError):
    """禅道库读取失败，message 面向用户可读。"""

    def __init__(self, message: str, kind: str = 'unknown'):
        super().__init__(message)
        self.kind = kind


def _cfg_value(config, field: str, env_key: str, default=''):
    """取配置值：优先 ZentaoConfig 字段，其次 settings/env。"""
    if config is not None:
        val = getattr(config, field, '') or ''
        if val:
            return val
    return getattr(settings, env_key, default) or default


class ZentaoReadOnlyDB:
    """禅道数据库只读客户端。

    用法：
        db = ZentaoReadOnlyDB.from_config(config)
        bugs = db.fetch_bugs(product_ids=[57], date_from=..., valid_only=True)
    """

    def __init__(self, host: str, port: int, user: str, password: str,
                 database: str, prefix: str = 'zt_', timeout: int = 15):
        if not host or not user or not database:
            raise ZentaoDBError(
                '禅道数据库连接信息不完整（需要 host/user/database），'
                '请在禅道配置中填写数据库地址或设置 ZENTAO_DB_* 环境变量',
                kind='config_missing',
            )
        self.host = host
        self.port = int(port or 3306)
        self.user = user
        self.password = password
        self.database = database
        self.prefix = prefix or 'zt_'
        self.timeout = timeout
        self._conn = None
        self._columns_cache: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------ 连接
    @classmethod
    def from_config(cls, config=None) -> 'ZentaoReadOnlyDB':
        return cls(
            host=_cfg_value(config, 'db_host', 'ZENTAO_DB_HOST'),
            port=_cfg_value(config, 'db_port', 'ZENTAO_DB_PORT', 3306),
            user=_cfg_value(config, 'db_user', 'ZENTAO_DB_USER'),
            password=_cfg_value(config, 'db_password', 'ZENTAO_DB_PASSWORD'),
            database=_cfg_value(config, 'db_name', 'ZENTAO_DB_NAME'),
            prefix=_cfg_value(config, 'db_prefix', 'ZENTAO_DB_PREFIX', 'zt_'),
        )

    @property
    def conn(self):
        if self._conn is not None:
            return self._conn
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover
            raise ZentaoDBError(f'缺少 pymysql 依赖: {exc}', kind='dependency')

        try:
            conn = pymysql.connect(
                host=self.host, port=self.port, user=self.user,
                password=self.password, database=self.database,
                charset='utf8mb4', connect_timeout=8,
                read_timeout=self.timeout, write_timeout=self.timeout,
                cursorclass=pymysql.cursors.Cursor,
            )
        except Exception as exc:
            raise _translate_conn_error(exc, self.host, self.port, self.database)

        # 强制只读：即便后续误写了写语句，也会被数据库拒绝
        try:
            with conn.cursor() as cur:
                cur.execute('SET SESSION TRANSACTION READ ONLY')
            conn.commit()
        except Exception as exc:
            logger.warning('设置会话只读失败（继续，但本模块只发 SELECT）: %s', exc)

        self._conn = conn
        return conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # ------------------------------------------------------------------ 工具
    def table(self, name: str) -> str:
        return f'`{self.prefix}{name}`'

    def _existing_columns(self, table_short: str) -> List[str]:
        """返回 t_<table_short> 实际存在的列（缓存）。"""
        if table_short in self._columns_cache:
            return self._columns_cache[table_short]
        sql = (
            'SELECT COLUMN_NAME FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s'
        )
        cols = []
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, (self.database, self.prefix + table_short))
                cols = [r[0] for r in cur.fetchall()]
        except Exception as exc:
            logger.warning('探测表 %s 字段失败: %s', table_short, exc)
        self._columns_cache[table_short] = cols
        return cols

    def _select_cols(self, table_short: str, whitelist: Iterable[str]) -> List[str]:
        """按白名单与实际存在列取交集，保证跨版本兼容。"""
        actual = set(c.lower() for c in self._existing_columns(table_short))
        if not actual:
            # 探测失败时按白名单全给，交给数据库报错兜底
            return list(whitelist)
        return [c for c in whitelist if c.lower() in actual]

    def _query(self, sql: str, params=None) -> List[tuple]:
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params or ())
                return list(cur.fetchall())
        except ZentaoDBError:
            raise
        except Exception as exc:
            raise ZentaoDBError(f'查询禅道库失败: {exc}', kind='query')

    # ------------------------------------------------------------------ 查询
    def ping(self) -> dict:
        """连通性自检：返回库名、版本、可用表，供前端"测试连接"使用。"""
        info = {'database': self.database, 'prefix': self.prefix}
        with self.conn.cursor() as cur:
            cur.execute('SELECT VERSION()')
            info['server_version'] = cur.fetchone()[0]
            cur.execute(
                'SELECT TABLE_NAME FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s,%s,%s)',
                (self.database, self.prefix + 'bug', self.prefix + 'product',
                 self.prefix + 'module', self.prefix + 'build'),
            )
            info['tables'] = sorted(r[0] for r in cur.fetchall())
        if self.prefix + 'bug' not in info['tables']:
            raise ZentaoDBError(
                f'库 {self.database} 中未找到 {self.prefix}bug 表，请确认库名/表前缀',
                kind='schema',
            )
        return info

    def fetch_products(self, with_bug_count: bool = False) -> List[dict]:
        """产品列表。

        with_bug_count=True 时额外带上 ``bug_count``（有效缺陷数，口径同
        ``fetch_bugs(valid_only=True)``）。用于前端产品选择时把「0 条缺陷」的
        产品标出来 —— 覆盖率配置里的 product_id 可能指向一个从未录缺陷的产品，
        若直接预选它，复盘会产出一份空报告，用户很难判断是选错还是真没数据。

        统计用一次 GROUP BY 聚合（走 product 索引），不逐产品查询。
        """
        cols = self._select_cols('product', PRODUCT_COLUMNS)
        if not cols:
            return []
        sql = 'SELECT %s FROM %s' % (
            ', '.join('`%s`' % c for c in cols), self.table('product'),
        )
        if 'deleted' in cols:
            sql += " WHERE deleted='0'"
        sql += ' ORDER BY id'
        rows = self._query(sql)
        products = [dict(zip(cols, r)) for r in rows]

        if with_bug_count:
            counts = self.count_bugs_by_product()
            for p in products:
                p['bug_count'] = counts.get(int(p['id']), 0)
        return products

    def count_bugs_by_product(self) -> dict:
        """按产品统计有效缺陷数，返回 {product_id(int): count(int)}。

        失败时返回空 dict 而不是抛错：调用方只把它当提示信息用，
        不能因为统计失败让产品列表整体不可用。
        """
        try:
            bug_cols = self._select_cols('bug', BUG_COLUMNS)
            if 'product' not in bug_cols:
                return {}
            where, params = self._build_bug_where(
                bug_cols,
                closed_only=True,
                resolutions=VALID_RESOLUTIONS,
            )
            sql = 'SELECT `product`, COUNT(*) FROM %s' % self.table('bug')
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            sql += ' GROUP BY `product`'
            out = {}
            for pid, cnt in self._query(sql, params):
                try:
                    out[int(pid)] = int(cnt)
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as exc:  # noqa: BLE001 - 提示性统计，不影响主流程
            logger.warning('统计各产品缺陷数失败：%s', exc)
            return {}

    def fetch_modules(self, product_id: Optional[int] = None) -> List[dict]:
        """禅道模块树。注意：多数产品实际未录入模块，调用方需容忍空结果。"""
        cols = self._select_cols('module', MODULE_COLUMNS)
        if not cols:
            return []
        sql = 'SELECT %s FROM %s' % (
            ', '.join('`%s`' % c for c in cols), self.table('module'),
        )
        where, params = [], []
        if 'deleted' in cols:
            where.append("deleted='0'")
        if product_id is not None and 'root' in cols:
            where.append('root=%s')
            params.append(int(product_id))
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY root, path'
        rows = self._query(sql, params)
        return [dict(zip(cols, r)) for r in rows]

    def _build_bug_where(
        self,
        cols: List[str],
        product_ids: Optional[List[int]] = None,
        date_from=None,
        date_to=None,
        resolutions=None,
        closed_only: bool = True,
        exclude_types: Iterable[str] = DEFAULT_EXCLUDED_TYPES,
    ):
        """构造公共 WHERE，供 fetch_bugs / count_funnel 复用，保证两处口径一致。"""
        where, params = [], []
        if 'deleted' in cols:
            where.append("deleted='0'")
        if product_ids:
            ids = [int(p) for p in product_ids if str(p).strip()]
            if ids:
                where.append('product IN (%s)' % ','.join(['%s'] * len(ids)))
                params.extend(ids)
        if closed_only and 'status' in cols:
            where.append('status IN (%s)' % ','.join(['%s'] * len(VALID_STATUSES)))
            params.extend(VALID_STATUSES)
        # resolutions=None 表示不按 resolution 过滤（全口径）
        if resolutions and 'resolution' in cols:
            where.append('resolution IN (%s)' % ','.join(['%s'] * len(resolutions)))
            params.extend(list(resolutions))
        ex_types = [t for t in (exclude_types or []) if t]
        if ex_types and 'type' in cols:
            where.append('(type IS NULL OR type NOT IN (%s))' % ','.join(['%s'] * len(ex_types)))
            params.extend(ex_types)
        if date_from and 'openedDate' in cols:
            where.append('openedDate >= %s')
            params.append(date_from)
        if date_to and 'openedDate' in cols:
            where.append('openedDate <= %s')
            params.append(date_to)
        return where, params

    def fetch_bugs(
        self,
        product_ids: Optional[List[int]] = None,
        date_from=None,
        date_to=None,
        valid_only: bool = True,
        exclude_types: Iterable[str] = DEFAULT_EXCLUDED_TYPES,
        limit: Optional[int] = None,
        resolutions=None,
    ) -> List[dict]:
        """拉取历史 Bug。

        valid_only=True 时只返回已闭环缺陷（status∈{resolved,closed}）；
        resolutions 进一步限定解决方案：
          - None + valid_only=True  → 所有已闭环（全口径）
          - RESOLUTION_FIXED        → 仅开发修复（与覆盖率线一致）
          - RESOLUTION_WITH_BYDESIGN→ 修复 + 设计如此
        """
        cols = self._select_cols('bug', BUG_COLUMNS)
        if 'id' not in cols:
            raise ZentaoDBError(
                f'{self.prefix}bug 表缺少可识别字段，无法读取', kind='schema',
            )
        # ⚠️ resolutions=None 表示「不按 resolution 过滤」（全收）。
        # 早先这里写 `if resolutions is None and valid_only: resolutions = VALID_RESOLUTIONS`，
        # 把"不过滤"的语义悄悄变成了"只取 fixed"，导致调用方传 None 仍拿到 128 条（
        # 禅道 143 条里的 11 条 external 被无声丢弃）。2026-10-22 实测修正：
        # 需要"只取 fixed"请显式传 RESOLUTION_FIXED。
        where, params = self._build_bug_where(
            cols,
            product_ids=product_ids,
            date_from=date_from,
            date_to=date_to,
            resolutions=resolutions,
            closed_only=valid_only,
            exclude_types=exclude_types,
        )
        sql = 'SELECT %s FROM %s' % (
            ', '.join('`%s`' % c for c in cols), self.table('bug'),
        )
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += ' ORDER BY id DESC'
        if limit:
            sql += ' LIMIT %d' % int(limit)

        rows = self._query(sql, params)
        return [dict(zip(cols, r)) for r in rows]

    def count_funnel(
        self,
        product_ids: Optional[List[int]] = None,
        date_from=None,
        date_to=None,
        resolutions=None,
        exclude_types: Iterable[str] = DEFAULT_EXCLUDED_TYPES,
    ) -> dict:
        """统计「禅道总数 → 各步过滤后」的漏斗，让用户看到每个数字的来历。

        用户实测反馈：禅道页面显示 143 项，工具只读取 91 条，差值无法自查。
        ⇒ 必须把每一步过滤掉多少条明确列出来（2026-10-22 需求）。
        """
        cols = self._select_cols('bug', BUG_COLUMNS)
        if 'id' not in cols:
            return {}

        # 第 1 步：该产品全部 Bug（含禅道里已逻辑删除的，解释 149 vs 143）
        all_rows = self._count_raw(cols, product_ids, date_from, date_to,
                                   include_deleted=True)
        # 第 2 步：剔除 deleted
        alive = self._count_raw(cols, product_ids, date_from, date_to,
                                include_deleted=False)
        # 第 3 步：已闭环（resolved/closed）
        closed = self._count_raw(cols, product_ids, date_from, date_to,
                                 include_deleted=False, closed_only=True)
        # 第 4 步：resolution 命中
        res_matched = self._count_raw(
            cols, product_ids, date_from, date_to, include_deleted=False,
            closed_only=True, resolutions=resolutions)
        # 第 5 步：再排除 type
        final = self._count_raw(
            cols, product_ids, date_from, date_to, include_deleted=False,
            closed_only=True, resolutions=resolutions, exclude_types=exclude_types)

        # 成分明细：解释"被排除的那些是什么"
        base_w, base_p = self._build_bug_where(
            cols, product_ids, date_from, date_to, None, True, [])
        base_sql = self.table('bug') + ((' WHERE ' + ' AND '.join(base_w)) if base_w else '')

        by_resolution = [
            {'name': r[0] or '(空)', 'count': r[1]}
            for r in self._query(
                'SELECT resolution, COUNT(*) FROM %s GROUP BY resolution ORDER BY 2 DESC'
                % base_sql, base_p)
        ]
        by_type = [
            {'name': r[0] or '(空)', 'count': r[1]}
            for r in self._query(
                'SELECT type, COUNT(*) FROM %s GROUP BY type ORDER BY 2 DESC' % base_sql,
                base_p)
        ]

        return {
            'all_rows': all_rows,
            'alive': alive,
            'closed': closed,
            'resolution_matched': res_matched,
            'final': final,
            'excluded_deleted': all_rows - alive,
            'excluded_not_closed': alive - closed,
            'excluded_by_resolution': closed - res_matched,
            'excluded_by_type': res_matched - final,
            'by_resolution': by_resolution,
            'by_type': by_type,
            'resolutions': list(resolutions) if resolutions else [],
            'exclude_types': list(exclude_types or []),
        }

    def _count_raw(self, cols, product_ids, date_from, date_to,
                   include_deleted=False, closed_only=False,
                   resolutions=None, exclude_types=()) -> int:
        w, p = self._build_bug_where(
            cols, product_ids, date_from, date_to, resolutions, closed_only, exclude_types)
        if include_deleted:
            w = [c for c in w if not c.startswith("deleted='0'")]
        sql = 'SELECT COUNT(*) FROM %s' % self.table('bug')
        if w:
            sql += ' WHERE ' + ' AND '.join(w)
        rows = self._query(sql, p)
        return int(rows[0][0]) if rows else 0


def _translate_conn_error(exc: Exception, host: str, port: int, database: str) -> ZentaoDBError:
    """把 pymysql 异常翻译成可操作的提示。"""
    msg = str(exc)
    code = None
    args = getattr(exc, 'args', None)
    if args and isinstance(args[0], int):
        code = args[0]

    if code == 1045:
        return ZentaoDBError(
            f'禅道数据库认证失败（{host}:{port}）：账号或密码不对，'
            f'或该账号未被授权访问 {database}。请检查只读账号配置。',
            kind='auth',
        )
    if code == 1049:
        return ZentaoDBError(
            f'禅道数据库 {database} 不存在（{host}:{port}），请检查库名。',
            kind='database',
        )
    if code == 1130:
        return ZentaoDBError(
            f'禅道数据库拒绝来自当前主机的连接（{host}:{port}）：'
            f'需要在禅道库上给该账号授予本机 IP 的访问权限。',
            kind='host_not_allowed',
        )
    if code == 1044:
        return ZentaoDBError(
            f'账号无权访问库 {database}（{host}:{port}），请检查授权。',
            kind='privilege',
        )
    if isinstance(exc, (TimeoutError,)) or 'timed out' in msg.lower():
        return ZentaoDBError(
            f'连接禅道数据库超时（{host}:{port}），请检查网络/防火墙。',
            kind='timeout',
        )
    return ZentaoDBError(
        f'连接禅道数据库失败（{host}:{port}/{database}）：{msg[:300]}',
        kind='connect',
    )


# ----------------------------------------------------------------------------
# 文本处理（方案 A：只用标题 + 非空文字，忽略截图）
# ----------------------------------------------------------------------------
_IMG_RE = re.compile(r'<img[^>]*>', re.I)
_BR_RE = re.compile(r'<br\s*/?>', re.I)
_PARA_RE = re.compile(r'</p>', re.I)
_TAG_RE = re.compile(r'<[^>]+>')
# 版本前缀：mini2 v 1.0.3—— / mini2iOSv1.0.0---- / mini2 V1.0.0-- 等混用写法
_VERSION_PREFIX_RE = re.compile(
    r'^\s*[\w\u4e00-\u9fff]{1,20}?\s*(?:ios|android)?\s*v?\s*\d+(?:\.\d+)*\s*[-—–]{2,}\s*',
    re.I,
)
# 「任意前缀 + 连续短横线」：2026重阳运营活动-----定制结果页...（实测产品13 的写法）
# 短横线数量在 2~10 之间浮动，且 -- — – 可能混用
_DASH_SPLIT_RE = re.compile(r'\s*[-—–]{2,10}\s*')
# 活动类前缀：2026重阳运营活动 / 中秋运营活动 / 财神节活动
_ACTIVITY_PREFIX_RE = re.compile(r'^(?:\d{4}\s*)?[\u4e00-\u9fff]{0,12}(?:运营)?活动$')
# 模板占位行，剥完只剩这些等于没有内容
_TEMPLATE_TOKENS = {'[步骤]', '[结果]', '[期望]', '[重现步骤]', '[期望结果]'}


def strip_html_keep_text(value) -> str:
    """剥 HTML 并丢弃图片占位，只留可读文字（方案 A）。"""
    if not value:
        return ''
    s = str(value)
    s = _IMG_RE.sub('', s)
    s = _BR_RE.sub('\n', s)
    s = _PARA_RE.sub('\n', s)
    s = _TAG_RE.sub('', s)
    s = (s.replace('&nbsp;', ' ').replace('&amp;', '&')
          .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))
    lines = []
    for line in s.split('\n'):
        t = line.strip()
        if not t or t in _TEMPLATE_TOKENS:
            continue
        lines.append(t)
    return '\n'.join(lines).strip()


def strip_version_prefix(title: str) -> str:
    """去掉标题里的版本/活动前缀。

    实测两种格式混用（2026-10-22）：
      - mini2 v1.0.3——状态记录：...        （版本号 + 长破折号）
      - 2026重阳运营活动-----定制结果页...  （活动名 + 连续短横线）
    """
    t = (title or '').strip()
    stripped = _VERSION_PREFIX_RE.sub('', t, count=1)
    if stripped != t:
        return stripped
    # 通用兜底：任意前缀 + 连续短横线（2~10 个，-- — – 混用）
    parts = _DASH_SPLIT_RE.split(t, maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        return parts[1].strip()
    return t


def extract_activity(title: str) -> str:
    """识别「活动名前缀」：2026重阳运营活动 / 中秋运营活动 / 财神节活动。

    运营活动型产品的 Bug 标题前缀是活动名而非功能模块，
    这些缺陷应归到活动域，而不是当成功能域。
    """
    t = (title or '').strip()
    prefix = _DASH_SPLIT_RE.split(t, maxsplit=1)[0].strip()
    # 去掉版本号残留
    prefix = re.sub(r'^.*?v?\d+(?:\.\d+)+\s*', '', prefix, flags=re.I).strip()
    if prefix and _ACTIVITY_PREFIX_RE.match(prefix):
        return prefix
    return ''


def extract_domain(title: str) -> str:
    """从标题里抽功能域。

    依次尝试三种结构（实测并存）：
      1. 「功能域：描述」      → 取冒号前片段          （mini2 等 App 产品）
      2. 「活动名-----功能短语」→ 取短横线后的前 2~10 字 （运营活动产品）
      3. 都不匹配 → 返回空串，由上层兜底
    """
    body = strip_version_prefix(title)

    # 结构 1：冒号分隔
    m = re.match(r'^\s*([^：:，,（(]{2,24})\s*[：:]', body)
    if m:
        domain = m.group(1).strip()
        # 排除测试维度词（「文案：xxx」里的"文案"是测什么，不是测哪个功能）
        if (domain and not domain.isdigit() and len(domain) <= 24
                and domain not in _DOMAIN_EXCLUDE_WORDS):
            return domain

    # 结构 2：无冒号时，用正文起首的功能短语（如「定制结果页保存的图片...」→ 定制结果页）
    # 只在标题确实被短横线切过（说明有前缀）时才启用，避免把整句话当前缀
    if len(_DASH_SPLIT_RE.split((title or '').strip(), maxsplit=1)) == 2:
        # 优先匹配常见页面/对象词，提高准确度
        page_hit = re.search(
            r'(定制结果页|结果页|过程页|首页|活动页|分享页|保存页|弹窗|'
            r'引导页|详情页|列表页|播放页|加载页|入口页|悬浮窗)',
            body,
        )
        if page_hit:
            return page_hit.group(1)
        # 退化为前 2~8 个汉字（遇到标点即停），但要排除明显是句子片段的脏域名
        m2 = re.match(r'^\s*([\u4e00-\u9fffA-Za-z]{2,8})', body)
        if m2 and _looks_like_domain(m2.group(1)):
            return m2.group(1)
    return ''


# 脏域名特征（2026-10-22 实测：标题截断被当成域名，产生大量碎片域）
#   「iOS提醒列表只」「安卓游戏过程中点」「排行榜的分数算的」「提醒最后一天应该」
#   「文案需跟需求一致」「模版图传错了」「涉政涉黄图片需审」「连击的时候没有看」
_DOMAIN_BAD_TAIL = ('的', '了', '只', '点', '应该', '需', '要', '是', '在', '和',
                    '与', '都', '就', '还', '也', '把', '被', '让', '给', '对',
                    '过', '很', '太', '不', '没有', '可以', '时候')
_DOMAIN_BAD_HEAD = ('iOS', 'android', 'Android', '安卓', '苹果', '点击', '出现',
                    '发现', '导致', '造成', '建议', '需要', '应该', '如果', '当')

# 测试维度词不能当功能域（2026-10-22 实测：标题写「文案：xxx」时
# 会把"文案"当成一个功能域，产出「文案-文案与需求一致性」这种语义重复的测试点；
# 更糟的是「文案-视觉还原与样式一致性」——"文案"域里的视觉问题，完全说不通）。
# 这些词是"测什么"，不是"测哪个功能"，必须排除，归到未分类。
_DOMAIN_EXCLUDE_WORDS = {
    '文案', '提示语', '文案错误', '错别字', '文字',
    '动画', '播放', '预览', '音频', '音乐',
    '样式', '颜色', '图标', 'icon',
    '适配', '尺寸', '分辨率',
    '埋点', '接口', '请求', '日志',
    '权限', '校验', '边界',
    '刷新', '回显', '同步',
    '问题', 'bug', 'Bug', 'BUG', '缺陷', '异常', '错误',
    '优化', '需求', '功能', '测试', '验证',
}


def _looks_like_domain(word: str) -> bool:
    """判断截断出来的片段是否像一个「功能域」而非句子开头或测试维度词。

    宁可返回 False（归到未分类）也不要造出「iOS提醒列表只」这种假域名，
    或「文案」「动画」这种测试维度词——假域名会让统计表变垃圾、
    维度词会让测试点标题语义重复（「文案-文案与需求一致性」）。
    """
    w = (word or '').strip()
    if len(w) < 2:
        return False
    if w in _DOMAIN_EXCLUDE_WORDS:
        return False
    if w.endswith(_DOMAIN_BAD_TAIL):
        return False
    if w.startswith(_DOMAIN_BAD_HEAD):
        return False
    # 含动词/助词比例过高说明是句子片段
    bad_chars = sum(1 for ch in w if ch in '的了是在和与都就还也把被让给对过很太不')
    if bad_chars * 2 >= len(w):
        return False
    return True
