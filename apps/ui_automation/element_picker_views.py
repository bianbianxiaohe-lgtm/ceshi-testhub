"""
元素拾取器：从设备抓元素 → 展示 → 一键存入元素库（阶段一 + 阶段二）。

设计动机（2026-09-21）：
  之前 iOS 用例只能靠"填一句自然语言描述 → 跑 → 失败 → 查日志"来试错，
  每套用例都要重新调一遍，成本极高。而项目里 Android 早已有元素 dump 能力
  （`smart_locator.dump_page_elements`）与"定位失败自动回写元素库"
  （`appium_engine._auto_learn_find` + `_update_element_locator`）——
  **iOS 两者都没有**。

  本模块提供：
    1. `dump-elements`    —— 抓设备当前页面元素（平台无关，见 element_provider）
    2. `save-elements`    —— 把选中的元素批量存入 `Element` 元素库（按平台区分）
    3. `learn-locator`    —— 阶段二：定位失败时重新 dump、自动修正并回写元素库
                            （对标 Android 的 _auto_learn_find / _update_element_locator）

  ⚠️ 元素库是**可复用资产**：拾取一次，多套用例/多次执行都能用；
     而"每步写一句自然语言描述"是**一次性劳动**。这是成本能降下来的关键。
"""
import logging
import re

from django.db import transaction
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .element_provider import dump_elements
from .models import (
    AppConfig, AppDevice, Element, ElementGroup, LocatorStrategy, UiProject,
)

logger = logging.getLogger(__name__)


def _resolve_device_project(device, requested_project_id=None):
    """元素必须挂在某个项目下（Element.project 非空）。

    优先用请求显式指定的项目；否则取"该设备上已有元素所属的项目"；
    再否则放弃（由调用方报错让用户选项目）。
    """
    if requested_project_id:
        return requested_project_id
    existing = (Element.objects
                .filter(project__isnull=False)
                .order_by('-id')
                .values_list('project_id', flat=True)
                .first())
    return existing


