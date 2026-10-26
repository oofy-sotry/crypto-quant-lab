from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import transaction

from backtest.services import data_version
from market.aggregates import aggregate_minutes
from market.models import (
    Asset,
    DailyAgg,
    DailyCandle,
    HourlyBar,
    IntegrityIssue,
    MinuteCandle,
    ReprocessRun,
)
from market.reprocess import (
    SourceLooksIncomplete,
    lock_days,
    reprocess_aggregates,
    reprocess_daily,
    reprocess_minutes,
    run_reprocess,
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


@pytest.mark.django_db(transaction=True)
def test_lock_days_rejects_overlapping_period_and_frees_after_commit(btc, hold_lock):
    finish = hold_lock(btc, DAY, DAY.replace(day=22))
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


def broken_btc_day(btc):
    """하루치 분봉·집계를 만들고 03시 1시간을 지운다. 원본(업비트 흉내)은 온전한 하루."""
    fill_minutes(btc, T0, T0 + timedelta(days=1))
    reprocess_aggregates(btc, DAY, DAY)
    client = FakeMinuteClient(source_from_db(btc).values())
    MinuteCandle.objects.filter(
        asset=btc, ts__gte=T0 + timedelta(hours=3), ts__lt=T0 + timedelta(hours=4)
    ).delete()
    reprocess_aggregates(btc, DAY, DAY)  # 빠진 상태로 집계·검사 → 빈 구간 이슈
    assert IntegrityIssue.objects.filter(asset=btc, resolved_at__isnull=True).exists()
    return client


def snapshot(asset):
    return (
        MinuteCandle.objects.filter(asset=asset).count(),
        list(DailyAgg.objects.filter(asset=asset).values_list("minute_count", "aggregated_at")),
        list(IntegrityIssue.objects.filter(asset=asset).values_list("type", "resolved_at")),
    )


def run(btc, client, dry_run):
    return run_reprocess(
        btc, "minutes", DAY, DAY, dry_run=dry_run, reason="테스트", requested_by="pytest",
        client=client,
    )  # fmt: skip


@pytest.mark.django_db
def test_run_reprocess_dry_run_reports_diff_without_changing_db(btc):
    client = broken_btc_day(btc)
    before = snapshot(btc)

    record = run(btc, client, dry_run=True)

    assert record.status == ReprocessRun.Status.SUCCESS
    assert record.dry_run is True
    assert (record.rows_before, record.rows_after, record.changed_rows) == (1380, 1440, 60)
    assert record.diff["minutecandle"]["dates"] == {"2026-10-20": {"inserted": 60}}
    assert record.diff["checks"]["resolved"] == 1  # 실행하면 빈 구간 이슈가 해결될 것
    assert record.finished_at is not None
    assert snapshot(btc) == before  # DB는 그대로


@pytest.mark.django_db
def test_run_reprocess_apply_restores_data_and_resolves_issue_then_idempotent(btc):
    client = broken_btc_day(btc)

    first = run(btc, client, dry_run=False)
    second = run(btc, client, dry_run=False)

    assert first.changed_rows == 60
    assert MinuteCandle.objects.filter(asset=btc).count() == 1440
    assert DailyAgg.objects.get(asset=btc).minute_count == 1440
    assert not IntegrityIssue.objects.filter(asset=btc, resolved_at__isnull=True).exists()
    assert second.changed_rows == 0
    assert second.diff["dailyagg"]["updated"] == 0
    assert ReprocessRun.objects.count() == 2  # 두 번 다 이력이 남음


@pytest.mark.django_db
def test_run_reprocess_failure_rolls_back_everything(btc):
    client = broken_btc_day(btc)
    before = snapshot(btc)

    # 분봉 반영까지 끝난 뒤 재집계 단계에서 실패
    with patch("market.reprocess.reprocess_aggregates", side_effect=RuntimeError("boom")):
        record = run(btc, client, dry_run=False)

    assert record.status == ReprocessRun.Status.FAILED
    assert record.error_message == "RuntimeError: boom"
    assert record.changed_rows is None
    assert snapshot(btc) == before  # 앞에서 넣은 분봉 60개도 롤백


@pytest.mark.django_db(transaction=True)
def test_run_reprocess_rejects_while_same_period_is_running(btc, hold_lock):
    finish = hold_lock(btc, DAY, DAY)
    try:
        record = run(btc, FakeMinuteClient([]), dry_run=False)
    finally:
        finish()

    assert record.status == ReprocessRun.Status.REJECTED
    assert record.changed_rows is None
    assert ReprocessRun.objects.get().status == ReprocessRun.Status.REJECTED  # 거부도 기록


@pytest.mark.django_db
def test_reprocess_daily_delete_only_bumps_data_version(btc):
    # 남은 행의 수집 시각은 그대로라 Max(collected_at)만으로는 바뀐 걸 모른다.
    days = [DAY - timedelta(days=i) for i in range(20)]  # 1개 삭제 = 5% (삭제 상한 10% 아래)
    upsert_candles(btc, [candle(d) for d in days], today=DAY + timedelta(days=1))
    version = data_version(btc)

    result = reprocess_daily(
        btc, days[-1], DAY, client=FakeDailyClient([candle(d) for d in days[1:]])
    )

    assert result.diff["dailycandle"]["deleted"] == 1
    assert data_version(btc) != version


@pytest.mark.django_db
@pytest.mark.parametrize("keep_hours", [0, 21])  # 원본이 비었거나, 기간의 12.5%가 빠짐
def test_reprocess_minutes_refuses_mass_delete_and_rolls_back(btc, keep_hours):
    fill_minutes(btc, T0, T0 + timedelta(days=1))
    source = [b for ts, b in source_from_db(btc).items() if ts < T0 + timedelta(hours=keep_hours)]

    record = run(btc, FakeMinuteClient(source), dry_run=False)

    assert record.status == ReprocessRun.Status.FAILED
    assert "SourceLooksIncomplete" in record.error_message
    assert MinuteCandle.objects.filter(asset=btc).count() == 1440  # 아무것도 안 지움


@pytest.mark.django_db
def test_reprocess_daily_refuses_empty_source(btc):
    upsert_candles(btc, [candle(DAY)], today=DAY + timedelta(days=1))

    with pytest.raises(SourceLooksIncomplete):
        reprocess_daily(btc, DAY, DAY, client=FakeDailyClient([]))
