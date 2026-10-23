from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from market.minutes import collect_minutes, upsert_minute_candles
from market.models import Asset, MinuteCandle
from market.upbit import MinuteBar

T0 = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


def bar(ts: datetime, close: str = "105") -> MinuteBar:
    return MinuteBar(
        ts=ts,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal(close),
        volume=Decimal("0.5"),
        value=Decimal("52.5"),
    )


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")  # 0005_seed_assets 마이그레이션으로 생성됨


@pytest.mark.django_db
def test_upsert_minute_candles_splits_into_batches(btc, django_assert_num_queries):
    bars = [bar(T0 + timedelta(minutes=i)) for i in range(5)]

    # 5행을 2행씩 → INSERT 3번
    with django_assert_num_queries(3):
        assert upsert_minute_candles(btc, bars, batch_size=2) == 5

    assert MinuteCandle.objects.filter(asset=btc).count() == 5


@pytest.mark.django_db
def test_upsert_minute_candles_is_idempotent_and_overwrites(btc):
    upsert_minute_candles(btc, [bar(T0, close="105")])
    upsert_minute_candles(btc, [bar(T0, close="106.5")])

    rows = MinuteCandle.objects.filter(asset=btc)
    assert rows.count() == 1
    assert rows.get().close == Decimal("106.5")
    assert rows.get().ts == T0


@pytest.mark.django_db
def test_upsert_minute_candles_with_no_bars_does_nothing(btc):
    assert upsert_minute_candles(btc, []) == 0


class FakeMinuteClient:
    """정해 둔 분봉을 최신순으로 돌려주는 가짜 클라이언트. 받은 인자를 기록한다."""

    def __init__(self, bars):
        self.bars = sorted(bars, key=lambda b: b.ts, reverse=True)
        self.calls = []

    def iter_minute_candles(self, market, since, to=None):
        self.calls.append((market, since, to))
        for b in self.bars:
            if (to is None or b.ts < to) and b.ts >= since:
                yield b


@pytest.mark.django_db
def test_collect_minutes_saves_in_batches_and_reports_progress(btc):
    client = FakeMinuteClient([bar(T0 + timedelta(minutes=i)) for i in range(5)])
    progress = []

    saved = collect_minutes(
        btc,
        since=T0,
        to=T0 + timedelta(minutes=10),
        client=client,
        batch_size=2,
        on_batch=lambda n, oldest: progress.append((n, oldest)),
    )

    assert saved == 5
    assert MinuteCandle.objects.filter(asset=btc).count() == 5
    # 최신부터 2개씩: 04·03분 → 02·01분 → 00분
    assert progress == [
        (2, T0 + timedelta(minutes=3)),
        (4, T0 + timedelta(minutes=1)),
        (5, T0),
    ]


@pytest.mark.django_db
def test_collect_minutes_excludes_current_minute_by_default(btc):
    now = T0 + timedelta(minutes=2, seconds=30)
    client = FakeMinuteClient(
        [bar(T0), bar(T0 + timedelta(minutes=1)), bar(T0 + timedelta(minutes=2))]
    )

    with patch("market.minutes.timezone.now", return_value=now):
        saved = collect_minutes(btc, since=T0, client=client)

    # 06:02는 아직 진행 중인 분이라 빠진다
    assert saved == 2
    assert client.calls == [("KRW-BTC", T0, T0 + timedelta(minutes=2))]
