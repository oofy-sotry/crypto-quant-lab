from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from market.models import CollectionRun


@pytest.fixture
def fake_collect():
    def run(trigger, days):
        return CollectionRun.objects.create(
            trigger=trigger, status=CollectionRun.Status.SUCCESS, finished_at=timezone.now()
        )

    with patch("market.management.commands.collect.collect_candles", side_effect=run) as mock:
        yield mock


@pytest.mark.django_db
def test_collect_defaults_to_recent_seven_days(fake_collect):
    call_command("collect", stdout=StringIO())

    fake_collect.assert_called_once_with(CollectionRun.Trigger.MANUAL, days=7)


@pytest.mark.django_db
def test_collect_all_runs_backfill(fake_collect):
    call_command("collect", "--all", stdout=StringIO())

    fake_collect.assert_called_once_with(CollectionRun.Trigger.BACKFILL, days=None)
