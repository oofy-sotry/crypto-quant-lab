from datetime import date

import pytest
from django.urls import reverse

from market.models import Asset, IntegrityIssue


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model",
    [
        "market_asset",
        "market_dailycandle",
        "market_collectionrun",
        "market_integrityissue",
        "backtest_backtestrun",
    ],
)
def test_admin_changelists_render(admin_client, model):
    assert admin_client.get(reverse(f"admin:{model}_changelist")).status_code == 200


@pytest.mark.django_db
def test_acknowledge_source_gap_action_resolves_with_note(admin_client):
    issue = IntegrityIssue.objects.create(
        asset=Asset.objects.get(symbol="KRW-ETH"),
        date=date(2017, 10, 21),
        type="missing",
        severity="error",
    )

    admin_client.post(
        reverse("admin:market_integrityissue_changelist"),
        {"action": "acknowledge_source_gap", "_selected_action": [issue.pk]},
    )

    issue.refresh_from_db()
    assert issue.resolved_at is not None
    assert issue.note == "업비트 원본에도 없는 데이터 (확인됨)"
