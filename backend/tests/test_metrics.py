import math

import pandas as pd
import pytest

from backtest.metrics import compute_metrics


def frame(strategy_returns, positions):
    returns = pd.Series(strategy_returns, dtype=float)
    return pd.DataFrame(
        {
            "strategy_return": returns,
            "equity": (1 + returns).cumprod(),
            "position": pd.Series(positions, dtype=float),
        }
    )


def test_metrics_match_hand_calculation():
    # 자산: 1.1 → 0.99 → 1.089 → 1.089
    metrics = compute_metrics(frame([0.1, -0.1, 0.1, 0.0], [1, 1, 1, 1]))

    assert metrics["total_return"] == pytest.approx(0.089)
    # 고점 1.1에서 0.99까지 -10%
    assert metrics["max_drawdown"] == pytest.approx(-0.1)
    # 4일 → 4/365년
    assert metrics["cagr"] == pytest.approx(1.089 ** (365 / 4) - 1)
    returns = pd.Series([0.1, -0.1, 0.1, 0.0])
    assert metrics["sharpe"] == pytest.approx(returns.mean() / returns.std() * math.sqrt(365))
    assert metrics["trades"] == 1
    assert metrics["exposure"] == 1.0


def test_drawdown_counts_drop_from_starting_capital():
    # 첫날부터 -20% → 시작 자산 1.0 대비 낙폭 -20%
    metrics = compute_metrics(frame([-0.2, 0.1], [1, 1]))

    assert metrics["max_drawdown"] == pytest.approx(-0.2)


def test_trades_and_win_rate_per_round_trip():
    # 거래1: +10%, +10% → 이익 / 현금 / 거래2: -5% → 손실
    metrics = compute_metrics(frame([0.1, 0.1, 0.0, -0.05], [1, 1, 0, 1]))

    assert metrics["trades"] == 2
    assert metrics["win_rate"] == 0.5
    assert metrics["exposure"] == 0.75


def test_win_rate_includes_exit_fee():
    # 보유 중 +0.03%였지만, 판 날(포지션 0) 수수료 -0.05%까지 넣으면 손실 거래다.
    metrics = compute_metrics(frame([0.0003, -0.0005, 0.0], [1, 0, 0]))

    assert metrics["trades"] == 1
    assert metrics["win_rate"] == 0.0


def test_no_trades_gives_zero_sharpe_and_win_rate():
    metrics = compute_metrics(frame([0.0, 0.0, 0.0], [0, 0, 0]))

    assert metrics["trades"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["sharpe"] == 0.0
    assert metrics["total_return"] == 0.0
