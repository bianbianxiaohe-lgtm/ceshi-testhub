# -*- coding: utf-8 -*-
"""验证「提示词文件 → PromptConfig(DB)」是否真正同步（内容级，不只看长度）。

背景：运行期通过 FK writer_prompt_config / reviewer_prompt_config 读 DB 的
PromptConfig，不是读 md 文件。所以「文件改了」不等于「生效了」，必须比对内容。

容器侧用法：
  docker cp scripts/_verify_prompt_sync.py <容器>:/tmp/
  docker exec <容器> python /tmp/_verify_prompt_sync.py
  docker exec <容器> cat /tmp/_verify_prompt_sync.txt

判据：每个类型的 DB content md5 == 对应提示词文件 md5 ⇒ RESULT=SYNCED。
analyzer 是人工定制版（1466 字符），与文件不同属**预期**，单独标记 CUSTOM。
"""
import hashlib
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django  # noqa: E402

django.setup()

from django.apps import apps as django_apps  # noqa: E402

OUT = '/tmp/_verify_prompt_sync.txt'
lines = []

FILE_MAP = {
    'writer': 'tester.md',
    'reviewer': 'tester_pro.md',
    'analyzer': 'tester_analyzer.md',
}
PROMPTS_DIR = '/app/apps/requirement_analysis/independent_skill/prompts/'

# 2026-10-13 新增章节锚点串：出现在 DB content 里才算「新提示词已进入运行链路」。
# ⚠️ 关键词必须取自提示词文件的真实文本，不要凭印象写（曾把 4.1 写成「同域变体」，
#    文件里实际是「重复 / 再进入」变体，导致误报 MISSING）。
FEATURES = {
    'writer': [
        ('4.1 重复/再进入变体', '再进入'),
        ('4.2 交互时序与并发', '交互时序与并发'),
        ('4.3 状态迁移与权益边界', '状态迁移与权益边界'),
        ('4.4 预期结果必须可判伪', '预期结果必须可判伪'),
        ('4.5 交付自检清单', '交付自检清单'),
    ],
    'reviewer': [
        ('高发维度1 重复/再进入变体', '重复/再进入变体'),
        ('高发维度2 交互时序', '交互时序'),
        ('高发维度3 状态迁移与权益边界', '状态迁移与权益边界'),
        ('可判伪检查', '预期结果是否可判伪'),
        ('高发维度缺失清单', '高发维度缺失清单'),
    ],
}

# analyzer 是人工定制版（DB 1466 字符 ≠ 文件 1959），差异属预期，不得判为 MISMATCH
CUSTOM_KEEP = {'analyzer'}


def w(msg=''):
    lines.append(str(msg))
    print(msg)


def md5(text):
    # 文本口径：与 update_prompt_configs.py 一致（open(encoding='utf-8').read()，
    # universal newlines 会把 \r\n 归一为 \n），故与 md5sum 的原始字节 md5 可能不同。
    return hashlib.md5(text.encode('utf-8')).hexdigest().upper()


