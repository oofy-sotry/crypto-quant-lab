import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction

from market.aggregates import aggregate_minutes
from market.models import Asset, DailyAgg, HourlyBar, IntegrityIssue, MinuteCandle
from market.reprocess import lock_days, reprocess_aggregates

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
