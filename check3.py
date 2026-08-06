import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask
m = getattr(TestCaseGenerationTask, '_build_confirmed_answers_context', None)
print("method:", m)
print("callable:", callable(m) if m else False)
