import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction

from backtest.services import data_version
from market.aggregates import aggregate_minutes
from market.models import Asset, DailyAgg, DailyCandle, HourlyBar, IntegrityIssue, MinuteCandle
from market.reprocess import (
    lock_days,
    reprocess_aggregates,
    reprocess_daily,
    reprocess_minutes,
)
from market.services import upsert_candles
from market.upbit import Candle, MinuteBar

DAY = date(2026, 10, 20)
T0 = datetime(2026, 10, 20, tzinfo=UTC)


def get_asset(symbol):
    # transaction=True 테스트는 pytest-django가 맨 뒤에 몰아 돌리고, 앞선 transaction=True 테스트가
    # 끝날 때 테이블을 비워 마이그레이션이 넣은 시드 종목이 없을 수 있다.
    return Asset.objects.get_or_create(symbol=symbol, defaults={"name": symbol})[0]


@pytest.fixture
def btc():
    return get_asset("KRW-BTC")


def hold_lock_in_other_connection(asset, start, end):
    """다른 DB 연결(스레드)에서 락을 잡고 있게 한다. 돌려준 release()를 부르면 풀린다."""
    locked, release = threading.Event(), threading.Event()

    def worker():
        try:
            with transaction.atomic():
                assert lock_days(asset, start, end)
                locked.set()
                release.wait(timeout=10)
        finally:
            connection.close()  # 스레드마다 연결이 따로 생기므로 직접 닫는다

    thread = threading.Thread(target=worker)
    thread.start()
    assert locked.wait(timeout=10)

    def finish():
        release.set()
        thread.join()

    return finish


@pytest.mark.django_db(transaction=True)
def test_lock_days_rejects_overlapping_period_and_frees_after_commit(btc):
    finish = hold_lock_in_other_connection(btc, DAY, DAY.replace(day=22))
    try:
        with transaction.atomic():
            assert lock_days(btc, DAY.replace(day=22), DAY.replace(day=25)) is False  # 22일 겹침
        with transaction.atomic():
            assert lock_days(btc, DAY.replace(day=23), DAY.replace(day=25)) is True  # 안 겹침
        eth = get_asset("KRW-ETH")
        with transaction.atomic():
            assert lock_days(eth, DAY, DAY) is True  # 다른 종목
    finally:
        finish()

    with transaction.atomic():
        assert lock_days(btc, DAY, DAY) is True  # 상대 트랜잭션이 끝나면 풀림


def fill_minutes(asset, start, end, close="100"):
    p, c = Decimal("100"), Decimal(close)
    rows = []
    ts = start
    while ts < end:
        rows.append(
            MinuteCandle(asset=asset, ts=ts, open=p, high=max(p, c), low=min(p, c), close=c,
                         volume=Decimal(1), value=c)
        )  # fmt: skip
        ts += timedelta(minutes=1)
    MinuteCandle.objects.bulk_create(rows)


@pytest.mark.django_db
def test_reprocess_aggregates_rebuilds_changed_and_removes_orphans(btc):
    fill_minutes(btc, T0, T0 + timedelta(days=2))
    for unit in ("hour", "day"):
        aggregate_minutes(btc, unit, T0, T0 + timedelta(days=2))
    # 20일 03시 분봉 값을 고치고, 21일 분봉은 통째로 지운다
    MinuteCandle.objects.filter(
        asset=btc, ts__gte=T0 + timedelta(hours=3), ts__lt=T0 + timedelta(hours=4)
    ).update(close=Decimal("101"), high=Decimal("101"))
    MinuteCandle.objects.filter(asset=btc, ts__gte=T0 + timedelta(days=1)).delete()

    result = reprocess_aggregates(btc, DAY, DAY + timedelta(days=1))

    assert (result.rows_before, result.rows_after, result.changed) == (2, 1, 2)
    assert result.diff["hourlybar"]["updated"] == 1
    assert result.diff["hourlybar"]["deleted"] == 24
    assert result.diff["dailyagg"] == {
        "inserted": 0,
        "updated": 1,
        "deleted": 1,
        "dates": {"2026-10-20": {"updated": 1}, "2026-10-21": {"deleted": 1}},
    }
    assert not HourlyBar.objects.filter(bucket__gte=T0 + timedelta(days=1)).exists()
    assert DailyAgg.objects.get(asset=btc).high == Decimal("101")
    # 재검증: 21일은 분봉이 없어 하루 전체 빈 구간
    assert result.diff["checks"]["created"] == 1
    assert IntegrityIssue.objects.get(asset=btc).date == DAY + timedelta(days=1)


@pytest.mark.django_db
def test_reprocess_aggregates_twice_changes_nothing(btc):
    fill_minutes(btc, T0, T0 + timedelta(days=1))

    first = reprocess_aggregates(btc, DAY, DAY)
    second = reprocess_aggregates(btc, DAY, DAY)

    assert first.changed == 1
    assert second.changed == 0
    assert second.diff["hourlybar"] == {"inserted": 0, "updated": 0, "deleted": 0, "dates": {}}


