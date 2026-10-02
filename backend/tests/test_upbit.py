import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import requests
import responses

from market.upbit import BASE_URL, UpbitClient, current_trading_day, parse_candle

CANDLES_URL = f"{BASE_URL}/candles/days"

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


@responses.activate
def test_fetch_daily_candles_sends_params_and_parses_decimals():
    responses.get(CANDLES_URL, body=f"[{RAW}]")

    candles = UpbitClient().fetch_daily_candles("KRW-BTC", count=1, to=date(2026, 10, 2))

    request = responses.calls[0].request
    assert "market=KRW-BTC" in request.url
    assert "count=1" in request.url
    assert "to=2026-10-02T00%3A00%3A00Z" in request.url
    assert candles[0].value == Decimal("92081396132.22375")


@responses.activate
def test_fetch_daily_candles_raises_on_unknown_market():
    responses.get(CANDLES_URL, status=404, json={"error": {"message": "Code not found"}})

    with pytest.raises(requests.HTTPError):
        UpbitClient().fetch_daily_candles("KRW-NOPE")


@responses.activate
def test_retries_with_exponential_backoff_on_429():
    responses.get(CANDLES_URL, status=429)
    responses.get(CANDLES_URL, status=429)
    responses.get(CANDLES_URL, body=f"[{RAW}]")
    waits = []

    candles = UpbitClient(min_interval=0, sleep=waits.append).fetch_daily_candles("KRW-BTC")

    assert len(candles) == 1
    assert waits == [0.5, 1.0]


@responses.activate
def test_gives_up_after_max_retries():
    responses.get(CANDLES_URL, status=503)
    waits = []

    with pytest.raises(requests.HTTPError):
        UpbitClient(max_retries=2, min_interval=0, sleep=waits.append).fetch_daily_candles(
            "KRW-BTC"
        )

    assert len(responses.calls) == 3  # 첫 시도 + 재시도 2번
    assert waits == [0.5, 1.0]


@responses.activate
def test_retries_on_connection_error():
    responses.get(CANDLES_URL, body=requests.ConnectionError("reset"))
    responses.get(CANDLES_URL, body=f"[{RAW}]")

    candles = UpbitClient(sleep=lambda _: None).fetch_daily_candles("KRW-BTC")

    assert len(candles) == 1


@responses.activate
def test_does_not_retry_client_errors():
    responses.get(CANDLES_URL, status=404)

    with pytest.raises(requests.HTTPError):
        UpbitClient(sleep=lambda _: None).fetch_daily_candles("KRW-NOPE")

    assert len(responses.calls) == 1


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@responses.activate
def test_throttle_keeps_min_interval_between_requests():
    responses.get(CANDLES_URL, body="[]")
    clock = FakeClock()
    waits = []

    def sleep(seconds):
        waits.append(round(seconds, 2))
        clock.sleep(seconds)

    client = UpbitClient(min_interval=0.15, sleep=sleep, clock=clock)
    client.fetch_daily_candles("KRW-BTC")  # 첫 요청은 기다리지 않음
    clock.now += 0.05  # 0.05초 뒤 두 번째 요청
    client.fetch_daily_candles("KRW-BTC")
    clock.now += 1.0  # 충분히 지난 뒤 세 번째 요청
    client.fetch_daily_candles("KRW-BTC")

    assert waits == [0.1]


def raw_candles(last: date, count: int) -> str:
    """last부터 하루씩 과거로 count개의 업비트 일봉 응답 JSON을 만든다."""
    from datetime import timedelta

    rows = []
    for i in range(count):
        day = last - timedelta(days=i)
        rows.append(
            {
                "candle_date_time_kst": f"{day.isoformat()}T09:00:00",
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
def test_iter_daily_candles_paginates_until_listing_date():
    responses.get(CANDLES_URL, body=raw_candles(date(2026, 10, 1), 200))
    responses.get(CANDLES_URL, body=raw_candles(date(2026, 3, 15), 3))

    candles = list(UpbitClient(min_interval=0).iter_daily_candles("KRW-BTC"))

    assert len(candles) == 203
    assert candles[0].date == date(2026, 10, 1)
    assert candles[-1].date == date(2026, 3, 13)
    # 두 번째 페이지는 첫 페이지의 가장 오래된 날짜(3/16) 이전을 요청한다.
    assert "to=2026-03-16T00%3A00%3A00Z" in responses.calls[1].request.url


@responses.activate
def test_iter_daily_candles_stops_at_since():
    responses.get(CANDLES_URL, body=raw_candles(date(2026, 10, 1), 200))

    candles = list(
        UpbitClient(min_interval=0).iter_daily_candles("KRW-BTC", since=date(2026, 9, 25))
    )

    assert [c.date for c in candles][-1] == date(2026, 9, 25)
    assert len(candles) == 7
    assert len(responses.calls) == 1


def test_current_trading_day_switches_at_kst_9am():
    kst = ZoneInfo("Asia/Seoul")
    # KST 10/3 08:59 → 아직 10/2 일봉이 진행 중
    assert current_trading_day(datetime(2026, 10, 3, 8, 59, tzinfo=kst)) == date(2026, 10, 2)
    # KST 10/3 09:00 → 10/3 일봉 시작
    assert current_trading_day(datetime(2026, 10, 3, 9, 0, tzinfo=kst)) == date(2026, 10, 3)
