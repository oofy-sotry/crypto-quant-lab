"""업비트 공개 시세 API 클라이언트 (API 키 불필요).

문서: https://docs.upbit.com/kr/reference/list-candles-days
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    date: date  # KST 거래일
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    value: Decimal


def parse_candle(raw: dict) -> Candle:
    """업비트 일봉 응답 한 건을 Candle로 바꾼다.

    숫자 필드는 응답 JSON을 parse_float=Decimal로 읽었다고 가정한다.
    """
    return Candle(
        date=datetime.fromisoformat(raw["candle_date_time_kst"]).date(),
        open=Decimal(raw["opening_price"]),
        high=Decimal(raw["high_price"]),
        low=Decimal(raw["low_price"]),
        close=Decimal(raw["trade_price"]),
        volume=Decimal(raw["candle_acc_trade_volume"]),
        value=Decimal(raw["candle_acc_trade_price"]),
    )
