from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from market.aggregates import upsert_aggregates
from market.models import Asset, MinuteCandle

pytestmark = pytest.mark.django_db

START = datetime(2026, 10, 22, 23, 0, tzinfo=UTC)


@pytest.fixture
def btc():
    """2026-10-22 23:00 ~ 10-23 00:59 UTC 분봉 120개 + 시간봉·일 집계."""
    asset = Asset.objects.get(symbol="KRW-BTC")
    MinuteCandle.objects.bulk_create(
        MinuteCandle(
            asset=asset,
            ts=START + timedelta(minutes=i),
            open=Decimal(100 + i),
            high=Decimal(101 + i),
            low=Decimal(99 + i),
            close=Decimal(100 + i),
            volume=Decimal("0.5"),
            value=Decimal(50 + i),
        )
        for i in range(120)
    )
    for unit in ("hour", "day"):
        upsert_aggregates(asset, unit, START.replace(hour=0), START + timedelta(days=2))
    return asset


def test_minutes_filters_half_open_range_in_utc(client, btc):
    response = client.get(
        reverse("minute-list"),
        {"symbol": "KRW-BTC", "from": "2026-10-23T00:00:00Z", "to": "2026-10-23T00:03:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert [m["ts"] for m in body["results"]] == [
        "2026-10-23T00:00:00Z",
        "2026-10-23T00:01:00Z",
        "2026-10-23T00:02:00Z",
    ]
    assert body["results"][0]["open"] == "160.00000000"  # Decimal은 문자열


def test_minutes_treats_naive_time_as_utc(client, btc):
    response = client.get(
        reverse("minute-list"), {"symbol": "KRW-BTC", "from": "2026-10-23T00:58:00"}
    )

    assert [m["ts"] for m in response.json()["results"]] == [
        "2026-10-23T00:58:00Z",
        "2026-10-23T00:59:00Z",
    ]


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ({}, 400),
        ({"symbol": "KRW-BTC", "from": "어제"}, 400),
        ({"symbol": "KRW-BTC", "from": "2026-10-23T01:00Z", "to": "2026-10-23T00:00Z"}, 400),
        ({"symbol": "KRW-NOPE"}, 404),
    ],
)
def test_minutes_rejects_invalid_queries(client, query, status):
    assert client.get(reverse("minute-list"), query).status_code == status


def test_bars_returns_hourly_and_daily_aggregates(client, btc):
    hourly = client.get(reverse("bar-list"), {"symbol": "KRW-BTC", "unit": "hour"}).json()
    daily = client.get(reverse("bar-list"), {"symbol": "KRW-BTC", "unit": "day"}).json()

    assert [b["bucket"] for b in hourly["results"]] == [
        "2026-10-22T23:00:00Z",
        "2026-10-23T00:00:00Z",
    ]
    assert hourly["results"][1]["open"] == "160.00000000"
    assert hourly["results"][1]["minute_count"] == 60
    assert [b["bucket"] for b in daily["results"]] == [
        "2026-10-22T00:00:00Z",
        "2026-10-23T00:00:00Z",
    ]


def test_bars_filters_range_and_requires_unit(client, btc):
    response = client.get(
        reverse("bar-list"),
        {"symbol": "KRW-BTC", "unit": "hour", "from": "2026-10-23T00:00Z"},
    )
    assert [b["bucket"] for b in response.json()["results"]] == ["2026-10-23T00:00:00Z"]

    assert client.get(reverse("bar-list"), {"symbol": "KRW-BTC"}).status_code == 400
    assert client.get(reverse("bar-list"), {"symbol": "KRW-BTC", "unit": "week"}).status_code == 400


def test_minute_status_lists_latest_per_asset(client, btc):
    response = client.get(reverse("minute-status"))

    assert response.status_code == 200
    rows = {row["symbol"]: row for row in response.json()}
    assert rows["KRW-BTC"] == {
        "symbol": "KRW-BTC",
        "last_minute": "2026-10-23T00:59:00Z",
        "last_hour": "2026-10-23T00:00:00Z",
        "last_day": "2026-10-23T00:00:00Z",
    }
    assert rows["KRW-ETH"]["last_minute"] is None  # 분봉이 없는 종목도 빠지지 않는다
