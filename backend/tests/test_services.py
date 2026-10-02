from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from market.models import Asset, CollectionRun, DailyCandle, IntegrityIssue
from market.services import collect_candles, upsert_candles
from market.upbit import Candle

TODAY = date(2026, 10, 2)


def candle(day: date, close: str = "105") -> Candle:
    return Candle(
        date=day,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal(close),
        volume=Decimal("10"),
        value=Decimal("1000"),
    )


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")  # 0005_seed_assets 마이그레이션으로 생성됨


@pytest.mark.django_db
def test_upsert_inserts_new_candles_and_marks_today_not_final(btc):
    count = upsert_candles(btc, [candle(date(2026, 10, 1)), candle(TODAY)], today=TODAY)

    assert count == 2
    saved = {c.date: c.is_final for c in DailyCandle.objects.filter(asset=btc)}
    assert saved == {date(2026, 10, 1): True, TODAY: False}


@pytest.mark.django_db
def test_upsert_is_idempotent_and_overwrites_values(btc):
    upsert_candles(btc, [candle(TODAY, close="105")], today=TODAY)
    # 다음 날 다시 수집: 같은 날짜가 마감된 값으로 덮어써져야 한다.
    upsert_candles(btc, [candle(TODAY, close="107.5")], today=date(2026, 10, 3))

    rows = DailyCandle.objects.filter(asset=btc)
    assert rows.count() == 1
    assert rows.get().close == Decimal("107.5")
    assert rows.get().is_final is True


@pytest.mark.django_db
def test_upsert_with_no_candles_does_nothing(btc):
    assert upsert_candles(btc, [], today=TODAY) == 0


class FakeClient:
    """종목별로 정해 둔 일봉을 돌려주는 가짜 업비트 클라이언트."""

    def __init__(self, candles_by_symbol, fail=()):
        self.candles_by_symbol = candles_by_symbol
        self.fail = set(fail)
        self.calls = []

    def iter_daily_candles(self, symbol, since=None):
        self.calls.append((symbol, since))
        if symbol in self.fail:
            raise ConnectionError("boom")
        return iter(self.candles_by_symbol.get(symbol, []))


@pytest.mark.django_db
def test_collect_recent_days_records_success_run(btc):
    Asset.objects.exclude(symbol="KRW-BTC").update(is_active=False)
    client = FakeClient({"KRW-BTC": [candle(date(2026, 10, 1)), candle(date(2026, 9, 30))]})

    run = collect_candles(CollectionRun.Trigger.CRON, days=7, client=client)

    assert run.status == CollectionRun.Status.SUCCESS
    assert run.assets_count == 1
    assert run.upserted_count == 2
    assert run.finished_at is not None
    symbol, since = client.calls[0]
    assert symbol == "KRW-BTC"
    assert since is not None  # 최근 7일만 요청


@pytest.mark.django_db
def test_collect_backfill_sets_listed_on(btc):
    Asset.objects.exclude(symbol="KRW-BTC").update(is_active=False)
    client = FakeClient({"KRW-BTC": [candle(date(2026, 10, 1)), candle(date(2017, 9, 25))]})

    collect_candles(CollectionRun.Trigger.BACKFILL, days=None, client=client)

    btc.refresh_from_db()
    assert btc.listed_on == date(2017, 9, 25)
    assert client.calls[0] == ("KRW-BTC", None)  # 전체 기간 요청


@pytest.mark.django_db
def test_collect_continues_after_one_asset_fails():
    client = FakeClient({"KRW-ETH": [candle(date(2026, 10, 1))]}, fail={"KRW-BTC"})

    run = collect_candles(CollectionRun.Trigger.MANUAL, days=7, client=client)

    assert run.status == CollectionRun.Status.PARTIAL
    assert "KRW-BTC: ConnectionError" in run.error_message
    assert DailyCandle.objects.filter(asset__symbol="KRW-ETH").count() == 1


@pytest.mark.django_db
def test_collect_marks_failed_when_all_assets_fail():
    client = FakeClient({}, fail={a.symbol for a in Asset.objects.all()})

    run = collect_candles(CollectionRun.Trigger.MANUAL, days=7, client=client)

    assert run.status == CollectionRun.Status.FAILED


@pytest.mark.django_db
def test_collect_runs_integrity_checks_and_links_issues_to_run(btc):
    Asset.objects.exclude(symbol="KRW-BTC").update(is_active=False)
    btc.listed_on = date(2026, 9, 28)
    btc.save()
    # 9/29가 빠진 데이터
    days = [date(2026, 9, 28), date(2026, 9, 30), date(2026, 10, 1)]
    client = FakeClient({"KRW-BTC": [candle(day) for day in days]})

    with patch("market.services.current_trading_day", return_value=TODAY):
        run = collect_candles(CollectionRun.Trigger.CRON, days=7, client=client)

    issue = IntegrityIssue.objects.get(type=IntegrityIssue.Type.MISSING)
    assert issue.date == date(2026, 9, 29)
    assert issue.detected_run == run
