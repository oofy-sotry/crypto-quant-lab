"""요청·코드 블록 하나가 실행한 SQL 수와 DB 시간을 잰다.

Django의 CaptureQueriesContext(connection.queries)는 DEBUG일 때만 쌓이고 테스트용이다.
connection.execute_wrapper는 운영 설정에서도 동작하고, 쿼리마다 시간을 직접 잴 수 있다.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.db import connection


@dataclass
class QueryLog:
    """execute_wrapper로 끼워 넣으면 쿼리마다 (SQL, 걸린 초)를 쌓는다."""

    queries: list[tuple[str, float]] = field(default_factory=list)

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.queries.append((sql, time.perf_counter() - start))

    @property
    def count(self) -> int:
        return len(self.queries)

    @property
    def total_ms(self) -> float:
        return sum(seconds for _, seconds in self.queries) * 1000


@contextmanager
def capture_queries():
    """with capture_queries() as log: ... → log.count, log.total_ms."""
    log = QueryLog()
    with connection.execute_wrapper(log):
        yield log
