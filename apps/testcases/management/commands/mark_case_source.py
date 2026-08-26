from django.core.management.base import BaseCommand

from apps.testcases.models import TestCase


class Command(BaseCommand):
    help = (
        '批量标记用例来源（ai/manual/unknown）：\n'
        '  python manage.py mark_case_source --version-id 26 --source ai\n'
        '  python manage.py mark_case_source --project 5 --source manual\n'
        '  python manage.py mark_case_source --ids 1,2,3 --source ai'
    )

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True, choices=['ai', 'manual', 'unknown'])
        parser.add_argument('--version-id', dest='version_id', type=int, help='按版本标记')
        parser.add_argument('--project', type=int, help='按项目标记')
        parser.add_argument('--ids', help='按用例ID标记，逗号分隔')

    def handle(self, *args, **options):
        source = options['source']
        qs = TestCase.objects.all()
        if options['version_id']:
            qs = qs.filter(versions__id=options['version_id'])
        elif options['project']:
            qs = qs.filter(project_id=options['project'])
        elif options['ids']:
            ids = [int(x) for x in options['ids'].split(',') if x.strip()]
            qs = qs.filter(id__in=ids)
        else:
            self.stderr.write('请指定 --version-id / --project / --ids 之一')
            return
        total = qs.distinct().count()
        updated = qs.distinct().update(source=source)
        self.stdout.write(f'命中 {total} 条，已标记 {updated} 条为 {source}')
