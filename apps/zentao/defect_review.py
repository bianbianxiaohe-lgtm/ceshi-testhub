"""历史缺陷复盘：从禅道库读取项目历史有效 Bug，做统计与测试点提炼。

**纯规则实现，全程不调用 LLM**（2026-10-22 评估后确认不做 LLM 归并）：
  - 取数：ZentaoReadOnlyDB（只读）
  - 归一：标题剥离版本前缀、抽取功能域
  - 统计：总量/有效量/排除量、按功能域/类型/严重度/版本/时间的分布、口径说明
  - 提炼：功能域 × 测试维度的聚类（纯规则，可解释、可复算）

为什么不做 LLM 归并（有数据支撑，别轻易推翻）：
  实测未分类缺陷占比 0~2.8%、域切分清楚；「标题相似」的测试点其实是
  **同一维度 × 不同功能域**的正交切片（checks 签名相同但 count/keywords 不同），
  合并反而丢掉"这个域历史上踩过几条"的信息。而 LLM 会带来：数据外发、
  耗时从毫秒涨到分钟、结果不可复现（同数据两次跑不一样）三重代价。
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from django.utils import timezone

from .db_reader import (
    DEFAULT_EXCLUDED_TYPES,
    RESOLUTION_WITH_BYDESIGN,
    ZentaoDBError,
    ZentaoReadOnlyDB,
    _looks_like_domain,
    extract_activity,
    extract_domain,
    strip_html_keep_text,
    strip_version_prefix,
)

logger = logging.getLogger(__name__)

# 易漏模式的规则词表：命中即给该缺陷打一个"测试维度"标签。
# 这些维度是"换个版本/换个页面还会再犯"的固有规律，用于提炼测试点。
SCENE_RULES = (
    ('状态回显/刷新', ('回显', '刷新', '重启', '重新进入', '切回', '返回后', '再次进入',
                   '恢复', '未更新', '不更新', '显示旧', '还是显示', '没有变')),
    ('账号/权限切换', ('切换账号', '切换登录', '未登录', '登录后', '退出登录', '注销',
                   '会员', '非会员', '权限', '免费次数', '权益')),
    ('数据一致性', ('不一致', '对不上', '同步', '天数', '统计', '重复', '串',
                '关联', '级联', '联动')),
    ('跨端/多设备', ('iOS', 'Android', '安卓', '苹果', '其他设备', '对方', '双端',
                 '两端', '跨端')),
    ('入口/跳转路由', ('跳转', '进入', '未进入', '点击未', '无响应', '不弹', '未弹出',
                  '入口', '返回按钮', '路由', '页面空白', '白屏')),
    ('空态/默认值', ('默认', '空状态', '占位', '兜底', '剪影', '未展示', '展示异常',
                 '显示异常', '缺少', '缺失')),
    ('组件/外部环境', ('小组件', 'widget', '桌面', '通知', '推送', '后台', '锁屏',
                  '通知栏')),
    ('表单校验/边界', ('校验', '限制', '范围', '上限', '下限', '超长', '最大', '最小',
                  '边界', '必填', '不能为空', '输入', '空格', '提示语', '错误提示',
                  'toast', 'Toast', '无效', '格式', '字数')),
    ('网络异常', ('网络', '超时', '断网', '弱网', '失败重试', '加载失败', '卡住',
              '一直在加载', '一直加载', '加载中', '无响应', '没反应', '无反应',
              '下载失败', '重新下载')),
    ('文案与需求一致性', ('文案', '文案错误', '错别字', '应为', '应该是', '参考需求',
                   '与原型', '产品确认', '与需求', '参考设计')),
    ('动画与多媒体', ('动画', '播放', '预览', '视频', '闪屏', '闪烁', '黑屏', '截断',
                '卡顿', '顿挫', '静态', '偏移', '尺寸', '比例')),
    ('接口与埋点', ('接口', '埋点', '请求', '重复调用', '重复请求', '扣减', '数数')),
    ('进程与冷启动', ('杀进程', '杀掉进程', '冷启动', '重启', '卸载重装', '后台',
                '未及时更新', '闪退')),
    ('生成耗时/轮询', ('生成中', '轮询', '进度', '卡在', '生成失败', '生成成功',
                 '下载进度', '卡了')),
    # 界面优化类专用（仅在纳入 interfaceoptimize 时出现）
    ('视觉还原度', ('颜色', '黑色背景', '背景色', '图标', 'icon', '模糊', '清晰',
                '模糊不清', '大小', '偏上', '偏下', '太偏', '遮挡', '被挡', '对齐',
                '间距', '换行', '截断', '变形')),
)

# 一条缺陷可能命中多个维度，但落测试点时只看"最像测试策略"的那些。
# 这里保留全部命中，由 UI 决定展示；统计口径不做优先级裁剪，避免引入主观判断。


# 功能域归并表：把标题里的碎片化前缀归到大功能域。
#
# 设计依据（mini2 实测 123 个原始域的真实分布）：
#   - 「状态记录 / 自定义状态 / 添加状态 / 状态设定页 / 状态生成 / 状态应用 / 状态1.0」
#     都是同一个状态功能的不同层级写法 → 状态记录
#   - 「心情罐子 / 心情罐子应用内 / 心情罐子对方页 / 心情罐子->小组件安装页」→ 心情罐子
#   - 「想你应用内 / 想你小组件 / 想你小号组件 / 想你双人小组件」→ 想你（组件类另行叠加维度）
#   - 「引导 / 引导页 / 前置引导 / 教学引导 / 匹配教学 / 教学流程」→ 引导与教学
#   - 「登录 / 登录页 / 切换登录 / 切换账号 / 注销账号 / 我的绑定手机号」→ 登录与账号
#   - 「我的 / 我的形象 / 我的形象页 / min人形象 / 首页形象 / 首页对方mini人」注意区分：
#     「我的形象」属形象管理，「首页*」属首页
#
# 规则按顺序匹配，先命中者胜（因此更具体的规则必须排在更宽泛的规则之前）。
DOMAIN_RULES = (
    # --- 首页类必须排在形象之前：'首页形象' 含 '形象'，否则会被形象管理抢走 ---
    # 注意：第二轮标题兜底时「进入首页后…」这类叙述会误伤，
    # 因此这里只放「首页+具体对象」的组合词，不放裸的「首页」。
    ('首页', ('首页mini', '首页形象', '首页对方', '首页&', '首页、')),
    # --- 形象相关 ---
    ('形象管理', ('我的形象', 'min人形象', 'mini人形象', '真人照片形象', '定制形象',
              '形象生成', '新形象生成', '传图生成', '一键生成', '换照片', '历史形象',
              '历史记录', '上传照片', 'mini我定制', '装扮', '切换装扮', '背景更换',
              '服装', '动作库')),
    # --- 状态功能 ---
    ('状态记录', ('状态记录', '自定义状态', '添加状态', '状态设定页', '状态生成',
              '状态应用', '状态修改', '状态1.0', '状态入口', '状态记录推送',
              '状态记录入口')),
    # --- 心情罐子 ---
    ('心情罐子', ('心情罐子',)),
    # --- 想你 ---
    ('想你', ('想你',)),
    # --- 默契问答 ---
    ('默契问答', ('默契问答',)),
    # --- 小组件（通用，须在具体组件之后）---
    ('小组件', ('小组件', '桌面小人', '桌面娃娃', '桌面')),
    # --- 推送 / 通知 ---
    ('推送通知', ('推送', '通知栏', '通知')),
    # --- 互动 ---
    ('互动', ('互动', '人物互动', '小纸条')),
    # --- 登录账号与权限 ---
    ('登录与账号', ('登录', '切换账号', '注销', '绑定手机号', '隐私同意', '隐私政策',
               '协议', '授权管理', '权限管理', '我的权限', '接入客服')),
    # --- 付费与权益 ---
    ('付费与权益', ('付费', '会员', '权益', 'vip', 'VIP', '订阅', '升级')),
    # --- 邀请匹配（在「我的」之前）---
    ('邀请与匹配', ('邀请', '匹配', '扫码', '分享')),
    # --- 接口与埋点 ---
    ('接口与埋点', ('接口', '埋点', '请求', '日志', '数数平台')),
    # --- 「我的」及个人信息（宽泛规则放后面）---
    ('我的与个人信息', ('我的', '个人信息', '昵称', '关于我们', '关于页面', '解除匹配',
                  '新形象生成成功标识')),
    # --- 引导与教学 ---
    ('引导与教学', ('引导', '教学', '新人注册')),
    # --- 其他杂项 ---
    ('应用基础', ('应用icon', 'logo替换', '日期显示', '闪退', '闪屏')),
)


# 「跨域通用」是 `_build_rule_testpoints` 聚合出来的**合成维度**（同一 scene
# 在多个域都没达阈值时才合并），不是产品里真实存在的模块。
# 它不能参与「需求 → 功能域」匹配，否则其 raw_domains 会把多个真实域一起拉进来。
CROSS_DOMAIN_LABEL = '跨域通用'


# 运营活动型产品的「页面环节」域。
#
# 为什么不做「活动名·页面环节」两级（2026-10-22 实测数据否定）：
#   按活动名拆开（元旦26/端午14/立秋9/母亲节9/财神9…）后，
#   每个活动的缺陷 Top1 维度几乎都是「分享/跨端」，信息完全重复，
#   等于把同一句话重复 13 遍。真正可跨活动复用的是「哪个页面环节容易出问题」。
# ⇒ 因此只按页面环节拆，活动名作为标签保留在缺陷标题里即可。
ACTIVITY_PAGE_RULES = (
    ('定制结果页', ('定制结果页',)),
    ('过程页', ('过程页', '生成中页', '加载页', '制作过程')),
    ('结果页', ('结果页', '保存图片', '保存页', '结果')),
    ('分享页', ('分享页', '分享卡片', '分享图')),
    ('首页', ('首页', '活动首页', '活动入口')),
    ('引导页', ('引导页', '引导流程')),
    ('分享与跨端', ('分享', '微信', 'QQ', 'qq', '鸿蒙', '双端')),
    ('适配与尺寸', ('适配', 'iphone', 'iPhone', '屏幕', '机型')),
    ('音乐与动画', ('音乐', '音频', '声音', '动画')),
    # ⚠️ 这里**不能**放「文案」「埋点」「校验」这类词：
    #    它们是"测什么"（scene），不是"测哪个功能"（domain）。
    #    早先放了「文案」，结果产出「文案-文案与需求一致性」「文案-视觉还原与样式一致性」
    #    这种语义重复甚至矛盾的测试点（2026-10-22 实测）。
    #    这类缺陷会由 SCENE_RULES 打上对应 scene，不需要占用 domain。
)


def activity_page_domain(body: str) -> str:
    """给运营活动类缺陷判定「页面环节」域。返回空串表示无法判定。"""
    text = body or ''
    for domain, keywords in ACTIVITY_PAGE_RULES:
        for kw in keywords:
            if kw in text:
                return domain
    return ''


# 描述性字眼：域名里出现即说明它是句子片段而非模块名
_DESCRIPTIVE_WORDS = ('需', '应该', '不一致', '错', '没有', '部分', '无法', '失败')


def _is_known_domain(d: str) -> bool:
    """判断一个未归并的域名是否是「产品里真实存在的功能域」，而非标题碎片。

    在 `db_reader._looks_like_domain`（已含助词尾、动词头、脏字符比例等规则）
    之上再补两条与产品统计口径相关的判据：
      - 太长（>8）基本是整句而非模块名
      - 含描述性字眼（需/应该/不一致/错/没有…）说明是句子
    宁可误判为「未分类」，也不要造出假功能域污染统计表。
    """
    w = (d or '').strip()
    if not _looks_like_domain(w):
        return False
    if len(w) > 8:
        return False
    if any(k in w for k in _DESCRIPTIVE_WORDS):
        return False
    return True


def merge_domain(raw_domain: str, title: str = '') -> str:
    """把原始功能域前缀归并到大功能域。

    ⚠️ 两轮匹配是关键（2026-10-22 实测踩过的坑）：
    早先版本把 `raw_domain + title` 拼起来一次性匹配，结果标题正文里出现
    「进入首页后…」「引导…」等字样时，几乎所有缺陷都被 `首页` / `引导` 规则抢走，
    导致「首页」虚高到 25 条、「我的与个人信息」被吃空。
    因此改为：**第一轮只匹配原始域前缀（精确），第二轮才对标题兜底**。

    ⚠️ 第二轮兜底仍可能救不回来，此时**必须返回「未分类」而不是原样返回 d**：
    实测报告 #10/#12 里残留「文案需跟需求一致」「涉政涉黄图片需审」
    「连击的时候没有看」「邀请与匹配」这类由标题截断产生的假域名，
    它们会作为独立"功能域"进入统计表，让用户以为产品真有这些模块。
    返回「未分类」由 `_build_rule_testpoints` 统一归口，语义才是对的。
    """
    d = (raw_domain or '').strip()
    if d:
        for merged, keywords in DOMAIN_RULES:
            for kw in keywords:
                if kw in d:
                    return merged
        # 已是 ACTIVITY_PAGE_RULES 里的页面环节，直接判定为真实域
        if any(d == page for page, _kws in ACTIVITY_PAGE_RULES):
            return d
    # 前缀没救回来（或本身为空）才用标题兜底
    t = title or ''
    if t:
        for merged, keywords in DOMAIN_RULES:
            for kw in keywords:
                if kw in t:
                    return merged
        page = activity_page_domain(t)
        if page:
            return page
    # 两轮都没命中：只有确认是真实功能域才保留，否则统一落「未分类」。
    if _is_known_domain(d):
        return d
    return '未分类'


def classify_scenes(text: str) -> List[str]:
    """按规则给一条缺陷打测试维度标签（可多条）。"""
    t = (text or '').lower()
    hits = []
    for scene, keywords in SCENE_RULES:
        for kw in keywords:
            if kw.lower() in t:
                hits.append(scene)
                break
    return hits


def _norm_domain(raw: str) -> str:
    """功能域归一：去掉空白与残留符号，便于同类合并。"""
    d = re.sub(r'\s+', '', raw or '')
    d = d.strip('-—–_·。.、')
    return d


def _severity_label(sev) -> str:
    """禅道 severity 是 1~4 的字符串，1 最严重。"""
    s = str(sev or '').strip()
    return {'1': '1-致命', '2': '2-严重', '3': '3-一般', '4': '4-建议'}.get(s, s or '未填')


def _type_label(t) -> str:
    return {
        'functionalissues': '功能缺陷',
        'interfaceoptimize': '界面优化',
        'pde': 'PDE',
        'RC': 'RC',
        'codeerror': '代码错误',
        'demandnotmatch': '与需求不符',
        'config': '配置相关',
        'performance': '性能问题',
        'designdefect': '设计缺陷',
        'dataerror': '数据错误',
        'others': '其他',
    }.get(str(t or ''), str(t or '未填'))


def _resolution_label(r) -> str:
    """禅道解决方案的中文名。external 类缺陷同样是真实问题，需要可见。"""
    return {
        'fixed': '开发已修复',
        'bydesign': '设计如此',
        'external': '外部原因',
        'duplicate': '重复',
        'notrepro': '无法重现',
        'willnotfix': '不予解决',
        'postponed': '延期',
        'tostory': '转需求',
        'Legacy': '历史遗留',
        '': '未填',
    }.get(str(r or ''), str(r or '未填'))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_defect_review(
    config=None,
    product_ids: Optional[List[int]] = None,
    date_from=None,
    date_to=None,
    exclude_types=None,
    resolutions=None,
    top_n: int = 30,
) -> dict:
    """执行一次历史缺陷复盘，返回可直接落库/返回前端的 dict。

    口径可配（2026-10-22 用户要求"数字来历可见、口径可调"）：
      - resolutions: 纳入哪些解决方案。**默认 None = 全收**（只要已闭环就纳入）。
        背景：产品13 实测 143 条中有 11 条标 external（外部原因），内容是
        「iOS黄历打不开」「分享到QQ没反应」「提醒少一天」——都是实打实的产品问题，
        对写用例价值很高。排除它们会让"禅道143 vs 复盘132"对不上，用户会以为统计错了。
        ⇒ 默认全收，改为在报告里**分类展示** resolution，让用户自己判断而非被静默过滤。
      - exclude_types: 要排除的缺陷类型。**默认不排除**（None→[]）；
        界面优化类会自动归到「界面表现」域，不与功能域混在一起

    不写数据库，纯计算；调用方决定如何保存。
    """
    started = timezone.now()
    exclude_types = list(exclude_types or [])
    db = ZentaoReadOnlyDB.from_config(config)
    # 空结果时用于解释"为什么是 0"的两个对照量
    unfiltered_total = None
    date_hint = None
    funnel = {}
    try:
        info = db.ping()
        products = db.fetch_products()
        # 漏斗：让用户看到「禅道 143 → 纳入 91」的每一步
        try:
            funnel = db.count_funnel(
                product_ids=product_ids,
                date_from=date_from,
                date_to=date_to,
                resolutions=resolutions,
                exclude_types=exclude_types,
            )
        except Exception as exc:
            logger.warning('漏斗统计失败（不影响主流程）: %s', exc)

        bugs = db.fetch_bugs(
            product_ids=product_ids,
            date_from=date_from,
            date_to=date_to,
            valid_only=True,
            exclude_types=exclude_types,
            resolutions=resolutions,
        )
        # 0 条时必须有可见且准确的原因，不能静默标"完成"（2026-10-22 用户反馈）
        if not bugs:
            try:
                same_scope = db.fetch_bugs(
                    product_ids=product_ids,
                    date_from=None,
                    date_to=None,
                    valid_only=True,
                    exclude_types=exclude_types,
                    resolutions=resolutions,
                )
                unfiltered_total = len(same_scope)
                if unfiltered_total:
                    opened_dates = sorted(
                        str(b.get('openedDate'))[:10]
                        for b in same_scope if b.get('openedDate')
                    )
                    if opened_dates:
                        date_hint = {'from': opened_dates[0], 'to': opened_dates[-1]}
            except Exception as exc:
                logger.warning('空结果对照查询失败: %s', exc)
    finally:
        db.close()

    product_name = {int(p['id']): p['name'] for p in products if p.get('id') is not None}

    # ---- 归一 ----
    items = []
    skipped_no_title = 0
    for b in bugs:
        raw_title = (b.get('title') or '').strip()
        if not raw_title:
            skipped_no_title += 1
            continue
        body = strip_version_prefix(raw_title)
        steps_text = strip_html_keep_text(b.get('steps'))
        raw_domain = _norm_domain(extract_domain(raw_title))
        domain = merge_domain(raw_domain, body)

        # 运营活动型产品：标题前缀是活动名（2026重阳运营活动-----...）。
        # 不按活动名成域（各活动易漏维度高度重复、信息冗余），
        # 改按「页面环节」成域，活动名保留在 body 里作为可追溯标签。
        activity = extract_activity(raw_title)
        if activity:
            page_domain = activity_page_domain(body)
            domain = page_domain or '运营活动'
            body = f'{activity}·{body}'

        # 界面优化类单独成域：不与功能域混在一起，避免"样式问题"稀释功能测试点
        if str(b.get('type') or '') == 'interfaceoptimize' and not activity:
            domain = '界面表现'

        scenes = classify_scenes(f'{body}\n{steps_text}')
        pid = b.get('product')
        items.append({
            'bug_id': b.get('id'),
            'title': body,
            'raw_title': raw_title,
            'raw_domain': raw_domain,
            'domain': domain,
            'scenes': scenes,
            'severity': str(b.get('severity') or ''),
            'severity_label': _severity_label(b.get('severity')),
            'type': str(b.get('type') or ''),
            'type_label': _type_label(b.get('type')),
            # 解决方案：external（外部原因）等也全部保留，用这个字段让用户自己识别，
            # 而不是在取数阶段静默排除（否则"禅道143 vs 复盘132"对不上）
            'resolution': str(b.get('resolution') or ''),
            'resolution_label': _resolution_label(b.get('resolution')),
            'product_id': pid,
            'product_name': product_name.get(int(pid), str(pid)) if pid is not None else '',
            'opened_build': str(b.get('openedBuild') or ''),
            'opened_date': _fmt_date(b.get('openedDate')),
            'has_text': bool(steps_text),
        })

    # ---- 统计 ----
    domain_counter = Counter(i['domain'] for i in items)
    domain_details = []
    for domain, count in domain_counter.most_common():
        rows = [i for i in items if i['domain'] == domain]
        scene_counter = Counter()
        for r in rows:
            for s in r['scenes']:
                scene_counter[s] += 1
        domain_details.append({
            'domain': domain,
            'count': count,
            'ratio': _ratio(count, len(items)),
            'top_scenes': [
                {'scene': s, 'count': c} for s, c in scene_counter.most_common(5)
            ],
            'sample_titles': [r['title'] for r in rows[:3]],
            'bug_ids': [r['bug_id'] for r in rows],
        })

    scene_counter_all = Counter()
    for i in items:
        for s in i['scenes']:
            scene_counter_all[s] += 1

    # 未命中任何规则的数量：衡量规则覆盖率，避免"看起来都归好类了"的错觉
    unmatched = sum(1 for i in items if not i['scenes'])

    stats = {
        'bug_total_raw': len(bugs),
        'bug_eligible': len(items),
        'skipped_no_title': skipped_no_title,
        # 口径漏斗：禅道全部 → 纳入复盘，每一步过滤了多少条（用户要求可见）
        'funnel': funnel,
        'with_text_steps': sum(1 for i in items if i['has_text']),
        'text_step_ratio': _ratio(sum(1 for i in items if i['has_text']), len(items)),
        'by_domain': domain_details[:top_n],
        'domain_count': len(domain_details),
        'by_type': _counter_rows(Counter(i['type_label'] for i in items), len(items)),
        # 解决方案分布：external（外部原因）等分类展示，让用户看到它们确实被统计了
        'by_resolution': _counter_rows(
            Counter(i['resolution_label'] for i in items), len(items)),
        'by_severity': _counter_rows(Counter(i['severity_label'] for i in items), len(items)),
        'by_build': _counter_rows(Counter(i['opened_build'] or '未填' for i in items), len(items)),
        'by_product': _counter_rows(Counter(i['product_name'] or '未填' for i in items), len(items)),
        'by_scene': [
            {'scene': s, 'count': c, 'ratio': _ratio(c, len(items))}
            for s, c in scene_counter_all.most_common()
        ],
        'scene_unmatched': unmatched,
        'scene_match_ratio': _ratio(len(items) - unmatched, len(items)),
        'date_range': _date_range(items),
    }

    # ---- 测试点候选（纯规则版）----
    testpoints = _build_rule_testpoints(domain_details, items)

    return {
        'ok': True,
        'generated_at': started.isoformat(),
        'elapsed_ms': int((timezone.now() - started).total_seconds() * 1000),
        'source': {
            'mode': 'db_readonly',
            'database': info.get('database'),
            'server_version': info.get('server_version'),
            'product_ids': product_ids or [],
            'date_from': str(date_from) if date_from else '',
            'date_to': str(date_to) if date_to else '',
            'excluded_types': list(exclude_types or []),
            'text_policy': 'A: 仅标题 + 非空文字，忽略截图',
        },
        'stats': stats,
        'items': items,
        'testpoints': testpoints,
        'llm_used': False,
        'empty_reason': _build_empty_reason(
            len(items), unfiltered_total, date_from, date_to, date_hint
        ),
        'notes': _build_notes(stats) + _build_empty_notes(
            len(items), unfiltered_total, date_from, date_to, date_hint
        ),
    }


def _build_empty_reason(count, unfiltered_total, date_from, date_to, date_hint):
    """count==0 时给出可操作的原因；非空返回 None。"""
    if count:
        return None
    scope = ''
    if date_from or date_to:
        scope = '时间范围 %s ~ %s 内' % (date_from or '最早', date_to or '至今')
    if unfiltered_total is None:
        return '该产品在禅道库中没有符合条件的有效缺陷（status=resolved/closed 且 resolution=fixed）。'
    if unfiltered_total == 0:
        return (
            '该产品在禅道库中没有符合条件的有效缺陷'
            '（status=resolved/closed 且 resolution=fixed）。'
            '请确认产品是否选对，或该产品在禅道里是否记录了缺陷。'
        )
    hint = ''
    if date_hint:
        hint = '该产品历史缺陷的时间跨度为 %s ~ %s。' % (date_hint['from'], date_hint['to'])
    return (
        '%s没有缺陷，但该产品历史上共有 %d 条有效缺陷。%s'
        '请放宽或清空时间范围后重新复盘。' % (scope or '当前条件下', unfiltered_total, hint)
    )


def _build_empty_notes(count, unfiltered_total, date_from, date_to, date_hint):
    reason = _build_empty_reason(count, unfiltered_total, date_from, date_to, date_hint)
    return [reason] if reason else []


# 每个易漏维度对应的「测试点表述模板」与「验证要点」。
#
# 这是本功能的产物核心：不是"某域有 7 条缺陷"，而是
# 「状态记录-待机动画：进入页面后动画应正常播放并完整展示」
# —— 后者才能直接喂给用例生成。
#
# 模板中的 {domain} 会被替换成功能域，{count} 是该维度在该域的历史缺陷数。
SCENE_TP_TEMPLATES = {
    '入口/跳转路由': {
        'title': '{domain}-核心入口跳转与响应',
        'desc': (
            '历史缺陷中该域有 {count} 条是「入口点了没反应 / 没进入目标页 / 不该弹的弹了」。'
            '需覆盖该域所有入口的点击→跳转→返回闭环。'
        ),
        'checks': [
            '每个功能入口点击后应进入正确页面，不允许无响应',
            '从二级页返回后，入口状态与数据应正确',
            '不该出现的弹窗/页面不应出现（前置条件不满足时）',
            '连续快速点击入口不应重复跳转或叠加页面',
        ],
    },
    '跨端/多设备': {
        'title': '{domain}-双端一致性与跨设备同步',
        'desc': (
            '历史缺陷中该域有 {count} 条是「iOS 与安卓表现不一致」或「A 操作后对方的设备没同步」。'
            '需覆盖双端对比与双端联动。'
        ),
        'checks': [
            'iOS 与安卓同操作路径下，展示与交互结果一致',
            'A 端修改后，B 端（对方/另一设备）应同步更新',
            '冷启动与后台恢复后，跨端数据仍一致',
        ],
    },
    '组件/外部环境': {
        'title': '{domain}-多尺寸组件与外部环境展示',
        'desc': (
            '历史缺陷中该域有 {count} 条与小组件/桌面/通知栏相关。'
            '需覆盖各尺寸组件及系统环境的组合。'
        ),
        'checks': [
            '小号/中号/大号组件均正确渲染，不越界不截断',
            '组件点击各区域（图标/文字/空白）行为符合预期',
            '系统主题（深色/浅色）与桌面背景下展示正常',
            '组件数据与 App 内保持一致，修改后同步刷新',
        ],
    },
    '空态/默认值': {
        'title': '{domain}-空态与默认值兜底',
        'desc': (
            '历史缺陷中该域有 {count} 条是「该展示的没展示 / 默认值不对 / 缺兜底」。'
            '需覆盖无数据、首次进入、数据被清理三类空态。'
        ),
        'checks': [
            '首次进入（无任何数据）时展示正确的空态或默认形象',
            '数据被清除/资源缺失时不应白屏或卡死',
            '解除关系、切换账号等状态变化后应回落到正确的默认态',
            '该展示的标识（红点/角标/新功能提示）应按条件出现与消失',
        ],
    },
    '账号/权限切换': {
        'title': '{domain}-账号切换与会员权限边界',
        'desc': (
            '历史缺陷中该域有 {count} 条是「切换账号后状态串了 / 会员过期仍可用 / 免费次数判断错」。'
            '需覆盖账号态与权益态的组合。'
        ),
        'checks': [
            '同一设备切换不同账号，不残留上一账号的数据与状态',
            '会员过期/降级后，付费功能应立即收紧',
            '免费次数耗尽、达到上限时的限制与提示正确',
            '未登录/未匹配等异常账号态下的入口与提示正确',
        ],
    },
    '动画与多媒体': {
        'title': '{domain}-动画播放完整性',
        'desc': (
            '历史缺陷中该域有 {count} 条与动画/预览相关（不播放、卡住、截断、偏移）。'
        ),
        'checks': [
            '进入页面后动画应自动播放且完整播放完毕',
            '动画不应卡在某一帧或无限加载',
            '图片/形象不应被截断或位置偏移',
            '资源未下载完成时的降级表现可接受',
        ],
    },
    '接口与埋点': {
        'title': '{domain}-接口调用时机与埋点完整性',
        'desc': (
            '历史缺陷中该域有 {count} 条是「接口重复调用 / 时机不对 / 埋点缺失」。'
        ),
        'checks': [
            '同一操作不应重复请求同一接口',
            '接口调用时机正确（前置条件未满足前不应调用）',
            '关键操作均上报埋点，参数与平台一致',
        ],
    },
    '状态回显/刷新': {
        'title': '{domain}-状态回显与刷新时机',
        'desc': (
            '历史缺陷中该域有 {count} 条是「改了但没刷新 / 重启后又回退」。'
        ),
        'checks': [
            '修改后立即回显新值，无需手动刷新',
            '杀进程重启后，数据仍为最新值',
            '从其他页面返回后，应重新拉取并展示最新数据',
        ],
    },
    '生成耗时/轮询': {
        'title': '{domain}-生成流程进度与异常兜底',
        'desc': (
            '历史缺陷中该域有 {count} 条是「生成进度卡住 / 轮询停止 / 失败无提示」。'
        ),
        'checks': [
            '生成过程进度可见且持续更新，不卡死',
            '生成失败时展示明确的失败态，可重试',
            '页面停留/切后台/杀进程后再进入，能续上生成结果',
        ],
    },
    '文案与需求一致性': {
        'title': '{domain}-文案与需求一致性',
        'desc': '历史缺陷中该域有 {count} 条为文案错误或与需求/原型不一致。',
        'checks': [
            '关键文案与需求文档逐字一致',
            '提示语、按钮文案、toast 内容符合规范',
            '中英文/符号无错别字与乱码',
        ],
    },
    '表单校验/边界': {
        'title': '{domain}-输入校验与边界值',
        'desc': '历史缺陷中该域有 {count} 条为输入校验或边界值处理不当。',
        'checks': [
            '空值、纯空格、超长、特殊字符均有正确校验与提示',
            '上下限边界值（最大值/最小值/临界值）处理正确',
            '校验失败时提示明确且不阻断正常流程',
        ],
    },
    '数据一致性': {
        'title': '{domain}-关联数据一致性',
        'desc': '历史缺陷中该域有 {count} 条为数据不一致、关联数据未联动。',
        'checks': [
            '同一数据在多处展示应一致',
            '关联数据（对方/统计/历史）应同步更新',
            '重复操作不应产生重复数据',
        ],
    },
    '进程与冷启动': {
        'title': '{domain}-冷启动与进程恢复',
        'desc': '历史缺陷中该域有 {count} 条与杀进程/冷启动/后台恢复相关。',
        'checks': [
            '杀进程后冷启动，页面与数据恢复正常',
            '从后台切回，不应停留在错误页面或旧状态',
            '卸载重装后，服务端数据应正确恢复',
        ],
    },
    '网络异常': {
        'title': '{domain}-弱网与失败重试',
        'desc': '历史缺陷中该域有 {count} 条为无响应/加载失败/下载失败。',
        'checks': [
            '断网或弱网时展示明确错误，不无限 loading',
            '网络恢复后可重试成功',
            '资源下载失败后可重新下载并生效',
        ],
    },
    '视觉还原度': {
        'title': '{domain}-视觉还原与样式一致性',
        'desc': (
            '历史缺陷中该域有 {count} 条为界面优化类（颜色/图标/尺寸/遮挡/对齐不符）。'
            '需按设计稿逐项比对。'
        ),
        'checks': [
            '与设计稿逐项比对：颜色、字号、间距、圆角、图标',
            '元素不被遮挡、不越界、不截断、不变形',
            '不同屏幕尺寸/分辨率下布局正常',
            '双端（iOS/Android）视觉表现一致',
        ],
    },
}


# 业务领域词典：用于「在标题里找词」，而不是把中文切碎。
#
# 为什么不用正则切词（2026-10-22 实测教训）：
#   中文没有分词器时按 2~5 字滑窗切，必然切出 `新形象生成成` / `心情罐子小组` /
#   `象后` / `上拉的默契问` 这类半截词，反而污染 prompt。
#   改为「词典匹配」后，抽出的词 100% 是完整业务词。
#
# 词典来源：对 mini2 全量 237 条标题做 n-gram doc-frequency 挖掘
#   （docs-freq >= 3 的 2~5 字片段），再人工筛掉「的样子 / 的时候 / 应该是」等
#   非业务片段。因此词表来自真实数据，不是凭印象编的。
#   —— 换产品时词表需要重新挖一次（本模块保留可复算的挖掘思路见文档）。
DOMAIN_VOCAB = (
    # —— 核心实体 ——
    '我的形象', '历史形象', '默认形象', '当前形象', '定制形象', '形象页', '形象生成',
    '新形象', '真人形象', '人物形象',
    '状态记录', '自定义状态', '添加状态', '状态设定页', '状态列表', '状态动画',
    '待机动画', '互动动画', '教学动画', '预览动画',
    '心情罐子', '想你', '默契问答', '小纸条', '人物状态', '桌面娃娃', '桌面小人',
    '个人信息', '个人中心', '授权管理', '解除匹配', '邀请匹配', '匹配码',
    '会员', '免费次数', '权益', '付费', '订阅',
    '头像', '昵称', '性别', '生日',
    '手机号', '验证码', '登录', '注销',
    # —— 载体 / 环境 ——
    '小组件', '大组件', '中号组件', '小号组件', '双人组件',
    '推送', '通知栏', '后台', '冷启动', '杀进程', '卸载重装',
    '接口', '埋点', '轮询', '进度',
    # —— 常见业务动作/对象 ——
    '照片', '相册', '生成失败', '生成成功', '重新生成', '重新下载', '资源文件',
    '红点', '角标', '弹窗', 'toast', '文案',
    '天数', '次数', '历史记录', '列表', '封面图',
)

# 英文/技术词单独匹配（大小写敏感度低）
DOMAIN_VOCAB_EN = (
    'iOS', 'Android', 'vip', 'VIP', 'mini', 'icon', 'push', 'toast', 'UI',
    'API', 'App', 'app',
)

# 词典里的「泛词」：虽然是业务词，但几乎每个测试点都会命中，提供不了区分度。
# 只在没有任何更具体词命中时才拿出来兜底。
GENERIC_VOCAB = {'mini', 'App', 'app', 'UI', '接口', '埋点', '弹窗', '文案', '列表'}


def extract_keywords(titles: List[str], top_n: int = 6) -> List[str]:
    """从缺陷标题里匹配业务关键词（词典匹配，不切词）。

    ⚠️ 这一步是「精准」的关键：模板化 checks（如"动画应完整播放"）不含业务信息，
    生成用例时 AI 不知道要测"待机动画"还是"预览动画"。

    策略：
      1. 按 DOMAIN_VOCAB 在标题里找词，统计「出现在多少条不同标题里」；
      2. 长的优先（`历史形象` 优于 `形象`），避免短词包含长词时重复；
      3. 泛词（GENERIC_VOCAB）只在没有具体词时兜底，保证关键词有区分度；
      4. 只保留出现在 >=2 条标题里的词，过滤一次性描述。

    Args:
        titles: 标题列表（同一测试点下的相关缺陷标题）
        top_n: 最多返回多少个关键词
    """
    if not titles:
        return []
    doc_freq = Counter()
    for raw in titles:
        body = strip_version_prefix(raw or '')
        body = re.sub(r'/[A-Za-z0-9_\-/?=&.]+', ' ', body)  # 接口路径不是业务词
        hit = set()
        for word in DOMAIN_VOCAB:
            if word in body:
                hit.add(word)
        lowered = body.lower()
        for word in DOMAIN_VOCAB_EN:
            if word.lower() in lowered:
                hit.add(word)
        for w in hit:
            doc_freq[w] += 1

    # 长词优先；被更长词完整包含的短词丢弃（有「历史形象」就不要只留「形象」）
    candidates = [(w, c) for w, c in doc_freq.items() if c >= 2]
    candidates.sort(key=lambda x: (-len(x[0]), -x[1]))

    specific, generic = [], []
    for word, count in candidates:
        if any(word != other and word in other for other, _ in candidates):
            continue
        (generic if word in GENERIC_VOCAB else specific).append(word)

    picked = specific[:top_n]
    if not picked:
        picked = generic[:top_n]
    return picked


def _build_rule_testpoints(domain_details: List[dict], items: List[dict]) -> List[dict]:
    """生成「可直接用于生成用例」的测试点。

    ⚠️ 产物定位（对齐需求初衷）：
    本函数产出的不是缺陷统计，而是**测试点**——
    每条都包含 title（测试什么）、description（为什么要测，基于多少条历史缺陷）、
    checks（验证要点，可直接转成用例步骤与预期）、
    keywords（业务关注点，来自历史缺陷标题的高频实词）。

    keywords 的作用：模板化 checks 只说明"测动画"，keywords 说明"测的是待机动画/
    预览动画/状态设定页"，两者结合才能生成精准用例。2026-10-22 用户明确指出
    纯模板产物不够精准，故补此栏。

    粒度：按「功能域 × 易漏维度」拆点，但过滤掉低频组合（阈值 MIN_TP_COUNT），
    避免产出上百条碎片；维度无模板时归入域级测试点。

    纯规则、可复算：每条测试点都能追溯到具体 bug_ids。
    """
    MIN_TP_COUNT = 2  # 某维度在该域少于 N 条时不单独成点，避免碎片
    # 缺陷数超过该阈值的域，允许拆出更多测试点；小域只保留最高的几个，避免碎片
    BIG_DOMAIN_THRESHOLD = 15

    by_domain = defaultdict(list)
    for i in items:
        by_domain[i['domain']].append(i)

    out = []
    for d in domain_details:
        domain = d['domain']
        rows = by_domain[domain]
        scene_counter = Counter()
        scene_bugs = defaultdict(list)
        scene_rows = defaultdict(list)
        for r in rows:
            for s in r['scenes']:
                scene_counter[s] += 1
                scene_bugs[s].append(r['bug_id'])
                scene_rows[s].append(r)

        # 大域最多拆 6 个测试点，小域最多 3 个：控制总量，避免"一次测 89 个维度"
        max_points = 6 if len(rows) >= BIG_DOMAIN_THRESHOLD else 3
        made = 0
        for scene, count in scene_counter.most_common():
            if count < MIN_TP_COUNT or made >= max_points:
                continue
            tpl = SCENE_TP_TEMPLATES.get(scene)
            if not tpl:
                continue
            bug_ids = scene_bugs[scene]
            related = scene_rows[scene]
            examples = [r['title'] for r in related][:3]
            keywords = extract_keywords([r['title'] for r in related])

            desc = tpl['desc'].format(domain=domain, count=count)
            if keywords:
                desc += f'业务关注点：{"、".join(keywords)}。'

            out.append({
                'tp_id': '',
                'domain': domain,
                'scene': scene,
                'title': tpl['title'].format(domain=domain),
                'description': desc,
                'checks': list(tpl['checks']),
                'keywords': keywords,
                'count': count,
                'ratio': _ratio(count, len(rows)),
                'examples': examples,
                'source_bug_ids': bug_ids[:30],
                'raw_domains': sorted({r.get('raw_domain') or '未分类' for r in rows})[:6],
                'source': 'rule',
            })
            made += 1

        # 域级兜底：该域没有形成任何集中维度时，至少给一条整体回归点
        if made == 0:
            keywords = extract_keywords([r['title'] for r in rows])
            out.append({
                'tp_id': '',
                'domain': domain,
                'scene': '',
                'title': f'{domain}-核心功能回归',
                'description': (
                    f'该域历史缺陷 {len(rows)} 条，未形成集中易漏模式，'
                    f'建议按功能整体回归。'
                    + (f'业务关注点：{"、".join(keywords)}。' if keywords else '')
                ),
                'checks': ['该域核心流程可正常走通', '关键数据展示与保存正确'],
                'keywords': keywords,
                'count': len(rows),
                'ratio': _ratio(len(rows), len(items)),
                'examples': [r['title'] for r in rows[:3]],
                'source_bug_ids': [r['bug_id'] for r in rows[:30]],
                'raw_domains': sorted({r.get('raw_domain') or '未分类' for r in rows})[:6],
                'source': 'rule',
            })

    # ------------------------------------------------------------------
    # 第二轮：跨域按 scene 合并补漏（2026-10-22）
    #
    # 问题：按页面环节拆域后，域的颗粒度变细，单域内的某维度常常只有 1 条缺陷，
    # 被 MIN_TP_COUNT 过滤掉 ⇒ 维度消失。
    # 实例：「结果页」域有 5 条缺陷但都不足 2 条同维度，最终只产出"核心功能回归"，
    # 而"结果页文案问题"实际散落在其它域里 ⇒ 需求只改结果页文案时找不到对应测试点。
    #
    # 做法：对**每个域都没能成点的维度**，跨域汇总后再判断一次；若跨域总量
    # 达到阈值，就生成一条「跨域测试点」，并在描述里标明涉及哪些域。
    # ------------------------------------------------------------------
    made_domains = {tp['domain'] for tp in out if tp.get('scene')}
    scene_global = defaultdict(lambda: {'count': 0, 'bugs': [], 'rows': [], 'domains': set()})
    for it in items:
        for s in it['scenes']:
            g = scene_global[s]
            g['count'] += 1
            g['bugs'].append(it['bug_id'])
            g['rows'].append(it)
            g['domains'].add(it['domain'])

    for scene, g in sorted(scene_global.items(), key=lambda x: -x[1]['count']):
        if g['count'] < MIN_TP_COUNT:
            continue
        tpl = SCENE_TP_TEMPLATES.get(scene)
        if not tpl:
            continue
        # 该维度已在某个域单独成点且覆盖了主要部分，就不重复出跨域点
        covered = sum(
            tp['count'] for tp in out if tp.get('scene') == scene
        )
        if covered >= g['count'] * 0.7:
            continue

        domains_involved = sorted(g['domains'])
        kw = extract_keywords([r['title'] for r in g['rows']])
        desc = (
            f'该维度在 {len(domains_involved)} 个功能域共出现 {g["count"]} 条缺陷'
            f'（{ "、".join(domains_involved[:5]) }），单域内未达阈值，故跨域合并。'
        )
        if kw:
            desc += f'业务关注点：{"、".join(kw)}。'
        out.append({
            'tp_id': '',
            'domain': CROSS_DOMAIN_LABEL,
            'scene': scene,
            'title': tpl['title'].format(domain='（跨域）'),
            'description': desc,
            'checks': list(tpl['checks']),
            'keywords': kw,
            'count': g['count'],
            'ratio': _ratio(g['count'], len(items)),
            'examples': [r['title'] for r in g['rows'][:3]],
            'source_bug_ids': g['bugs'][:30],
            'raw_domains': domains_involved[:6],
            'source': 'rule_cross_domain',
        })

    # 排序：缺陷多的点优先（先补高频漏测区），同级按域聚合展示
    out.sort(key=lambda x: (-x['count'], x['domain']))
    for idx, tp in enumerate(out, 1):
        tp['tp_id'] = 'TP-%03d' % idx
    return out


# 注入详略档位：控制 prompt 预算（2026-10-22 实测产品13/20 条测试点的体量）
#   brief    title + 关键词                          ≈  800 字符
#   standard title + 关键词 + 验证要点                ≈ 1600 字符（默认）
#   full     standard + 2 条历史缺陷示例              ≈ 2600 字符
DETAIL_LEVELS = ('brief', 'standard', 'full')
DEFAULT_DETAIL_LEVEL = 'standard'

# ---------------------------------------------------------------------------
# 变更意图识别 + 维度加权（2026-10-22 用户提出的关键问题）
#
# 问题：「新版本只改一个小功能，但该模块历史上 bug 多，会不会生成一堆没价值的用例？」
# 用户明确指出：**前提还是按当前迭代版本的需求重点考虑**，历史缺陷数量 ≠ 本次重点。
#
# 做法：
#   1. 从需求文本识别「变更意图」（改文案 / 加入口 / 调动画 / 修适配…）
#   2. 测试点按 scene 与变更意图匹配程度加权：
#        匹配 → 1.0 ；同域异类 → 0.3 ；仅同域兜底 → 0.1
#   3. 加权后排序取前 N，让小改动只注入少量精准测试点
# ---------------------------------------------------------------------------

# 变更意图 → 触发词 + 对应的测试点 scene
CHANGE_INTENTS = (
    ('文案', ('文案', '提示语', '文字', '错别字', '标题', '措辞', 'toast', '话术'),
     ('文案与需求一致性',)),
    ('入口与跳转', ('入口', '跳转', '点击', '打开', '进入', '返回', '按钮', '路由'),
     ('入口/跳转路由',)),
    ('动画与展示', ('动画', '播放', '预览', '音效', '音乐', '视频', '展示效果'),
     ('动画与多媒体',)),
    ('视觉与样式', ('样式', '颜色', '图标', 'icon', 'UI', '排版', '间距', '对齐',
              '设计稿', '视觉'),
     ('视觉还原度',)),
    ('适配与端', ('适配', '屏幕', '机型', 'iOS', '安卓', '双端', '鸿蒙', '分辨率'),
     ('跨端/多设备', '视觉还原度')),
    ('权限与会员', ('权限', '会员', 'vip', 'VIP', '付费', '订阅', '权益', '免费次数'),
     ('账号/权限切换',)),
    ('数据与状态', ('数据', '状态', '刷新', '回显', '同步', '保存', '缓存', '重置'),
     ('状态回显/刷新', '数据一致性')),
    ('生成与流程', ('生成', '进度', '轮询', '上传', '提交', '流程', '步骤'),
     ('生成耗时/轮询', '进程与冷启动')),
    ('校验与边界', ('校验', '限制', '上限', '边界', '输入', '超长', '必填'),
     ('表单校验/边界',)),
    ('接口与埋点', ('接口', '埋点', '上报', '请求', '日志'),
     ('接口与埋点',)),
    ('组件与环境', ('小组件', '组件', '桌面', '通知', '推送', '后台'),
     ('组件/外部环境',)),
    ('网络异常', ('网络', '超时', '断网', '失败重试', '加载失败'),
     ('网络异常',)),
)

# 规模判断：需求里出现这些词说明是大范围改动
LARGE_CHANGE_HINTS = (
    '整体', '全面', '重构', '大改', '全新', '升级改造', '新增模块', '新增功能',
    '改版', '重做', '多个页面', '所有', '批量',
)
# 小范围改动的暗示词
SMALL_CHANGE_HINTS = (
    '文案', '文字', '错别字', '措辞', '颜色', '图标', 'icon', '间距',
    '一个字', '措辞修改', '提示语', '标题',
)

# 规模 → 建议注入条数上限
SCALE_MAX_POINTS = {'small': 5, 'medium': 12, 'large': 20}


def detect_change_intent(requirement_text: str) -> dict:
    """从需求文本识别「变更意图」与「改动规模」。

    这是回答"小改动却被历史缺陷带偏"的核心：只有识别出本次改的是什么类型，
    才能把同域但无关的测试点降权，避免"改了文案却生成一堆动画用例"。

    Returns:
        {
          'intents': ['文案', ...],          # 命中的变更意图（按命中词数降序）
          'scenes': {'文案与需求一致性', ...},# 对应应重点覆盖的测试点 scene
          'scale': 'small'|'medium'|'large',
          'scale_reason': str,
          'suggested_max_points': int,
        }
    """
    text = requirement_text or ''
    if not text.strip():
        return {
            'intents': [], 'scenes': set(), 'scale': 'medium',
            'scale_reason': '未提供需求文本，无法判断改动规模，按中等处理',
            'suggested_max_points': SCALE_MAX_POINTS['medium'],
        }

    hits = []
    scenes = set()
    for name, keywords, scene_names in CHANGE_INTENTS:
        n = sum(1 for k in keywords if k in text)
        if n:
            hits.append((n, name))
            scenes.update(scene_names)
    hits.sort(key=lambda x: -x[0])
    intents = [name for _n, name in hits]

    # 规模判断：长度 + 暗示词 + 命中意图数量
    large_hit = [w for w in LARGE_CHANGE_HINTS if w in text]
    small_hit = [w for w in SMALL_CHANGE_HINTS if w in text]
    length = len(text)

    if large_hit:
        scale = 'large'
        reason = f'需求含大范围改动表述（{"、".join(large_hit[:3])}）'
    elif length >= 1500 and len(intents) >= 3:
        scale = 'large'
        reason = f'需求较长（{length} 字）且涉及 {len(intents)} 类改动'
    elif small_hit and len(intents) <= 2 and length < 800:
        scale = 'small'
        reason = f'需求聚焦（{"、".join(small_hit[:2])}），涉及 {len(intents)} 类改动'
    else:
        scale = 'medium'
        reason = f'需求长度 {length} 字，涉及 {len(intents)} 类改动'

    return {
        'intents': intents,
        'scenes': scenes,
        'scale': scale,
        'scale_reason': reason,
        'suggested_max_points': SCALE_MAX_POINTS[scale],
    }


def score_testpoint(tp: dict, intent: dict) -> float:
    """按「变更意图匹配度」给测试点打分，用于排序与截断。

    权重设计（2026-10-22 用户要求"按当前迭代重点"）：
      1.0 —— 测试点的 scene 与本次变更意图匹配（改文案 → 文案类测试点）
      0.3 —— 同域但类型不同（改文案 → 该域的动画测试点）
      0.1 —— 兜底类测试点（无 scene）
    最终分 = 历史缺陷数 × 权重，保证"再多的历史问题，只要和本次无关也排后面"。
    """
    base = tp.get('count', 0) or 1
    scene = tp.get('scene') or ''
    if not scene:
        return base * 0.1
    if intent.get('scenes') and scene in intent['scenes']:
        return base * 1.0
    return base * 0.3


def build_testpoint_prompt_block(
    testpoints: List[dict],
    domains: Optional[List[str]] = None,
    max_points: int = 20,
    max_examples: int = 2,
    detail_level: str = DEFAULT_DETAIL_LEVEL,
    requirement_text: str = '',
    change_scale: str = '',
) -> str:
    """把测试点拼成可直接注入用例生成 prompt 的文本块（只要文本时的便捷入口）。"""
    return build_testpoint_prompt_block_with_meta(
        testpoints,
        domains=domains,
        max_points=max_points,
        max_examples=max_examples,
        detail_level=detail_level,
        requirement_text=requirement_text,
        change_scale=change_scale,
    )[0]


def build_testpoint_prompt_block_with_meta(
    testpoints: List[dict],
    domains: Optional[List[str]] = None,
    max_points: int = 20,
    max_examples: int = 2,
    detail_level: str = DEFAULT_DETAIL_LEVEL,
    requirement_text: str = '',
    change_scale: str = '',
):
    """同 build_testpoint_prompt_block，但同时返回**实际进入 prompt 的条目**。

    返回 (block_text, meta)：
      meta = {
        'items': [{'domain','scene','title','count'}, ...],  # 真正注入的那几条
        'intents': [...], 'scale': 'small/medium/large',
        'effective_max': int, 'testpoint_total': int, 'detail_level': str,
      }

    为什么要返回条目：生成侧只把「注入了 N 条、多少字符」写日志，用户无法知道
    具体命中哪几条历史测试点（2026-10-23 用户提出）。审计信息必须落库，
    且**不能另写一套筛选逻辑**，否则审计结果与实际注入会不一致。
    把测试点拼成可直接注入用例生成 prompt 的文本块。

    这是「历史测试点 → 新版本精准用例」的落地出口。

    ⚠️ 四条硬约束（都来自实测/用户反馈）：
      1. **按功能域筛选**：产品可能沉淀 60+ 测试点，全量注入会到 12000+ 字符且大量
         无关，稀释模型注意力。默认 max_points=20。
      2. **按变更意图加权**（2026-10-22 用户提出）：历史缺陷多 ≠ 本次重点。
         需求只改文案时，同域的动画/跳转测试点必须降权，否则会生成一堆无价值用例。
      3. **名额按域轮转**：纯按缺陷数降序会让大域吃满名额，小域一条都进不去。
      4. **详略可选**：detail_level ∈ {brief, standard, full}，控制 prompt 预算。

    Args:
        requirement_text: 本次迭代的需求文本，用于识别变更意图；为空则不做意图加权
        change_scale: 人工指定的改动规模（small/medium/large），优先于自动判断
    """
    empty_meta = {
        'items': [], 'intents': [], 'scale': '', 'effective_max': 0,
        'testpoint_total': len(testpoints or []), 'detail_level': detail_level,
    }
    if not testpoints:
        return '', empty_meta
    if detail_level not in DETAIL_LEVELS:
        detail_level = DEFAULT_DETAIL_LEVEL

    pool = testpoints
    filtered = False
    if domains:
        wanted = {d.strip() for d in domains if d and d.strip()}
        # 「跨域通用」不参与需求匹配，但确实是本产品跨模块的高发易漏点。
        # ⚠️ 不能无条件全带上：实测「跳转到分享页」会把 5 条跨域测试点
        # （关联数据/弱网/组件/动画）全部塞进来，把"按域精准筛选"直接冲淡。
        # 只在它的 scene 与本次变更意图匹配时才纳入。
        intent_scenes = detect_change_intent(requirement_text).get('scenes') or set()
        scoped = [
            tp for tp in testpoints
            if tp.get('domain') in wanted
            or (
                tp.get('domain') == CROSS_DOMAIN_LABEL
                and tp.get('scene') in intent_scenes
            )
        ]
        if scoped:
            pool = scoped
            filtered = True

    # 变更意图识别：自动判断 + 人工覆盖规模
    intent = detect_change_intent(requirement_text)
    if change_scale in SCALE_MAX_POINTS:
        scale_cn = {'small': '小', 'medium': '中', 'large': '大'}[change_scale]
        intent['scale'] = change_scale
        intent['scale_reason'] = f'人工指定为{scale_cn}范围改动'
        intent['suggested_max_points'] = SCALE_MAX_POINTS[change_scale]
    # 未显式指定条数时，按规模自动收敛（小改动不需要 20 条）
    effective_max = min(max_points, intent['suggested_max_points']) if intent['intents'] else max_points

    # ⚠️ 意图筛选**不能挂在 `len(pool) > effective_max` 下面**：
    # 实测「只改结果页文案」筛完只剩 3 条（< 名额 5），于是整段跳过意图过滤，
    # 把视觉还原/双端一致性也一起注入了 —— 与"小改动只取精确匹配"的初衷相反。
    # 过滤是语义问题，不是容量问题，必须独立判断。
    scored = sorted(pool, key=lambda tp: -score_testpoint(tp, intent))
    if intent['intents'] and intent['scale'] == 'small':
        # 小改动：**只保留意图精确匹配的测试点**。
        # 实测踩过两次——"只改结果页文案"先是被"每域保底 1 条"塞进无关域，
        # 修完又因为"同域异类权重 0.3 仍过线"塞进关联数据/双端一致性/视觉还原。
        # 用户明确指出：历史缺陷多 ≠ 本次重点。故小改动只取精确匹配，
        # 名额有剩时最多再补 1 条同域参考，绝不铺开。
        exact = [tp for tp in scored if intent['scenes'] and tp.get('scene') in intent['scenes']]
        if exact:
            pool = exact[:effective_max]
        else:
            pool = scored[:min(effective_max, 3)]
    elif len(pool) > effective_max:
        if intent['intents']:
            # 中/大改动：保留意图匹配 + 同域异类，兜底类仅在名额有剩时补
            primary = [tp for tp in scored
                       if score_testpoint(tp, intent) >= (tp.get('count', 1) or 1) * 0.3]
            fallback = [tp for tp in scored if tp not in primary]
            pool = (primary + fallback)[:effective_max]
        else:
            # 无意图（未提供需求文本）：退回按域轮转，保证各域都有代表
            bucket = {}
            for tp in scored:
                bucket.setdefault(tp.get('domain') or '', []).append(tp)
            domain_order = sorted(
                bucket.keys(),
                key=lambda d: -max(score_testpoint(t, intent) for t in bucket[d]),
            )
            picked, round_idx = [], 0
            while len(picked) < effective_max:
                added = False
                for d in domain_order:
                    if round_idx < len(bucket[d]):
                        picked.append(bucket[d][round_idx])
                        added = True
                        if len(picked) >= effective_max:
                            break
                if not added:
                    break
                round_idx += 1
            pool = picked
    else:
        pool = pool[:effective_max]

    lines = ['【历史缺陷复盘测试点（务必覆盖，这些是本产品历史上真实踩过的坑）】']
    meta_bits = []
    if filtered:
        meta_bits.append(
            f'已按功能域筛选：{"、".join(sorted({tp.get("domain", "") for tp in pool}))}'
        )
    if intent['intents']:
        meta_bits.append(f'本次变更类型：{"、".join(intent["intents"][:4])}')
        meta_bits.append(f'改动规模：{intent["scale"]}')
    if meta_bits:
        lines.append(f'（{"；".join(meta_bits)}）')
    elif len(testpoints) > effective_max:
        lines.append(f'（共沉淀 {len(testpoints)} 个测试点，此处仅列最相关的 {len(pool)} 个）')

    # 小改动时明确约束 AI 别铺开：这是"按本次迭代重点"的关键提示
    if intent['intents'] and intent['scale'] == 'small':
        lines.append(
            f'注意：本次仅涉及「{"、".join(intent["intents"][:3])}」类改动，'
            '请勿扩展生成与本类改动无关的用例（如动画、适配、权限等），'
            '围绕上述测试点做深度覆盖即可。'
        )

    for tp in pool:
        if detail_level == 'brief':
            kw = tp.get('keywords') or []
            suffix = f'｜关注：{"、".join(kw)}' if kw else ''
            lines.append(f'- {tp.get("title", "")}{suffix}')
            continue

        lines.append(f'- {tp.get("title", "")}（历史 {tp.get("count", 0)} 条缺陷）')
        kw = tp.get('keywords') or []
        if kw:
            lines.append(f'  业务关注点：{"、".join(kw)}')
        for c in (tp.get('checks') or [])[:4]:
            lines.append(f'  · {c}')
        if detail_level == 'full':
            examples = (tp.get('examples') or [])[:max_examples]
            if examples:
                lines.append('  历史缺陷示例：' + ' / '.join(e[:60] for e in examples))

    if detail_level == 'brief':
        lines.append('要求：生成的用例必须覆盖以上历史易漏点，围绕"关注"设计具体场景。')
    elif detail_level == 'full':
        lines.append(
            '要求：生成的用例必须覆盖以上测试点，并围绕"业务关注点"和"历史缺陷示例"'
            '设计具体场景与预期，不要只写通用描述。'
        )
    else:
        lines.append(
            '要求：生成的用例必须覆盖以上测试点，并围绕"业务关注点"设计具体场景与预期，'
            '不要只写通用描述。'
        )

    # 实际进入 prompt 的条目快照：供生成侧落库做审计（用户可查「这次到底用了哪几条」）
    items = [
        {
            'domain': tp.get('domain') or '',
            'scene': tp.get('scene') or '',
            'title': tp.get('title') or '',
            'count': int(tp.get('count') or 0),
        }
        for tp in pool
    ]
    meta = {
        'items': items,
        'intents': list(intent.get('intents') or []),
        'scale': intent.get('scale') or '',
        'effective_max': effective_max,
        'testpoint_total': len(testpoints),
        'detail_level': detail_level,
    }
    return '\n'.join(lines), meta


def estimate_prompt_tokens(text: str) -> int:
    """粗估 token 数（中文约 1 字 ≈ 1 token，另按 0.25 计入标点/换行开销）。"""
    if not text:
        return 0
    return int(len(text) * 1.1)


# ---------------------------------------------------------------------------
# 相关性闸门（2026-10-22 与用户确认：严格模式）
#
# 背景：方案 A 只解决了"不关联就不注入"，但实测「关联了复盘报告 + 需求完全无关
# （如"仅调整后端日志格式"）」时仍注入了 1247 字符 —— 这正是用户最担心的
# "历史缺陷带偏本次生成"。
#
# 严格模式原则：**宁可不注入，也不注入无关测试点**。
#   - 命中任一需求功能域           → 注入（按域筛选）
#   - 命中任一变更意图测试点 scene → 注入（按意图加权）
#   - 两者都无                     → 返回 ''，并在日志/预览里给出明确原因
# 不再使用"筛不到就退回全量"的宽松兜底。
# ---------------------------------------------------------------------------

# 与历史缺陷体系无关的强信号（命中即判无关，优先于其它判断）。
# 这些词本身也是 CHANGE_INTENTS 的触发词，必须显式排除，否则
# "仅调整后端日志格式"会因命中「接口与埋点-日志」意图而被判为相关。
IRRELEVANT_HINTS = (
    '后端日志', '日志格式', '日志级别', '日志切分', '打点格式',
    '数据库索引', '库表结构', '慢查询', '定时任务调度', '运维脚本', '服务器配置',
)

# 严格模式下的意图最小证据强度：
# 至少命中 1 个关键词，且意图对应的 scene 必须真实存在于测试点池中。
RELEVANCE_MODES = ('strict', 'loose')
DEFAULT_RELEVANCE_MODE = 'strict'


def assess_defect_relevance(
    requirement_text: str,
    testpoints: List[dict],
    mode: str = DEFAULT_RELEVANCE_MODE,
) -> dict:
    """判断本次需求与历史缺陷体系是否相关，决定"要不要注入"。

    Args:
        requirement_text: 本次迭代需求文本
        testpoints: 复盘报告的全量测试点（不要传已勾选收窄后的池）
        mode: 'strict'（默认，与用户确认）/ 'loose'（兼容旧的兜底行为）

    Returns:
        {
          'relevant': bool,
          'reason': str,            # 人类可读结论，用于前端提示与日志
          'matched_domains': [...], # 需求提到的功能域
          'matched_intents': [...], # 命中的变更意图
          'matched_scenes': [...],  # 与意图对应且确实存在于池中的 scene
          'irrelevant_hits': [...], # 命中"无关信号"的词
          'mode': str,
        }
    """
    text = (requirement_text or '').strip()
    tps = testpoints or []
    result = {
        'relevant': False,
        'reason': '',
        'matched_domains': [],
        'matched_intents': [],
        'matched_scenes': [],
        'irrelevant_hits': [],
        'mode': mode,
    }
    if not text:
        result['reason'] = '未提供需求文本，无法判断相关性，按严格模式不注入'
        return result
    if not tps:
        result['reason'] = '复盘报告没有测试点，不注入'
        return result

    irrelevant = [w for w in IRRELEVANT_HINTS if w in text]
    result['irrelevant_hits'] = irrelevant

    domains = suggest_domains_for_requirement(text, tps)
    intent = detect_change_intent(text)
    intents = list(intent.get('intents') or [])

    # 意图命中必须落到"池里真实存在的 scene"上，否则该意图没有可注入的落点
    pool_scenes = {tp.get('scene') for tp in tps if tp.get('scene')}
    matched_scenes = sorted((intent.get('scenes') or set()) & pool_scenes)

    result['matched_domains'] = domains
    result['matched_intents'] = intents
    result['matched_scenes'] = matched_scenes

    if mode == 'loose':
        result['relevant'] = True
        result['reason'] = '宽松模式：关联了复盘报告即注入'
        return result

    # 严格模式：命中无关信号直接否决（"仅调整后端日志格式"这类）
    if irrelevant:
        result['reason'] = (
            f'需求命中与历史缺陷体系无关的信号（{"、".join(irrelevant[:3])}），'
            '严格模式下不注入，避免历史缺陷带偏本次生成'
        )
        return result

    if domains:
        result['relevant'] = True
        result['reason'] = f'命中功能域：{"、".join(domains[:4])}'
        return result

    # 命中变更意图但池里没有对应 scene：说明**需求本身属于本产品的业务范畴**
    # （如"分享入口"是本产品的真实功能），只是这份复盘报告恰好没沉淀该类型测试点。
    # 此时若直接不注入，会把"报告数据不全"误判成"需求无关"（2026-10-22 实测踩到：
    # 「在首页新增分享入口按钮」被判无关）。故用**无落点意图**作为弱相关放行，
    # 并按 domain/intent 双空 → 才判无关 的严格口径。
    if intents:
        result['relevant'] = True
        result['reason'] = (
            f'命中本产品业务范畴的变更类型（{"、".join(intents[:3])}），'
            '但本次复盘报告未沉淀该类型测试点，注入内容可能偏少'
        )
        return result

    result['reason'] = '需求既未命中复盘报告的任何功能域，也未命中任何变更意图，严格模式下不注入'
    return result


def scope_by_relevance(
    pool: List[dict], relevance: dict, default_max_points: int = 20
) -> tuple:
    """按相关性结论收窄「待注入测试点 + 名额」。

    这是注入侧与预览侧**必须共用**的唯一实现（2026-10-22 实测踩到：
    两边各写一份 → 预览 used=20/1247 字符、真实注入 3 条/467 字符，
    用户看到"预览和生成不一致"的黑盒落差）。

    规则：
      - 强相关（命中功能域）：全部交给 `build_testpoint_prompt_block` 按域筛选，
        名额用默认值。
      - 弱相关（仅命中变更意图、无功能域）：只取与命中意图同 scene 的测试点，
        名额收到 8；同 scene 一条都没有才退回 3 条高频兜底。
        没有域圈定范围时若仍给 20 条，等于注入全量（实测 1247 字符）。

    Returns:
        (scoped_pool, max_points)
    """
    if not relevance.get('relevant'):
        return [], 0
    if relevance.get('matched_domains'):
        # 强相关：由 `build_testpoint_prompt_block` 按 domains 过滤（见其内部
        # 对 CROSS_DOMAIN_LABEL 的补充放行），名额用默认值。
        return pool, default_max_points

    scenes = set(relevance.get('matched_scenes') or [])
    if scenes:
        hit = [tp for tp in pool if tp.get('scene') in scenes]
        if hit:
            return hit, 8
    # 弱相关且无同类落点：仅给极少量高频兜底，避免整块注入
    return list(pool), 3


def suggest_domains_for_requirement(
    text: str, testpoints: List[dict], top_n: int = 6
) -> List[str]:
    """根据需求文本自动推荐相关功能域（用于注入时筛选测试点）。

    纯字符串匹配：需求里提到"形象""状态记录"就带上对应域。
    命中为 0 时返回空列表，由调用方决定是否让用户手选——不猜测，不硬塞。

    ⚠️ 只接受**看起来像功能域**的名字：早期版本生成的报告里沉淀过
    「iOS提醒列表只」「排行榜的分数算的」这类由标题截断产生的假域名，
    若放行会让"需求里恰好出现这些字"就误判为强相关。故此处复用
    `db_reader._looks_like_domain` 再过滤一次（报告数据无法回溯修复，
    只能在消费侧防御）。

    ⚠️⚠️ **不使用 `raw_domains` 做匹配**（2026-10-22 实测踩到，代价很大）：
    `raw_domains` 记录的是"该域内所有缺陷的原始前缀集合"，它并不受域边界约束——
    实测「结果页」域的 raw 里混进了 `分享页`、「过程页」域的 raw 里混进了 `首页`。
    一旦拿 raw 去匹配需求，说一句"跳转到分享页"就会把「结果页」「过程页」「首页」
    同时点亮，注入量从 467 暴涨到 1501 字符，还会带出一堆无关的视觉/动画测试点。
    ⇒ 严格模式下**只认域名词本身**。宁可少命中（弱相关兜底会保住基础覆盖），
      也不能因为一个词把半个产品的历史缺陷全拉进来。
    """
    if not text or not testpoints:
        return []

    all_domains = sorted({tp.get('domain') for tp in testpoints if tp.get('domain')})
    hits = []
    for domain in all_domains:
        # ⚠️ 「跨域通用」是聚合出来的补充维度，其 raw_domains 收纳了多个真实域名，
        # 若参与匹配，需求提到任一真实域都会把整组跨域测试点一并拉进来。
        # 它应当只在"按域筛选已经圈定范围"之后作为补充存在，不参与需求匹配。
        if domain == CROSS_DOMAIN_LABEL:
            continue
        if not _looks_like_domain(domain):
            continue
        # 只认域名词本身命中（如"状态记录""心情罐子""分享页"）
        if domain in text:
            hits.append(domain)
    return hits[:top_n]


def _build_notes(stats: dict) -> List[str]:
    notes = []
    funnel = stats.get('funnel') or {}
    resolutions = funnel.get('resolutions') or []
    excluded_types = funnel.get('exclude_types') or []

    res_text = '、'.join(resolutions) if resolutions else '全部'
    type_text = ('已排除 ' + '、'.join(excluded_types)) if excluded_types else '未排除任何类型'
    notes.append(
        '口径：统计 status∈{resolved,closed} 且 resolution∈{%s} 的缺陷，%s。'
        % (res_text, type_text)
    )
    if funnel.get('all_rows') is not None:
        notes.append(
            '数量漏斗：禅道该产品全部 %s 条 → 剔除已删除 %s 条后 %s 条 → '
            '已闭环 %s 条 → resolution 命中 %s 条 → 排除类型后纳入复盘 %s 条。'
            % (
                funnel.get('all_rows'), funnel.get('excluded_deleted'),
                funnel.get('alive'), funnel.get('closed'),
                funnel.get('resolution_matched'), funnel.get('final'),
            )
        )
    if stats['text_step_ratio'] < 30:
        notes.append(
            f"仅 {stats['text_step_ratio']}% 的缺陷有可读的复现文字（其余内容在截图里），"
            '本版按方案 A 只用标题 + 非空文字，测试点基于标题提炼。'
        )
    if stats['scene_match_ratio'] < 60:
        notes.append(
            f"规则识别到易漏维度的缺陷占 {stats['scene_match_ratio']}%，"
            f"未识别 {stats['scene_unmatched']} 条已归入所属功能域的兜底测试点。"
        )
    if stats['domain_count'] > 25:
        notes.append(
            f'功能域共 {stats["domain_count"]} 个，较分散；'
            '如需更聚合的归类，可开启 LLM 归并（会调用模型并产生费用）。'
        )
    return notes


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _ratio(part: int, total: int) -> float:
    if not total:
        return 0.0
    return round(part * 100.0 / total, 1)


def _counter_rows(counter: Counter, total: int) -> List[dict]:
    return [
        {'name': k, 'count': v, 'ratio': _ratio(v, total)}
        for k, v in counter.most_common()
    ]


def _fmt_date(value) -> str:
    if not value:
        return ''
    try:
        return value.strftime('%Y-%m-%d')
    except Exception:
        return str(value)[:10]


def _date_range(items: List[dict]) -> dict:
    dates = sorted(i['opened_date'] for i in items if i.get('opened_date'))
    if not dates:
        return {'from': '', 'to': ''}
    return {'from': dates[0], 'to': dates[-1]}
