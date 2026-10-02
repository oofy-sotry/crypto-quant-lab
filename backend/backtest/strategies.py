"""매매 전략.

모든 전략은 같은 모양의 함수다: 종가 Series → 목표 비중(signal) Series.
signal[t]는 "t일 종가까지 보고 내린 판단"이다(0 = 현금, 1 = 전액 보유).
실제 보유(position)는 엔진에서 하루 늦춰(shift(1)) 적용한다.
"""

import pandas as pd


def buy_and_hold(close: pd.Series) -> pd.Series:
    """처음부터 끝까지 보유. 다른 전략의 비교 기준(벤치마크)."""
    return pd.Series(1.0, index=close.index)


def ma_cross(close: pd.Series, short: int, long: int) -> pd.Series:
    """단기 이동평균이 장기 이동평균보다 위에 있으면 보유, 아니면 현금.

    장기 이동평균을 계산할 데이터가 모자란 초반(워밍업 구간)은 NaN이라 비교 결과가 False → 현금.
    """
    if not 0 < short < long:
        raise ValueError("short는 0보다 크고 long보다 작아야 합니다.")
    short_ma = close.rolling(short).mean()
    long_ma = close.rolling(long).mean()
    return (short_ma > long_ma).astype(float)


STRATEGIES = {
    "buy_and_hold": buy_and_hold,
    "ma_cross": ma_cross,
}
