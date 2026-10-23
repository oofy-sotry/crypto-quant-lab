import time
from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from market.minutes import BATCH_SIZE, collect_minutes
from market.models import Asset

PROGRESS_EVERY = 50_000  # 이 행 수마다 진행 상황 출력


class Command(BaseCommand):
    help = "업비트 1분봉을 수집한다. 기본은 활성 종목 전체의 최근 1일."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1, help="최근 며칠을 수집할지")
        parser.add_argument(
            "--asset", action="append", help="종목 코드(예: KRW-BTC). 여러 번 줄 수 있음"
        )
        parser.add_argument(
            "--to",
            help="이 시각(UTC, 예: 2026-03-01T00:00) 이전부터 받는다. 끊긴 백필을 이어 받을 때",
        )
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)

    def handle(self, *args, **options):
        assets = Asset.objects.filter(is_active=True)
        if options["asset"]:
            assets = assets.filter(symbol__in=options["asset"])
            missing = set(options["asset"]) - set(assets.values_list("symbol", flat=True))
            if missing:
                raise CommandError(f"없는 종목: {', '.join(sorted(missing))}")

        to = None
        if options["to"]:
            to = datetime.fromisoformat(options["to"]).replace(tzinfo=UTC)
        since = (to or timezone.now()) - timedelta(days=options["days"])

        for asset in assets:
            started = time.monotonic()
            next_report = PROGRESS_EVERY

            def report(saved, oldest, asset=asset, started=started):
                nonlocal next_report
                if saved >= next_report:
                    elapsed = time.monotonic() - started
                    self.stdout.write(
                        f"  {asset.symbol} {saved:,}행 "
                        f"({oldest:%Y-%m-%d %H:%M}까지), {elapsed:.0f}초"
                    )
                    next_report += PROGRESS_EVERY

            saved = collect_minutes(
                asset, since=since, to=to, batch_size=options["batch_size"], on_batch=report
            )
            elapsed = time.monotonic() - started
            self.stdout.write(
                f"[{asset.symbol}] 저장 {saved:,}행, {elapsed:.1f}초 "
                f"({saved / elapsed if elapsed else 0:,.0f}행/초)"
            )
