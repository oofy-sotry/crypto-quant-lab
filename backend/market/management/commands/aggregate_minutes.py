import time
from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Min
from django.utils import timezone

from market.aggregates import MODELS, aggregate_minutes, delete_orphan_aggregates
from market.integrity import run_minute_checks
from market.models import Asset


def utc_midnight(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class Command(BaseCommand):
    help = (
        "분봉을 시간봉·일봉으로 집계하고 분봉 정합성 검사를 돌린다."
        " 기본은 활성 종목 전체의 최근 2일(UTC)."
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
        starts = []
        for asset in assets:
            if options["all"]:
                first = asset.minute_candles.aggregate(first=Min("ts"))["first"]
                if first is None:
                    self.stdout.write(f"[{asset.symbol}] 분봉 없음, 건너뜀")
                    continue
                start = utc_midnight(first)
            else:
                start = end - timedelta(days=options["days"])
            starts.append(start)

            for unit in MODELS:
                started = time.monotonic()
                changed = aggregate_minutes(asset, unit, start, end)
                # 분봉이 사라진 구간의 옛 집계도 지워 재처리(reprocess)와 같은 결과를 만든다.
                deleted = len(delete_orphan_aggregates(asset, unit, start, end))
                self.stdout.write(
                    f"[{asset.symbol}] {unit} {start:%Y-%m-%d}~{end - timedelta(days=1):%Y-%m-%d}"
                    f" 바뀐 행 {changed:,}, 삭제 {deleted:,}, {time.monotonic() - started:.1f}초"
                )

        if not starts:
            return
        # 빈 구간이 전 종목 공통인지 보려면 다른 종목도 함께 봐야 해서
        # 검사는 활성 종목 전체로 한다.
        first_day, last_day = min(starts).date(), (end - timedelta(days=1)).date()
        summary = run_minute_checks(first_day, last_day)
        for symbol, s in summary.items():
            self.stdout.write(
                f"[{symbol}] 분봉 검사 {first_day}~{last_day}: 새 이슈 {s['created']},"
                f" 다시 열림 {s['reopened']}, 해결 {s['resolved']}"
            )
