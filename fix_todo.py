import os, django, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()
from apps.ui_automation.models import Element, TestCase
from apps.ui_automation.smart_locator import smart_match_locator

for el in Element.objects.filter(locator_value='TODO_待补充控件定位器'):
    matched_strategy, matched_value = smart_match_locator(el.name)
    if matched_value:
        el.locator_value = matched_value
        el.save()
        print(f'Fixed: {el.name} -> {matched_value}')
    else:
        print(f'Not matched: {el.name}')

print('---')
for tc in TestCase.objects.order_by('-id')[:3]:
    for s in tc.steps.all().order_by('step_number'):
        el = s.element
        if el:
            print(f'Case {tc.id} Step {s.step_number}: {el.name} = {el.locator_value}')
