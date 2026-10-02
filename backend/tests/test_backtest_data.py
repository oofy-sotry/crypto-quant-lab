from datetime import date, timedelta
from decimal import Decimal

import pytest

from backtest.data import DataNotReady, load_close
from market.models import Asset, DailyCandle, IntegrityIssue

FIRST = date(2026, 1, 1)


@pytest.fixture
def btc():
    asset = Asset.objects.get(symbol="KRW-BTC")
    DailyCandle.objects.bulk_create(
        DailyCandle(
            asset=asset,
            date=FIRST + timedelta(days=i),
            open=Decimal(100 + i),
            high=Decimal(100 + i),
            low=Decimal(100 + i),
            close=Decimal(100 + i),
            volume=Decimal(1),
            value=Decimal(1),
            is_final=True,
        )
        for i in range(30)  # 1/1 ~ 1/30
    )
    return asset


@pytest.mark.django_db
def test_load_close_includes_warmup_and_previous_day(btc):
    close = load_close(btc, start=date(2026, 1, 10), end=date(2026, 1, 20), warmup_days=5)

    # 1/10 - 5일 - 1일 = 1/4 부터
    assert close.index[0].date() == date(2026, 1, 4)
    assert close.index[-1].date() == date(2026, 1, 20)
    assert close.dtype == float
    assert close.iloc[0] == 103.0


@pytest.mark.django_db
def test_load_close_rejects_unresolved_error_in_range(btc):
    IntegrityIssue.objects.create(
        asset=btc, date=date(2026, 1, 15), type="missing", severity="error"
    )

    with pytest.raises(DataNotReady, match="2026-01-15"):
        load_close(btc, start=date(2026, 1, 10), end=date(2026, 1, 20))


@pytest.mark.django_db
def test_load_close_ignores_resolved_errors_and_warnings(btc):
    IntegrityIssue.objects.create(
        asset=btc,
        date=date(2026, 1, 15),
        type="missing",
        severity="error",
        resolved_at="2026-01-16T00:00Z",
        note="원본에도 없음",
    )
    IntegrityIssue.objects.create(
        asset=btc, date=date(2026, 1, 16), type="spike", severity="warning"
    )

    assert len(load_close(btc, start=date(2026, 1, 10), end=date(2026, 1, 20))) == 12


@pytest.mark.django_db
def test_load_close_rejects_insufficient_warmup(btc):
    with pytest.raises(DataNotReady, match="워밍업"):
        load_close(btc, start=date(2026, 1, 3), end=date(2026, 1, 20), warmup_days=5)


@pytest.mark.django_db
def test_load_close_rejects_end_after_last_final_candle(btc):
    with pytest.raises(DataNotReady, match="확정된 일봉"):
        load_close(btc, start=date(2026, 1, 10), end=date(2026, 2, 5))
