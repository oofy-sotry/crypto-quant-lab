import json
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import responses

from market.upbit import BASE_URL, UpbitClient, parse_minute_candle

MINUTES_URL = f"{BASE_URL}/candles/minutes/1"

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


@responses.activate
def test_fetch_minute_candles_sends_to_in_utc():
    responses.get(MINUTES_URL, body=f"[{RAW}]")
    # KST로 넘겨도 UTC로 바꿔 보낸다 (15:22 KST = 06:22 UTC)
    to = datetime(2026, 10, 23, 15, 22, tzinfo=ZoneInfo("Asia/Seoul"))

    bars = UpbitClient().fetch_minute_candles("KRW-BTC", count=1, to=to)

    url = responses.calls[0].request.url
    assert "market=KRW-BTC" in url
    assert "count=1" in url
    assert "to=2026-10-23T06%3A22%3A00Z" in url
    assert bars[0].ts == datetime(2026, 10, 23, 6, 21, tzinfo=UTC)