class FakeMinuteClient:
    """DB의 분봉을 "업비트 원본"으로 본떠 돌려준다. 원본 쪽을 고쳐 차이를 만든다."""

    def __init__(self, bars):
        self.bars = sorted(bars, key=lambda b: b.ts, reverse=True)

    def iter_minute_candles(self, market, since, to=None):
        for b in self.bars:
            if b.ts >= since and (to is None or b.ts < to):
                yield b


def source_from_db(asset):
    fields = ["ts", "open", "high", "low", "close", "volume", "value"]
    return {
        row["ts"]: MinuteBar(**row)
        for row in MinuteCandle.objects.filter(asset=asset).values(*fields)
    }


@pytest.mark.django_db
def test_reprocess_minutes_applies_only_differences(btc):
    fill_minutes(btc, T0, T0 + timedelta(days=1))
    reprocess_aggregates(btc, DAY, DAY)
    source = source_from_db(btc)
    # DB에서 1시간 사라짐(원본엔 있음), 원본 한 분 값이 바뀜, DB에만 있는 분 하나
    MinuteCandle.objects.filter(
        asset=btc, ts__gte=T0 + timedelta(hours=3), ts__lt=T0 + timedelta(hours=4)
    ).delete()
    changed_ts = T0 + timedelta(hours=10)
    source[changed_ts] = MinuteBar(**{**source[changed_ts].__dict__, "close": Decimal("100.5"),
                                      "high": Decimal("100.5")})  # fmt: skip
    extra_ts = T0 + timedelta(hours=11)
    del source[extra_ts]

    result = reprocess_minutes(btc, DAY, DAY, client=FakeMinuteClient(source.values()))

    minutes = result.diff["minutecandle"]
    assert (minutes["inserted"], minutes["updated"], minutes["deleted"]) == (60, 1, 1)
    assert (result.rows_before, result.rows_after, result.changed) == (1380, 1439, 62)
    assert MinuteCandle.objects.get(asset=btc, ts=changed_ts).close == Decimal("100.5")
    assert not MinuteCandle.objects.filter(asset=btc, ts=extra_ts).exists()
    # 이어서 재집계: 일봉 1개 갱신(거래량 바뀜)
    assert result.diff["dailyagg"]["updated"] == 1
    assert DailyAgg.objects.get(asset=btc).minute_count == 1439


@pytest.mark.django_db
def test_reprocess_minutes_same_source_changes_nothing(btc):
    fill_minutes(btc, T0, T0 + timedelta(days=1))
    reprocess_aggregates(btc, DAY, DAY)
    client = FakeMinuteClient(source_from_db(btc).values())

    result = reprocess_minutes(btc, DAY, DAY, client=client)

    assert result.changed == 0
    assert result.diff["dailyagg"]["updated"] == 0


class FakeDailyClient:
    def __init__(self, candles):
        self.candles = sorted(candles, key=lambda c: c.date, reverse=True)

    def iter_daily_candles(self, market, since=None):
        return iter(c for c in self.candles if since is None or c.date >= since)


def candle(day, close="100"):
    p = Decimal("100")
    c = Decimal(close)
    return Candle(date=day, open=p, high=max(p, c), low=min(p, c), close=c,
                  volume=Decimal(1), value=c)  # fmt: skip


@pytest.mark.django_db
def test_reprocess_daily_unchanged_source_keeps_data_version(btc):
    days = [DAY - timedelta(days=i) for i in range(3)]
    upsert_candles(btc, [candle(d) for d in days], today=DAY + timedelta(days=1))
    version = data_version(btc)

    result = reprocess_daily(btc, days[-1], DAY, client=FakeDailyClient([candle(d) for d in days]))

    assert result.changed == 0
    assert data_version(btc) == version  # 백테스트 캐시 그대로


@pytest.mark.django_db
def test_reprocess_daily_changed_candle_updates_and_bumps_data_version(btc):
    days = [DAY - timedelta(days=i) for i in range(3)]
    upsert_candles(btc, [candle(d) for d in days], today=DAY + timedelta(days=1))
    DailyCandle.objects.filter(asset=btc, date=days[1]).delete()  # 하루 빠짐
    version = data_version(btc)
    source = [candle(days[0], close="105"), candle(days[1]), candle(days[2])]

    result = reprocess_daily(btc, days[-1], DAY, client=FakeDailyClient(source))

    assert result.diff["dailycandle"]["inserted"] == 1
    assert result.diff["dailycandle"]["updated"] == 1
    assert (result.rows_before, result.rows_after) == (2, 3)
    assert DailyCandle.objects.get(asset=btc, date=DAY).close == Decimal("105")
    assert data_version(btc) != version  # 바뀐 일봉이 있으니 캐시 무효화
    assert "checks" in result.diff


@pytest.mark.django_db
def test_reprocess_daily_ignores_source_outside_period(btc):
    outside = DAY + timedelta(days=1)

    result = reprocess_daily(btc, DAY, DAY, client=FakeDailyClient([candle(DAY), candle(outside)]))

    assert result.changed == 1
    assert not DailyCandle.objects.filter(asset=btc, date=outside).exists()
