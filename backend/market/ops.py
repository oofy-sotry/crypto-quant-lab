"""운영 콘솔: 종목×날짜 상태 매트릭스와 하루 상세.

칸 하나 = (종목, UTC 날짜). 쿼리는 표 크기와 상관없이 고정 개수(테이블마다 GROUP BY 한 번)로 센다.
"""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate

from market.integrity import find_gaps_in_db
from market.models import (
    Asset,
    DailyAgg,
    DailyCandle,
    HourlyBar,
    IntegrityIssue,
    MinuteCandle,
    ReprocessRun,
)

# 칸 상태. 위에 있을수록 먼저 보여 준다(한 칸에 여러 문제가 있으면 가장 심한 것).
ERROR = "error"  # 미해결 error 이슈
NO_MINUTES = "no_minutes"  # 분봉이 하나도 없음(수집 안 됨)
NOT_AGGREGATED = "not_aggregated"  # 일 집계가 없거나, 집계한 분봉 수가 지금 분봉 수와 다름
WARNING = "warning"  # 미해결 warning 이슈
OK = "ok"

# 하루 상세에서 보여 줄 빈 구간 최소 길이. 경고 기준(30분)보다 짧은 것도 보여 원인 파악을 돕는다.
DETAIL_MIN_GAP = timedelta(minutes=10)


def utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """UTC 날짜 start~end(포함) → [start 0시, end 다음 날 0시)."""
    return (
        datetime.combine(start, time(), tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), time(), tzinfo=UTC),
    )


def cell_status(minutes: int, agg_minutes: int | None, errors: int, warnings: int) -> str:
    if errors:
        return ERROR
    if not minutes:
        return NO_MINUTES
    if agg_minutes != minutes:
        return NOT_AGGREGATED
    if warnings:
        return WARNING
    return OK


def day_matrix(start: date, end: date) -> dict:
    """활성 종목 × start~end(UTC, 포함) 날짜의 상태 표."""
    assets = list(Asset.objects.filter(is_active=True).order_by("symbol"))
    lo, hi = utc_bounds(start, end)

    # COUNT(*): COUNT(id)는 id가 인덱스에 없어 힙을 읽는다(Bitmap Heap Scan, 버퍼 4,046).
    # COUNT(*)면 unique(asset_id, ts)만 읽는 Index Only Scan(버퍼 1,437, 116 → 90ms, 30일 21만 행).
    minutes = {
        (r["asset_id"], r["day"]): r["n"]
        for r in MinuteCandle.objects.filter(ts__gte=lo, ts__lt=hi)
        .annotate(day=TruncDate("ts", tzinfo=UTC))
        .values("asset_id", "day")
        .annotate(n=Count("*"))
    }
    agg_minutes = {
        (asset_id, bucket.astimezone(UTC).date()): count
        for asset_id, bucket, count in DailyAgg.objects.filter(
            bucket__gte=lo, bucket__lt=hi
        ).values_list("asset_id", "bucket", "minute_count")
    }
    final_candles = set(
        DailyCandle.objects.filter(date__range=(start, end), is_final=True).values_list(
            "asset_id", "date"
        )
    )
    issues: dict[tuple, Counter] = defaultdict(Counter)
    for r in (
        IntegrityIssue.objects.filter(date__range=(start, end), resolved_at__isnull=True)
        .values("asset_id", "date", "severity")
        .annotate(n=Count("id"))
        .order_by()
    ):
        issues[(r["asset_id"], r["date"])][r["severity"]] += r["n"]
    reprocess: Counter = Counter()
    for asset_id, run_start, run_end in ReprocessRun.objects.filter(
        start_date__lte=end, end_date__gte=start
    ).values_list("asset_id", "start_date", "end_date"):
        day = max(run_start, start)
        while day <= min(run_end, end):
            reprocess[(asset_id, day)] += 1
            day += timedelta(days=1)

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    rows = []
    for asset in assets:
        cells = []
        for day in days:
            key = (asset.id, day)
            n = minutes.get(key, 0)
            errors = issues[key][IntegrityIssue.Severity.ERROR]
            warnings = issues[key][IntegrityIssue.Severity.WARNING]
            cells.append(
                {
                    "date": day,
                    "status": cell_status(n, agg_minutes.get(key), errors, warnings),
                    "minute_count": n,
                    "aggregated_minutes": agg_minutes.get(key),
                    "daily_final": key in final_candles,
                    "open_errors": errors,
                    "open_warnings": warnings,
                    "reprocess_runs": reprocess[key],
                }
            )
        rows.append({"symbol": asset.symbol, "cells": cells})
    return {"start": start, "end": end, "rows": rows}


def day_detail(asset: Asset, day: date) -> dict:
    """한 종목·하루의 상세: 분봉 수와 빈 구간, 시간대별 집계, 일봉 대조, 이슈, 재처리 이력."""
    lo, hi = utc_bounds(day, day)
    minute_rows = MinuteCandle.objects.filter(asset=asset, ts__gte=lo, ts__lt=hi)
    hourly = dict(
        HourlyBar.objects.filter(asset=asset, bucket__gte=lo, bucket__lt=hi).values_list(
            "bucket", "minute_count"
        )
    )
    hours = [lo + timedelta(hours=h) for h in range(24)]
    agg = DailyAgg.objects.filter(asset=asset, bucket=lo).first()
    candle = DailyCandle.objects.filter(asset=asset, date=day).first()
    price_fields = ["open", "high", "low", "close", "volume", "value"]
    return {
        "symbol": asset.symbol,
        "date": day,
        "minute_count": minute_rows.count(),
        "gaps": [
            {"start": s, "end": e, "minutes": int((e - s) / timedelta(minutes=1))}
            for s, e in find_gaps_in_db(asset, lo, hi, DETAIL_MIN_GAP)
        ],
        "hourly": [{"hour": h, "minute_count": hourly.get(h, 0)} for h in hours],
        "daily_agg": (
            {f: getattr(agg, f) for f in [*price_fields, "minute_count"]} if agg else None
        ),
        "daily_candle": (
            {f: getattr(candle, f) for f in [*price_fields, "is_final"]} if candle else None
        ),
        "issues": list(asset.issues.filter(date=day).select_related("asset")),
        "reprocess_runs": list(
            asset.reprocess_runs.filter(start_date__lte=day, end_date__gte=day).select_related(
                "asset"
            )
        ),
    }