def parse_project_id(value):
    """把前端传来的各种项目 id 形态归一化成 `UiProject.id`（整数）。

    ⚠️ 这是**必需的防御**，不是锦上添花：前端项目选择器用的是"统一项目源"
    （`/api/ui-automation/all-projects/`），id 形态有三种：
      - `ui_9`   / `ui_9`（UI 自动化项目，`ui_` 前缀）
      - `proj_2` （AI 用例生成项目，`proj_` 前缀，**根本不属于 UiProject 表**）
      - `9`      （裸数字，老页面/接口直调）
    直接把 `ui_9` 当外键查询会抛
    `ValueError: Field 'id' expected a number but got 'ui_9'` → **接口 500**。
    （实测：用例编辑器传的就是统一 id，dev 用真实 id 测所以没暴露。）

    Returns:
        (project_id:int|None, error:str)
        error 非空表示这个 id 无法对应到 UiProject（如 proj_ 前缀的 AI 项目）。
    """
    if value is None or value == '':
        return None, '缺少 project_id'
    if isinstance(value, int):
        return (value, '') if value > 0 else (None, 'project_id 不合法: %s' % value)

    s = str(value).strip()
    # 去掉可能的前缀：ui_9 / proj_2 -> 9 / 2
    m = re.match(r'^(?:ui|proj)_(\d+)$', s, re.I)
    if m:
        pid = int(m.group(1))
        if s.lower().startswith('proj_'):
            # AI 用例生成项目在 apps.projects.Project，不是 UiProject，
            # 元素库挂在 UiProject 下，所以这种 id 必须明确报错而不是硬查。
            return None, ('「%s」是 AI 用例生成项目，元素库只支持 UI 自动化项目。'
                          '请在「UI自动化 → 项目管理」里选择/创建一个 UI 项目'
                          % s)
        return pid, ''

    if s.isdigit():
        return int(s), ''

    return None, 'project_id 无法识别: %s' % s


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def dump_device_elements(request):
    """抓取设备当前页面的可交互元素（平台无关）。

    请求体：
        {
          "device_id": 7,
          "app_config_id": 3,        # 可选：Android 需要它来 activate_app
          "only_clickable": false,   # 可选：只看可点元素
          "keyword": "日记",          # 可选：按文案过滤（前端搜索）
          "include_unportable": false # 可选：是否包含坐标类元素（默认排除，见下）
        }
    返回：
        {
          "platform": "ios", "count": 230,
          "elements": [ {name,strategy,value,text,class_name,clickable,bounds,center_x,center_y,rect}, ... ],
          "excluded_unportable": 12,  # 被排除的坐标类元素个数（让用户知道有这东西）
          "error": null
        }

    ⚠️ **默认排除坐标类元素**（`strategy=coordinate` / 纯数字值）：
    它们的定位值换设备就失效，写进用例必然错位，引擎护栏也会把它拦成 failed。
    排除掉可以从源头避免"抓了一堆、存了一堆、用的时候才发现不能用"。
    但仍返回 `excluded_unportable` 计数，让用户知道"这里有元素，只是不可跨设备"，
    而不是以为拾取器漏抓了。
    """
    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': '缺少 device_id'}, status=400)

    device = AppDevice.objects.filter(id=device_id).first()
    if not device:
        return Response({'error': '设备不存在'}, status=404)

    app_config = None
    app_config_id = request.data.get('app_config_id')
    if app_config_id:
        app_config = AppConfig.objects.filter(id=app_config_id).first()
    if app_config is None and device.platform == 'android':
        # Android 建会话需要 package/activity，缺了会连不上
        app_config = AppConfig.objects.filter(platform='android').first()

    result = dump_elements(device, app_config)

    elements = result.get('elements') or []
    if request.data.get('only_clickable'):
        elements = [e for e in elements if e.get('clickable')]

    # 标注每个元素能否跨设备，并默认剔除不能用的（坐标类）
    for e in elements:
        portable, why = _is_portable(e)
        e['cross_device'] = portable
        if not portable:
            e['unusable_reason'] = why
    if not request.data.get('include_unportable'):
        excluded = [e for e in elements if not e['cross_device']]
        elements = [e for e in elements if e['cross_device']]
        result['excluded_unportable'] = len(excluded)
        if excluded:
            result['excluded_note'] = (
                '已排除 %d 个仅坐标可定位的元素（换设备会错位，不能写进用例）；'
                '若该元素确实没有文字/控件标识，可用断言兜底或改用视觉定位'
                % len(excluded))

    keyword = (request.data.get('keyword') or '').strip()
    if keyword:
        kw = keyword.lower()
        elements = [e for e in elements
                    if kw in (e.get('name') or '').lower()
                    or kw in (e.get('text') or '').lower()]

    result['elements'] = elements
    result['count'] = len(elements)
    result['filtered'] = bool(request.data.get('only_clickable') or keyword)
    return Response(result)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def save_picked_elements(request):
    """把拾取到的元素批量存入元素库（按平台区分，同名同平台则更新）。

    请求体：
        {
          "project_id": 1,
          "platform": "ios",
          "page": "日记本",              # 可选，便于分组管理
          "device_id": 7,               # 可选，仅用于记录来源
          "elements": [ {"name","strategy","value","text","center_x","center_y"} ]
        }
    返回：{created: n, updated: n, elements: [...]}

    设计要点：
      - `Element.platform` 区分平台：同一个业务元素在 iOS/Android 的 locator 不同。
      - 去重键 = (project, platform, name)：重复拾取同一元素时更新 locator，
        而不是堆一堆重复记录。
    """
    # ⚠️ 前端传的是"统一项目 id"（可能带 ui_/proj_ 前缀），必须归一化。
    #    直接当外键用会 ValueError -> 500（生产实测踩到）。
    project_id, pid_err = parse_project_id(request.data.get('project_id'))
    platform = (request.data.get('platform') or '').strip().lower()
    page = (request.data.get('page') or '').strip()
    items = request.data.get('elements') or []

    if pid_err:
        return Response({'error': pid_err}, status=400)
    if not platform:
        return Response({'error': '缺少 platform'}, status=400)
    if not isinstance(items, list) or not items:
        return Response({'error': 'elements 不能为空'}, status=400)
    if not UiProject.objects.filter(id=project_id).exists():
        return Response({'error': '项目不存在（id=%s）' % project_id}, status=404)

    group = None
    if page:
        group, _ = ElementGroup.objects.get_or_create(
            project_id=project_id, name=page,
            defaults={'description': '元素拾取器自动创建'},
        )

    created, updated, saved = 0, 0, []
    with transaction.atomic():
        for it in items:
            value = (it.get('value') or '').strip()
            name = (it.get('name') or it.get('text') or '').strip()
            if not (value and name):
                continue
            strategy_name = (it.get('strategy') or 'accessibility_id').strip()
            strategy, _ = LocatorStrategy.objects.get_or_create(
                name=strategy_name, defaults={'description': '元素拾取器'})

            # 元素库去重键是 (project, platform, name)，但「页面」也是身份的一部分：
            # 「编辑」按钮在首页和详情页是两个不同元素（坐标/上下文都不同）。
            # 不加 page 限定就会出现"拾取第二页的「编辑」把第一页的覆盖掉"，
            # 而且是静默覆盖 —— 用户只会发现第一页的用例突然点错了位置。
            query = {'project_id': project_id, 'platform': platform, 'name': name}
            if page:
                query['page'] = page
            obj = Element.objects.filter(**query).first()

            # 记录"这个元素长什么样"，用于同名元素之间区分。
            # ⚠️ 这不是锦上添花：元素库里同名元素很常见（不同页面各有一个「编辑」，
            # 或者同页里 text 相同但控件不同的两个节点），而没有这些信息时
            # 用户面对两个 id 完全无从选择 —— 只能乱猜。
            backup = _build_backup_locators(it)
            desc = _build_description(it)

            # 注意这里**不更新** page/group：元素已经归属某个页面分组，
            # 重复拾取同一页时它们本来就相等；跨页同名会被上面的 page 限定区分开，
            # 走到这里却要改 page 只能说明查重键与身份不一致。
            if obj:
                obj.locator_strategy = strategy
                obj.locator_value = value
                obj.page = page or obj.page
                obj.group = group or obj.group
                obj.validation_status = 'VALID'
                update_fields = [
                    'locator_strategy', 'locator_value', 'page', 'group',
                    'validation_status', 'updated_at']
                # 重新拾取是"刷新这个元素"的语义，描述与上下文信息应当一并更新，
                # 否则早期存下的空描述会一直空着（本次就是在补这个历史缺口）。
                if desc:
                    obj.description = desc
                    update_fields.append('description')
                if backup:
                    obj.backup_locators = backup
                    update_fields.append('backup_locators')
                obj.save(update_fields=update_fields)
                updated += 1
            else:
                obj = Element.objects.create(
                    project_id=project_id,
                    platform=platform,
                    group=group,
                    name=name,
                    description=desc,
                    element_type=_guess_element_type(it),
                    locator_strategy=strategy,
                    locator_value=value,
                    backup_locators=backup or None,
                    page=page,
                    validation_status='VALID',
                    created_by=request.user if request.user.is_authenticated else None,
                )
                created += 1
            saved.append({'id': obj.id, 'name': obj.name,
                          'strategy': strategy_name, 'value': value})

    return Response({'created': created, 'updated': updated, 'elements': saved})


