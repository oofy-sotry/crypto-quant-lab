"""조회 API의 요청당 쿼리 수를 고정한다.

행마다 쿼리가 늘어나는 N+1(예: 이슈마다 종목 조회)이 생기면 여기서 실패한다.
그래서 데이터는 종목 여러 개·행 여러 개로 만든다.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from market.aggregates import upsert_aggregates
from market.models import (
    Asset,
    CollectionRun,
    DailyCandle,
    IntegrityIssue,
    MinuteCandle,
    ReprocessRun,
)

pytestmark = pytest.mark.django_db

START = datetime(2026, 10, 22, tzinfo=UTC)


@pytest.fixture
def data():
    assets = list(Asset.objects.all())
    for asset in assets:
        DailyCandle.objects.bulk_create(
            DailyCandle(
                asset=asset,
                date=date(2026, 10, 1) + timedelta(days=i),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
                value=1,
                is_final=True,
            )
            for i in range(3)
        )
        MinuteCandle.objects.bulk_create(
            MinuteCandle(
                asset=asset,
                ts=START + timedelta(minutes=i),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=Decimal(1),
                value=Decimal(1),
            )
            for i in range(90)
        )
        for unit in ("hour", "day"):
            upsert_aggregates(asset, unit, START, START + timedelta(days=1))
        IntegrityIssue.objects.create(
            asset=asset,
            date=date(2026, 10, 2),
            type=IntegrityIssue.Type.MISSING,
            severity=IntegrityIssue.Severity.ERROR,
        )
    CollectionRun.objects.create(trigger=CollectionRun.Trigger.MANUAL)
    CollectionRun.objects.create(trigger=CollectionRun.Trigger.CRON)
    run = ReprocessRun.objects.create(
        asset=assets[0],
        target=ReprocessRun.Target.AGGREGATES,
        start_date=date(2026, 10, 22),
        end_date=date(2026, 10, 22),
        dry_run=True,
        reason="테스트",
        requested_by="test",
    )
    return {"reprocess_id": run.id}


@pytest.mark.parametrize(
    ("name", "query", "expected"),
    [
        ("asset-list", {}, 1),
        ("candle-list", {"symbol": "KRW-BTC"}, 3),  # 종목 + COUNT + 목록 (페이지 번호 방식)
        ("minute-list", {"symbol": "KRW-BTC", "page_size": 30}, 2),  # 종목 + 목록 (COUNT 없음)
        ("bar-list", {"symbol": "KRW-BTC", "unit": "hour"}, 2),
        ("minute-status", {}, 1),  # 전 종목 최신 시각을 서브쿼리로 한 번에
        ("integrity-issue-list", {}, 2),  # COUNT + 목록(종목은 JOIN)
        ("integrity-summary", {}, 3),  # 이슈 수 + 일봉 범위 + 마지막 수집
        ("collection-run-list", {}, 2),
        ("ops-days", {"days": 30}, 6),  # 종목 + 테이블마다 GROUP BY 한 번(칸 수와 무관)
        ("reprocess", {}, 2),  # COUNT + 목록(종목은 JOIN)
    ],
)
def test_list_api_query_count_is_fixed(
    client, data, django_assert_num_queries, name, query, expected
):
    with django_assert_num_queries(expected):
        response = client.get(reverse(name), query)

    assert response.status_code == 200


def test_ops_day_detail_query_count_is_fixed(client, data, django_assert_num_queries):
    # 종목, 분봉 수, 빈 구간, 시간봉, 일 집계, 일봉, 이슈, 재처리 이력
    with django_assert_num_queries(8):
        response = client.get(reverse("ops-day", args=["KRW-BTC", "2026-10-22"]))

    assert response.status_code == 200


def test_reprocess_detail_query_count_is_fixed(client, data, django_assert_num_queries):
    with django_assert_num_queries(1):  # 종목은 JOIN
        response = client.get(reverse("reprocess-detail", args=[data["reprocess_id"]]))

    assert response.status_code == 200
