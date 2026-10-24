from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command

from market.models import Asset, DailyAgg, HourlyBar, IntegrityIssue, MinuteCandle

NOW = datetime(2026, 10, 23, 6, 30, tzinfo=UTC)
TODAY = datetime(2026, 10, 23, tzinfo=UTC)


@pytest.fixture
def btc():
    return Asset.objects.get(symbol="KRW-BTC")


def add_minute(asset, ts):
    p = Decimal("100")
    MinuteCandle.objects.create(
        asset=asset, ts=ts, open=p, high=p, low=p, close=p, volume=Decimal(1), value=p
    )


def run(*args):
    out = StringIO()
    with patch("market.management.commands.aggregate_minutes.timezone.now", return_value=NOW):
        call_command("aggregate_minutes", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_aggregate_minutes_command_skips_today_and_old_days(btc):
    add_minute(btc, TODAY - timedelta(days=3, hours=-1))  # 기본 범위(2일) 밖
    add_minute(btc, TODAY - timedelta(hours=1))  # 어제 23시
    add_minute(btc, TODAY + timedelta(hours=1))  # 오늘(UTC) — 아직 안 끝남

    out = run("--asset", "KRW-BTC")

    assert list(DailyAgg.objects.values_list("bucket", flat=True)) == [TODAY - timedelta(days=1)]
    assert list(HourlyBar.objects.values_list("bucket", flat=True)) == [TODAY - timedelta(hours=1)]
    assert "[KRW-BTC] day 2026-10-21~2026-10-22 바뀐 행 1" in out


@pytest.mark.django_db
def test_aggregate_minutes_command_all_starts_from_first_minute(btc):
    add_minute(btc, TODAY - timedelta(days=30, hours=-5))
    add_minute(btc, TODAY - timedelta(hours=1))

    out = run("--all", "--asset", "KRW-BTC")

    assert DailyAgg.objects.filter(asset=btc).count() == 2
    assert "2026-09-23~2026-10-22" in out


@pytest.mark.django_db
def test_aggregate_minutes_command_all_skips_assets_without_minutes(btc):
    out = run("--all", "--asset", "KRW-ETH")

    assert "[KRW-ETH] 분봉 없음" in out
    assert not DailyAgg.objects.exists()


@pytest.mark.django_db
def test_aggregate_minutes_command_rejects_unknown_asset():
    with pytest.raises(CommandError, match="KRW-NOPE"):
        run("--asset", "KRW-NOPE")


@pytest.mark.django_db
def test_aggregate_minutes_command_runs_minute_checks_for_all_assets(btc):
    yesterday = TODAY - timedelta(days=1)
    minute = yesterday
    while minute < TODAY:  # BTC만 어제 하루 꽉 채움
        add_minute(btc, minute)
        minute += timedelta(minutes=1)

    out = run("--days", "1", "--asset", "KRW-BTC")

    # BTC는 깨끗하고, 분봉이 없는 다른 종목은 하루 전체가 빈 구간
    gaps = IntegrityIssue.objects.filter(type=IntegrityIssue.Type.MINUTE_GAP)
    assert sorted(gaps.values_list("asset__symbol", flat=True)) == [
        "KRW-DOGE",
        "KRW-ETH",
        "KRW-SOL",
        "KRW-XRP",
    ]
    assert "[KRW-BTC] 분봉 검사 2026-10-22~2026-10-22: 새 이슈 0" in out
    assert "[KRW-ETH] 분봉 검사 2026-10-22~2026-10-22: 새 이슈 1" in out
