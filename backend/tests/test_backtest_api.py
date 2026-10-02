from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.throttling import ScopedRateThrottle

from market.models import Asset, DailyCandle, IntegrityIssue

FIRST = date(2026, 1, 1)


@pytest.fixture
def btc():
    asset = Asset.objects.get(symbol="KRW-BTC")
    DailyCandle.objects.bulk_create(
        DailyCandle(
            asset=asset,
            date=FIRST + timedelta(days=i),
            open=Decimal(c),
            high=Decimal(c),
            low=Decimal(c),
            close=Decimal(c),
            volume=Decimal(1),
            value=Decimal(1),
            is_final=True,
        )
        for i, c in enumerate(100 + (i % 7) * 3 for i in range(60))
    )
    return asset


def body(**overrides):
    values = {
        "symbol": "KRW-BTC",
        "strategy": "ma_cross",
        "short": 3,
        "long": 10,
        "start": "2026-01-20",
        "end": "2026-02-28",
    }
    values.update(overrides)
    return {k: v for k, v in values.items() if v is not None}


@pytest.mark.django_db
def test_post_backtest_returns_201_then_200_for_same_request(client, btc):
    url = reverse("backtest-create")

    first = client.post(url, body(), content_type="application/json")
    second = client.post(url, body(), content_type="application/json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    result = first.json()
    assert result["params"]["fee"] == 0.0005  # 기본 수수료
    assert {"metrics", "benchmark", "equity_curve"} <= result.keys()


@pytest.mark.django_db
def test_get_backtest_detail(client, btc):
    created = client.post(reverse("backtest-create"), body(), content_type="application/json")

    response = client.get(reverse("backtest-detail", args=[created.json()["id"]]))

    assert response.status_code == 200
    assert response.json()["metrics"] == created.json()["metrics"]
    assert client.get(reverse("backtest-detail", args=[99999])).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"symbol": "KRW-NOPE"},
        {"strategy": "magic"},
        {"short": 10, "long": 3},
        {"short": None},  # ma_cross인데 short 없음
        {"start": "2026-02-28", "end": "2026-01-20"},
        {"fee": 0.5},
    ],
)
def test_post_backtest_rejects_invalid_input(client, btc, overrides):
    response = client.post(
        reverse("backtest-create"), body(**overrides), content_type="application/json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_buy_and_hold_does_not_need_windows(client, btc):
    response = client.post(
        reverse("backtest-create"),
        body(strategy="buy_and_hold", short=None, long=None),
        content_type="application/json",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_post_backtest_returns_422_when_data_has_open_errors(client, btc):
    IntegrityIssue.objects.create(
        asset=btc, date=date(2026, 2, 1), type="missing", severity="error"
    )

    response = client.post(reverse("backtest-create"), body(), content_type="application/json")

    assert response.status_code == 422
    assert "2026-02-01" in response.json()["detail"]


@pytest.mark.django_db
def test_backtest_endpoint_is_throttled(client, btc):
    # DRF throttle은 import 시점에 설정을 클래스 속성으로 읽어 두므로 settings 변경으로는 안 바뀐다.
    rates = {**ScopedRateThrottle.THROTTLE_RATES, "backtest": "2/min"}
    url = reverse("backtest-create")

    with patch.object(ScopedRateThrottle, "THROTTLE_RATES", rates):
        codes = [
            client.post(url, body(), content_type="application/json").status_code for _ in range(3)
        ]

    assert codes == [201, 200, 429]
