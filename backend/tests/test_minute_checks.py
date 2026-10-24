from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from market.aggregates import aggregate_minutes
from market.integrity import find_gaps_in_db, run_integrity_checks, run_minute_checks
from market.models import Asset, DailyCandle, IntegrityIssue, MinuteCandle

DAY = date(2026, 10, 20)
T0 = datetime(2026, 10, 20, tzinfo=UTC)
T = IntegrityIssue.Type


def fill_minutes(asset, start, end, skip=()):
    """[start, end) 매 분 분봉(가격 100, 거래량 1). skip 구간 [a, b)는 비운다."""
    rows = []
    ts = start
    while ts < end:
        if not any(a <= ts < b for a, b in skip):
            p = Decimal("100")
            rows.append(
                MinuteCandle(asset=asset, ts=ts, open=p, high=p, low=p, close=p, volume=1, value=p)
            )
        ts += timedelta(minutes=1)
    MinuteCandle.objects.bulk_create(rows)
    return len(rows)


def daily_candle(asset, day, count, close="100"):
    p = Decimal("100")
    DailyCandle.objects.create(
        asset=asset,
        date=day,
        open=p,
        high=p,
        low=p,
        close=Decimal(close),
        volume=Decimal(count),
        value=p * count,
        is_final=True,
    )


@pytest.fixture
def assets():
    return list(Asset.objects.filter(is_active=True))  # 시드 5종목


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")


@pytest.mark.django_db
def test_find_gaps_in_db_includes_range_edges(btc):
    fill_minutes(btc, T0 + timedelta(hours=1), T0 + timedelta(hours=23))

    gaps = find_gaps_in_db(btc, T0, T0 + timedelta(days=1), timedelta(minutes=30))

    assert gaps == [
        (T0, T0 + timedelta(hours=1)),
        (T0 + timedelta(hours=23), T0 + timedelta(days=1)),
    ]


@pytest.mark.django_db
def test_find_gaps_in_db_whole_range_when_no_minutes(btc):
    gaps = find_gaps_in_db(btc, T0, T0 + timedelta(days=1), timedelta(minutes=30))

    assert gaps == [(T0, T0 + timedelta(days=1))]


@pytest.mark.django_db
def test_run_minute_checks_without_any_minutes_does_nothing(assets):
    assert run_minute_checks(DAY, DAY) == {}
    assert not IntegrityIssue.objects.exists()


@pytest.mark.django_db
def test_run_minute_checks_clean_day(assets):
    for a in assets:
        n = fill_minutes(a, T0, T0 + timedelta(days=1))
        daily_candle(a, DAY, n)
        aggregate_minutes(a, "day", T0, T0 + timedelta(days=1))

    summary = run_minute_checks(DAY, DAY)

    assert summary["KRW-BTC"] == {"created": 0, "reopened": 0, "resolved": 0}
    assert not IntegrityIssue.objects.exists()


@pytest.mark.django_db
def test_run_minute_checks_shared_gap_and_single_asset_gap(assets, btc):
    maintenance = (T0 + timedelta(hours=17), T0 + timedelta(hours=20))
    btc_only = (T0 + timedelta(hours=5), T0 + timedelta(hours=6))
    for a in assets:
        skip = [maintenance, btc_only] if a == btc else [maintenance]
        fill_minutes(a, T0, T0 + timedelta(days=1), skip=skip)

    run_minute_checks(DAY, DAY)

    issues = IntegrityIssue.objects.filter(type=T.MINUTE_GAP)
    assert issues.count() == 5  # 종목마다 그날 하나
    others = issues.exclude(asset=btc)
    assert all(i.detail["all_assets"] for i in others)
    btc_issue = issues.get(asset=btc)
    assert btc_issue.detail["minutes"] == 180  # 가장 긴 것(점검)
    assert btc_issue.detail["count"] == 2
    assert btc_issue.severity == IntegrityIssue.Severity.WARNING


@pytest.mark.django_db
def test_run_minute_checks_flags_asset_with_no_minutes_while_others_have(assets, btc):
    for a in assets:
        if a != btc:
            fill_minutes(a, T0, T0 + timedelta(days=1))

    run_minute_checks(DAY, DAY)

    issue = IntegrityIssue.objects.get(type=T.MINUTE_GAP)
    assert issue.asset == btc
    assert issue.detail["minutes"] == 1440
    assert issue.detail["all_assets"] is False  # 수집 누락 의심


@pytest.mark.django_db
def test_run_minute_checks_price_mismatch_is_error_and_resolves_after_fix(assets, btc):
    n = fill_minutes(btc, T0, T0 + timedelta(days=1))
    daily_candle(btc, DAY, n, close="101")
    aggregate_minutes(btc, "day", T0, T0 + timedelta(days=1))

    run_minute_checks(DAY, DAY)

    issue = IntegrityIssue.objects.get(asset=btc, type=T.MINUTE_MISMATCH)
    assert issue.severity == IntegrityIssue.Severity.ERROR
    assert issue.detail == {"close": {"minute": "100.00000000", "daily": "101.00000000"}}

    DailyCandle.objects.filter(asset=btc, date=DAY).update(close=Decimal("100"))
    summary = run_minute_checks(DAY, DAY)

    assert summary["KRW-BTC"]["resolved"] == 1
    issue.refresh_from_db()
    assert issue.resolved_at is not None


@pytest.mark.django_db
def test_run_minute_checks_only_touches_its_date_range(assets, btc):
    old = IntegrityIssue.objects.create(
        asset=btc, date=DAY - timedelta(days=10), type=T.MINUTE_GAP, severity="warning"
    )
    for a in assets:
        fill_minutes(a, T0, T0 + timedelta(days=1))

    run_minute_checks(DAY, DAY)

    old.refresh_from_db()
    assert old.resolved_at is None


@pytest.mark.django_db
def test_daily_checks_do_not_resolve_minute_issues(btc):
    issue = IntegrityIssue.objects.create(
        asset=btc, date=DAY, type=T.MINUTE_GAP, severity="warning"
    )
    daily_candle(btc, DAY, 1440)

    run_integrity_checks(btc, today=DAY + timedelta(days=1))

    issue.refresh_from_db()
    assert issue.resolved_at is None
