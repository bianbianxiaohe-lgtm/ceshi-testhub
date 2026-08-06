import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from apps.ui_automation.models import Element
from apps.ui_automation.smart_locator import smart_match_locator

# 手动修复所有 TODO 元素
for el in Element.objects.filter(locator_value='TODO_待补充控件定位器'):
    matched = smart_match_locator(el.name)
    if matched and matched[1]:
        el.locator_value = matched[1]
        el.save()
        print(f'Fixed: {el.name} -> {matched[1]}')
    else:
        print(f'Not matched: {el.name}')

# 再检查一次
print('\nRemaining TODO:')
for el in Element.objects.filter(locator_value='TODO_待补充控件定位器'):
    print(f'  {el.name} (case id: {el.id})')
