import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from market.aggregate_reference import diff_against_db, reference_aggregate
from market.aggregates import aggregate_minutes
from market.models import Asset, HourlyBar, MinuteCandle

START = datetime(2026, 10, 20, tzinfo=UTC)
END = START + timedelta(days=2)


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")


def random_minutes(asset, seed=7):
    """이틀치 분봉. 약 10%는 거래 없는 분으로 빼고, 일부 구간은 통째로 비운다."""
    rng = random.Random(seed)
    price = Decimal("150000000")
    rows = []
    ts = START
    while ts < END:
        no_trade = rng.random() < 0.1
        maintenance = 17 <= ts.hour < 19  # 매일 2시간 통째로 빔
        if not (no_trade or maintenance):
            o = price
            c = (o * Decimal(1 + rng.uniform(-0.002, 0.002))).quantize(Decimal("0.00000001"))
            h = max(o, c) + Decimal(rng.randint(0, 50000))
            low = min(o, c) - Decimal(rng.randint(0, 50000))
            vol = Decimal(rng.randint(1, 10**9)) / Decimal(10**8)
            rows.append(
                MinuteCandle(
                    asset=asset,
                    ts=ts,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    volume=vol,
                    value=(vol * c).quantize(Decimal("0.00000001")),
                )
            )
            price = c
        ts += timedelta(minutes=1)
    MinuteCandle.objects.bulk_create(rows)
    return rows


def as_dicts(rows):
    fields = ["ts", "open", "high", "low", "close", "volume", "value"]
    return [{f: getattr(r, f) for f in fields} for r in rows]


def test_reference_aggregate_hand_example():
    t = datetime(2026, 10, 22, 9, tzinfo=UTC)
    minutes = [
        # 순서가 섞여 들어와도 시각순으로 계산해야 한다
        {"ts": t + timedelta(minutes=1), "open": Decimal("105"), "high": Decimal("120"),
         "low": Decimal("100"), "close": Decimal("110"), "volume": Decimal("2"),
         "value": Decimal("220")},
        {"ts": t, "open": Decimal("100"), "high": Decimal("110"), "low": Decimal("95"),
         "close": Decimal("105"), "volume": Decimal("1"), "value": Decimal("105")},
    ]  # fmt: skip

    result = reference_aggregate(minutes, "hour")

    assert list(result) == [t]
    bar = result[t]
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (
        Decimal("100"),
        Decimal("120"),
        Decimal("95"),
        Decimal("110"),
    )
    assert bar["vwap"] == Decimal("108.33333333")  # 325 / 3, 소수 8자리 반올림
    assert bar["minute_count"] == 2
    assert bar["volatility"] is None  # 수익률 1개 → 표본 표준편차 없음


def test_reference_aggregate_empty():
    assert reference_aggregate([], "day") == {}


@pytest.mark.django_db
@pytest.mark.parametrize("unit", ["hour", "day"])
def test_db_aggregate_matches_pandas_reference(btc, unit):
    random_minutes(btc)

    aggregate_minutes(btc, unit, START, END)

    assert diff_against_db(btc, unit, START, END) == []


@pytest.mark.django_db
def test_diff_against_db_reports_wrong_and_missing_rows(btc):
    rows = random_minutes(btc)
    aggregate_minutes(btc, "hour", START, END)
    HourlyBar.objects.filter(bucket=START).update(close=Decimal("1"))
    HourlyBar.objects.filter(bucket=START + timedelta(hours=1)).delete()

    diffs = diff_against_db(btc, "hour", START, END)

    assert [(d["bucket"], d["field"]) for d in diffs] == [
        (START, "close"),
        (START + timedelta(hours=1), "row"),
    ]
    first_hour = [r for r in rows if r.ts < START + timedelta(hours=1)]
    assert diffs[0]["expected"] == first_hour[-1].close
