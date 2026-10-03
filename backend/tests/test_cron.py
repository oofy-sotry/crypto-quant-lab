from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.throttling import AnonRateThrottle

from market.models import CollectionRun

URL = "/api/cron/collect/"
SECRET = "test-cron-secret"


@pytest.fixture(autouse=True)
def cron_secret(settings):
    settings.CRON_SECRET = SECRET


@pytest.fixture
def fake_collect():
    def run(trigger):
        return CollectionRun.objects.create(
            trigger=trigger,
            status=CollectionRun.Status.SUCCESS,
            finished_at=timezone.now(),
            assets_count=5,
            upserted_count=35,
        )

    with patch("market.views.collect_candles", side_effect=run) as mock:
        yield mock


@pytest.mark.django_db
def test_cron_collect_runs_with_valid_secret(client, fake_collect):
    response = client.get(URL, HTTP_AUTHORIZATION=f"Bearer {SECRET}")

    assert response.status_code == 200
    fake_collect.assert_called_once_with(CollectionRun.Trigger.CRON)
    body = response.json()
    assert body["trigger"] == "cron"
    assert body["status"] == "success"
    assert body["upserted_count"] == 35


@pytest.mark.django_db
@pytest.mark.parametrize(
    "header",
    [None, "Bearer wrong-secret", SECRET, f"Basic {SECRET}"],
    ids=["missing", "wrong", "no-scheme", "basic"],
)
def test_cron_collect_rejects_bad_authorization(client, fake_collect, header):
    extra = {"HTTP_AUTHORIZATION": header} if header else {}
    response = client.get(URL, **extra)

    assert response.status_code == 401
    fake_collect.assert_not_called()


@pytest.mark.django_db
def test_cron_collect_rejects_everything_when_secret_unset(client, fake_collect, settings):
    """비밀값이 비어 있을 때 "Bearer "만 보내면 통과하는 구멍이 없어야 한다."""
    settings.CRON_SECRET = ""

    response = client.get(URL, HTTP_AUTHORIZATION="Bearer ")

    assert response.status_code == 401
    fake_collect.assert_not_called()


@pytest.mark.django_db
def test_cron_collect_sentry_test_raises_without_collecting(client, fake_collect):
    with pytest.raises(RuntimeError, match="Sentry"):
        client.get(URL + "?sentry_test=1", HTTP_AUTHORIZATION=f"Bearer {SECRET}")

    fake_collect.assert_not_called()


@pytest.mark.django_db
def test_cron_collect_is_not_throttled(client, fake_collect):
    """Cron은 throttle(Redis)에 막히면 안 된다. anon 한도를 1회로 줄여도 계속 통과해야 한다."""
    # DRF throttle은 import 시점에 설정을 클래스 속성으로 읽어 두므로 settings 변경으로는 안 바뀐다.
    rates = {**AnonRateThrottle.THROTTLE_RATES, "anon": "1/min"}

    with patch.object(AnonRateThrottle, "THROTTLE_RATES", rates):
        codes = [
            client.get(URL, HTTP_AUTHORIZATION=f"Bearer {SECRET}").status_code for _ in range(3)
        ]

    assert codes == [200, 200, 200]
