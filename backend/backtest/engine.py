"""백테스트 시뮬레이션.

가정
- t일 종가에 신호를 계산하고, 그 신호로 t일 종가에 매매해 t+1일 수익률부터 반영된다.
  → position[t] = signal[t-1]  (shift(1): 미래 데이터를 미리 보는 오류 방지)
- 평가 시작일 직전에는 현금으로 시작한다. 시작일에 보유 중이면 진입 수수료를 낸다.
- 수수료는 포지션이 바뀐 날 |비중 변화| × fee 만큼 그날 수익률에서 뺀다.
"""

import pandas as pd


def simulate(close: pd.Series, signal: pd.Series, start, fee: float = 0.0) -> pd.DataFrame:
    """signal대로 매매했을 때의 일별 수익률과 자산 곡선을 계산한다.

    close, signal은 워밍업 구간을 포함한 전체 기간(날짜 오름차순). 결과는 start 이후만 돌려준다.
    start 당일 수익률은 전날 종가 대비라서 close에 start 전날이 최소 하루 있어야 한다.
    """
    daily_return = close.pct_change()
    position = signal.shift(1)

    frame = pd.DataFrame(
        {"close": close, "return": daily_return, "signal": signal, "position": position}
    )
    frame = frame.loc[frame.index >= start].copy()
    if frame.empty or frame["return"].isna().any():
        raise ValueError("평가 기간의 수익률을 계산하려면 시작일 전날 데이터가 필요합니다.")

    # 시작일 직전은 현금(0)이라고 보고 비중 변화를 계산한다.
    frame["trade"] = frame["position"].diff().fillna(frame["position"].iloc[0]).abs()
    frame["cost"] = frame["trade"] * fee
    frame["strategy_return"] = frame["position"] * frame["return"] - frame["cost"]
    frame["equity"] = (1 + frame["strategy_return"]).cumprod()
    return frame
