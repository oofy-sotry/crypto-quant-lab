"""요청·코드 블록 하나가 실행한 SQL 수와 DB 시간을 잰다.

Django의 CaptureQueriesContext(connection.queries)는 DEBUG일 때만 쌓이고 테스트용이다.
connection.execute_wrapper는 운영 설정에서도 동작하고, 쿼리마다 시간을 직접 잴 수 있다.
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class Query:
    sql: str
    params: object  # 같은 문장을 다시 실행(EXPLAIN)할 수 있게 그대로 둔다
    seconds: float


@dataclass
class QueryLog:
    """execute_wrapper로 끼워 넣으면 실행된 쿼리를 차례로 쌓는다."""

    queries: list[Query] = field(default_factory=list)

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.queries.append(Query(sql, params, time.perf_counter() - start))

    @property
    def count(self) -> int:
        return len(self.queries)

    @property
    def total_ms(self) -> float:
        return sum(q.seconds for q in self.queries) * 1000


@contextmanager
def capture_queries():
    """with capture_queries() as log: ... → log.count, log.total_ms."""
    log = QueryLog()
    with connection.execute_wrapper(log):
        yield log


SLOW_QUERIES_KEY = "ops:slow_queries"
SLOW_QUERIES_KEEP = 50  # 최근 몇 건까지 보관할지
SLOW_QUERIES_TTL = 7 * 24 * 60 * 60
# 배치 작업(Cron)은 큰 upsert가 원래 오래 걸리고 소요 시간은 실행 기록(CollectionRun.detail)에
# 따로 남는다. 여기까지 쌓으면 목록이 배치 쿼리로 금방 차서 API의 느린 쿼리가 묻힌다.
SLOW_QUERY_SKIP_PREFIXES = ("/api/cron/",)


def record_slow_queries(path: str, log: QueryLog) -> int:
    """SLOW_QUERY_MS 이상 걸린 쿼리를 경고 로그로 남기고 Redis 목록 앞에 붙인다. 붙인 수를 돌려준다.

    목록은 읽고-붙이고-쓰기라 동시에 들어온 요청끼리 한두 건을 덮어쓸 수 있다. 운영 참고용이라
    정확한 집계보다 요청을 느리게 하지 않는 쪽을 골랐다. Redis 장애는 요청을 실패시키지 않는다.
    """
    if path.startswith(SLOW_QUERY_SKIP_PREFIXES):
        return 0
    slow = [q for q in log.queries if q.seconds * 1000 >= settings.SLOW_QUERY_MS]
    if not slow:
        return 0
    now = timezone.now().isoformat()
    entries = []
    for q in slow:
        ms = round(q.seconds * 1000, 1)
        logger.warning("느린 쿼리 %.1fms %s: %s", ms, path, q.sql[:300])
        # 파라미터 값은 남기지 않는다(SQL 모양만으로 원인을 찾고, 값이 공개 목록에 나가지 않게).
        entries.append({"at": now, "path": path, "ms": ms, "sql": q.sql[:500]})
    try:
        kept = cache.get(SLOW_QUERIES_KEY) or []
        cache.set(SLOW_QUERIES_KEY, (entries + kept)[:SLOW_QUERIES_KEEP], SLOW_QUERIES_TTL)
    except Exception:
        logger.warning("느린 쿼리 목록 저장 실패", exc_info=True)
    return len(entries)


def recent_slow_queries() -> list[dict]:
    return cache.get(SLOW_QUERIES_KEY) or []


class QueryTimingMiddleware:
    """응답에 `Server-Timing: db;dur=<ms>;desc="<n> queries"` 헤더를 붙인다.

    브라우저 개발자 도구(Network → Timing)와 curl -I로 요청당 쿼리 수·DB 시간을 바로 본다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with capture_queries() as log:
            response = self.get_response(request)
        response["Server-Timing"] = f'db;dur={log.total_ms:.1f};desc="{log.count} queries"'
        record_slow_queries(request.path, log)
        return response
