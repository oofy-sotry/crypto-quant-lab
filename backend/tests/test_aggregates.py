import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from market.aggregates import AGG_VERSION, aggregate_minutes, upsert_aggregates
from market.models import Asset, DailyAgg, HourlyBar, MinuteCandle

DAY = datetime(2026, 10, 22, tzinfo=UTC)


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")


def minute(asset, ts, o, h, low, c, vol="1", val=None):
    vol = Decimal(vol)
    MinuteCandle.objects.create(
        asset=asset,
        ts=ts,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=vol,
        value=Decimal(val) if val is not None else vol * Decimal(c),
    )


@pytest.fixture
def three_minutes(btc):
    """09:00~09:02 세 분봉 + 다음 시간 첫 분봉 하나."""
    t = DAY.replace(hour=9)
    minute(btc, t, "100", "110", "95", "105", vol="1", val="105")
    minute(btc, t + timedelta(minutes=1), "105", "120", "100", "110", vol="2", val="220")
    minute(btc, t + timedelta(minutes=2), "110", "112", "90", "99", vol="1", val="99")
    minute(btc, t + timedelta(hours=1), "99", "101", "98", "100")


@pytest.mark.django_db
def test_aggregate_minutes_hourly_values(btc, three_minutes):
    changed = aggregate_minutes(btc, "hour", DAY, DAY + timedelta(days=1))

    assert changed == 2
    bar = HourlyBar.objects.get(asset=btc, bucket=DAY.replace(hour=9))
    assert (bar.open, bar.high, bar.low, bar.close) == (
        Decimal("100"),
        Decimal("120"),
        Decimal("90"),
        Decimal("99"),
    )
    assert bar.volume == Decimal("4")
    assert bar.value == Decimal("424")
    assert bar.vwap == Decimal("106")  # 424 / 4
    returns = [math.log(110 / 105), math.log(99 / 110)]
    mean = sum(returns) / 2
    expected = math.sqrt(sum((r - mean) ** 2 for r in returns) / (2 - 1))
    assert bar.volatility == pytest.approx(expected, rel=1e-12)
    assert bar.minute_count == 3
    assert bar.agg_version == AGG_VERSION


@pytest.mark.django_db
def test_aggregate_minutes_vwap_rounds_once(btc):
    # 실제 BTC 2026-06-08 11시 합계. 참값 95288369.26067264|4999… → 8자리 반올림은 …264.
    # 나눗셈 결과(소수 12자리 …2645000)를 다시 반올림하면 …265가 된다(이중 반올림).
    minute(btc, DAY, "1", "1", "1", "1", vol="55.07139608", val="5247663525.37180000")

    aggregate_minutes(btc, "hour", DAY, DAY + timedelta(hours=1))

    assert HourlyBar.objects.get(asset=btc).vwap == Decimal("95288369.26067264")


@pytest.mark.django_db
def test_aggregate_minutes_single_minute_bucket_has_no_volatility(btc, three_minutes):
    aggregate_minutes(btc, "hour", DAY, DAY + timedelta(days=1))

    bar = HourlyBar.objects.get(asset=btc, bucket=DAY.replace(hour=10))
    assert bar.minute_count == 1
    assert bar.volatility is None  # 수익률 0개


@pytest.mark.django_db
def test_aggregate_minutes_daily_uses_utc_day_boundary(btc, three_minutes):
    # 다음 날 UTC 00:00 분봉은 다음 일봉에 들어가야 한다.
    minute(btc, DAY + timedelta(days=1), "1", "1", "1", "1")

    aggregate_minutes(btc, "day", DAY, DAY + timedelta(days=2))

    days = list(DailyAgg.objects.filter(asset=btc).values_list("bucket", "minute_count"))
    assert days == [(DAY, 4), (DAY + timedelta(days=1), 1)]
    agg = DailyAgg.objects.get(asset=btc, bucket=DAY)
    assert (agg.open, agg.close) == (Decimal("100"), Decimal("100"))


@pytest.mark.django_db
def test_aggregate_minutes_only_reads_given_range(btc, three_minutes):
    # 10시 분봉은 범위 밖
    aggregate_minutes(btc, "hour", DAY.replace(hour=9), DAY.replace(hour=10))

    assert list(HourlyBar.objects.values_list("bucket", flat=True)) == [DAY.replace(hour=9)]


@pytest.mark.django_db
def test_aggregate_minutes_rerun_changes_nothing(btc, three_minutes):
    aggregate_minutes(btc, "hour", DAY, DAY + timedelta(days=1))
    before = {b.bucket: b.aggregated_at for b in HourlyBar.objects.all()}

    # 같은 데이터로 다시 돌리면 바뀐 행 0, 집계 시각도 그대로
    assert aggregate_minutes(btc, "hour", DAY, DAY + timedelta(days=1)) == 0
    assert {b.bucket: b.aggregated_at for b in HourlyBar.objects.all()} == before


@pytest.mark.django_db
def test_aggregate_minutes_updates_only_changed_bucket(btc, three_minutes):
    aggregate_minutes(btc, "hour", DAY, DAY + timedelta(days=1))
    MinuteCandle.objects.filter(ts=DAY.replace(hour=9, minute=2)).update(close=Decimal("101"))

    assert aggregate_minutes(btc, "hour", DAY, DAY + timedelta(days=1)) == 1
    assert HourlyBar.objects.get(bucket=DAY.replace(hour=9)).close == Decimal("101")


@pytest.mark.django_db
def test_aggregate_minutes_keeps_assets_separate(btc, three_minutes):
    eth = Asset.objects.get(symbol="KRW-ETH")
    minute(eth, DAY.replace(hour=9), "5", "5", "5", "5")

    aggregate_minutes(btc, "hour", DAY, DAY + timedelta(days=1))

    assert not HourlyBar.objects.filter(asset=eth).exists()
    assert HourlyBar.objects.get(asset=btc, bucket=DAY.replace(hour=9)).minute_count == 3


@pytest.mark.django_db
def test_upsert_aggregates_reports_inserted_and_updated_buckets(btc, three_minutes):
    nine, ten = DAY.replace(hour=9), DAY.replace(hour=10)

    assert sorted(upsert_aggregates(btc, "hour", DAY, DAY + timedelta(days=1))) == [
        (nine, True),
        (ten, True),
    ]
    MinuteCandle.objects.filter(ts=ten).update(close=Decimal("1"))

    # 바뀐 10시만, 새로 넣은 게 아니라 고친 것으로
    assert upsert_aggregates(btc, "hour", DAY, DAY + timedelta(days=1)) == [(ten, False)]
