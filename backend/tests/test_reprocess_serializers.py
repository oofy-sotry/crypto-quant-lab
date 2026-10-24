from datetime import date
from unittest.mock import patch

import pytest

from market.serializers import ReprocessRequestSerializer

TODAY = date(2026, 10, 24)  # 진행 중인 일봉 날짜


def validate(**overrides):
    data = {
        "symbol": "KRW-BTC",
        "target": "minutes",
        "start": "2026-10-01",
        "end": "2026-10-23",
        "reason": "분봉 누락 복구",
        "requested_by": "oofy",
        **overrides,
    }
    serializer = ReprocessRequestSerializer(data=data)
    with patch("market.serializers.current_trading_day", return_value=TODAY):
        serializer.is_valid()
    return serializer


@pytest.mark.django_db
def test_reprocess_request_defaults_to_dry_run():
    s = validate()

    assert s.errors == {}
    assert s.validated_data["dry_run"] is True
    assert s.validated_data["asset"].symbol == "KRW-BTC"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"end": "2026-10-24"}, "마감된 날(2026-10-23)까지만"),  # 오늘(진행 중)
        ({"start": "2026-10-23", "end": "2026-10-22"}, "start는 end보다"),
        ({"start": "2026-09-22"}, "minutes는 한 번에 31일까지"),  # 32일
        ({"target": "daily", "start": "2025-10-22"}, "daily는 한 번에 366일까지"),  # 367일
    ],
)
def test_reprocess_request_rejects_invalid_period(overrides, message):
    s = validate(**overrides)

    assert message in str(s.errors["non_field_errors"][0])


@pytest.mark.django_db
def test_reprocess_request_accepts_limits_exactly():
    assert validate(start="2026-09-23").errors == {}  # 분봉 31일
    assert validate(target="daily", start="2025-10-23").errors == {}  # 일봉 366일


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["reason", "requested_by", "symbol", "target"])
def test_reprocess_request_requires_fields(field):
    s = validate(**{field: ""})

    assert field in s.errors


@pytest.mark.django_db
def test_reprocess_request_unknown_symbol():
    assert "symbol" in validate(symbol="KRW-NOPE").errors
