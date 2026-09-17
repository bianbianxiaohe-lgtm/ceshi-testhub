from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0007_add_midscene_web_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='testcasestep',
            name='action_type',
            field=models.CharField(choices=[
                ('click', '点击'),
                ('tap', '轻触'),
                ('double_tap', '双击'),
                ('long_press', '长按'),
                ('fill', '输入文本'),
                ('input', '输入'),
                ('clear', '清空'),
                ('getText', '获取文本'),
                ('waitFor', '等待元素'),
                ('hover', '悬停'),
                ('scroll', '滚动'),
                ('swipe', '滑动'),
                ('screenshot', '截图'),
                ('assert', '断言'),
                ('wait', '等待'),
                ('switchTab', '切换标签页'),
                ('launch_app', '启动应用'),
                ('close_app', '关闭应用'),
                ('back', '返回'),
                ('home', '主页'),
                ('aiAct', 'AI操作(Midscene)'),
                ('aiTap', 'AI点击(Midscene)'),
                ('aiInput', 'AI输入(Midscene)'),
                ('aiQuery', 'AI查询(Midscene)'),
                ('aiAssert', 'AI断言(Midscene)'),
                ('navigate', '导航(Midscene)'),
            ], max_length=20, verbose_name='操作类型'),
        ),
    ]
