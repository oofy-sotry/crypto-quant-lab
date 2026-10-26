from unittest.mock import patch

import pytest
from django.db import connection

from config.querylog import (
    SLOW_QUERIES_KEEP,
    Query,
    QueryLog,
    capture_queries,
    recent_slow_queries,
    record_slow_queries,
)
from market.models import Asset

pytestmark = pytest.mark.django_db


def test_capture_queries_counts_queries_and_time():
    with capture_queries() as log:
        Asset.objects.count()
        list(Asset.objects.all())

    assert log.count == 2
    assert "COUNT" in log.queries[0].sql
    assert log.total_ms > 0


def test_capture_queries_keeps_params_for_rerun():
    with capture_queries() as log:
        Asset.objects.filter(symbol="KRW-BTC").exists()

    query = log.queries[0]
    assert "KRW-BTC" in query.params
    with connection.cursor() as cursor:  # 같은 문장을 그대로 다시 실행할 수 있다
        cursor.execute(query.sql, query.params)
        assert cursor.fetchone() is not None


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


def slow_log(*seconds, sql="SELECT 1"):
    return QueryLog([Query(sql, ("비밀값",), s) for s in seconds])


def test_record_slow_queries_keeps_newest_first_without_params(settings):
    settings.SLOW_QUERY_MS = 200
    record_slow_queries("/api/a/", slow_log(0.05, 0.3, sql="SELECT old"))
    added = record_slow_queries("/api/b/", slow_log(0.25))

    entries = recent_slow_queries()
    assert added == 1
    assert [(e["path"], e["ms"]) for e in entries] == [("/api/b/", 250.0), ("/api/a/", 300.0)]
    assert "비밀값" not in str(entries)  # 파라미터 값은 남기지 않음


def test_record_slow_queries_skips_cron_and_caps_list(settings):
    settings.SLOW_QUERY_MS = 1
    assert record_slow_queries("/api/cron/minutes/", slow_log(5)) == 0

    record_slow_queries("/api/a/", slow_log(*[0.01] * 60))

    assert len(recent_slow_queries()) == SLOW_QUERIES_KEEP


def test_record_slow_queries_survives_cache_failure(settings):
    settings.SLOW_QUERY_MS = 1
    with patch("config.querylog.cache.get", side_effect=ConnectionError("redis down")):
        assert record_slow_queries("/api/a/", slow_log(0.5)) == 1  # 요청은 실패하지 않음
