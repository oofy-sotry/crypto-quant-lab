import random
import statistics
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection

from market.minutes import upsert_minute_candles
from market.models import Asset, MinuteCandle
from market.upbit import MinuteBar

BENCH_SYMBOL = "BENCH-UPSERT"


def synthetic_bars(n: int, seed: int = 0) -> list[MinuteBar]:
    """실제 분봉과 자릿수가 비슷한 합성 데이터(가격 1억 원대, 거래량 소수 8자리)."""
    rng = random.Random(seed)
    start = datetime(2020, 1, 1, tzinfo=UTC)
    bars = []
    for i in range(n):
        o = Decimal(rng.randrange(100_000_000, 120_000_000))
        c = o + rng.randrange(-50_000, 50_000)
        volume = Decimal(rng.randrange(1, 10**9)) / 10**8
        bars.append(
            MinuteBar(
                ts=start + timedelta(minutes=i),
                open=o,
                high=max(o, c) + 1_000,
                low=min(o, c) - 1_000,
                close=c,
                volume=volume,
                value=(volume * c).quantize(Decimal("0.00000001")),
            )
        )
    return bars


class Command(BaseCommand):
    help = (
        "배치 크기별 분봉 upsert 속도를 잰다. 측정용 종목에만 쓰고 끝나면 지운다. "
        "실제 수집처럼 배치마다 커밋한다(autocommit)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--rows", type=int, default=100_000)
        parser.add_argument("--batch-sizes", type=int, nargs="+", default=[500, 2000, 5000])
        parser.add_argument("--repeat", type=int, default=3)

    def handle(self, *args, **options):
        n = options["rows"]
        bars = synthetic_bars(n)
        asset, _ = Asset.objects.get_or_create(
            symbol=BENCH_SYMBOL, defaults={"name": "측정용", "is_active": False}
        )
        table = MinuteCandle._meta.db_table
        self.stdout.write(
            f"테이블 기존 행 {MinuteCandle.objects.exclude(asset=asset).count():,}, "
            f"측정 {n:,}행 × {options['repeat']}회 (중앙값)"
        )
        self.stdout.write("배치 크기 | 새 행 INSERT 행/초 | 전부 충돌 upsert 행/초")
        try:
            for size in options["batch_sizes"]:
                inserts, conflicts = [], []
                for _ in range(options["repeat"]):
                    t = time.perf_counter()
                    upsert_minute_candles(asset, bars, batch_size=size)
                    inserts.append(n / (time.perf_counter() - t))

                    t = time.perf_counter()
                    upsert_minute_candles(asset, bars, batch_size=size)
                    conflicts.append(n / (time.perf_counter() - t))

                    self._cleanup(asset, table)
                self.stdout.write(
                    f"{size:>9,} | {statistics.median(inserts):>18,.0f} | "
                    f"{statistics.median(conflicts):>21,.0f}"
                )
        finally:
            self._cleanup(asset, table)
            asset.delete()

    def _cleanup(self, asset, table):
        # 지운 행(dead tuple)이 다음 측정을 느리게 하지 않도록 매번 VACUUM한다.
        MinuteCandle.objects.filter(asset=asset).delete()
        with connection.cursor() as cursor:
            cursor.execute(f"VACUUM {table}")
