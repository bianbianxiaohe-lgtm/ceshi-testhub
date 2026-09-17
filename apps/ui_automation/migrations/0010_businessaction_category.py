from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0009_appdevice_wda'),
    ]

    operations = [
        migrations.AddField(
            model_name='businessaction',
            name='category',
            field=models.CharField(
                choices=[
                    ('precondition', '前置准备'),
                    ('business', '业务操作'),
                    ('extract', '数据提取'),
                    ('teardown', '收尾清理'),
                    ('other', '其他'),
                ],
                default='business',
                help_text='前置准备=登录/切账号等；业务操作=下单/搜索等；收尾清理=退出登录',
                max_length=20,
                verbose_name='分类',
            ),
        ),
    ]
