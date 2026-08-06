import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

# 1. 检查 _build_confirmed_answers_context 在 TestCaseGenerationTask 上
from apps.requirement_analysis.models import TestCaseGenerationTask
print("_build_confirmed_answers_context:", getattr(TestCaseGenerationTask, '_build_confirmed_answers_context', None) is not None)
# 尝试调用（静态方法不需要实例）
try:
    r = TestCaseGenerationTask._build_confirmed_answers_context.__func__ if hasattr(TestCaseGenerationTask._build_confirmed_answers_context, '__func__') else TestCaseGenerationTask._build_confirmed_answers_context
    print("callable:", callable(r))
except Exception as e:
    print(f"error: {e}")

# 2. 列出所有注册的 URL pattern 中包含 auto-fill 或 knowledge 的
from django.urls import get_resolver
resolver = get_resolver()
for pattern in resolver.url_patterns:
    if hasattr(pattern, 'url_patterns'):
        for p in pattern.url_patterns:
            s = str(p.pattern)
            if 'auto' in s.lower() or 'knowledge' in s.lower() or 'fill' in s.lower():
                print(f"URL pattern: {s}")
