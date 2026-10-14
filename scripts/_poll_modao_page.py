# -*- coding: utf-8 -*-
"""轮询墨刀画布运行进度，直到完成/失败或超时。

用法（容器内）：
  python /app/scripts/_poll_modao_page.py <page_id> [timeout_seconds]

输出落 /tmp/_poll_modao_page.txt，宿主机 cat 取回。
"""
import sys
import time

sys.path.insert(0, '/app')
import os  # noqa: E402

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from apps.requirement_analysis.models import ModaoPage  # noqa: E402

page_id = int(sys.argv[1]) if len(sys.argv) > 1 else 722
timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 240

OUT = '/tmp/_poll_modao_page.txt'
lines = []


def w(s):
    lines.append(s)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


FIELDS = ['page_summary', 'page_testpoints_json', 'page_testcases_json',
          'page_smoke_json']

# ⚠️ 判据坑（2026-10-13 实测）：不能用 page.stage_status 判断本轮是否跑完。
#    画布级 page.current_stage/stage_status 是**上一轮遗留**的（这里仍是 9-07 那轮的
#    stage=4/done），新一轮启动后它不会立刻变 ⇒ 一进来就误判 FINISHED。
#    正确判据：① proto.status 离开 'designing' ② 且 page.work_log 长度发生变化
#    （work_log 每步都会追加时间戳，是最可靠的"本轮确实动过"信号）。
pg0 = ModaoPage.objects.get(pk=page_id)
wl0 = len(pg0.work_log or '')
w('baseline: work_log_len=%d  proto.status=%s  page(stage=%s,%s)' % (
    wl0, pg0.prototype.status, pg0.current_stage, pg0.stage_status))

start = time.time()
last = None
while True:
    pg = ModaoPage.objects.get(pk=page_id)
    p = pg.prototype
    wl = len(pg.work_log or '')
    sig = (pg.current_stage, pg.stage_status, p.status,
           len(pg.page_testpoints_json or ''), len(pg.page_testcases_json or ''), wl)
    if sig != last:
        w('t=%-4ds page(stage=%s,%s) proto=%s tp=%d tc=%d worklog=%d' % (
            int(time.time() - start), pg.current_stage, pg.stage_status,
            p.status, sig[3], sig[4], wl))
        last = sig
    err = (pg.error_message or '').strip()
    if p.status != 'designing' and wl > wl0:
        w('FINISHED (proto=%s, work_log %d→%d)' % (p.status, wl0, wl))
        if err:
            w('  page.error=%s' % err[:500])
        if (p.error_message or '').strip():
            w('  proto.error=%s' % p.error_message.strip()[:500])
        break
    if pg.stage_status == 'failed' and wl > wl0:
        w('FAILED stage=%s err=%s' % (pg.current_stage, err[:500]))
        break
    if time.time() - start > timeout:
        w('TIMEOUT after %ds (proto=%s, work_log %d→%d) —— 可再次调用本脚本继续等'
          % (timeout, p.status, wl0, wl))
        break
    time.sleep(15)

pg = ModaoPage.objects.get(pk=page_id)
w('')
w('=== 最终字段长度 ===')
for f in FIELDS:
    w('  %-22s len=%d' % (f, len(getattr(pg, f, '') or '')))
w('  work_log tail: %s' % ((pg.work_log or '')[-300:].replace('\n', ' | ')))
