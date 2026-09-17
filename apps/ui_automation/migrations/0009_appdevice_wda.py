from django.db import migrations, models


class Migration(migrations.Migration):
    """AppDevice 增加 iOS 远端 WDA 连接字段（wda_host / wda_port）。

    用途：与已有的 adb_host 对称——iOS 真机的 WDA 服务跑在「插着手机的电脑」上，
    后端通过 http://<wda_host>:<wda_port> 远程驱动设备。
    """

    dependencies = [
        ('ui_automation', '0008_add_midscene_action_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='appdevice',
            name='wda_host',
            field=models.CharField(
                blank=True, default='',
                help_text='iOS 设备专用：手机USB所在电脑的 IP（如 192.168.8.71），该电脑需已跑通 WDA 并转发 8100 端口',
                max_length=50, verbose_name='WDA主机'),
        ),
        migrations.AddField(
            model_name='appdevice',
            name='wda_port',
            field=models.PositiveIntegerField(
                default=8100,
                help_text='iOS 设备专用：WDA 服务端口，默认 8100',
                verbose_name='WDA端口'),
        ),
    ]
