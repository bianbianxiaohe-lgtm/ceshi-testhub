# Generated migration for midscene_web execution mode

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ui_automation', '0006_business_action'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aicase',
            name='execution_mode',
            field=models.CharField(
                choices=[
                    ('text', '文本模式(browser-use)'),
                    ('midscene', 'Midscene APP 自动化'),
                    ('midscene_web', 'Midscene Web 自动化'),
                ],
                default='text',
                help_text='text=浏览器文本模式；midscene=Midscene 真机 APP 自动化；midscene_web=Midscene Web 浏览器自动化',
                max_length=20,
                verbose_name='执行模式'
            ),
        ),
        migrations.AlterField(
            model_name='aiexecutionrecord',
            name='execution_mode',
            field=models.CharField(
                choices=[
                    ('text', '文本模式'),
                    ('midscene', 'Midscene APP 自动化'),
                    ('midscene_web', 'Midscene Web 自动化'),
                ],
                default='text',
                max_length=20,
                verbose_name='执行模式'
            ),
        ),
    ]
