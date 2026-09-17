from django.db import migrations, models


class Migration(migrations.Migration):
    """AIExecutionRecord 增加模型消耗统计字段。

    回放模式的目标是"零模型"，所以必须能量化每次执行的花费：
      model_calls       调用了几次模型
      prompt_tokens     输入 token
      completion_tokens 输出 token
      tokens_estimated  True = 没有真实 usage，数字是按截图尺寸估算的
      replay_mode       True = 本次走的是固化回放
    """

    dependencies = [
        ('ui_automation', '0012_aicase_steps_frozen_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiexecutionrecord',
            name='model_calls',
            field=models.IntegerField(default=0, verbose_name='模型调用次数'),
        ),
        migrations.AddField(
            model_name='aiexecutionrecord',
            name='prompt_tokens',
            field=models.IntegerField(default=0, verbose_name='输入 token'),
        ),
        migrations.AddField(
            model_name='aiexecutionrecord',
            name='completion_tokens',
            field=models.IntegerField(default=0, verbose_name='输出 token'),
        ),
        migrations.AddField(
            model_name='aiexecutionrecord',
            name='tokens_estimated',
            field=models.BooleanField(
                default=False,
                help_text='True 表示没有拿到接口返回的真实 usage，数字是按截图尺寸估算的',
                verbose_name='token 为估算值',
            ),
        ),
        migrations.AddField(
            model_name='aiexecutionrecord',
            name='replay_mode',
            field=models.BooleanField(
                default=False,
                help_text='True 表示本次执行走的是固化回放，理论上不调用视觉模型',
                verbose_name='纯坐标回放',
            ),
        ),
        # 执行代码里一直在写 error_message，但模型上没有这个字段 —— 补上，
        # 否则 save() 会因为未知字段直接抛异常。
        migrations.AddField(
            model_name='aiexecutionrecord',
            name='error_message',
            field=models.TextField(blank=True, default='', verbose_name='错误信息'),
        ),
    ]
