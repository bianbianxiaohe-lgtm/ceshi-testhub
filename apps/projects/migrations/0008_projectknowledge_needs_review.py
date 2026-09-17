from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0007_remove_project_idx_project_owner_and_more'),
    ]

    operations = [
        # 知识沉淀待复核机制：新增 needs_review 字段，默认 False（存量条目视为已确认）
        migrations.AddField(
            model_name='projectknowledge',
            name='needs_review',
            field=models.BooleanField(
                default=False,
                help_text='自动沉淀（来源=zentao_coverage）的条目默认待复核，'
                          '人工确认前不进入向量召回；手动创建默认为 False',
                verbose_name='待复核',
            ),
        ),
    ]
