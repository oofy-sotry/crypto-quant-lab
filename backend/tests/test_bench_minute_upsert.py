from io import StringIO

import pytest
from django.core.management import call_command

from market.management.commands.bench_minute_upsert import BENCH_SYMBOL, synthetic_bars
from market.models import Asset, MinuteCandle


def test_synthetic_bars_are_valid_ohlc_one_minute_apart():
    bars = synthetic_bars(3)

    assert [(b.ts - bars[0].ts).seconds for b in bars] == [0, 60, 120]
    assert all(b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close) for b in bars)


# VACUUM은 트랜잭션 안에서 못 돌아서 테스트를 트랜잭션으로 감싸지 않는다.
@pytest.mark.django_db(transaction=True)
def test_bench_minute_upsert_reports_and_cleans_up():
    out = StringIO()

    call_command(
        "bench_minute_upsert", "--rows", "10", "--batch-sizes", "3", "--repeat", "1", stdout=out
    )

    assert "        3 |" in out.getvalue()
    assert not Asset.objects.filter(symbol=BENCH_SYMBOL).exists()
    assert MinuteCandle.objects.count() == 0
