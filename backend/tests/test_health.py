from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_ok(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}


@pytest.mark.django_db
def test_health_returns_503_when_cache_fails(client):
    with patch("config.views.cache.set", side_effect=ConnectionError):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    assert response.json()["checks"]["cache"] == "error: ConnectionError"
