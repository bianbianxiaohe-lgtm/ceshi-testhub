# -*- coding: utf-8 -*-
"""重跑前的可行性预检（只读 + 一次极小 LLM 连通测试）。

背景：墨刀线跑一次要走「模块拆分→测试点→风险→PCI→合并→用例→冒烟→质量」
多轮 LLM 调用。若模型 key 余额不足/不通，跑到一半失败既浪费时间又留下脏状态，
所以**先花几秒钟做一次极小调用**。

输出：
  - 候选 proto / page 的前置数据是否齐全
  - dev 的 AIModelConfig（不打印任何密钥）
  - 一次 1 句话的 LLM 连通测试结果

用法：
  docker exec testhub-dev-backend-1 python /app/scripts/_precheck_modao_rerun.py
  docker exec testhub-dev-backend-1 cat /tmp/_precheck_modao_rerun.txt
"""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402
from apps.requirement_analysis.models import (  # noqa: E402
    ModaoPrototype, ModaoPage, AIModelConfig,
)

OUT = '/tmp/_precheck_modao_rerun.txt'
lines = []
PROTO_ID = 65
PAGE_ID = 722


def w(s=''):
    lines.append(s)


def jlen(v):
    return len(v or '')


w('现在：%s' % timezone.now())

# ---------- 1. 候选 proto 前置数据 ----------
w('')
w('=== proto %d ===' % PROTO_ID)
try:
    p = ModaoPrototype.objects.get(pk=PROTO_ID)
    w('title=%s  status=%s  stage=%s  updated_at=%s'
      % (p.title, p.status, p.current_stage, p.updated_at))
    w('project=%s version=%s created_by=%s' % (p.project_id, p.version_id, p.created_by_id))
    for f in ('extracted_json', 'requirement_summary', 'clarification_log', 'module_split',
              'risks_json', 'pci_json', 'final_testpoints_json', 'testcases_json',
              'smoke_json', 'quality_report_json', 'merged_testcases_json'):
        w('   %-24s len=%d' % (f, jlen(getattr(p, f, ''))))
    w('   pages=%d' % p.pages.count())
except ModaoPrototype.DoesNotExist:
    w('!! proto %d 不存在' % PROTO_ID)

# ---------- 2. 候选 page 前置数据 ----------
w('')
w('=== page %d ===' % PAGE_ID)
try:
    pg = ModaoPage.objects.select_related('prototype').get(pk=PAGE_ID)
    w('proto=%s P%s %s' % (pg.prototype_id, pg.page_no, pg.page_name))
    w('current_stage=%s stage_status=%s selected=%s' % (
        pg.current_stage, pg.stage_status, pg.selected))
    for f in ('text', 'page_summary', 'page_clarification',
              'page_testpoints_json', 'page_testcases_json', 'page_smoke_json'):
        w('   %-22s len=%d' % (f, jlen(getattr(pg, f, ''))))
except ModaoPage.DoesNotExist:
    w('!! page %d 不存在' % PAGE_ID)

# ---------- 3. 模型配置（不打印密钥） ----------
w('')
w('=== AIModelConfig ===')
# 不打印任何含密钥的字段
SAFE = [f.name for f in AIModelConfig._meta.fields
        if not any(k in f.name.lower() for k in ('key', 'secret', 'token', 'password'))]
w('fields: ' + ', '.join(SAFE))
for m in AIModelConfig.objects.all().order_by('id'):
    vals = {k: getattr(m, k, None) for k in SAFE
            if k in ('id', 'name', 'role', 'model_name', 'provider', 'is_active',
                     'temperature', 'max_tokens', 'base_url')}
    w('   ' + '  '.join('%s=%s' % (k, v) for k, v in vals.items() if v is not None))

# ---------- 4. 一次极小 LLM 连通测试 ----------
w('')
w('=== LLM 连通测试（1 句话）===')
# 走墨刀线真实用的入口：AIModelService.call_openai_compatible_api
# （见 modao_workflow.py:580），这样测出来的就是跑生成时那条通路。
try:
    from apps.requirement_analysis.ai_model_service import AIModelService

    # analyzer 优先取 siliconflow 的（见 ModaoWorkflow.resolve_configs）
    for role in ('analyzer', 'writer'):
        try:
            if role == 'analyzer':
                cfg = (AIModelConfig.get_active_config('siliconflow', 'analyzer')
                       or AIModelConfig.objects.filter(role='analyzer', is_active=True).first())
            else:
                cfg = AIModelConfig.objects.filter(role='writer', is_active=True).first()
            if not cfg:
                w('[%s] 无 active 配置' % role)
                continue
            # ⚠️ call_openai_compatible_api 是 async：直接调用只会得到一个协程对象、
            # **不会真的发请求**，str() 出来是 '<coroutine object ...>'，
            # 若不 await 就会把「没测」误报成「调用成功」（已踩过）。
            coro = AIModelService.call_openai_compatible_api(
                cfg,
                messages=[{'role': 'user', 'content': '只回复两个字：正常'}],
                max_tokens=16,
                temperature=0,
            )
            if inspect.iscoroutine(coro):
                resp = asyncio.run(coro)
            else:
                resp = coro
            txt = resp if isinstance(resp, str) else str(resp)
            if 'coroutine object' in txt:
                w('[%s] 测试无效（未真正 await）' % role)
            else:
                w('[%s] id=%s 调用成功，返回=%r' % (role, cfg.id, txt[:40]))
        except Exception as e:
            # 402 Insufficient Balance = 余额不足，会直接卡死阶段1/3/4
            w('[%s] 调用失败：%s: %s' % (role, type(e).__name__, str(e)[:300]))
except Exception as e:
    w('服务导入/初始化失败：%s: %s' % (type(e).__name__, str(e)[:300]))

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
