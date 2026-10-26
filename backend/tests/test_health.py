from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from config.querylog import SLOW_QUERIES_KEY


@pytest.mark.django_db
def test_health_ok(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "cache": "ok"}
    assert set(body["latency_ms"]) == {"database", "cache"}


@pytest.mark.django_db
def test_health_returns_503_when_cache_fails(client):
    with patch("config.views.cache.set", side_effect=ConnectionError):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    assert response.json()["checks"]["cache"] == "error: ConnectionError"
    assert response.json()["queries"]["slow_24h"] is None  # 목록이 Redis에 있어 알 수 없음


@pytest.mark.django_db
def test_health_reports_slow_queries_of_last_24_hours(client, settings):
    settings.SLOW_QUERY_MS = 150
    now = timezone.now()
    cache.set(
        SLOW_QUERIES_KEY,
        [
            {"at": (now - timedelta(hours=1)).isoformat(), "path": "/a", "ms": 300, "sql": "S"},
            {"at": (now - timedelta(hours=30)).isoformat(), "path": "/b", "ms": 300, "sql": "S"},
        ],
    )

    body = client.get(reverse("health")).json()

    assert body["queries"] == {"slow_threshold_ms": 150, "slow_24h": 1}


@pytest.mark.django_db
def test_openapi_schema_and_swagger_ui_are_served(client):
    schema = client.get(reverse("schema"))
    docs = client.get(reverse("swagger-ui"))

    assert schema.status_code == 200
    assert b"/api/backtests/" in schema.content
    assert docs.status_code == 200


@pytest.mark.django_db
def test_health_survives_slow_query_list_failure(client):
    # Redis 확인은 통과했는데 목록 읽기에서 실패해도 health는 500으로 죽지 않는다.
    with patch("config.views.recent_slow_queries", side_effect=ConnectionError):
        response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json()["queries"]["slow_24h"] is None