def _guess_element_type(item):
    """按控件类型猜一个语义类型，纯粹为了让元素库列表看着清楚。"""
    cls = (item.get('class_name') or '').lower()
    if 'textfield' in cls or 'edittext' in cls:
        return 'INPUT'
    if 'button' in cls:
        return 'BUTTON'
    if 'image' in cls:
        return 'IMAGE'
    if item.get('text'):
        return 'TEXT'
    return 'BUTTON'


#: 存进 backup_locators 的上下文条目（key -> 展示名）。
#: 全部存在一个 JSON 数组里，**不新增数据库字段**：
#: 这些是"辅助人判断"的元信息，不参与定位计算。
_CONTEXT_LABELS = {
    'text': '可见文字',
    'class_name': '控件类型',
    'bounds': '屏幕位置',
    'center': '中心坐标',
    'rect': '元素尺寸',
    'clickable': '可点击',
}


def _build_backup_locators(item):
    """把拾取到的上下文信息（位置/控件类型/可点击性）存进 backup_locators。

    为什么不新增字段：这些信息**不参与定位计算**，只用于「同名元素选哪个」这类
    人工判断场景。存 JSON 数组既不动表结构（不用迁移），又能被前端直接展示。

    返回形如：
        [{"role": "context", "key": "bounds", "value": "[0,2400][240,2470]"},
         {"role": "context", "key": "class_name", "value": "XCUIElementTypeButton"}]
    """
    out = []
    for key in ('text', 'class_name', 'bounds', 'rect', 'clickable'):
        v = item.get(key)
        if v in (None, '', [], {}):
            continue
        if isinstance(v, (list, tuple)):
            v = ','.join(str(x) for x in v)
        elif isinstance(v, bool):
            v = '是' if v else '否'
        out.append({'role': 'context', 'key': key,
                    'label': _CONTEXT_LABELS.get(key, key),
                    'value': str(v)[:200]})

    cx, cy = item.get('center_x'), item.get('center_y')
    if cx is not None and cy is not None:
        # 坐标同时冗余成"相对屏幕的方位"，因为用户看 (120,2435) 没有直觉，
        # 看「下部」才有 —— 而且机型分辨率不同坐标值不可比。
        out.append({'role': 'context', 'key': 'center', 'label': '中心坐标',
                    'value': '%s,%s' % (cx, cy)})

    # 原始定位表达式也留一份：重学时可能从坐标升级成更稳的 accessibility_id
    if item.get('value'):
        out.insert(0, {'role': 'context', 'key': 'picked_value', 'label': '拾取时定位值',
                       'value': str(item['value'])[:200]})
    return out


def _build_description(item):
    """元素描述：优先用**可见文字**，没有文字时退化成可读的"上下文摘要"。

    ⚠️ 曾经的实现是 `(text or '')[:200]` —— 于是"只有坐标、没有文字"的元素
    （Android 的 screen_text 兜底策略会产出这类元素）描述恒为空，
    在歧义列表里表现为两个一模一样的空行，用户完全无法区分。

    ⚠️ 刻意**不用 `name` 兜底**：调用方传来的 `name` 是"元素名"，
    在拾取器场景里它可能来自 AI 生成的步骤描述（如「1、点击万年历tab」），
    把它当成"屏幕上的可见文字"会误导用户在候选列表里做错误判断。
    只认真正的可见文字，其余情况一律退化成上下文摘要。
    """
    text = (item.get('text') or '').strip()
    if text:
        return text[:200]
    parts = []
    cls = (item.get('class_name') or '').strip()
    if cls:
        parts.append(cls.replace('XCUIElementType', '').replace('android.widget.', ''))
    if item.get('bounds'):
        parts.append(str(item['bounds'])[:60])
    if item.get('center_x') is not None:
        parts.append('(%s,%s)' % (item.get('center_x'), item.get('center_y')))
    if parts:
        return (' · '.join(parts))[:200]
    # 最后兜底：连控件类型/位置都没有，就退回元素名（至少不是空）
    return (item.get('name') or '').strip()[:200]



