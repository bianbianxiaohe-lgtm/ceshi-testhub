import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.db import connection
from apps.defects.models import Defect
from apps.data_factory.models import DataFactoryRecord
from apps.analytics.models import AnalyticsEvent
from apps.app_automation.models import AppProject

cur = connection.cursor()
for p in ['defect%', 'data_factory%', 'analytics%', 'app_%']:
    cur.execute("SHOW TABLES LIKE %s", [p])
    rows = cur.fetchall()
    print(p, '->', len(rows), 'tables')

print('ORM OK: Defect / DataFactoryRecord / AnalyticsEvent / AppProject 均可导入')
print('Defect 字段:', [f.name for f in Defect._meta.fields][:6])
