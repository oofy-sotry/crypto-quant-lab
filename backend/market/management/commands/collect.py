from django.core.management.base import BaseCommand

from market.models import CollectionRun
from market.services import RECENT_DAYS, collect_candles


class Command(BaseCommand):
    help = "업비트 일봉을 수집한다. 기본은 최근 7일 재수집, --all이면 상장일부터 전체 백필."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--days", type=int, default=RECENT_DAYS, help="최근 며칠을 수집할지")
        group.add_argument("--all", action="store_true", help="상장일부터 전체 기간 백필")

    def handle(self, *args, **options):
        if options["all"]:
            run = collect_candles(CollectionRun.Trigger.BACKFILL, days=None)
        else:
            run = collect_candles(CollectionRun.Trigger.MANUAL, days=options["days"])

        self.stdout.write(
            f"[{run.status}] 종목 {run.assets_count}개, 저장 {run.upserted_count}건, "
            f"소요 {(run.finished_at - run.started_at).total_seconds():.1f}초"
        )
        if run.error_message:
            self.stderr.write(run.error_message)
