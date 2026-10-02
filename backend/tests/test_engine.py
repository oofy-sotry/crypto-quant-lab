import pandas as pd
import pytest

from backtest.engine import simulate
from backtest.strategies import ma_cross

DAYS = pd.date_range("2026-01-01", periods=6)


def series(values):
    return pd.Series(values, index=DAYS[: len(values)], dtype=float)


def test_simulate_shifts_signal_by_one_day_and_compounds_returns():
    close = series([100, 100, 110, 99, 99, 120])
    signal = series([1, 1, 1, 0, 0, 1])

    frame = simulate(close, signal, start=DAYS[1], fee=0.0)

    # 손계산
    # 날짜         1/2    1/3    1/4    1/5    1/6
    # 수익률       0      +10%   -10%   0      +21.2%
    # position    1      1      1      0      0      (전날 signal)
    # 전략 수익률   0      +10%   -10%   0      0
    # 자산         1.00   1.10   0.99   0.99   0.99
    assert frame["position"].tolist() == [1, 1, 1, 0, 0]
    assert frame["equity"].round(10).tolist() == [1.0, 1.1, 0.99, 0.99, 0.99]
    # 1/6에 +21.2%가 났지만 신호(1/5 종가 판단 = 0)를 따라 현금이라 수익을 못 먹는다.


def test_simulate_charges_fee_on_entry_and_exit():
    close = series([100, 100, 110, 99, 99, 120])
    signal = series([1, 1, 1, 0, 0, 1])

    frame = simulate(close, signal, start=DAYS[1], fee=0.001)

    # 1/2 진입(현금→보유): 0.1% 차감, 1/5 청산(보유→현금): 0.1% 차감
    assert frame["trade"].tolist() == [1, 0, 0, 1, 0]
    expected = (1 - 0.001) * 1.1 * 0.9 * (1 - 0.001)
    assert frame["equity"].iloc[-1] == pytest.approx(expected)


def test_future_prices_do_not_change_past_positions():
    """미래참조(look-ahead) 회귀 테스트: 미래 가격을 바꿔도 과거 포지션은 그대로여야 한다."""
    base = [100, 102, 101, 105, 107, 104, 110, 108, 111, 115]
    changed = base[:6] + [50, 300, 20, 400]  # 7번째 날(index 6)부터 미래를 크게 바꿈
    days = pd.date_range("2026-01-01", periods=len(base))
    close_a = pd.Series(base, index=days, dtype=float)
    close_b = pd.Series(changed, index=days, dtype=float)

    a = simulate(close_a, ma_cross(close_a, 2, 3), start=days[1])
    b = simulate(close_b, ma_cross(close_b, 2, 3), start=days[1])

    # position[t]는 t-1일까지의 가격만 보므로, index 6까지의 포지션은 같아야 한다.
    assert a["position"].loc[: days[6]].equals(b["position"].loc[: days[6]])


def test_simulate_requires_previous_day_before_start():
    close = series([100, 110])

    with pytest.raises(ValueError):
        simulate(close, series([1, 1]), start=DAYS[0])
