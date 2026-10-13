"""Verify the runtime state of the rebuilt PRODUCTION backend image (2026-10-13).

Run inside the container:
    docker cp scripts/_verify_img.py testhub-backend:/tmp/_verify_img.py
    docker exec testhub-backend python /tmp/_verify_img.py
    docker exec testhub-backend cat /tmp/_verify_img.txt

Why a file: `docker exec python -c "..."` output is NOT captured by the
rebuild script's Add-Content logger, so those checks appeared empty in the log.
"""
import io
import os
import sys

OUT = []


def w(msg):
    OUT.append(str(msg))


def main():
    sys.path.insert(0, '/app')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

    w('=== 1. zentao coverage judge constants (expect 600 / 600 / 0.0) ===')
    try:
        import django
        django.setup()
        from apps.zentao import services as s
        w('JUDGE_CASE_CHARS=%s' % s.JUDGE_CASE_CHARS)
        w('JUDGE_BUG_CHARS=%s' % s.JUDGE_BUG_CHARS)
        w('JUDGE_TEMPERATURE=%s' % s.JUDGE_TEMPERATURE)
        ok = (s.JUDGE_CASE_CHARS == 600 and s.JUDGE_BUG_CHARS == 600
              and float(s.JUDGE_TEMPERATURE) == 0.0)
        w('RESULT=%s' % ('OK' if ok else 'MISMATCH'))
    except Exception as exc:  # noqa: BLE001
        w('ERROR %s: %s' % (type(exc).__name__, exc))

    w('')
    w('=== 2. PromptConfig active lengths (expect writer 3089 / reviewer 1012 / analyzer 1466) ===')
    try:
        from apps.requirement_analysis.models import PromptConfig
        qs = PromptConfig.objects.filter(is_active=True).order_by('prompt_type')
        if not qs.exists():
            w('NO ACTIVE PromptConfig')
        for p in qs:
            w('%s len=%d' % (p.prompt_type, len(p.content or '')))
    except Exception as exc:  # noqa: BLE001
        w('ERROR %s: %s' % (type(exc).__name__, exc))

    w('')
    w('=== 3. ProjectKnowledge (expect global>=16 / confirmed>=16 after report#29 promote) ===')
    try:
        from apps.projects.models import ProjectKnowledge
        w('total=%d' % ProjectKnowledge.objects.count())
        w('global(version is null)=%d' % ProjectKnowledge.objects.filter(version__isnull=True).count())
        w('confirmed(needs_review=False)=%d' % ProjectKnowledge.objects.filter(needs_review=False).count())
        w('pending(needs_review=True)=%d' % ProjectKnowledge.objects.filter(needs_review=True).count())
    except Exception as exc:  # noqa: BLE001
        w('ERROR %s: %s' % (type(exc).__name__, exc))

    w('')
    w('=== 4. prompt file md5 baked into the image ===')
    import hashlib
    targets = [
        '/app/tester.md',
        '/app/tester_pro.md',
        '/app/apps/requirement_analysis/independent_skill/prompts/tester.md',
        '/app/apps/requirement_analysis/independent_skill/prompts/tester_pro.md',
        '/app/apps/zentao/services.py',
    ]
    for path in targets:
        try:
            with open(path, 'rb') as fh:
                w('%s %s' % (hashlib.md5(fh.read()).hexdigest().upper(), path))
        except Exception as exc:  # noqa: BLE001
            w('MISSING %s (%s)' % (path, exc))

    with io.open('/tmp/_verify_img.txt', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(OUT))
    print('written /tmp/_verify_img.txt (%d lines)' % len(OUT))


if __name__ == '__main__':
    main()
