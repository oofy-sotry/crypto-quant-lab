import json
from datetime import UTC, datetime, timedelta
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


def raw_minutes(last: datetime, count: int, step: int = 1) -> str:
    """last부터 step분 간격으로 과거로 count개 (step>1이면 거래 없는 분이 빠진 구간)."""
    rows = []
    for i in range(count):
        ts = last - timedelta(minutes=i * step)
        rows.append(
            {
                "candle_date_time_utc": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "opening_price": 100.0,
                "high_price": 110.0,
                "low_price": 90.0,
                "trade_price": 105.0,
                "candle_acc_trade_price": 1000.0,
                "candle_acc_trade_volume": 10.0,
            }
        )
    return json.dumps(rows)


@responses.activate
def test_iter_minute_candles_paginates_from_oldest_ts_of_previous_page():
    last = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    # 첫 페이지는 거래 없는 분이 섞여 200개가 400분에 걸친다
    responses.get(MINUTES_URL, body=raw_minutes(last, 200, step=2))
    responses.get(MINUTES_URL, body=raw_minutes(last - timedelta(minutes=400), 3))

    since = datetime(2026, 10, 1, tzinfo=UTC)
    bars = list(UpbitClient(min_interval=0).iter_minute_candles("KRW-BTC", since=since))

    assert len(bars) == 203
    # 두 번째 페이지는 첫 페이지의 가장 오래된 분(398분 전) 이전을 요청한다
    assert "to=2026-10-22T23%3A22%3A00Z" in responses.calls[1].request.url
    assert bars[-1].ts == last - timedelta(minutes=402)


@responses.activate
def test_iter_minute_candles_stops_at_since_and_passes_to():
    last = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    responses.get(MINUTES_URL, body=raw_minutes(last, 200))

    bars = list(
        UpbitClient(min_interval=0).iter_minute_candles(
            "KRW-BTC", since=last - timedelta(minutes=9), to=last + timedelta(minutes=1)
        )
    )

    assert len(bars) == 10  # since 포함
    assert len(responses.calls) == 1
    assert "to=2026-10-23T06%3A01%3A00Z" in responses.calls[0].request.url
