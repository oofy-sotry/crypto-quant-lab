import json
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_explain_scenarios_reports_statements_and_saves_json(tmp_path):
    out = StringIO()
    path = tmp_path / "result.json"

    call_command(
        "explain_scenarios",
        "--only",
        "minute_status",
        "gaps_31d",
        "--repeat",
        "1",
        "--label",
        "test",
        "--out",
        str(path),
        stdout=out,
    )

    saved = json.loads(path.read_text())
    assert saved["label"] == "test"
    assert set(saved["results"]) == {"minute_status", "gaps_31d"}
    status = saved["results"]["minute_status"]
    assert status["queries"] == len(status["statements"]) > 0
    assert all("exec_ms" in s and "scans" in s for s in status["statements"])
    assert "minute_status:" in out.getvalue()
