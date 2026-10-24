from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command

from market.models import ReprocessRun
from market.reprocess import Result

ARGS = ["--asset", "KRW-BTC", "--target", "aggregates", "--start", "2026-10-20"]


def run(*extra):
    out = StringIO()
    call_command(
        "reprocess", *ARGS, "--end", "2026-10-21", "--reason", "테스트", *extra, stdout=out
    )
    return out.getvalue()


@pytest.mark.django_db
def test_reprocess_command_defaults_to_dry_run():
    out = run()

    record = ReprocessRun.objects.get()
    assert record.dry_run is True
    assert record.start_date == date(2026, 10, 20)
    assert record.end_date == date(2026, 10, 21)
    assert record.reason == "테스트"
    assert record.requested_by  # OS 사용자 이름
    assert "dry-run (반영 안 함): success" in out
    assert "dailyagg: 추가 0, 변경 0, 삭제 0" in out


@pytest.mark.django_db
def test_reprocess_command_apply_and_requested_by():
    run("--apply", "--requested-by", "oofy")

    record = ReprocessRun.objects.get()
    assert record.dry_run is False
    assert record.requested_by == "oofy"


@pytest.mark.django_db
def test_reprocess_command_failure_exits_with_error():
    with (
        patch.dict("market.reprocess.TARGETS", {"aggregates": lambda *a, **k: 1 / 0}),
        pytest.raises(CommandError, match="ZeroDivisionError"),
    ):
        run("--apply")

    assert ReprocessRun.objects.get().status == ReprocessRun.Status.FAILED


@pytest.mark.django_db
def test_reprocess_command_reports_counts():
    fake = Result(rows_before=2, rows_after=1, changed=1, diff={"checks": {"resolved": 1}})
    with patch.dict("market.reprocess.TARGETS", {"aggregates": lambda *a, **k: fake}):
        out = run()

    assert "행 수 2 → 1, 바뀐 행 1" in out
    assert "재검증: {'resolved': 1}" in out


@pytest.mark.django_db
@pytest.mark.parametrize(
    "args, message",
    [
        (["--asset", "KRW-NOPE"], "없는 종목"),
        (["--start", "2026-10-22"], "--start가 --end보다"),
    ],
)
def test_reprocess_command_validates_input(args, message):
    base = dict(zip(ARGS[::2], ARGS[1::2], strict=True))
    base.update(dict(zip(args[::2], args[1::2], strict=True)))
    flat = [x for kv in base.items() for x in kv]
    with pytest.raises(CommandError, match=message):
        call_command("reprocess", *flat, "--end", "2026-10-21", "--reason", "x", stdout=StringIO())