@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def learn_locator(request):
    """阶段二：定位失败时自动重学并回写元素库（对标 Android 的 _auto_learn_find）。

    与 Android 的差异（重要）：
      - Android 从 `page_source` 里按 **resource-id** 学（`com.xxx:id/yyy`）；
      - iOS 没有 resource-id，只能按 **accessibility 的文案** 学，
        所以返回的 strategy 是 `accessibility_id`，value 是元素文案。

    请求体：
        {
          "device_id": 7,
          "app_config_id": 3,
          "element_id": 88,        # 可选：指定要修正的元素库记录
          "name": "写日记"          # 未给 element_id 时按名字找/建
        }
    返回：{found: bool, strategy, value, element_id, candidates: [...]}
    """
    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': '缺少 device_id'}, status=400)
    device = AppDevice.objects.filter(id=device_id).first()
    if not device:
        return Response({'error': '设备不存在'}, status=404)

    app_config = None
    app_config_id = request.data.get('app_config_id')
    if app_config_id:
        app_config = AppConfig.objects.filter(id=app_config_id).first()

    want_name = (request.data.get('name') or '').strip()
    element_id = request.data.get('element_id')

    result = dump_elements(device, app_config)
    if result.get('error'):
        return Response({'found': False, 'error': result['error']}, status=200)

    elements = result.get('elements') or []
    match = _match_element(elements, want_name)
    if not match:
        return Response({
            'found': False,
            'message': '页面上没有找到与「%s」匹配的元素' % want_name,
            'candidates': _candidate_preview(elements),
        })

    strategy = match.get('strategy') or 'accessibility_id'
    value = match.get('value') or ''

    # 回写元素库
    if element_id:
        try:
            el = Element.objects.get(id=element_id)
            strategy_obj, _ = LocatorStrategy.objects.get_or_create(
                name=strategy, defaults={'description': '自动学习'})
            el.locator_strategy = strategy_obj
            el.locator_value = value
            el.validation_status = 'VALID'
            el.save(update_fields=['locator_strategy', 'locator_value',
                                   'validation_status', 'updated_at'])
        except Element.DoesNotExist:
            element_id = None

    return Response({
        'found': True,
        'strategy': strategy,
        'value': value,
        'element_id': element_id,
        'matched': {'name': match.get('name'), 'text': match.get('text'),
                    'class_name': match.get('class_name'),
                    'center': [match.get('center_x'), match.get('center_y')]},
        'candidates': _candidate_preview(elements),
    })


def _match_element(elements, want):
    """按文案匹配元素。优先级：完全相等 → 去空白相等 → 包含（取面积最小）。

    与 iOS Node 侧 `findElementByText` 的匹配规则保持一致，
    否则会出现"跑用例能命中、拾取器命不中"的诡异不一致。
    """
    want = (want or '').strip()
    if not want:
        return None
    norm = lambda s: re.sub(r'\s+', '', s or '')
    target = norm(want)

    exact, trim, contains = [], [], []
    for e in elements:
        for field in ('name', 'text'):
            v = e.get(field) or ''
            if v == want:
                exact.append(e)
                break
            if norm(v) == target:
                trim.append(e)
                break
            # 短词不做包含匹配（会误命中）
            if len(want) >= 3 and want in v:
                contains.append(e)
                break

    for bucket in (exact, trim, contains):
        if bucket:
            if bucket is trim or bucket is contains:
                # 取面积最小的（更接近真正可点的叶子元素）
                bucket = sorted(
                    bucket,
                    key=lambda e: (e.get('rect') or [0, 0, 10**9, 10**9])[2]
                    * (e.get('rect') or [0, 0, 1, 10**9])[3])
            return bucket[0]
    return None


def _candidate_preview(elements, limit=30):
    seen, out = set(), []
    for e in elements:
        t = e.get('name') or e.get('text') or ''
        if not t or t in seen:
            continue
        seen.add(t)
        out.append({'name': t, 'strategy': e.get('strategy'),
                    'class_name': e.get('class_name'),
                    'center': [e.get('center_x'), e.get('center_y')]})
        if len(out) >= limit:
            break
    return out


# ============================================================
# 阶段三：用元素库校正「AI 生成 / 手写」的步骤定位
# ============================================================
#: 只有这两个动作会消费定位值（引擎 target = selector_hint || prompt）。
#: 与前端 AICaseList.vue 的 LOCATOR_ACTIONS、以及写回后的展示条件保持一致。
LOCATOR_ACTIONS = ('aiTap', 'aiInput')

#: ⚠️ **不可跨设备使用**的定位策略。
#: 坐标（`coordinate`）与纯数字表达式只在**当时那台设备**上成立：
#: 换机型后分辨率、状态栏高度、安全区、dpr 全变，必错位；同一台设备旋转屏幕也会偏。
#: 因此它们**不能**被当作 `selector_hint` 写入用例 —— 引擎侧还有
#: `midscene_engine._guard_semantic_prompt` 护栏会把 `(120,2435)` 这类写法直接拦成
#: failed，写进去等于给用户埋一个必然执行的失败步骤。
#: 这里提前识别并标 `cross_device=False`，让用户"看得见但选不了"，而不是事后报错。
UNPORTABLE_STRATEGIES = ('coordinate', 'screen_text', 'position')

