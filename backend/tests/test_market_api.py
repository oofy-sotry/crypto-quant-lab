from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from market.models import Asset, CollectionRun, DailyCandle, IntegrityIssue


@pytest.fixture
def btc():
    asset = Asset.objects.get(symbol="KRW-BTC")
    DailyCandle.objects.bulk_create(
        DailyCandle(
            asset=asset,
            date=date(2026, 1, 1) + timedelta(days=i),
            open=Decimal("100.12345678"),
            high=Decimal(110),
            low=Decimal(90),
            close=Decimal(105),
            volume=Decimal(1),
            value=Decimal(1),
            is_final=i < 9,
        )
        for i in range(10)
    )
    return asset


@pytest.mark.django_db
def test_assets_lists_seeded_symbols_without_pagination(client):
    response = client.get(reverse("asset-list"))

    assert response.status_code == 200
    assert [a["symbol"] for a in response.json()] == [
        "KRW-BTC",
        "KRW-DOGE",
        "KRW-ETH",
        "KRW-SOL",
        "KRW-XRP",
    ]


@pytest.mark.django_db
def test_candles_filters_by_date_range_and_keeps_decimal_strings(client, btc):
    response = client.get(
        reverse("candle-list"), {"symbol": "KRW-BTC", "from": "2026-01-03", "to": "2026-01-05"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["count"] == 3
    assert [c["date"] for c in body["results"]] == ["2026-01-03", "2026-01-04", "2026-01-05"]
    assert body["results"][0]["open"] == "100.12345678"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "status"),
    [
        ({}, 400),  # symbol 필수
        ({"symbol": "KRW-BTC", "from": "2026-02-01", "to": "2026-01-01"}, 400),
        ({"symbol": "KRW-BTC", "from": "not-a-date"}, 400),
        ({"symbol": "KRW-NOPE"}, 404),
    ],
)
def test_candles_rejects_invalid_queries(client, query, status):
    assert client.get(reverse("candle-list"), query).status_code == status


@pytest.mark.django_db
def test_integrity_issues_filters(client, btc):
    IntegrityIssue.objects.create(
        asset=btc, date=date(2026, 1, 5), type="missing", severity="error"
    )
    IntegrityIssue.objects.create(
        asset=btc,
        date=date(2026, 1, 6),
        type="spike",
        severity="warning",
        resolved_at="2026-01-07T00:00Z",
    )

    open_only = client.get(reverse("integrity-issue-list"), {"resolved": "false"}).json()
    warnings = client.get(reverse("integrity-issue-list"), {"severity": "warning"}).json()

    assert [i["type"] for i in open_only["results"]] == ["missing"]
    assert [i["symbol"] for i in warnings["results"]] == ["KRW-BTC"]


@pytest.mark.django_db
def test_integrity_summary_counts_open_issues_per_asset(client, btc):
    IntegrityIssue.objects.create(
        asset=btc, date=date(2026, 1, 5), type="missing", severity="error"
    )
    IntegrityIssue.objects.create(
        asset=btc, date=date(2026, 1, 6), type="spike", severity="warning"
    )
    CollectionRun.objects.create(trigger="cron", status="success")

    body = client.get(reverse("integrity-summary")).json()

    summary = next(a for a in body["assets"] if a["symbol"] == "KRW-BTC")
    # 일봉 10개 × 이슈 2개를 한 쿼리로 JOIN했다면 개수가 부풀려졌을 것
    assert summary["candle_count"] == 10
    assert (summary["open_errors"], summary["open_warnings"]) == (1, 1)
    assert summary["last_final_date"] == "2026-01-09"
    assert body["last_run"]["trigger"] == "cron"
