from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from market.integrity import check_candle_values, find_missing_dates
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


def bar(day, o, h, low, c, volume=10):
    return SimpleNamespace(
        date=d(day),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal(volume),
    )


def types_of(findings):
    return [(f.date.day, f.type) for f in findings]


def test_check_candle_values_accepts_valid_candle():
    assert check_candle_values([bar(1, "100", "110", "90", "105")]) == []


def test_check_candle_values_detects_ohlc_violations():
    findings = check_candle_values(
        [
            bar(1, "100", "104", "90", "105"),  # 종가가 고가보다 높음
            bar(2, "100", "110", "101", "105"),  # 저가가 시가보다 높음
        ]
    )

    assert types_of(findings) == [(1, "ohlc_invalid"), (2, "ohlc_invalid")]
    assert findings[0].detail["close"] == "105"


def test_check_candle_values_detects_non_positive_price_and_zero_volume():
    findings = check_candle_values([bar(1, "0", "110", "0", "105"), bar(2, "1", "1", "1", "1", 0)])

    assert (1, "non_positive") in types_of(findings)
    assert (2, "zero_volume") in types_of(findings)
    zero_volume = next(f for f in findings if f.type == "zero_volume")
    assert zero_volume.severity == IntegrityIssue.Severity.WARNING
