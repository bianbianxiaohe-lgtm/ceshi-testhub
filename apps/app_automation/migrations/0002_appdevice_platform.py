from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_automation', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='appdevice',
            name='platform',
            field=models.CharField(
                choices=[('android', 'Android'), ('ios', 'iOS')],
                default='android',
                max_length=20,
                verbose_name='平台',
            ),
        ),
        migrations.AlterField(
            model_name='appdevice',
            name='android_version',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='系统版本'),
        ),
    ]
