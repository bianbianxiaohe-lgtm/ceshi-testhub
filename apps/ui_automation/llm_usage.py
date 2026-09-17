"""
模型调用消耗统计。

回放模式的目标是"零模型"，所以必须能量化每次执行到底花了多少，否则无法
判断固化是否真的有收益。

两条数据来源：

1. **真实 usage**（优先）
   兼容 OpenAI 协议的接口在响应里会带 ``usage.prompt_tokens`` /
   ``usage.completion_tokens``。midscene 内部把响应吃掉了不往外传，所以
   我们另开一个转发端点 ``/api/ui-automation/llm-proxy/``，把 midscene 的
   base_url 指过来，由代理记录 usage 并累加到当前执行记录。见
   ``llm_proxy_view``（views.py）。

2. **估算**（兜底）
   代理没生效时（直连、被绕过、非 OpenAI 协议），按截图尺寸 + 提示词长度
   估算。视觉模型的图片 token 有公开的换算规则，误差大约 ±20%，用来做
   横向对比足够了。

线程安全：执行是跑在后台线程里的，用线程局部变量存"当前执行记录 id"，
避免把 usage 一路手动传参下去。
"""
from __future__ import annotations

import logging
import math
import threading

logger = logging.getLogger(__name__)

#: 每个执行线程当前正在服务的执行记录 id
_state = threading.local()

#: 视觉模型图片 token 换算（OpenAI 规则）
#: 一张图按 512x512 切 tile，外加 85 的固定开销
IMAGE_BASE_TOKENS = 85
IMAGE_TOKENS_PER_TILE = 170
#: 中英文混排下每个字符大致折算的 token 数（粗略）
TOKENS_PER_CHAR = 0.6


def set_current_execution(execution_id):
    """把当前线程绑定到某个执行记录，之后 record_usage 都记到它头上。"""
    _state.execution_id = execution_id


def clear_current_execution():
    _state.execution_id = None


def get_current_execution():
    return getattr(_state, 'execution_id', None)


def estimate_image_tokens(width, height) -> int:
    """按截图尺寸估算一张图占多少输入 token。"""
    try:
        w = max(int(width or 0), 1)
        h = max(int(height or 0), 1)
    except (TypeError, ValueError):
        return IMAGE_BASE_TOKENS
    tiles = math.ceil(w / 512) * math.ceil(h / 512)
    return IMAGE_BASE_TOKENS + IMAGE_TOKENS_PER_TILE * max(tiles, 1)


def estimate_text_tokens(text) -> int:
    """按字符数粗估文本 token。"""
    if not text:
        return 0
    return max(int(len(str(text)) * TOKENS_PER_CHAR), 1)


def record_usage(prompt_tokens=0, completion_tokens=0, calls=1, estimated=False,
                 execution_id=None):
    """把一次（或若干次）模型调用记到执行记录上。

    任何异常都不能影响用例执行 —— 统计只是旁路，统计失败不应该让用例挂掉。
    """
    eid = execution_id or get_current_execution()
    if not eid:
        return
    try:
        from .models import AIExecutionRecord
        rec = AIExecutionRecord.objects.filter(id=eid).first()
        if rec is None:
            return
        rec.model_calls = (rec.model_calls or 0) + max(int(calls or 0), 0)
        rec.prompt_tokens = (rec.prompt_tokens or 0) + max(int(prompt_tokens or 0), 0)
        rec.completion_tokens = (rec.completion_tokens or 0) + max(int(completion_tokens or 0), 0)
        update = ['model_calls', 'prompt_tokens', 'completion_tokens']

        # 真实数字优先：只由"估算"来源写过的记录才保持 estimated=True；
        # 一旦收到真实 usage，就把标记翻回 False，避免整条记录被误标为估算。
        if estimated:
            if rec.model_calls == max(int(calls or 0), 0):
                rec.tokens_estimated = True
                update.append('tokens_estimated')
        elif rec.tokens_estimated:
            rec.tokens_estimated = False
            update.append('tokens_estimated')

        rec.save(update_fields=update)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[LLMUsage] 记录 token 失败（不影响执行）: %s', exc)


def record_step_estimate(execution_id=None, screenshot_b64='', prompt='',
                         completion_hint=''):
    """没拿到真实 usage 时的兜底估算：一次动作 = 一张截图 + 提示词。

    只在"该步确实调用了模型"时调用（launch / wait / 纯坐标点击不算）。
    """
    prompt_tokens = estimate_text_tokens(prompt)
    # 截图按常见手机分辨率估算；有 base64 时按长度反推长宽意义不大，
    # 这里统一用一个保守值，保证估算稳定、可比。
    prompt_tokens += estimate_image_tokens(1170, 2532)
    completion_tokens = estimate_text_tokens(completion_hint) or 40
    record_usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        calls=1,
        estimated=True,
        execution_id=execution_id,
    )
