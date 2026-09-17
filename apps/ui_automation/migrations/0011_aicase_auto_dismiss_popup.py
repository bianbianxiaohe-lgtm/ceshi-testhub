from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0010_businessaction_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='aicase',
            name='auto_dismiss_popup',
            field=models.BooleanField(
                default=True,
                help_text='执行时遇到权限请求/协议/广告等弹窗自动关闭并重试该步骤',
                verbose_name='自动处理弹窗',
            ),
        ),
    ]