#: 纯坐标/数字形状的定位值（护栏的同类判断，用于兜住 strategy 标注不准的历史数据）
_PURE_COORD_VALUE = re.compile(
    r'^\s*[\(\（]?\s*\d{1,5}\s*[,，]\s*\d{1,5}\s*[\)\）]?\s*$'
)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def match_steps_to_elements(request):
    """把用例步骤的「自然语言描述」对到元素库，回填 selector_hint（不落库）。

    设计动机：
      自然语言生成步骤（`generate-steps`）产出的只有 prompt，定位仍靠视觉模型
      看图猜坐标 —— 密集图标条上必不准，且点错不报错。而元素库里已经有
      设备实测出来的精确 locator（iOS = 元素文案、Android = xpath）。
      这里负责**把两者接上**，让"描述型用例"也能用上真元素定位。

    为什么做成"显式点一下的按钮"而不是全自动：
      - 匹配结果会直接影响点击目标，用户必须在界面上**看得见、能改**；
      - 意图词（如"点击万年历"）可能同时匹配到多个元素，这类要标成
        ambiguous 交由用户决定，而不是赌一个；
      - 不依赖 LLM「是否听话」，确定性规则可复核。

    请求体：
        {
          "project_id": 1,
          "platform": "ios",          # 可选；给了就只在同平台元素里找
          "steps": [ {"action","prompt","selector_hint"}, ... ],
          "overwrite": false          # true = 连已填的 selector_hint 也重新匹配
        }

    返回：
        {
          "matched": 3, "skipped": 2, "total": 5,
          "steps": [ {...原步骤..., "selector_hint","_match": {...}} ]
        }
    """
    project_id, pid_err = parse_project_id(request.data.get('project_id'))
    if pid_err:
        return Response({'error': pid_err}, status=400)

    steps = request.data.get('steps')
    if not isinstance(steps, list) or not steps:
        return Response({'error': 'steps 不能为空'}, status=400)

    platform = (request.data.get('platform') or '').strip().lower()
    overwrite = bool(request.data.get('overwrite'))

    if platform and platform not in ('android', 'ios', 'harmony', 'web'):
        return Response({'error': 'platform 不合法: %s' % platform}, status=400)

    # 用户针对歧义步骤做出的"我选这个"决定：{步骤下标: element_id}。
    # 有明确选择时不该再去猜 —— 人的判断永远优先于匹配规则。
    picks = request.data.get('picks') or {}
    if not isinstance(picks, dict):
        picks = {}

    qs = Element.objects.filter(project_id=project_id)
    if platform:
        qs = qs.filter(platform=platform)
    elements = list(qs.values('id', 'name', 'page', 'platform', 'description',
                              'backup_locators',
                              'locator_strategy__name', 'locator_value'))
    if not elements:
        return Response({
            'error': '当前项目%s的元素库还是空的，请先用「元素拾取器」抓取并存入元素'
                     % ('（%s）' % platform if platform else ''),
            'total': len(steps), 'matched': 0, 'skipped': len(steps), 'steps': steps,
        }, status=200)

    by_id = {el['id']: el for el in elements}

    out, matched, skipped = [], 0, 0
    for idx, raw in enumerate(steps):
        step = dict(raw) if isinstance(raw, dict) else {}
        action = (step.get('action') or '').strip()
        prompt = (step.get('prompt') or '').strip()
        current = (step.get('selector_hint') or '').strip()

        # ① 用户已经明确选过元素了 -> 用他的选择，不再匹配。
        #    人的判断优先于任何规则，且这样"再点一次校正"不会把选择弄丢。
        picked_id = picks.get(str(idx)) or picks.get(idx)
        if picked_id:
            el = by_id.get(int(picked_id)) if str(picked_id).isdigit() else None
            if el:
                # ⚠️ 唯一一处**不能**尊重用户选择的地方：坐标类定位不可跨设备，
                #    让它落库等于给用例埋一个必然失败的步骤。前端已禁用该行，
                #    这里再拦一道（接口可能被直接调用），并说清为什么拒绝。
                portable, why = _is_portable(el)
                if not portable:
                    step['_match'] = {
                        'status': 'not_found',
                        'reason': '这条元素不能选中：%s' % why,
                    }
                    skipped += 1
                    out.append(step)
                    continue
                step['selector_hint'] = el['locator_value']
                step['_match'] = _match_payload(el, 'picked', '手动选择')
                matched += 1
                out.append(step)
                continue

        # 不该被校正的情况要在 _match 里说明原因，而不是静默跳过 ——
        # 用户点了按钮看到"0 条命中"却没有任何解释时，只会以为功能坏了。
        if action not in LOCATOR_ACTIONS:
            step['_match'] = {'status': 'skipped', 'reason': '该动作不做元素定位'}
            skipped += 1
            out.append(step)
            continue
        if current and not overwrite:
            step['_match'] = {'status': 'skipped',
                              'reason': '已有定位，未覆盖（可勾选"重新匹配"）'}
            skipped += 1
            out.append(step)
            continue
        if not prompt:
            step['_match'] = {'status': 'skipped', 'reason': '没有描述可供匹配'}
            skipped += 1
            out.append(step)
            continue

        result = _match_step_to_library(prompt, elements)
        if result['status'] == 'matched':
            step['selector_hint'] = result['value']
            matched += 1
        step['_match'] = result
        out.append(step)

    return Response({
        'total': len(steps), 'matched': matched,
        'skipped': len(steps) - matched, 'steps': out,
    })


