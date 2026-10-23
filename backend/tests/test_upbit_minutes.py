import json
from datetime import UTC, datetime
from decimal import Decimal

from market.upbit import parse_minute_candle

RAW = """{
    "market": "KRW-BTC",
    "candle_date_time_utc": "2026-10-23T06:21:00",
    "candle_date_time_kst": "2026-10-23T15:21:00",
    "opening_price": 109360000.0,
    "high_price": 109360000.0,
    "low_price": 109357000.0,
    "trade_price": 109357000.0,
    "timestamp": 1792736485561,
    "candle_acc_trade_price": 2733246.59371,
    "candle_acc_trade_volume": 0.02499367,
    "unit": 1
}"""


def test_parse_minute_candle_uses_utc_time_and_exact_decimals():
    bar = parse_minute_candle(json.loads(RAW, parse_float=Decimal))

    assert bar.ts == datetime(2026, 10, 23, 6, 21, tzinfo=UTC)
    assert bar.close == Decimal("109357000.0")
    assert bar.value == Decimal("2733246.59371")
    assert bar.volume == Decimal("0.02499367")
