import pandas as pd
import pytest

from backtest.strategies import buy_and_hold, ma_cross


def series(values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values)), dtype=float)


def test_buy_and_hold_always_holds():
    assert buy_and_hold(series([1, 2, 3])).tolist() == [1.0, 1.0, 1.0]


def test_ma_cross_holds_when_short_ma_above_long_ma():
    # short=1(종가 자체), long=3
    # 3일 이동평균: [nan, nan, 2, 3, 3.33, 3]
    close = series([1, 2, 3, 4, 3, 2])

    signal = ma_cross(close, short=1, long=3)

    # 워밍업 2일은 현금, 4>3 / 3<3.33 / 2<3
    assert signal.tolist() == [0.0, 0.0, 1.0, 1.0, 0.0, 0.0]


def test_ma_cross_rejects_invalid_windows():
    with pytest.raises(ValueError):
        ma_cross(series([1, 2, 3]), short=5, long=3)
