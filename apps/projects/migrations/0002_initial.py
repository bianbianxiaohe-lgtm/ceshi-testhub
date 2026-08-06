# Generated migration - projects 0002
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0001_initial'),
    ]
    operations = [
        migrations.AddField(
            model_name='project',
            name='members',
            field=models.ManyToManyField(blank=True, related_name='projects', to='users.user', verbose_name='成员'),
        ),
    ]