def _extract_intents(prompt):
    """从一句自然语言描述里抠出「可能对应的元素文案」候选，按可信度排序。

    为什么不直接用整句去匹配：元素库里存的是元素自身的文案（`万年历`），
    而用户/AI 写的是带动作和方位的句子（`点击底部「万年历」标签`），
    整句匹配必然一条都命中不了。

    候选来源（越靠前越可信）：
      ① 引号/括号内的内容（`「」『』【】""''`）—— 用户明确指出的名字；
      ② 去掉动作词后的主干（`点击XX` → `XX`）—— AI 生成时最常见的写法；
      ③ 整句兜底（让完全相等的匹配有机会命中）。
    """
    text = (prompt or '').strip()
    if not text:
        return []

    cands = []

    def _push(v):
        v = re.sub(r'\s+', ' ', (v or '')).strip(' 　，。、:：;；!！?？')
        if v and v not in cands:
            cands.append(v)

    # ① 引号/括号内
    for m in re.finditer(r'[「『【\[(（"\']([^」』】\])）"\']{1,40})[」』】\])）"\']', text):
        _push(m.group(1))
    # 全角书名号式的「」也常被单独留下（配对不全时兜底取第一段）
    for m in re.finditer(r'「([^」]{1,40})」', text):
        _push(m.group(1))

    # ② 去掉动作词与方位词后的主干
    body = text
    for w in ('点击', '点一下', '轻点', '单击', '点击底部', '点击顶部', '输入',
              '进入', '打开', '选择', '切换到', '滑动到', '向下滚动到'):
        body = body.replace(w, ' ')
    for w in ('底部导航栏', '导航栏', '标签栏', 'tab栏', '左上角', '右上角',
              '左下角', '右下角', '底部', '顶部', '上方', '下方', '标签页',
              '按钮', '图标', '输入框', '这一页', '页面', '上的', '中的', '的'):
        body = body.replace(w, ' ')
    # 「从左数第 1 个」这类序号词对元素文案匹配是噪声
    body = re.sub(r'从左(右)?数第\s*\d+\s*个', ' ', body)
    for piece in re.split(r'[，,。、;；\s]+', body):
        _push(piece)

    _push(text)
    # 去掉纯标点/单字噪声（单字几乎不可能是有意义的元素名，且易误命中）
    # 顺带做类型防护：调用方（含未来可能的 LLM 产出）不该让非字符串流进下游
    return [c for c in cands if isinstance(c, str) and len(c) >= 2]


def _match_step_to_library(prompt, elements):
    """拿一句描述去元素库找元素，返回可直接展示给用户的匹配结论。"""
    cands = _extract_intents(prompt)
    if not cands:
        return {'status': 'no_candidate', 'reason': '没能从描述里提取出元素名'}

    # ⚠️ 跨设备不可用的元素（坐标类）**不参与自动匹配**：
    #    自动填进去等于给用户埋一个"换设备必错、且会被引擎护栏拦成 failed"的步骤。
    #    它们仍会出现在歧义候选里（标 cross_device=false 供用户理解现状），
    #    但绝不自动落定。
    usable = [e for e in elements if _is_portable(e)[0]]

    best = None
    best_skipped = None
    for cand in cands:
        hits = _find_elements_by_text(usable, cand)
        if not hits:
            # 记录"只有坐标类元素能匹配上"的情况，好给用户一个明确解释
            if best_skipped is None:
                unusable_hits = _find_elements_by_text(
                    [e for e in elements if not _is_portable(e)[0]], cand)
                if unusable_hits:
                    best_skipped = (cand, unusable_hits)
        if not hits:
            continue
        if len(hits) == 1:
            return _match_payload(hits[0], 'exact' if hits[0]['name'] == cand else 'contains',
                                  cand)

        # ⭐ 同名多条时先做一次"可点优先级"消歧（2026-09-22 新增，实测有效）。
        #    这个 App 的元素树里 Button 与它内部的 StaticText **文案完全相同**
        #    （实测 144/275 个节点文字重复，如「理发」「结婚」各出现 2 次），
        #    导致本来唯一的元素被判成"歧义"，用户面对两个一模一样的选项无法选择。
        #    处理原则：**有可点控件可选时，就不该报歧义** —— 这不是真的歧义，
        #    而是"该点哪个"的工程常识（要点的是 Button，不是它里面的文字）。
        picked = _prefer_clickable(hits)
        if picked is not None:
            return _match_payload(
                picked,
                'clickable' if chosen_by_clickable(hits) else 'contains',
                cand,
                extra={'disambiguated': '同名多条，已按"可点控件优先"自动选定'})

        # 真的无法区分（都是可点、或都不可点）：标歧义，让用户自己定（宁可漏也不赌）
        if best is None:
            best = (cand, hits)

    if best:
        cand, hits = best
        return {
            'status': 'ambiguous',
            'reason': _ambiguous_reason(cand, hits),
            # ⚠️ 候选必须带**足以区分彼此**的信息。曾经只给 id + value，
            #    用户看到两个 id 完全无从判断该选哪个（等于没给选择）。
            'candidates': [_candidate_payload(h) for h in hits[:10]],
            'candidate_total': len(hits),
        }

    # 只有坐标类元素能匹配上：必须明确告知**为什么不能用**，
    # 否则用户看到"元素库里明明有这个元素"却匹配不上，只会认为是 bug。
    if best_skipped:
        cand, unusable_hits = best_skipped
        return {
            'status': 'not_found',
            'reason': '「%s」只匹配到设备相关的坐标定位（%s），它换设备就会错位、'
                      '执行时会被引擎拦截，因此不能自动填入。'
                      '请把 App 操作到目标页面后，在「元素拾取器」用控件文字重新抓一次'
                      '（能得到可跨设备的定位）' % (
                          cand, '、'.join(h['locator_value'] for h in unusable_hits[:3])),
            'tried': cands[:5],
            'unusable': [_candidate_payload(h) for h in unusable_hits[:5]],
            'near': _near_names(cands, elements),
        }

    # 未命中时给出"名字相近的几条"作为线索。最常见的原因是用户/AI 写的是
    # 「万年历」而元素库里的元素名是别的写法（拼音 id、英文名），
    # 只回一句"没找到"用户完全不知道该去抓什么。
    return {'status': 'not_found',
            'reason': '元素库里没有与「%s」匹配的元素' % (cands[0] if cands else prompt[:20]),
            'tried': cands[:5],
            'near': _near_names(cands, elements)}


