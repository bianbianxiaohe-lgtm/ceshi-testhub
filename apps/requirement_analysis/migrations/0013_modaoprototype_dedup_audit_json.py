from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('requirement_analysis', '0012_requirementanalysisresult_created_by_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='modaoprototype',
            name='dedup_audit_json',
            field=models.TextField(blank=True, default='[]', verbose_name='阶段3-去重审计记录'),
        ),
    ]
