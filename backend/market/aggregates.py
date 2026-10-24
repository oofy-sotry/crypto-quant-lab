"""분봉 → 시간봉·일봉 집계. 수백만 행을 파이썬으로 옮기지 않도록 DB 쿼리 한 문장으로 계산한다."""

from datetime import datetime, timedelta

from django.db import connection

from market.models import AggBar, Asset, DailyAgg, HourlyBar, MinuteCandle

# 집계 계산 방식(컬럼 정의·공식)이 바뀌면 올린다.
AGG_VERSION = 1

MODELS: dict[str, type[AggBar]] = {"hour": HourlyBar, "day": DailyAgg}

VALUE_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
    "vwap",
    "volatility",
    "minute_count",
    "agg_version",
]

# 윈도 함수로 분봉마다 구간 첫 시가·마지막 종가·직전 분 종가를 붙인 뒤 GROUP BY로 묶는다.
# - date_trunc(unit, ts, 'UTC'): 세션 타임존과 상관없이 UTC 기준으로 자른다(일봉 경계 = UTC 00:00).
# - 수익률은 같은 구간 안에서만 계산한다(구간 첫 분은 직전 분이 없음).
#   범위를 어디서 끊어 다시 집계해도 결과가 같아야 재처리가 멱등이 된다.
# - ON CONFLICT ... WHERE: 값이 그대로면 UPDATE하지 않는다 → aggregated_at이 괜히 바뀌지 않고,
#   RETURNING에는 실제로 새로 넣거나 바뀐 행만 나온다.
# - RETURNING (xmax = 0): 새로 INSERT된 행은 xmax(행을 지우거나 고친 트랜잭션 id)가 0이고,
#   ON CONFLICT로 UPDATE된 행은 0이 아니다. 추가와 변경을 한 문장에서 구분하는 PostgreSQL 관용구.
# - vwap: numeric 나눗셈은 피연산자 자릿수로 정한 소수 자리(여기선 12자리)에서 한 번 반올림한다.
#   그 값을 다시 8자리로 반올림하면 이중 반올림으로 마지막 자리가 1 틀릴 수 있다
#   (…264|4999… → …2645000 → …265). 소수 20자리로 나눈 뒤 8자리로 반올림한다.
SQL = """
INSERT INTO {table} (asset_id, bucket, {columns}, aggregated_at)
SELECT asset_id, bucket,
       any_value(first_open), max(high), min(low), any_value(last_close),
       sum(volume), sum(value),
       round(sum(value)::numeric(50, 20) / NULLIF(sum(volume), 0), 8),
       stddev_samp(ln(close::float8 / prev_close::float8)),
       count(*), %(version)s, now()
FROM (
    SELECT asset_id, date_trunc(%(unit)s, ts, 'UTC') AS bucket, high, low, close, volume, value,
           first_value(open) OVER w AS first_open,
           last_value(close) OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
               AS last_close,
           lag(close) OVER w AS prev_close
    FROM {minute_table}
    WHERE asset_id = %(asset_id)s AND ts >= %(start)s AND ts < %(end)s
    WINDOW w AS (PARTITION BY date_trunc(%(unit)s, ts, 'UTC') ORDER BY ts)
) m
GROUP BY asset_id, bucket
ON CONFLICT (asset_id, bucket) DO UPDATE
SET {updates}, aggregated_at = EXCLUDED.aggregated_at
WHERE ({target_values}) IS DISTINCT FROM ({excluded_values})
RETURNING bucket, ({table}.xmax = 0) AS inserted
"""


def _build_sql(model: type[AggBar]) -> str:
    table = model._meta.db_table
    return SQL.format(
        table=table,
        minute_table=MinuteCandle._meta.db_table,
        columns=", ".join(VALUE_COLUMNS),
        updates=", ".join(f"{c} = EXCLUDED.{c}" for c in VALUE_COLUMNS),
        target_values=", ".join(f"{table}.{c}" for c in VALUE_COLUMNS),
        excluded_values=", ".join(f"EXCLUDED.{c}" for c in VALUE_COLUMNS),
    )


def aggregate_minutes(asset: Asset, unit: str, start: datetime, end: datetime) -> int:
    """upsert_aggregates와 같고, 새로 넣거나 바뀐 행 수만 돌려준다."""
    return len(upsert_aggregates(asset, unit, start, end))


def upsert_aggregates(
    asset: Asset, unit: str, start: datetime, end: datetime
) -> list[tuple[datetime, bool]]:
    """[start, end) 분봉을 unit("hour"|"day") 구간으로 집계해 저장한다.

    새로 넣거나 값이 바뀐 구간만 (구간 시작, 새로 넣었는지)로 돌려준다.
    start·end는 구간 경계에 맞춰 넘긴다(구간 중간에서 자르면 일부 분봉만으로 집계된다).
    분봉이 하나도 없는 구간은 행을 만들지 않는다.
    """
    model = MODELS[unit]
    params = {
        "unit": unit,
        "version": AGG_VERSION,
        "asset_id": asset.id,
        "start": start,
        "end": end,
    }
    with connection.cursor() as cursor:
        cursor.execute(_build_sql(model), params)
        return cursor.fetchall()


STEP = {"hour": timedelta(hours=1), "day": timedelta(days=1)}

# 분봉이 하나도 남지 않은 구간의 집계 행을 지운다. upsert만으로는 분봉이 사라진 구간의 옛 집계가
# 그대로 남기 때문에, 재처리에서 [start, end)를 "다시 만든 결과로 교체"하려면 이 단계가 필요하다.
DELETE_ORPHANS_SQL = """
DELETE FROM {table} a
WHERE a.asset_id = %(asset_id)s AND a.bucket >= %(start)s AND a.bucket < %(end)s
  AND NOT EXISTS (
      SELECT 1 FROM {minute_table} m
      WHERE m.asset_id = a.asset_id AND m.ts >= a.bucket AND m.ts < a.bucket + %(step)s
  )
RETURNING a.bucket
"""


def delete_orphan_aggregates(asset: Asset, unit: str, start: datetime, end: datetime) -> list:
    """[start, end)에서 분봉이 없는 구간의 집계 행을 지우고, 지운 구간 시작 시각들을 돌려준다."""
    sql = DELETE_ORPHANS_SQL.format(
        table=MODELS[unit]._meta.db_table, minute_table=MinuteCandle._meta.db_table
    )
    params = {"asset_id": asset.id, "start": start, "end": end, "step": STEP[unit]}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return [row[0] for row in cursor.fetchall()]
