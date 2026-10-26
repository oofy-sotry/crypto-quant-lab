from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from config.querylog import Query, QueryLog, record_slow_queries
from market.aggregates import upsert_aggregates
from market.models import Asset, DailyCandle, IntegrityIssue, MinuteCandle, ReprocessRun
from market.ops import cell_status

D1 = date(2026, 10, 20)
D2 = date(2026, 10, 21)
D3 = date(2026, 10, 22)
TODAY = date(2026, 10, 23)  # 진행 중인 날 → 표는 D3까지


def midnight(day):
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def fill(asset, day, minutes, skip=()):
    MinuteCandle.objects.bulk_create(
        MinuteCandle(
            asset=asset,
            ts=midnight(day) + timedelta(minutes=i),
            open=Decimal(100),
            high=Decimal(100),
            low=Decimal(100),
            close=Decimal(100),
            volume=Decimal(1),
            value=Decimal(100),
        )
        for i in range(minutes)
        if i not in skip
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((1440, 1440, 1, 1), "error"),  # 오류가 가장 먼저
        ((0, None, 0, 1), "no_minutes"),
        ((1440, None, 0, 0), "not_aggregated"),  # 집계 없음
        ((1440, 1380, 0, 1), "not_aggregated"),  # 집계 뒤 분봉이 바뀜
        ((1440, 1440, 0, 1), "warning"),
        ((1440, 1440, 0, 0), "ok"),
    ],
)
def test_cell_status_priority(args, expected):
    assert cell_status(*args) == expected


@pytest.fixture
def btc():
    """D1: 정상, D2: 분봉만 있고 집계 안 됨, D3: 분봉 없음 + 오류 이슈. D1~D2 재처리 이력 1건."""
    asset = Asset.objects.get(symbol="KRW-BTC")
    fill(asset, D1, 1440, skip=range(600, 640))  # 10:00~10:39 빈 구간 40분
    upsert_aggregates(asset, "hour", midnight(D1), midnight(D2))
    upsert_aggregates(asset, "day", midnight(D1), midnight(D2))
    fill(asset, D2, 60)
    DailyCandle.objects.create(
        asset=asset,
        date=D1,
        open=100,
        high=100,
        low=100,
        close=100,
        volume=1400,
        value=140000,
        is_final=True,
    )
    IntegrityIssue.objects.create(
        asset=asset, date=D1, type="minute_gap", severity="warning", detail={}
    )
    IntegrityIssue.objects.create(asset=asset, date=D3, type="missing", severity="error")
    ReprocessRun.objects.create(
        asset=asset,
        target="aggregates",
        start_date=D1,
        end_date=D2,
        dry_run=True,
        reason="확인",
        requested_by="test",
        status="success",
    )
    return asset


@pytest.mark.django_db
def test_ops_days_builds_matrix_of_closed_days(client, btc):
    with patch("market.views.current_trading_day", return_value=TODAY):
        response = client.get(reverse("ops-days"), {"days": 3})

    assert response.status_code == 200
    body = response.json()
    assert (body["start"], body["end"]) == ("2026-10-20", "2026-10-22")
    rows = {r["symbol"]: r["cells"] for r in body["rows"]}
    assert len(rows) == 5  # 활성 종목 전부, 데이터 없는 종목도
    d1, d2, d3 = rows["KRW-BTC"]
    assert d1 == {
        "date": "2026-10-20",
        "status": "warning",
        "minute_count": 1400,
        "aggregated_minutes": 1400,
        "daily_final": True,
        "open_errors": 0,
        "open_warnings": 1,
        "reprocess_runs": 1,
    }
    assert (d2["status"], d2["minute_count"], d2["aggregated_minutes"]) == (
        "not_aggregated",
        60,
        None,
    )
    assert (d2["reprocess_runs"], d3["reprocess_runs"]) == (1, 0)
    assert (d3["status"], d3["open_errors"]) == ("error", 1)
    assert {c["status"] for c in rows["KRW-ETH"]} == {"no_minutes"}


@pytest.mark.django_db
@pytest.mark.parametrize("days", ["0", "91", "abc"])
def test_ops_days_rejects_invalid_days(client, days):
    assert client.get(reverse("ops-days"), {"days": days}).status_code == 400


@pytest.mark.django_db
def test_ops_day_detail_shows_gaps_hours_comparison_issues_and_runs(client, btc):
    response = client.get(reverse("ops-day", args=["KRW-BTC", "2026-10-20"]))

    assert response.status_code == 200
    body = response.json()
    assert body["minute_count"] == 1400
    assert body["gaps"] == [
        {"start": "2026-10-20T10:00:00Z", "end": "2026-10-20T10:40:00Z", "minutes": 40}
    ]
    assert len(body["hourly"]) == 24
    assert body["hourly"][10] == {"hour": "2026-10-20T10:00:00Z", "minute_count": 20}
    assert body["daily_agg"]["close"] == "100.00000000"  # Decimal은 문자열
    assert body["daily_agg"]["minute_count"] == 1400
    assert body["daily_candle"]["volume"] == "1400.00000000"
    assert body["daily_candle"]["is_final"] is True
    assert [i["type"] for i in body["issues"]] == ["minute_gap"]
    assert [r["target"] for r in body["reprocess_runs"]] == ["aggregates"]


@pytest.mark.django_db
def test_ops_day_detail_without_data_and_bad_input(client):
    body = client.get(reverse("ops-day", args=["KRW-ETH", "2026-10-20"])).json()
    assert (body["minute_count"], body["daily_agg"], body["daily_candle"]) == (0, None, None)
    assert all(h["minute_count"] == 0 for h in body["hourly"])

    assert client.get(reverse("ops-day", args=["KRW-NOPE", "2026-10-20"])).status_code == 404
    assert client.get(reverse("ops-day", args=["KRW-BTC", "어제"])).status_code == 400


@pytest.mark.django_db
def test_ops_slow_queries_lists_recorded_entries(client, settings):
    settings.SLOW_QUERY_MS = 100
    record_slow_queries("/api/minutes/", QueryLog([Query("SELECT 느림", (1,), 0.4)]))

    body = client.get(reverse("ops-slow-queries")).json()

    assert [(e["path"], e["ms"], e["sql"]) for e in body] == [
        ("/api/minutes/", 400.0, "SELECT 느림")
    ]
