"""재처리: 기간을 정해 원본을 다시 받거나 다시 계산한다.

바뀐 것만 반영한 뒤 정합성 검사를 다시 돌리고, 결과를 ReprocessRun에 남긴다.
"""

from datetime import date

from django.db import connection


def lock_days(asset, start: date, end: date) -> bool:
    """start~end(포함) 날짜마다 (종목, 날짜) advisory lock을 잡는다. 하나라도 못 잡으면 False.

    트랜잭션 안에서 불러야 한다. pg_try_advisory_xact_lock은
    - 기다리지 않고 바로 실패를 돌려준다(pg_advisory_xact_lock은 기다림) → 겹치는 요청에 바로 409.
    - 트랜잭션이 끝나면 저절로 풀린다 → 예외로 중간에 끝나도 락이 남지 않고, PgBouncer
      트랜잭션 모드(요청마다 다른 서버 연결)에서도 안전하다. 세션 단위 락은 거기서 깨진다.
    날짜마다 잡기 때문에 기간이 달라도 하루라도 겹치면 충돌한다.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT bool_and(pg_try_advisory_xact_lock(%s, d))"
            " FROM generate_series(%s::int, %s::int) AS d",
            [asset.id, start.toordinal(), end.toordinal()],
        )
        return cursor.fetchone()[0]
