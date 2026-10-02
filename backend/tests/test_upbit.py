import json
from datetime import date
from decimal import Decimal

from market.upbit import parse_candle

RAW = """{
    "market": "KRW-BTC",
    "candle_date_time_utc": "2026-10-01T00:00:00",
    "candle_date_time_kst": "2026-10-01T09:00:00",
    "opening_price": 113750000.0,
    "high_price": 115800000.0,
    "low_price": 113500000.0,
    "trade_price": 115657000.0,
    "candle_acc_trade_price": 92081396132.22375,
    "candle_acc_trade_volume": 804.24034244
}"""


def test_parse_candle_uses_kst_date_and_exact_decimals():
    candle = parse_candle(json.loads(RAW, parse_float=Decimal))

    assert candle.date == date(2026, 10, 1)
    assert candle.close == Decimal("115657000.0")
    # float로 읽었다면 끝자리가 달라질 수 있는 값이 그대로 보존된다.
    assert candle.value == Decimal("92081396132.22375")
    assert candle.volume == Decimal("804.24034244")
