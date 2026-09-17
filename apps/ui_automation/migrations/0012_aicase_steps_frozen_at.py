from django.db import migrations, models


class Migration(migrations.Migration):
    """AICase 增加 steps_frozen_at。

    第一次用自然语言跑通后，每一步「点哪里」就已经知道了。把坐标写回
    steps 并记下时间戳，之后的回放只按坐标操作，不再调用视觉模型。
    为空表示还没固化（仍走 AI 探索模式）。
    """

    dependencies = [
        ('ui_automation', '0011_aicase_auto_dismiss_popup'),
    ]

    operations = [
        migrations.AddField(
            model_name='aicase',
            name='steps_frozen_at',
            field=models.DateTimeField(
                blank=True,
                help_text='非空表示 steps 里已带坐标，执行时走纯坐标回放（不调用视觉模型）',
                null=True,
                verbose_name='步骤固化时间',
            ),
        ),
    ]