def _ambiguous_reason(cand, hits):
    """歧义提示要直接告诉用户"靠什么区分"，而不是只说"有 2 条"。"""
    pages = {h.get('page') or '' for h in hits}
    if len(pages) > 1:
        return ('「%s」在元素库里有 %d 条，分属不同页面（%s），'
                '请按"目标页面对应的那一页"选择' % (
                    cand, len(hits), '、'.join(sorted(p or '(未分组)' for p in pages))))
    return ('「%s」在元素库里有 %d 条同名元素，'
            '请按下面的「可见文字 / 控件类型 / 屏幕位置」选择符合预期的那一条'
            % (cand, len(hits)))


#: 真正适合作为"点击目标"的控件类型。
#: 与 iOS 的 `element_provider._dump_ios` 里 clickable 判定保持一致意图：
#: Button/Cell 是可点的；StaticText 只是文字（点它通常靠父容器响应，不稳）。
CLICKABLE_TYPES = (
    'XCUIElementTypeButton', 'XCUIElementTypeCell',
    'XCUIElementTypeTextField', 'XCUIElementTypeSecureTextField',
    'XCUIElementTypeSwitch', 'XCUIElementTypeLink',
    'android.widget.Button', 'android.widget.EditText',
)


def _is_clickable_el(el):
    """判断元素是否"本身可点"。兼容元素库记录与设备 dump 两种字段形态。"""
    cls = (el.get('class_name') or '').strip()
    if cls:
        if cls in CLICKABLE_TYPES:
            return True
        # 元素库里 clickable 是明确字段；dump 也有
    return bool(el.get('clickable'))


def chosen_by_clickable(hits):
    """`_prefer_clickable` 是否真的靠"可点优先"做出了选择（而非退到其它规则）。"""
    ck = [h for h in hits if _is_clickable_el(h)]
    return len(ck) == 1


def _prefer_clickable(hits):
    """同名多条时，若"可点控件"恰好唯一，就返回它；否则返回 None（交给歧义处理）。

    为什么这个规则是安全的（不是"猜"）：
      - 用户要"点击 XX"，XX 在页面上是一个 Button，Button 内部常有一个
        同名 StaticText。**要点的一定是 Button**，这是确定的工程事实，
        不是概率判断 —— 所以自动选定不会误伤。
      - 若可点控件有多个（真同名不同位置），或一个都没有，
        说明规则不适用，必须交回用户判断，绝不赌。
    """
    ck = [h for h in hits if _is_clickable_el(h)]
    if len(ck) == 1:
        return ck[0]
    return None


def _is_portable(el):
    """该元素的定位值能否跨设备使用。

    ⚠️ 这是**安全阀**，不是优化项：把坐标写进用例的后果是"换设备必错"，
    而引擎护栏会把它变成"每次执行都 failed 的步骤"。宁可让用户选不了，
    也不要给他一个看起来能选、实际必然失败的选项。

    ⚠️ **两种数据形态都要认**（踩过一次：只看 `locator_strategy__name` 导致
    dump 路径过滤完全失效，因为 dump 返回的元素用的是 `strategy`/`value` 字段名）：
      - 元素库记录（`.values(...)`）→ `locator_strategy__name` / `locator_value`
      - 设备实时 dump（`element_provider`）→ `strategy` / `value`
    """
    strategy_raw = (el.get('locator_strategy__name') or el.get('strategy') or '').strip()
    if strategy_raw.lower() in UNPORTABLE_STRATEGIES:
        return False, '定位策略「%s」是设备相关的（坐标类），换设备/换分辨率必错位' % strategy_raw

    value = (el.get('locator_value') or el.get('value') or '').strip()
    if _PURE_COORD_VALUE.match(value):
        # 兜住 strategy 标注不准的数据（早期拾取可能把坐标标成别的策略）
        return False, '定位值是纯坐标「%s」，不能跨设备使用' % value
    return True, ''


