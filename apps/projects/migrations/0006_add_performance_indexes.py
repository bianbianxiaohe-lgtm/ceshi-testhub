# 手动编写的性能索引迁移
# 为 projects 应用的 Project 模型添加 2 个索引

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0005_project_owner_alter_project_description_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['owner'], name='idx_project_owner'),
        ),
        migrations.AddIndex(
            model_name='project',
            index=models.Index(fields=['status'], name='idx_project_status'),
        ),
    ]
