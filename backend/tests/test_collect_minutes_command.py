from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command

NOW = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


@pytest.fixture
def fake_collect():
    with patch(
        "market.management.commands.collect_minutes.collect_minutes", return_value=10
    ) as mock:
        yield mock


@pytest.mark.django_db
def test_collect_minutes_defaults_to_last_day_for_all_active_assets(fake_collect):
    with patch("market.management.commands.collect_minutes.timezone.now", return_value=NOW):
        call_command("collect_minutes", stdout=StringIO())

    assert fake_collect.call_count == 5  # 시드 종목 5개
    kwargs = fake_collect.call_args.kwargs
    assert kwargs["since"] == NOW - timedelta(days=1)
    assert kwargs["to"] is None


@pytest.mark.django_db
def test_collect_minutes_resumes_before_given_to(fake_collect):
    out = StringIO()
    call_command(
        "collect_minutes",
        "--asset",
        "KRW-BTC",
        "--days",
        "30",
        "--to",
        "2026-03-01T00:00",
        stdout=out,
    )

    fake_collect.assert_called_once()
    asset = fake_collect.call_args.args[0]
    kwargs = fake_collect.call_args.kwargs
    assert asset.symbol == "KRW-BTC"
    assert kwargs["to"] == datetime(2026, 3, 1, tzinfo=UTC)
    assert kwargs["since"] == datetime(2026, 1, 30, tzinfo=UTC)
    assert "[KRW-BTC] 저장 10행" in out.getvalue()


@pytest.mark.django_db
def test_collect_minutes_rejects_unknown_asset(fake_collect):
    with pytest.raises(CommandError, match="KRW-NOPE"):
        call_command("collect_minutes", "--asset", "KRW-NOPE", stdout=StringIO())

    fake_collect.assert_not_called()
