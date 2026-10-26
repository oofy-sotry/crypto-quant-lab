import pytest
from django.db import connection

from config.querylog import capture_queries
from market.models import Asset

pytestmark = pytest.mark.django_db


def test_capture_queries_counts_queries_and_time():
    with capture_queries() as log:
        Asset.objects.count()
        list(Asset.objects.all())

    assert log.count == 2
    assert "COUNT" in log.queries[0][0]
    assert log.total_ms > 0


def test_capture_queries_records_failed_query():
    with capture_queries() as log, pytest.raises(Exception):  # noqa: B017
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM no_such_table")

    assert log.count == 1


def test_middleware_adds_server_timing_header(client):
    response = client.get("/api/assets/")

    timing = response["Server-Timing"]
    assert timing.startswith("db;dur=")
    assert timing.endswith('desc="1 queries"')


def test_capture_queries_stops_after_block():
    with capture_queries() as log:
        Asset.objects.count()
    Asset.objects.count()

    assert log.count == 1
