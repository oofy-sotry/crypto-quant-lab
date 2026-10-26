"""요청·코드 블록 하나가 실행한 SQL 수와 DB 시간을 잰다.

Django의 CaptureQueriesContext(connection.queries)는 DEBUG일 때만 쌓이고 테스트용이다.
connection.execute_wrapper는 운영 설정에서도 동작하고, 쿼리마다 시간을 직접 잴 수 있다.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.db import connection


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
        return response
