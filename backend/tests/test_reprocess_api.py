from datetime import date
from unittest.mock import patch

import pytest

from market.models import ReprocessRun
from market.reprocess import Result

URL = "/api/reprocess/"
TOKEN = "test-admin-token"
AUTH = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}
BODY = {
    "symbol": "KRW-BTC",
    "target": "aggregates",
    "start": "2026-10-20",
    "end": "2026-10-21",
    "reason": "집계 다시",
    "requested_by": "oofy",
}


@pytest.fixture(autouse=True)
def admin_token(settings):
    settings.ADMIN_API_TOKEN = TOKEN


@pytest.fixture(autouse=True)
def fixed_today():
    with patch("market.serializers.current_trading_day", return_value=date(2026, 10, 24)):
        yield


def fake_target(result=None, exc=None):
    def target(asset, start, end, client=None):
        if exc:
            raise exc
        return result or Result(rows_before=2, rows_after=2, changed=0, diff={"checks": {}})

    return patch.dict("market.reprocess.TARGETS", {"aggregates": target})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "headers", [{}, {"HTTP_AUTHORIZATION": "Bearer wrong"}, {"HTTP_AUTHORIZATION": "Bearer é"}]
)
def test_reprocess_api_requires_admin_token(client, headers):
    response = client.post(URL, BODY, content_type="application/json", **headers)

    assert response.status_code == 401
    assert not ReprocessRun.objects.exists()


@pytest.mark.django_db
def test_reprocess_api_rejects_everything_when_token_not_configured(client, settings):
    settings.ADMIN_API_TOKEN = ""

    response = client.post(URL, BODY, content_type="application/json", HTTP_AUTHORIZATION="Bearer ")

    assert response.status_code == 401


@pytest.mark.django_db
def test_reprocess_api_defaults_to_dry_run_and_records(client):
    with fake_target():
        response = client.post(URL, BODY, content_type="application/json", **AUTH)

    assert response.status_code == 201
    body = response.json()
    assert body["dry_run"] is True
    assert body["status"] == "success"
    assert body["symbol"] == "KRW-BTC"
    assert body["requested_by"] == "oofy"
    assert body["changed_rows"] == 0

    # 이력 조회는 공개
    detail = client.get(f"{URL}{body['id']}/")
    assert detail.status_code == 200
    assert detail.json()["reason"] == "집계 다시"


@pytest.mark.django_db
def test_reprocess_api_apply(client):
    with fake_target():
        response = client.post(
            URL, {**BODY, "dry_run": False}, content_type="application/json", **AUTH
        )

    assert response.json()["dry_run"] is False


@pytest.mark.django_db
def test_reprocess_api_failure_returns_500_with_record(client):
    with fake_target(exc=RuntimeError("upbit down")):
        response = client.post(URL, BODY, content_type="application/json", **AUTH)

    assert response.status_code == 500
    assert response.json()["error_message"] == "RuntimeError: upbit down"


@pytest.mark.django_db
def test_reprocess_api_conflict_returns_409(client):
    with patch("market.reprocess.lock_days", return_value=False):
        response = client.post(URL, BODY, content_type="application/json", **AUTH)

    assert response.status_code == 409
    assert response.json()["status"] == "rejected"


@pytest.mark.django_db
def test_reprocess_api_validates_period(client):
    response = client.post(
        URL, {**BODY, "end": "2026-10-24"}, content_type="application/json", **AUTH
    )

    assert response.status_code == 400
    assert not ReprocessRun.objects.exists()


@pytest.mark.django_db
def test_reprocess_detail_404(client):
    assert client.get(f"{URL}999/").status_code == 404
