f=open('/app/apps/ui_automation/appium_engine.py');c=f.read();f.close()
old="""def _do_click(self, element_data):
        \"\"\"点击元素\"\"\"
        if not element_data:
            raise ValueError(\"click 操作需要提供元素定位信息\")
        el = self.find_element(
            element_data.get('locator_strategy', 'xpath'),
            element_data.get('locator_value', '')
        )
        el.click()"""
new="""def _do_click(self, element_data):
        \"\"\"点击元素，支持坐标 (x,y)\"\"\"
        if not element_data:
            raise ValueError(\"click 操作需要提供元素定位信息\")
        loc_val = element_data.get('locator_value', '')
        if loc_val.startswith('(') and loc_val.endswith(')'):
            parts = loc_val.strip('()').split(',')
            from appium.webdriver.common.touch_action import TouchAction
            TouchAction(self.driver).tap(x=int(parts[0]), y=int(parts[1])).perform()
        else:
            el = self.find_element(
                element_data.get('locator_strategy', 'xpath'),
                loc_val
            )
            el.click()"""
if old in c:
    c=c.replace(old,new)
    f=open('/app/apps/ui_automation/appium_engine.py','w');f.write(c);f.close()
    print('OK')
else:
    print('NOT FOUND')
