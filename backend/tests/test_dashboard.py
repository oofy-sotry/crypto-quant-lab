import pytest
import requests
import responses

from market.dashboard import revalidate_dashboard

DASHBOARD = "https://dashboard.example.com"
URL = f"{DASHBOARD}/api/revalidate"


@pytest.fixture(autouse=True)
def dashboard_settings(settings):
    settings.DASHBOARD_URL = DASHBOARD
    settings.DASHBOARD_REVALIDATE_SECRET = "test-revalidate-secret"


@responses.activate
def test_revalidate_posts_with_bearer_secret():
    responses.post(URL, json={"revalidated": True})

    assert revalidate_dashboard() is True
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["Authorization"] == "Bearer test-revalidate-secret"


@responses.activate
@pytest.mark.parametrize("missing", ["DASHBOARD_URL", "DASHBOARD_REVALIDATE_SECRET"])
def test_revalidate_skips_without_settings(settings, missing):
    setattr(settings, missing, "")

    assert revalidate_dashboard() is False
    assert len(responses.calls) == 0


@responses.activate
@pytest.mark.parametrize(
    "error",
    [{"status": 401}, {"status": 500}, {"body": requests.ConnectionError()}],
    ids=["unauthorized", "server-error", "connection-error"],
)
def test_revalidate_failure_does_not_raise(error):
    responses.post(URL, **error)

    assert revalidate_dashboard() is False
