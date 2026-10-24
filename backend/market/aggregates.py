"""분봉 → 시간봉·일봉 집계. 수백만 행을 파이썬으로 옮기지 않도록 DB 쿼리 한 문장으로 계산한다."""

from datetime import datetime

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
#   rowcount가 "실제로 바뀐 행 수"가 된다.
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
    """[start, end) 분봉을 unit("hour"|"day") 구간으로 집계해 저장한다.

    새로 넣거나 값이 바뀐 행 수를 돌려준다.

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
        return cursor.rowcount