def md5_bin(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest().upper()


def main():
    model = None
    for cfg in django_apps.get_models():
        if cfg.__name__ == 'PromptConfig':
            model = cfg
            break
    if model is None:
        w('ERROR: PromptConfig 模型未找到')
        return

    field_names = {f.name for f in model._meta.fields}
    content_field = next((c for c in ('content', 'prompt_content', 'prompt')
                          if c in field_names), None)
    if not content_field:
        w('ERROR: 找不到内容字段 fields=%s' % sorted(field_names))
        return
    has_active = 'is_active' in field_names
    time_field = next((t for t in ('updated_at', 'update_time', 'modified_at')
                       if t in field_names), None)

    w('PromptConfig db_table=%s content=%s is_active=%s time=%s'
      % (model._meta.db_table, content_field, has_active, time_field))
    w('')

    bad = 0
    for ptype, fname in FILE_MAP.items():
        path = os.path.join(PROMPTS_DIR, fname)
        if not os.path.exists(path):
            w('[%s] FILE MISSING %s' % (ptype, path))
            bad += 1
            continue
        ftext = open(path, encoding='utf-8').read()
        fmd5 = md5(ftext)
        fbin = md5_bin(path)

        qs = model.objects.all()
        if 'prompt_type' in field_names:
            qs = qs.filter(prompt_type=ptype)
        if has_active:
            qs = qs.filter(is_active=True)
        rows = list(qs.order_by('id'))
        if not rows:
            w('[%s] DB 无 active 记录 (file md5=%s len=%d)' % (ptype, fmd5, len(ftext)))
            bad += 1
            continue

        for obj in rows:
            ctext = getattr(obj, content_field) or ''
            cmd5 = md5(ctext)
            same = (cmd5 == fmd5)
            custom = (not same) and ptype in CUSTOM_KEEP
            if same:
                tag = 'SYNCED  '
            elif custom:
                tag = 'CUSTOM  '
                w('       [预期差异] analyzer 为人工定制版，DB 内容 ≠ 文件属正常；'
                  '切勿执行 update_prompt_configs.py analyzer 覆盖')
            else:
                tag = 'MISMATCH'
                bad += 1
            tval = getattr(obj, time_field) if time_field else None
            w('[%s] id=%-3s %s file(text-md5=%s bin-md5=%s len=%d) db(md5=%s len=%d)'
              % (ptype, obj.id, tag, fmd5[:8], fbin[:8], len(ftext), cmd5[:8], len(ctext)))
            # ⚠️ updated_at 不能当同步判据：update_prompt_configs.py 用
            #    save(update_fields=['content'])，auto_now 的 updated_at 不会被刷新。
            w('       %s=%s (不代表同步时间，见脚本注释)' % (time_field or 'time', tval))
            w('       db_head=%r' % ctext[:60].replace('\n', '\\n'))

            # 锚点串：必须出现在 DB content 里（证明新提示词真的进了运行链路）
            if ptype in FEATURES and not custom:
                for label, needle in FEATURES[ptype]:
                    hit = needle in ctext
                    w('       feature %-24s %-14s %s'
                      % (label, needle, 'OK' if hit else 'MISSING'))
                    if not hit:
                        bad += 1

    # 生成任务实际引用的 FK：确认指向的是上面这批 active 记录
    w('')
    w('--- 生成任务实际引用的 PromptConfig ---')
    task_model = None
    for cfg in django_apps.get_models():
        if cfg.__name__ in ('TestCaseGenerationTask', 'IndependentCaseTask',
                            'RequirementAnalysisTask'):
            task_model = cfg
            break
    if task_model is None:
        w('(未找到生成任务模型，跳过)')
    else:
        tf = {f.name for f in task_model._meta.fields}
        w('模型=%s 字段含 writer=%s reviewer=%s'
          % (task_model.__name__, 'writer_prompt_config' in tf,
             'reviewer_prompt_config' in tf))
        if 'writer_prompt_config' in tf:
            order = '-id'
            try:
                recent = list(task_model.objects.all().order_by(order)[:5])
            except Exception:
                recent = []
            for t in recent:
                wf = getattr(t, 'writer_prompt_config_id', None)
                rf = getattr(t, 'reviewer_prompt_config_id', None)
                w('task id=%s writer_fk=%s reviewer_fk=%s'
                  % (t.id, wf, rf))
            ids = [getattr(t, 'writer_prompt_config_id', None) for t in recent]
            if not ids:
                w('(暂无生成任务记录)')

    w('')
    w('RESULT=%s' % ('SYNCED' if bad == 0 else 'MISMATCH(%d)' % bad))


try:
    main()
except Exception as exc:  # noqa: BLE001
    import traceback
    w('ERROR: %s' % exc)
    w(traceback.format_exc())
finally:
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
