import pytest

ALLOWED = "http://localhost:3000"


@pytest.fixture(autouse=True)
def allowed_origins(settings):
    settings.CORS_ALLOWED_ORIGINS = [ALLOWED]


@pytest.mark.django_db
def test_cors_allows_dashboard_origin(client):
    response = client.get("/api/assets/", HTTP_ORIGIN=ALLOWED)

    assert response["Access-Control-Allow-Origin"] == ALLOWED


@pytest.mark.django_db
def test_cors_ignores_unknown_origin(client):
    response = client.get("/api/assets/", HTTP_ORIGIN="https://evil.example.com")

    assert "Access-Control-Allow-Origin" not in response


def test_cors_preflight_for_backtest_post(client):
    """브라우저는 JSON POST 전에 OPTIONS로 허락을 먼저 묻는다(preflight)."""
    response = client.options(
        "/api/backtests/",
        HTTP_ORIGIN=ALLOWED,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
    )

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == ALLOWED
    assert "POST" in response["Access-Control-Allow-Methods"]
