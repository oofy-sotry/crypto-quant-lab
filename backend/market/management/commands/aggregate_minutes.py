import time
from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Min
from django.utils import timezone

from market.aggregates import MODELS, aggregate_minutes
from market.models import Asset


def utc_midnight(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class Command(BaseCommand):
    help = (
        "분봉을 시간봉·일봉으로 집계한다. 기본은 활성 종목 전체의 최근 2일(UTC)."
        " 오늘(UTC)처럼 아직 끝나지 않은 날은 집계하지 않는다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=2, help="어제부터 거슬러 며칠을 집계할지")
        parser.add_argument("--all", action="store_true", help="종목의 첫 분봉 날부터 전부")
        parser.add_argument(
            "--asset", action="append", help="종목 코드(예: KRW-BTC). 여러 번 줄 수 있음"
        )

    def handle(self, *args, **options):
        assets = Asset.objects.filter(is_active=True)
        if options["asset"]:
            assets = assets.filter(symbol__in=options["asset"])
            missing = set(options["asset"]) - set(assets.values_list("symbol", flat=True))
            if missing:
                raise CommandError(f"없는 종목: {', '.join(sorted(missing))}")

        end = utc_midnight(timezone.now())  # 오늘 0시(UTC) 전까지 = 끝난 날만
        for asset in assets:
            if options["all"]:
                first = asset.minute_candles.aggregate(first=Min("ts"))["first"]
                if first is None:
                    self.stdout.write(f"[{asset.symbol}] 분봉 없음, 건너뜀")
                    continue
                start = utc_midnight(first)
            else:
                start = end - timedelta(days=options["days"])

            for unit in MODELS:
                started = time.monotonic()
                changed = aggregate_minutes(asset, unit, start, end)
                self.stdout.write(
                    f"[{asset.symbol}] {unit} {start:%Y-%m-%d}~{end - timedelta(days=1):%Y-%m-%d}"
                    f" 바뀐 행 {changed:,}, {time.monotonic() - started:.1f}초"
                )
