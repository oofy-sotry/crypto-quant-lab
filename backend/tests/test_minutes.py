from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from market.minutes import upsert_minute_candles
from market.models import Asset, MinuteCandle
from market.upbit import MinuteBar

T0 = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


def bar(ts: datetime, close: str = "105") -> MinuteBar:
    return MinuteBar(
        ts=ts,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal(close),
        volume=Decimal("0.5"),
        value=Decimal("52.5"),
    )


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")  # 0005_seed_assets 마이그레이션으로 생성됨


@pytest.mark.django_db
def test_upsert_minute_candles_splits_into_batches(btc, django_assert_num_queries):
    bars = [bar(T0 + timedelta(minutes=i)) for i in range(5)]

    # 5행을 2행씩 → INSERT 3번
    with django_assert_num_queries(3):
        assert upsert_minute_candles(btc, bars, batch_size=2) == 5

    assert MinuteCandle.objects.filter(asset=btc).count() == 5


@pytest.mark.django_db
def test_upsert_minute_candles_is_idempotent_and_overwrites(btc):
    upsert_minute_candles(btc, [bar(T0, close="105")])
    upsert_minute_candles(btc, [bar(T0, close="106.5")])

    rows = MinuteCandle.objects.filter(asset=btc)
    assert rows.count() == 1
    assert rows.get().close == Decimal("106.5")
    assert rows.get().ts == T0


@pytest.mark.django_db
def test_upsert_minute_candles_with_no_bars_does_nothing(btc):
    assert upsert_minute_candles(btc, []) == 0
