"""
Appium 移动端自动化测试执行引擎
用于驱动 Android/iOS 真机或模拟器执行 App 自动化测试
API 风格与 Selenium 完全一致，可直接复用现有 TestCase/TestCaseStep 模型
"""
import os
import time
import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.options.ios import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementNotInteractableException, WebDriverException
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)


class AppiumTestEngine:
    """Appium 移动端测试执行引擎"""

    # 定位策略映射：App 元素 → AppiumBy
    LOCATOR_MAP = {
        'id': AppiumBy.ID,
        'accessibility_id': AppiumBy.ACCESSIBILITY_ID,
        'xpath': AppiumBy.XPATH,
        'class_name': AppiumBy.CLASS_NAME,
        'uiautomator': AppiumBy.ANDROID_UIAUTOMATOR,
        'android_uiautomator': AppiumBy.ANDROID_UIAUTOMATOR,
        'ios_predicate': AppiumBy.IOS_PREDICATE,
        'ios_class_chain': AppiumBy.IOS_CLASS_CHAIN,
        'css': AppiumBy.XPATH,  # 兼容 Web 端遗留策略，降级为 xpath
        'name': AppiumBy.ACCESSIBILITY_ID,
    }

    # 支持的操作类型
    ACTION_TYPES = {
        'click': '点击',
        'tap': '点击',
        'double_tap': '双击',
        'long_press': '长按',
        'fill': '输入文本',
        'input': '输入文本',
        'clear': '清空输入',
        'swipe': '滑动',
        'scroll': '滚动',
        'screenshot': '截图',
        'wait': '等待',
        'assert': '断言',
        'getText': '获取文本',
        'launch_app': '启动App',
        'close_app': '关闭App',
        'back': '返回',
        'home': '回到主页',
        'switch_context': '切换上下文',
    }

    def __init__(self, appium_server_url='http://localhost:4723', platform='android',
                 device_udid=None, app_package=None, app_activity=None,
                 bundle_id=None, app_path=None, no_reset=True,
                 new_command_timeout=300):
        """
        初始化 Appium 测试引擎

        Args:
            appium_server_url: Appium Server 地址
            platform: 平台类型 (android / ios)
            device_udid: 设备 UDID
            app_package: Android 包名
            app_activity: Android 启动 Activity
            bundle_id: iOS Bundle ID
            app_path: APK/IPA 文件路径
            no_reset: 是否不清除 App 数据
            new_command_timeout: 命令超时(秒)
        """
        self.appium_server_url = appium_server_url
        self.platform = platform
        self.device_udid = device_udid
        self.app_package = app_package
        self.app_activity = app_activity
        self.bundle_id = bundle_id
        self.app_path = app_path
        self.no_reset = no_reset
        self.new_command_timeout = new_command_timeout
        self.driver = None
        self.screenshots = []

    # ==================== 设备连接管理 ====================

    def connect(self):
        """连接 Appium Server，创建 WebDriver 会话"""
        try:
            if self.platform == 'android':
                self.driver = self._create_android_driver()
            elif self.platform == 'ios':
                self.driver = self._create_ios_driver()
            else:
                raise ValueError(f"不支持的平台: {self.platform}")

            self.driver.implicitly_wait(10)
            logger.info(f"Appium 连接成功: {self.platform} - {self.device_udid}")
            print(f"✓ Appium 连接成功: {self.platform} 设备 {self.device_udid or '自动检测'}")
            return True

        except Exception as e:
            logger.error(f"Appium 连接失败: {str(e)}")
            print(f"✗ Appium 连接失败: {str(e)}")
            raise

    def _create_android_driver(self):
        """创建 Android WebDriver"""
        options = UiAutomator2Options()
        options.platform_name = 'Android'
        options.automation_name = 'UiAutomator2'
        options.no_reset = self.no_reset
        options.new_command_timeout = self.new_command_timeout

        if self.device_udid:
            options.udid = self.device_udid
        if self.app_package:
            options.app_package = self.app_package
        if self.app_activity:
            options.app_activity = self.app_activity
        if self.app_path:
            options.app = self.app_path

        # 额外优化配置
        options.set_capability('autoGrantPermissions', True)
        options.set_capability('skipServerInstallation', True)
        options.set_capability('skipDeviceInitialization', True)
        # 小米 HyperOS 上忽略隐藏 API 策略权限错误（否则会话创建直接失败）
        options.set_capability('appium:ignoreHiddenApiPolicyError', True)

        driver = webdriver.Remote(self.appium_server_url, options=options)
        # 小米 HyperOS 上 skipDeviceInitialization 会跳过 app 自动启动，
        # 需显式把已安装的 app 拉到前台，否则会话建好却停在系统桌面
        if self.app_package:
            try:
                driver.activate_app(self.app_package)
                logger.info(f"已显式唤起 App: {self.app_package}")
                print(f"✓ 已唤起 App: {self.app_package}")
            except Exception as e:
                logger.warning(f"activate_app 失败（将在执行步骤时重试）: {e}")
        return driver

    def _create_ios_driver(self):
        """创建 iOS WebDriver"""
        options = XCUITestOptions()
        options.platform_name = 'iOS'
        options.automation_name = 'XCUITest'
        options.no_reset = self.no_reset
        options.new_command_timeout = self.new_command_timeout

        if self.device_udid:
            options.udid = self.device_udid
        if self.bundle_id:
            options.bundle_id = self.bundle_id
        if self.app_path:
            options.app = self.app_path

        options.set_capability('autoAcceptAlerts', True)
        options.set_capability('skipLogCapture', True)

        return webdriver.Remote(self.appium_server_url, options=options)

    def disconnect(self):
        """关闭 WebDriver 会话"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Appium 会话已关闭")
                print("✓ Appium 会话已关闭")
            except Exception as e:
                logger.warning(f"关闭 Appium 会话时出错: {e}")
            finally:
                self.driver = None

    # ==================== 元素查找 ====================

    def find_element(self, locator_strategy, locator_value, timeout=10, element_name=None, element_id=None):
        """
        根据定位策略查找元素。找不到时自动 dump 页面，尝试匹配 element_name 更新定位器后重试。
        """
        by = self.LOCATOR_MAP.get(locator_strategy.lower(), AppiumBy.XPATH)
        try:
            wait = WebDriverWait(self.driver, timeout)
            return wait.until(EC.presence_of_element_located((by, locator_value)))
        except (TimeoutException, NoSuchElementException) as e:
            # 自动 dump + 更新 + 重试
            try:
                new_value = self._auto_learn_find(locator_value, element_name)
                if new_value and new_value != locator_value:
                    logger.info(f"[自动学习] '{element_name}' 定位器更新: {locator_value} -> {new_value}")
                    # 更新数据库
                    if element_id:
                        self._update_element_locator(element_id, new_value)
                    # 重试用新定位器
                    wait2 = WebDriverWait(self.driver, 3)
                    return wait2.until(EC.presence_of_element_located((by, new_value)))
            except Exception:
                pass
            raise e

    def _auto_learn_find(self, old_value, element_name):
        """dump 页面，查找匹配 element_name 的控件 resource-id"""
        from .smart_locator import dump_page_elements
        elements = dump_page_elements(self)
        name_lower = (element_name or '').lower()
        # 1. 精确匹配：element_name 出现在某个控件的 text 或 chinese_name 中
        for el in elements:
            txt = (el.get('text', '') or '').lower()
            cn = (el.get('chinese_name', '') or '').lower()
            val = el.get('value', '') or ''
            if val and not val.startswith('android:') and name_lower:
                if name_lower in txt or name_lower in cn or txt in name_lower or cn in name_lower:
                    return val
        # 2. fallback：如果只有一个有效的 resource-id，就用它
        valid = [e for e in elements if e.get('value') and not e['value'].startswith('android:')]
        if len(valid) == 1:
            return valid[0]['value']
        return None

    def _update_element_locator(self, element_id, new_value):
        """更新数据库 Element 定位器值"""
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("UPDATE ui_elements SET locator_value = %s WHERE id = %s", [new_value, element_id])
            logger.info(f"[DB更新] Element id={element_id} 更新为 {new_value}")
        except Exception as e:
            logger.warning(f"[DB更新] Element id={element_id} 失败: {e}")

    def find_element_safe(self, locator_strategy, locator_value, timeout=5, element_name=None, element_id=None):
        """安全查找元素，找不到返回 None"""
        try:
            return self.find_element(locator_strategy, locator_value, timeout, element_name, element_id)
        except (TimeoutException, NoSuchElementException):
            return None

    # ==================== 步骤执行 ====================

    def execute_step(self, step_data: dict) -> dict:
        """
        执行单个测试步骤

        Args:
            step_data: 步骤数据字典，包含:
                - step_number: 步骤序号
                - action_type: 操作类型
                - description: 步骤描述
                - input_value: 输入值
                - wait_time: 等待时间(ms)
                - assert_type: 断言类型
                - assert_value: 断言期望值
                - element: 元素信息 {locator_strategy, locator_value, name}

        Returns:
            {step_number, action_type, description, success, error, screenshot}
        """
        step_result = {
            'step_number': step_data.get('step_number', 0),
            'action_type': step_data.get('action_type', ''),
            'description': step_data.get('description', ''),
            'success': False,
            'error': None,
            'screenshot': None,
        }

        try:
            action_type = step_data.get('action_type', '').lower()
            element_data = step_data.get('element')
            input_value = step_data.get('input_value', '')
            wait_time = step_data.get('wait_time', 0) or 0
            assert_type = step_data.get('assert_type', '')
            assert_value = step_data.get('assert_value', '')

            # 执行前等待
            if wait_time > 0:
                time.sleep(wait_time / 1000.0)

            # 分发操作
            if action_type in ('click', 'tap'):
                self._do_click(element_data)
            elif action_type == 'double_tap':
                self._do_double_tap(element_data)
            elif action_type == 'long_press':
                self._do_long_press(element_data, input_value)
            elif action_type in ('fill', 'input'):
                self._do_input(element_data, input_value)
            elif action_type == 'clear':
                self._do_clear(element_data)
            elif action_type == 'swipe':
                self._do_swipe(element_data, input_value)
            elif action_type == 'scroll':
                self._do_scroll(element_data, input_value)
            elif action_type == 'screenshot':
                self._do_screenshot(step_result)
            elif action_type == 'wait':
                self._do_wait(input_value)
            elif action_type in ('assert', 'assert_visible', 'assert_text'):
                self._do_assert(element_data, assert_type, assert_value)
            elif action_type == 'getText':
                self._do_get_text(element_data, step_result)
            elif action_type == 'launch_app':
                self._do_launch_app()
            elif action_type == 'close_app':
                self._do_close_app()
            elif action_type == 'back':
                self.driver.back()
            elif action_type == 'home':
                self._do_home()
            else:
                # 尝试作为通用断言处理
                if assert_type:
                    self._do_assert(element_data, assert_type, assert_value)
                else:
                    raise ValueError(f"不支持的操作类型: {action_type}")

            step_result['success'] = True
            print(f"  ✓ 步骤 {step_result['step_number']}: {step_result['description']} - 成功")

        except Exception as e:
            error_msg = str(e)
            step_result['success'] = False
            step_result['error'] = error_msg
            print(f"  ✗ 步骤 {step_result['step_number']}: {step_result['description']} - 失败: {error_msg}")

            # 失败截图
            try:
                screenshot_base64 = self.driver.get_screenshot_as_base64()
                step_result['screenshot'] = f'data:image/png;base64,{screenshot_base64}'
            except:
                pass

        return step_result

    # ==================== 具体操作方法 ====================

    def _do_click(self, element_data):
        """点击元素：优先使用坐标点击（更可靠），回退到元素 click()"""
        if not element_data:
            raise ValueError("click 操作需要提供元素定位信息")
        cx = element_data.get('center_x')
        cy = element_data.get('center_y')
        # 有坐标时优先使用坐标 tap（Android 自定义 View / 容器类控件经常 el.click() 无效）
        # driver.tap 是 Appium WebDriver 原生方法，兼容性最好
        if cx is not None and cy is not None:
            try:
                self.driver.tap([(int(cx), int(cy))])
                return
            except Exception:
                pass  # 坐标点击失败，回退到元素点击
        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )
        el.click()

    def _do_double_tap(self, element_data):
        """双击元素（优先坐标点击）"""
        if not element_data:
            raise ValueError("double_tap 操作需要提供元素定位信息")
        cx = element_data.get('center_x')
        cy = element_data.get('center_y')
        if cx is not None and cy is not None:
            try:
                # 双击：快速连续两次 tap
                self.driver.tap([(int(cx), int(cy))])
                time.sleep(0.05)
                self.driver.tap([(int(cx), int(cy))])
                return
            except Exception:
                pass
        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )
        from appium.webdriver.common.touch_action import TouchAction
        action = TouchAction(self.driver)
        action.tap(el, count=2).perform()

    def _do_long_press(self, element_data, duration_str=''):
        """长按元素（优先坐标长按）"""
        if not element_data:
            raise ValueError("long_press 操作需要提供元素定位信息")
        cx = element_data.get('center_x')
        cy = element_data.get('center_y')
        if cx is not None and cy is not None:
            try:
                duration = int(duration_str) if duration_str else 1000
                # driver.tap 支持 duration 参数（毫秒），直接实现长按
                self.driver.tap([(int(cx), int(cy)), (int(cx), int(cy))], duration=duration)
                return
            except Exception:
                pass
        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )
        duration = int(duration_str) if duration_str else 1000
        from appium.webdriver.common.touch_action import TouchAction
        TouchAction(self.driver).long_press(el, duration=duration).release().perform()

    def _do_input(self, element_data, text):
        """输入文本"""
        if not element_data:
            raise ValueError("input 操作需要提供元素定位信息")
        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )
        el.clear()
        el.send_keys(text or '')

    def _do_clear(self, element_data):
        """清空输入框"""
        if not element_data:
            raise ValueError("clear 操作需要提供元素定位信息")
        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )
        el.clear()

    def _do_swipe(self, element_data, direction_or_coords=''):
        """
        滑动操作
        支持方向: up/down/left/right
        支持坐标: x1,y1,x2,y2
        """
        size = self.driver.get_window_size()
        w, h = size['width'], size['height']

        direction = (direction_or_coords or 'up').strip().lower()
        if direction in ('up', 'down', 'left', 'right'):
            # 按方向滑动
            if direction == 'up':
                start_x, start_y = w // 2, int(h * 0.8)
                end_x, end_y = w // 2, int(h * 0.2)
            elif direction == 'down':
                start_x, start_y = w // 2, int(h * 0.2)
                end_x, end_y = w // 2, int(h * 0.8)
            elif direction == 'left':
                start_x, start_y = int(w * 0.8), h // 2
                end_x, end_y = int(w * 0.2), h // 2
            else:  # right
                start_x, start_y = int(w * 0.2), h // 2
                end_x, end_y = int(w * 0.8), h // 2
        else:
            # 按坐标滑动: "x1,y1,x2,y2"
            parts = direction_or_coords.replace(' ', '').split(',')
            if len(parts) == 4:
                start_x, start_y, end_x, end_y = map(int, parts)
            else:
                raise ValueError(f"无效的滑动参数: {direction_or_coords}")

        self.driver.swipe(start_x, start_y, end_x, end_y, duration=500)

    def _do_scroll(self, element_data, direction='down'):
        """滚动到指定元素或方向"""
        if element_data:
            # 滚动到元素可见
            el = self.find_element(
                element_data.get('locator_strategy', 'xpath'),
                element_data.get('locator_value', '')
            )
            # 使用移动端手势滚动到元素
            if self.platform == 'android':
                self.driver.execute_script(
                    'mobile: scrollGesture',
                    {'elementId': el.id, 'direction': direction or 'down', 'percent': 0.5}
                )
            else:
                self.driver.execute_script(
                    'mobile: scroll',
                    {'element': el.id, 'toVisible': True}
                )
        else:
            # 纯方向滚动
            self._do_swipe(None, direction or 'down')

    def _do_screenshot(self, step_result):
        """截图"""
        screenshot_base64 = self.driver.get_screenshot_as_base64()
        screenshot_url = f'data:image/png;base64,{screenshot_base64}'
        self.screenshots.append({
            'url': screenshot_url,
            'timestamp': datetime.now().isoformat(),
            'step_number': step_result['step_number'],
        })

    def _do_wait(self, seconds_str=''):
        """等待"""
        seconds = float(seconds_str) if seconds_str else 1.0
        time.sleep(seconds)

    def _do_assert(self, element_data, assert_type, assert_value):
        """断言检查"""
        if not element_data:
            raise ValueError("assert 操作需要提供元素定位信息")

        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )

        atype = (assert_type or 'exists').lower()

        if atype in ('exists', 'isvisible'):
            if not el.is_displayed():
                raise AssertionError(f"元素不可见: {element_data.get('name', 'unknown')}")

        elif atype == 'textcontains':
            actual_text = el.text or ''
            if assert_value not in actual_text:
                raise AssertionError(
                    f"文本不包含期望值 - 期望包含: '{assert_value}', 实际: '{actual_text}'"
                )

        elif atype == 'textequals':
            actual_text = el.text or ''
            if actual_text != assert_value:
                raise AssertionError(
                    f"文本不匹配 - 期望: '{assert_value}', 实际: '{actual_text}'"
                )

        elif atype == 'hasattribute':
            attr_name, _, attr_val = assert_value.partition('=')
            actual = el.get_attribute(attr_name.strip())
            if attr_val and actual != attr_val.strip():
                raise AssertionError(
                    f"属性值不匹配 - {attr_name}: 期望 '{attr_val.strip()}', 实际 '{actual}'"
                )

        elif atype == 'not_exists':
            el_safe = self.find_element_safe(
                element_data.get('locator_strategy', 'xpath'),
                element_data.get('locator_value', ''),
                timeout=2
            )
            if el_safe:
                raise AssertionError(f"元素不应存在但找到了: {element_data.get('name', 'unknown')}")

        else:
            # 默认：元素存在且可见
            if not el.is_displayed():
                raise AssertionError(f"断言失败: 元素不可见")

    def _do_get_text(self, element_data, step_result):
        """获取元素文本"""
        if not element_data:
            raise ValueError("getText 操作需要提供元素定位信息")
        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )
        text = el.text or ''
        step_result['extracted_text'] = text
        print(f"  ℹ 获取文本: '{text[:100]}'")

    def _do_launch_app(self):
        """启动 App"""
        if self.platform == 'android':
            self.driver.activate_app(self.app_package)
        else:
            self.driver.activate_app(self.bundle_id)

    def _do_close_app(self):
        """关闭 App"""
        if self.platform == 'android':
            self.driver.terminate_app(self.app_package)
        else:
            self.driver.terminate_app(self.bundle_id)

    def _do_home(self):
        """回到主页"""
        if self.platform == 'android':
            self.driver.press_keycode(3)  # KEYCODE_HOME
        else:
            self.driver.execute_script('mobile: pressButton', {'name': 'home'})

    # ==================== 工具方法 ====================

    @staticmethod
    def check_appium_available():
        """检查 Appium 环境是否可用"""
        try:
            import appium
            return True, None
        except ImportError:
            return False, (
                "Appium 客户端未安装。请执行: pip install Appium-Python-Client\n"
                "并确保 Appium Server 已启动: appium"
            )

    def get_page_source(self):
        """获取当前页面源码（XML）"""
        return self.driver.page_source if self.driver else ''

    def get_device_info(self):
        """获取设备信息"""
        if not self.driver:
            return {}
        try:
            return {
                'platform': self.platform,
                'device_name': self.driver.capabilities.get('deviceName', ''),
                'platform_version': self.driver.capabilities.get('platformVersion', ''),
                'udid': self.device_udid,
                'app_package': self.app_package or self.bundle_id,
                'screen_size': self.driver.get_window_size(),
            }
        except:
            return {}
