from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from market.minute_pipeline import delete_expired_minutes, run_minute_pipeline
from market.models import Asset, CollectionRun, DailyAgg, HourlyBar, MinuteCandle
from market.upbit import MinuteBar

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 26, 2, 30, tzinfo=UTC)  # Cron 실행 시각(UTC 02시대)
TODAY = datetime(2026, 10, 26, tzinfo=UTC)


def bar(ts, price=100):
    p = Decimal(price)
    return MinuteBar(ts=ts, open=p, high=p, low=p, close=p, volume=Decimal(1), value=p)


class FakeClient:
    """종목마다 [since, to) 범위의 분봉을 시간 역순으로 준다. fail에 든 종목은 예외."""

    def __init__(self, bars, fail=()):
        self.bars = sorted(bars, key=lambda b: b.ts, reverse=True)
        self.fail = set(fail)
        self.calls = []

    def iter_minute_candles(self, market, since, to=None):
        self.calls.append((market, since, to))
        if market in self.fail:
            raise ConnectionError("업비트 응답 없음")
        return iter(b for b in self.bars if since <= b.ts and (to is None or b.ts < to))


def two_days():
    """끝난 UTC 날 2일(10/24, 10/25) 전체 + 진행 중인 오늘 몇 분."""
    start = TODAY - timedelta(days=2)
    return [bar(start + timedelta(minutes=i)) for i in range(2 * 1440 + 30)]


def test_pipeline_collects_aggregates_and_records_closed_days_only():
    client = FakeClient(two_days())

    run = run_minute_pipeline("cron", client=client, now=NOW, keep_days=0)

    assert run.kind == CollectionRun.Kind.MINUTES
    assert run.status == CollectionRun.Status.SUCCESS
    btc = Asset.objects.get(symbol="KRW-BTC")
    assert MinuteCandle.objects.filter(asset=btc).count() == 2 * 1440  # 오늘 분은 받지 않음
    assert HourlyBar.objects.filter(asset=btc).count() == 48
    assert DailyAgg.objects.filter(asset=btc).count() == 2
    assert client.calls[0][1:] == (TODAY - timedelta(days=2), TODAY)
    assert run.upserted_count == 5 * 2 * 1440
    assert run.detail["range"] == ["2026-10-24", "2026-10-25"]
    assert set(run.detail["timings"]) == {"collect_aggregate_s", "checks_s", "retention_s"}
    assert run.finished_at is not None


def test_pipeline_continues_after_one_asset_fails_and_marks_partial():
    run = run_minute_pipeline(
        "cron", client=FakeClient(two_days(), fail={"KRW-ETH"}), now=NOW, keep_days=0
    )

    assert run.status == CollectionRun.Status.PARTIAL
    assert "KRW-ETH: ConnectionError" in run.error_message
    eth = Asset.objects.get(symbol="KRW-ETH")
    assert not MinuteCandle.objects.filter(asset=eth).exists()
    assert MinuteCandle.objects.filter(asset__symbol="KRW-SOL").count() == 2 * 1440


def test_pipeline_is_idempotent():
    client = FakeClient(two_days())
    run_minute_pipeline("cron", client=client, now=NOW, keep_days=0)
    before = MinuteCandle.objects.count(), HourlyBar.objects.count()

    run_minute_pipeline("cron", client=client, now=NOW, keep_days=0)

    assert (MinuteCandle.objects.count(), HourlyBar.objects.count()) == before


def test_delete_expired_minutes_keeps_aggregates_and_recent_days():
    btc = Asset.objects.get(symbol="KRW-BTC")
    cutoff = TODAY - timedelta(days=30)
    MinuteCandle.objects.bulk_create(
        MinuteCandle(asset=btc, **bar(ts).__dict__)
        for ts in (cutoff - timedelta(minutes=1), cutoff, NOW - timedelta(hours=3))
    )

    assert delete_expired_minutes(NOW, keep_days=30) == 1
    assert sorted(MinuteCandle.objects.values_list("ts", flat=True))[0] == cutoff
    assert delete_expired_minutes(NOW, keep_days=0) == 0  # 0이면 지우지 않음


@pytest.mark.django_db(transaction=True)
def test_pipeline_skips_asset_whose_days_are_being_reprocessed(hold_lock):
    # transaction=True 테스트는 앞선 테스트가 시드 종목을 지웠을 수 있어 직접 만든다.
    btc, _ = Asset.objects.get_or_create(symbol="KRW-BTC", defaults={"name": "비트코인"})
    Asset.objects.get_or_create(symbol="KRW-ETH", defaults={"name": "이더리움"})
    finish = hold_lock(btc, date(2026, 10, 25), date(2026, 10, 25))  # 이틀 중 하루라도 겹침
    try:
        run = run_minute_pipeline("cron", client=FakeClient(two_days()), now=NOW, keep_days=0)
    finally:
        finish()

    assert run.status == CollectionRun.Status.PARTIAL
    assert "KRW-BTC: 같은 날짜의 재처리가 실행 중이라 건너뜀" in run.error_message
    assert not MinuteCandle.objects.filter(asset=btc).exists()
    assert MinuteCandle.objects.filter(asset__symbol="KRW-ETH").count() == 2 * 1440
