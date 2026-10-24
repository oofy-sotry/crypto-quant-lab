from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from market.integrity import (
    check_candle_values,
    find_minute_gaps,
    find_minute_mismatches,
    find_missing_dates,
    find_spikes,
    find_stale,
)
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


def test_find_spikes_flags_moves_over_threshold_as_warning():
    closes = ["100", "125", "90", "200"]  # +25%, -28%, +122%
    candles = [bar(i + 1, c, c, c, c) for i, c in enumerate(closes)]

    findings = find_spikes(candles, threshold=Decimal("0.3"))

    assert [f.date for f in findings] == [d(4)]
    assert findings[0].severity == IntegrityIssue.Severity.WARNING
    assert findings[0].detail == {"prev_date": "2026-10-03", "change": "1.2222"}


def test_find_spikes_uses_absolute_change():
    candles = [bar(1, "100", "100", "100", "100"), bar(2, "60", "60", "60", "60")]  # -40%

    assert [f.date for f in find_spikes(candles)] == [d(2)]


def test_find_stale_ok_when_latest_final_is_yesterday():
    assert find_stale(latest_final=d(1), today=d(2)) == []


def test_find_stale_reports_lag_when_collection_stopped():
    findings = find_stale(latest_final=d(1), today=d(4))

    assert findings[0].type == IntegrityIssue.Type.STALE
    assert findings[0].detail == {"lag_days": 3}


def daily(day, o="100", h="110", low="90", c="105", volume="10", value="1000"):
    return SimpleNamespace(
        date=d(day),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal(volume),
        value=Decimal(value),
    )


def agg(day, **kwargs):
    """DailyAgg 대신. bucket은 그날 UTC 0시."""
    row = daily(day, **kwargs)
    row.bucket = datetime(2026, 10, day, tzinfo=UTC)
    return row


def test_find_minute_mismatches_matching_days_are_clean():
    assert find_minute_mismatches([agg(1), agg(2)], [daily(1), daily(2)]) == []


def test_find_minute_mismatches_price_difference_is_error():
    findings = find_minute_mismatches([agg(1, c="104", volume="9")], [daily(1)])

    assert len(findings) == 1
    f = findings[0]
    assert (f.date, f.type, f.severity) == (
        d(1),
        IntegrityIssue.Type.MINUTE_MISMATCH,
        IntegrityIssue.Severity.ERROR,
    )
    assert f.detail == {
        "close": {"minute": "104", "daily": "105"},
        "volume": {"minute": "9", "daily": "10"},
    }


def test_find_minute_mismatches_amount_only_is_warning_beyond_tolerance():
    within = agg(1, value="1000.0005")  # 상대 5e-7
    beyond = agg(2, value="1000.002")  # 상대 2e-6

    findings = find_minute_mismatches([within, beyond], [daily(1), daily(2)])

    assert [(f.date, f.severity) for f in findings] == [(d(2), IntegrityIssue.Severity.WARNING)]
    assert findings[0].detail == {"value": {"minute": "1000.002", "daily": "1000"}}


def test_find_minute_mismatches_skips_days_missing_on_either_side():
    assert find_minute_mismatches([agg(1, c="1")], [daily(2, c="1")]) == []


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def test_find_minute_gaps_ignores_short_gaps():
    gaps = [(at(1, 3), at(1, 3, 15)), (at(1, 5), at(1, 5, 29))]

    assert find_minute_gaps(gaps, peer_gaps=[]) == []


def test_find_minute_gaps_long_gap_is_warning_with_detail():
    findings = find_minute_gaps([(at(1, 17), at(1, 22, 30))], peer_gaps=[])

    assert len(findings) == 1
    f = findings[0]
    assert (f.date, f.type, f.severity) == (
        d(1),
        IntegrityIssue.Type.MINUTE_GAP,
        IntegrityIssue.Severity.WARNING,
    )
    assert f.detail == {
        "start": "2026-10-01T17:00:00+00:00",
        "end": "2026-10-01T22:30:00+00:00",
        "minutes": 330,
        "count": 1,
        "all_assets": False,
    }


def test_find_minute_gaps_marks_gap_shared_by_all_peers():
    gap = (at(1, 17), at(1, 22))
    peers_all = [[(at(1, 17), at(1, 21))], [(at(1, 18), at(1, 23))]]
    peers_some = [[(at(1, 17), at(1, 21))], [(at(1, 3), at(1, 4))]]

    assert find_minute_gaps([gap], peers_all)[0].detail["all_assets"] is True
    assert find_minute_gaps([gap], peers_some)[0].detail["all_assets"] is False


def test_find_minute_gaps_gap_across_midnight_counts_on_both_days():
    # 23:40~00:20 = 40분. 날짜별로 자르면 20분씩이라 놓친다.
    findings = find_minute_gaps([(at(1, 23, 40), at(2, 0, 20))], peer_gaps=[])

    assert [f.date for f in findings] == [d(1), d(2)]
    assert all(f.detail["minutes"] == 40 for f in findings)


def test_find_minute_gaps_gap_ending_at_midnight_stays_on_one_day():
    findings = find_minute_gaps([(at(1, 22), at(2, 0))], peer_gaps=[])

    assert [f.date for f in findings] == [d(1)]


def test_find_minute_gaps_keeps_longest_gap_per_day():
    gaps = [(at(1, 1), at(1, 2)), (at(1, 10), at(1, 13)), (at(1, 20), at(1, 20, 45))]

    findings = find_minute_gaps(gaps, peer_gaps=[])

    assert len(findings) == 1
    assert findings[0].detail["minutes"] == 180
    assert findings[0].detail["count"] == 3