def _candidate_payload(el):
    """单个候选：把"能让人做决定"的信息全部摊开。

    展示优先级（前端按这个顺序读）：
      1. `hint`          —— 一句话摘要，直接可读（后端算好，避免前端重复拼装）
      2. `page`          —— 所属页面（跨页同名时这是决定性依据）
      3. `context`       —— 可见文字/控件类型/屏幕位置/可点击，来自 backup_locators
      4. `value`         —— 选中后会填进用例的定位值（让用户知道自己在绑什么）
      5. `cross_device`  —— **能否跨设备使用**；false 时前端禁用该行并显示原因
    """
    el = dict(el)
    context = []
    for item in (el.get('backup_locators') or []):
        if not isinstance(item, dict):
            continue
        if item.get('role') not in (None, 'context'):
            continue
        val = item.get('value')
        if val in (None, ''):
            continue
        context.append({'label': item.get('label') or item.get('key') or '',
                        'value': str(val)})

    # 历史数据（本次改动之前拾取的）没有 backup_locators，
    # 用 description + locator_value 兜一个最小可读摘要，不留空白。
    summary_bits = []
    for b in (el.get('description') or '', el.get('locator_value') or ''):
        # 去掉重复片段：`编辑 · 编辑` 这种冗余摘要看着像出错了
        if b and b not in summary_bits:
            summary_bits.append(b)
    hint_parts = [c['value'] for c in context[:2]]
    seen = []
    for h in hint_parts or summary_bits:
        if h and h not in seen:
            seen.append(h)
    # 摘要全一样时（比如只有可见文字、定位值也等于它），补一个控件类型增强区分度
    if len(set(seen)) == 1 and len(context) > 2:
        extra = context[2]['value']
        if extra and extra not in seen:
            seen.append(extra)
    hint = ' · '.join(seen)

    portable, why = _is_portable(el)

    return {
        'id': el['id'],
        'name': el['name'],
        'page': el.get('page') or '',
        'page_label': el.get('page') or '(未分组)',
        'strategy': el.get('locator_strategy__name') or '',
        'value': el['locator_value'],
        'description': el.get('description') or '',
        'context': context,
        'hint': hint,
        # 跨设备可用性：前端据此禁用候选行。
        # 坐标类元素**看得见但选不了**，并直接说明原因，避免用户事后撞护栏。
        'cross_device': portable,
        'unusable_reason': why,
    }


def _match_payload(el, how, cand, extra=None):
    """统一的"命中"结论。

    ⚠️ 字段形态要兼容两种来源：
      - 元素库记录 → `locator_strategy__name` / `locator_value`
      - 设备 dump  → `strategy` / `value`
    （只认前者会让 dump 路径取到空值，曾栽过一次）
    """
    payload = {
        'status': 'matched',
        'how': how,
        'from': cand,
        'element_id': el.get('id'),
        'element_name': el.get('name'),
        'page': el.get('page') or '',
        'strategy': (el.get('locator_strategy__name') or el.get('strategy') or ''),
        'value': (el.get('locator_value') or el.get('value') or ''),
    }
    if extra:
        payload.update(extra)
    return payload


def _near_names(cands, elements, limit=6):
    """找名字"沾边"的元素作为线索（子串包含，任一方向）。

    只看名字、不做匹配决策，所以这里可以放宽 —— 它的作用是让用户
    "认出"元素库里真正的写法，而不是替用户做选择。
    """
    needles = [str(c).strip().lower() for c in (cands or [])
               if isinstance(c, str) and len(c.strip()) >= 2]
    if not needles:
        return []
    out, seen = [], set()
    for el in elements:
        name = (el.get('name') or '').strip()
        low = name.lower()
        if not name or name in seen:
            continue
        if any(n in low or low in n for n in needles):
            seen.add(name)
            out.append({'id': el['id'], 'name': name,
                        'page_label': el.get('page') or '(未分组)'})
            if len(out) >= limit:
                break
    return out


def _find_elements_by_text(elements, want):
    """在元素库里按文案找元素。

    匹配严格度刻意与 `_match_element`（设备实时元素）不同：
    设备元素来自单一页面，错一点也无所谓；元素库跨很多页面，
    宽松匹配会命中无关页面的同名元素。所以这里**不做"包含"兜底**，
    只认「完全相等」和「去空白相等」。
    """
    want = (want or '').strip()
    if not want:
        return []
    norm = lambda s: re.sub(r'\s+', '', s or '')
    target = norm(want)

    out = []
    for el in elements:
        name = (el.get('name') or '').strip()
        if name == want or norm(name) == target:
            out.append(el)
    return out
