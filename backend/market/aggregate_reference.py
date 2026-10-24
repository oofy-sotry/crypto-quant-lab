"""DB 집계(market/aggregates.py)가 맞는지 확인하는 pandas 참조 구현.

같은 정의를 SQL과 전혀 다른 방식(파이썬 Decimal + pandas groupby)으로 한 번 더 계산해서 비교한다.
운영 경로에서는 쓰지 않고, 테스트와 실제 데이터 검증에만 쓴다.
"""

import math
from collections.abc import Iterable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from market.aggregates import MODELS
from market.models import Asset

FREQ = {"hour": "h", "day": "D"}
PRICE_STEP = Decimal("0.00000001")  # 소수 8자리 (DecimalField decimal_places)
EXACT_FIELDS = ["open", "high", "low", "close", "volume", "value", "vwap", "minute_count"]
VOLATILITY_REL_TOL = 1e-9  # float 계산 순서 차이만 허용


def reference_aggregate(minutes: Iterable[dict], unit: str) -> dict[datetime, dict]:
    """분봉(ts, open, high, low, close, volume, value 키를 가진 dict)을 구간별로 집계한다.

    돌려주는 값: {구간 시작(UTC datetime): {필드: 값}}. 가격·거래량은 Decimal 그대로 계산한다.
    """
    df = pd.DataFrame(list(minutes))
    if df.empty:
        return {}
    df = df.sort_values("ts")
    df["bucket"] = pd.to_datetime(df["ts"], utc=True).dt.floor(FREQ[unit])
    groups = df.groupby("bucket", sort=True)

    close = df["close"].astype(float)
    log_return = np.log(close / groups["close"].shift(1).astype(float))  # 같은 구간 안에서만

    out = groups.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", lambda s: sum(s, Decimal(0))),
        value=("value", lambda s: sum(s, Decimal(0))),
        minute_count=("ts", "size"),
    )
    out["volatility"] = log_return.groupby(df["bucket"]).std(ddof=1)

    result = {}
    for bucket, row in out.iterrows():
        vwap = None
        if row["volume"] != 0:
            vwap = (row["value"] / row["volume"]).quantize(PRICE_STEP, rounding=ROUND_HALF_UP)
        vol = row["volatility"]
        result[bucket.to_pydatetime()] = {
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "value": row["value"],
            "vwap": vwap,
            "volatility": None if pd.isna(vol) else float(vol),
            "minute_count": int(row["minute_count"]),
        }
    return result


def diff_against_db(asset: Asset, unit: str, start: datetime, end: datetime) -> list[dict]:
    """[start, end) 구간에서 DB 집계와 참조 구현이 다른 곳을 모두 돌려준다. 빈 리스트면 일치."""
    minutes = asset.minute_candles.filter(ts__gte=start, ts__lt=end).values(
        "ts", "open", "high", "low", "close", "volume", "value"
    )
    expected = reference_aggregate(minutes.iterator(chunk_size=10_000), unit)
    actual = {
        bar["bucket"]: bar
        for bar in MODELS[unit]
        .objects.filter(asset=asset, bucket__gte=start, bucket__lt=end)
        .values("bucket", *EXACT_FIELDS, "volatility")
    }

    diffs = []
    for bucket in sorted(expected.keys() | actual.keys()):
        exp, act = expected.get(bucket), actual.get(bucket)
        if exp is None or act is None:
            diffs.append({"bucket": bucket, "field": "row", "expected": exp, "actual": act})
            continue
        for field in EXACT_FIELDS:
            if exp[field] != act[field]:
                diffs.append(
                    {"bucket": bucket, "field": field, "expected": exp[field], "actual": act[field]}
                )
        if not _same_volatility(exp["volatility"], act["volatility"]):
            diffs.append(
                {
                    "bucket": bucket,
                    "field": "volatility",
                    "expected": exp["volatility"],
                    "actual": act["volatility"],
                }
            )
    return diffs


def _same_volatility(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=VOLATILITY_REL_TOL, abs_tol=1e-15)
