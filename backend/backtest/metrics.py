"""백테스트 성과 지표.

코인은 365일 거래하므로 연율화에 365를 쓴다(주식은 보통 252 거래일).
"""

import math

import pandas as pd

PERIODS_PER_YEAR = 365


def compute_metrics(frame: pd.DataFrame) -> dict:
    """simulate() 결과로 지표를 계산한다. 비율 값은 소수(0.1 = 10%)로 돌려준다."""
    returns = frame["strategy_return"]
    equity = frame["equity"]
    position = frame["position"]
    days = len(frame)

    total_return = equity.iloc[-1] - 1
    years = days / PERIODS_PER_YEAR
    cagr = equity.iloc[-1] ** (1 / years) - 1 if equity.iloc[-1] > 0 else -1.0

    # 낙폭은 시작 자산(1.0)도 고점 후보로 본다. 첫날부터 떨어지는 경우를 놓치지 않기 위함.
    peak = equity.cummax().clip(lower=1.0)
    max_drawdown = (equity / peak - 1).min()

    std = returns.std(ddof=1)
    sharpe = returns.mean() / std * math.sqrt(PERIODS_PER_YEAR) if std > 0 else 0.0

    # 진입(0→양수)할 때마다 거래 번호를 붙여 거래별 수익률을 구한다.
    entries = (position > 0) & (position.shift(1, fill_value=0) == 0)
    trade_id = entries.cumsum().where(position > 0)
    trade_returns = (1 + returns).groupby(trade_id).prod() - 1
    trades = int(entries.sum())
    win_rate = float((trade_returns > 0).mean()) if trades else 0.0

    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "max_drawdown": float(max_drawdown),
        "sharpe": float(sharpe),
        "trades": trades,
        "win_rate": win_rate,
        "exposure": float(position.mean()),
        "days": days,
    }
