from datetime import date

from market.integrity import find_missing_dates
from market.models import IntegrityIssue


def d(day: int) -> date:
    return date(2026, 10, day)


def test_find_missing_dates_reports_each_gap_day_as_error():
    findings = find_missing_dates([d(1), d(2), d(5)], start=d(1), end=d(5))

    assert [f.date for f in findings] == [d(3), d(4)]
    assert all(f.type == IntegrityIssue.Type.MISSING for f in findings)
    assert all(f.severity == IntegrityIssue.Severity.ERROR for f in findings)


def test_find_missing_dates_ignores_dates_outside_range():
    # 상장 전(start 이전)과 오늘(end 이후)은 결측으로 보지 않는다.
    assert find_missing_dates([d(2), d(3)], start=d(2), end=d(3)) == []
