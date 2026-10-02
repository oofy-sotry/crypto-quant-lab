from datetime import date
from decimal import Decimal

import pytest

from market.models import Asset, DailyCandle
from market.services import upsert_candles
from market.upbit import Candle

TODAY = date(2026, 10, 2)


def candle(day: date, close: str = "105") -> Candle:
    return Candle(
        date=day,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal(close),
        volume=Decimal("10"),
        value=Decimal("1000"),
    )


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")  # 0005_seed_assets 마이그레이션으로 생성됨


@pytest.mark.django_db
def test_upsert_inserts_new_candles_and_marks_today_not_final(btc):
    count = upsert_candles(btc, [candle(date(2026, 10, 1)), candle(TODAY)], today=TODAY)

    assert count == 2
    saved = {c.date: c.is_final for c in DailyCandle.objects.filter(asset=btc)}
    assert saved == {date(2026, 10, 1): True, TODAY: False}


@pytest.mark.django_db
def test_upsert_is_idempotent_and_overwrites_values(btc):
    upsert_candles(btc, [candle(TODAY, close="105")], today=TODAY)
    # 다음 날 다시 수집: 같은 날짜가 마감된 값으로 덮어써져야 한다.
    upsert_candles(btc, [candle(TODAY, close="107.5")], today=date(2026, 10, 3))

    rows = DailyCandle.objects.filter(asset=btc)
    assert rows.count() == 1
    assert rows.get().close == Decimal("107.5")
    assert rows.get().is_final is True


@pytest.mark.django_db
def test_upsert_with_no_candles_does_nothing(btc):
    assert upsert_candles(btc, [], today=TODAY) == 0
