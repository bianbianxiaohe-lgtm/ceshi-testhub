from django.core.management.base import BaseCommand

from apps.zentao.models import ZentaoConfig
from apps.zentao.services import sync_zentao_bugs


class Command(BaseCommand):
    help = '同步禅道 Bug：python manage.py zentao_sync --config 1 [--coverage]'

    def add_arguments(self, parser):
        parser.add_argument('--config', type=int, required=True, help='ZentaoConfig id')
        parser.add_argument('--coverage', action='store_true', help='同步后执行覆盖率分析')

    def handle(self, *args, **options):
        config = ZentaoConfig.objects.get(id=options['config'])
        log = sync_zentao_bugs(config)
        self.stdout.write(f'[sync] {log.status}: {log.message}')
        if options['coverage'] and log.status == 'success':
            from apps.zentao.services import run_coverage_analysis

            report = run_coverage_analysis(config)
            self.stdout.write(
                f'[coverage] {report.status}: 覆盖率 {report.coverage_rate}% '
                f'({report.covered_bugs}/{report.total_bugs})'
            )
