import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()
from apps.ui_automation.models import Element
from apps.ui_automation.smart_locator import _load_kb, KB_FILE

# 删除旧 JSON 让 _load_kb 重新生成 DEFAULT
if os.path.exists(KB_FILE):
    os.remove(KB_FILE)
    print('removed old KB')

# 强制加载新 DEFAULT
kb = _load_kb()
print('new KB elements:', list(kb['万年历']['elements'].keys())[:10])

# 修复所有 TODO 元素
for el in Element.objects.filter(locator_value='TODO_待补充控件定位器'):
    from apps.ui_automation.smart_locator import smart_match_locator
    matched = smart_match_locator(el.name)
    if matched and matched[1]:
        el.locator_value = matched[1]
        el.save()
        print('Fixed:', el.name, '->', matched[1])
    else:
        print('Not matched:', el.name)

# 验证
for el in Element.objects.filter(locator_value='TODO_待补充控件定位器'):
    print('Still TODO:', el.name)
