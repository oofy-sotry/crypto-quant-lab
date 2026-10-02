from datetime import date, timedelta
from decimal import Decimal

import pytest

from market.integrity import run_integrity_checks
from market.models import Asset, DailyCandle, IntegrityIssue

TODAY = date(2026, 10, 10)


def make_candles(asset, days, close="100"):
    for day in days:
        DailyCandle.objects.create(
            asset=asset,
            date=day,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal("1"),
            value=Decimal("100"),
            is_final=day < TODAY,
        )


@pytest.fixture
def btc():
    asset = Asset.objects.get(symbol="KRW-BTC")
    asset.listed_on = date(2026, 10, 1)
    asset.save()
    return asset


def full_range():
    return [date(2026, 10, 1) + timedelta(days=i) for i in range(10)]  # 10/1 ~ 10/10


@pytest.mark.django_db
def test_clean_data_creates_no_issues(btc):
    make_candles(btc, full_range())

    assert run_integrity_checks(btc, TODAY) == {"created": 0, "reopened": 0, "resolved": 0}
    assert not IntegrityIssue.objects.exists()


@pytest.mark.django_db
def test_missing_day_creates_issue_once_even_if_checked_twice(btc):
    make_candles(btc, [d for d in full_range() if d != date(2026, 10, 5)])

    first = run_integrity_checks(btc, TODAY)
    second = run_integrity_checks(btc, TODAY)

    assert first["created"] == 1
    assert second["created"] == 0
    issue = IntegrityIssue.objects.get()
    assert (issue.date, issue.type) == (date(2026, 10, 5), "missing")


@pytest.mark.django_db
def test_issue_auto_resolves_when_data_is_filled(btc):
    make_candles(btc, [d for d in full_range() if d != date(2026, 10, 5)])
    run_integrity_checks(btc, TODAY)

    make_candles(btc, [date(2026, 10, 5)])  # 재수집으로 결측이 채워짐
    summary = run_integrity_checks(btc, TODAY)

    assert summary["resolved"] == 1
    assert IntegrityIssue.objects.get().resolved_at is not None


@pytest.mark.django_db
def test_acknowledged_issue_stays_resolved(btc):
    make_candles(btc, [d for d in full_range() if d != date(2026, 10, 5)])
    run_integrity_checks(btc, TODAY)
    IntegrityIssue.objects.update(resolved_at="2026-10-10T00:00Z", note="업비트 원본에도 없음")

    summary = run_integrity_checks(btc, TODAY)

    assert summary["reopened"] == 0
    assert IntegrityIssue.objects.get().resolved_at is not None


@pytest.mark.django_db
def test_auto_resolved_issue_reopens_when_problem_returns(btc):
    make_candles(btc, [d for d in full_range() if d != date(2026, 10, 5)])
    run_integrity_checks(btc, TODAY)
    IntegrityIssue.objects.update(resolved_at="2026-10-10T00:00Z")  # 자동 해결된 상태 (note 없음)

    summary = run_integrity_checks(btc, TODAY)

    assert summary["reopened"] == 1
    assert IntegrityIssue.objects.get().resolved_at is None
