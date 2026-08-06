"""
验证「用例库 → 结构化 Appium 用例」转换器（TestCaseViewSet.convert-from-testcases）。

运行环境：在后端容器（mysqlclient/PyMySQL 正常的 Django 环境）中执行，例如：
    docker exec -it testhub-backend-1 python scripts/verify_convert_appium.py
或在本地环境（需 DB 驱动正常）执行：
    python scripts/verify_convert_appium.py

脚本会：
  1. 建一个带标记名称的临时 UiProject（验证后级联删除，不污染数据）
  2. 选取/创建一个用例库用例作为来源
  3. 直接调用转换 action，断言返回 success 且生成用例、步骤、占位元素
  4. 校验占位元素的 locator_value 为 'TODO_待补充控件定位器'
  5. 清理临时数据
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.contrib.auth import get_user_model
from apps.ui_automation.models import UiProject, TestCase as UiTestCase, Element
from apps.ui_automation.views import TestCaseViewSet
from apps.testcases.models import TestCase as LibTestCase
from apps.projects.models import Project

MARKER = '__verify_convert_appium__'


class FakeRequest:
    def __init__(self, data, user):
        self.data = data
        self.user = user


def main():
    User = get_user_model()
    user = User.objects.first()
    if not user:
        print('FAIL: 库中无任何用户，无法运行验证')
        sys.exit(1)

    proj_name = f'{MARKER}project'
    UiProject.objects.filter(name=proj_name).delete()
    ui_proj = UiProject.objects.create(name=proj_name, owner=user)

    created_src = False
    src = (
        LibTestCase.objects.exclude(steps__isnull=True)
        .exclude(steps='')
        .first()
    )
    if not src:
        proj = Project.objects.first()
        src = LibTestCase.objects.create(
            title=f'{MARKER}source',
            steps='1. 输入用户名:admin\n2. 点击登录按钮\n3. 验证首页欢迎语显示',
            expected_result='登录成功并展示欢迎语',
            priority='high',
            project=proj,
        )
        created_src = True

    try:
        req = FakeRequest(
            {'case_ids': [src.id], 'ui_project_id': ui_proj.id},
            user,
        )
        resp = TestCaseViewSet().convert_from_testcases(req)
        payload = resp.data
        print('RESPONSE:', payload)

        assert payload.get('success'), '转换返回 success=False'
        assert payload.get('count', 0) >= 1, '未生成任何用例'

        ui_case = UiTestCase.objects.get(name=src.title, project=ui_proj)
        steps = ui_case.steps.all().order_by('step_number')
        placeholders = Element.objects.filter(
            project=ui_proj, locator_value='TODO_待补充控件定位器'
        )
        assert steps.count() >= 1, '未生成步骤'
        assert placeholders.count() >= 1, '未生成占位元素'

        print(f'OK: 生成用例「{ui_case.name}」，步骤 {steps.count()} 条，占位元素 {placeholders.count()} 个')
        print('    步骤采样:')
        for s in steps:
            print(f'      #{s.step_number} {s.action_type} -> 元素[{s.element.name}] 定位器={s.element.locator_value}')

        # 重复转换应被去重（同项目同名跳过）
        resp2 = TestCaseViewSet().convert_from_testcases(req)
        assert resp2.data.get('count', 0) == 0, '重复转换未去重'
        print('OK: 重复转换正确去重（count=0）')

        print('\n验证全部通过 ✅')
    finally:
        UiProject.objects.filter(name=proj_name).delete()
        if created_src:
            src.delete()
        print('已清理临时数据。')


if __name__ == '__main__':
    main()
