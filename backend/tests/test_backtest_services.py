from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from backtest.data import DataNotReady
from backtest.models import BacktestRun
from backtest.services import normalize_params, params_hash, run_backtest
from market.models import Asset, DailyCandle

FIRST = date(2026, 1, 1)


@pytest.fixture
def btc():
    asset = Asset.objects.get(symbol="KRW-BTC")
    closes = [100 + (i % 7) * 3 - (i % 3) for i in range(60)]  # 오르내리는 가격
    DailyCandle.objects.bulk_create(
        DailyCandle(
            asset=asset,
            date=FIRST + timedelta(days=i),
            open=Decimal(c),
            high=Decimal(c),
            low=Decimal(c),
            close=Decimal(c),
            volume=Decimal(1),
            value=Decimal(1),
            is_final=True,
        )
        for i, c in enumerate(closes)
    )
    return asset


def ma_params(**overrides):
    values = {
        "symbol": "KRW-BTC",
        "strategy": "ma_cross",
        "start": date(2026, 1, 20),
        "end": date(2026, 2, 28),
        "short": 3,
        "long": 10,
    }
    values.update(overrides)
    return normalize_params(**values)


def test_normalize_params_drops_windows_for_buy_and_hold():
    a = normalize_params("KRW-BTC", "buy_and_hold", FIRST, FIRST, short=3, long=10)
    b = normalize_params("KRW-BTC", "buy_and_hold", FIRST, FIRST)

    assert a == b
    assert params_hash(a) == params_hash(b)


def test_normalize_params_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        normalize_params("KRW-BTC", "magic", FIRST, FIRST)


@pytest.mark.django_db
def test_run_backtest_computes_once_then_serves_cache(btc):
    first, first_cached = run_backtest(ma_params())
    second, second_cached = run_backtest(ma_params())

    assert (first_cached, second_cached) == (False, True)
    assert first == second
    assert BacktestRun.objects.count() == 1
    curve = first["equity_curve"]
    assert curve[0]["date"] == "2026-01-20"
    assert curve[-1]["date"] == "2026-02-28"
    assert set(first["metrics"]) >= {"total_return", "cagr", "max_drawdown", "sharpe"}


@pytest.mark.django_db
def test_run_backtest_falls_back_to_db_when_cache_is_empty(btc):
    run_backtest(ma_params())
    cache.clear()

    _, cached = run_backtest(ma_params())

    assert cached is True
    assert BacktestRun.objects.count() == 1


@pytest.mark.django_db
def test_new_data_changes_version_and_recomputes(btc):
    run_backtest(ma_params())
    # 재수집으로 collected_at이 바뀌면 데이터 버전이 바뀐다
    candle = btc.candles.order_by("-date").first()
    candle.save()

    _, cached = run_backtest(ma_params())

    assert cached is False
    assert BacktestRun.objects.count() == 2


@pytest.mark.django_db
def test_run_backtest_propagates_data_not_ready(btc):
    with pytest.raises(DataNotReady):
        run_backtest(ma_params(end=date(2026, 3, 31)))
