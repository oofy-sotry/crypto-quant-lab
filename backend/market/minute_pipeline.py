"""매일 분봉 파이프라인: 수집 → 시간봉·일봉 집계 → 분봉 정합성 검사 → 보관 기간 지난 분봉 삭제.

Vercel Cron(`/api/cron/minutes/`)이 하루 한 번 부른다.
결과·단계별 소요 시간은 CollectionRun(kind=minutes)에 남는다.
"""

import logging
import time
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone

from market.aggregates import MODELS, aggregate_minutes, delete_orphan_aggregates
from market.integrity import run_minute_checks
from market.minutes import collect_minutes
from market.models import Asset, CollectionRun, MinuteCandle
from market.upbit import UpbitClient

logger = logging.getLogger(__name__)

# 끝난 UTC 날 중 최근 며칠을 다시 받고 집계할지. 2일이면 전날 Cron이 놓친 날(실패, 업비트 늦은 정정,
# 일봉 Cron보다 먼저 돌아 대조를 건너뛴 날)도 다음 날 메워진다.
RECENT_DAYS = 2


def utc_midnight(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def delete_expired_minutes(now: datetime, keep_days: int) -> int:
    """keep_days일보다 오래된 분봉을 지운다(집계 봉은 남긴다). keep_days가 0이면 지우지 않는다."""
    if keep_days <= 0:
        return 0
    cutoff = utc_midnight(now) - timedelta(days=keep_days)
    # 종목 조건이 없어도 PG18 skip scan이 unique(asset_id, ts) 인덱스를 쓴다(performance.md 3.1).
    deleted, _ = MinuteCandle.objects.filter(ts__lt=cutoff).delete()
    return deleted


def run_minute_pipeline(
    trigger: str,
    days: int = RECENT_DAYS,
    keep_days: int | None = None,
    client: UpbitClient | None = None,
    now: datetime | None = None,
) -> CollectionRun:
    """끝난 UTC 날 최근 days일의 분봉을 처리하고 결과를 CollectionRun(kind=minutes)에 남긴다.

    한 종목이 실패해도 나머지는 계속하고 partial로 기록한다(일봉 수집과 같은 규칙).
    검사는 빈 구간을 전 종목과 비교해야 해서 수집이 끝난 뒤 한 번에 한다.
    """
    client = client or UpbitClient()
    keep_days = settings.MINUTE_RETENTION_DAYS if keep_days is None else keep_days
    now = now or timezone.now()
    end = utc_midnight(now)  # 오늘 0시(UTC) 전까지 = 끝난 날만
    start = end - timedelta(days=days)
    assets = list(Asset.objects.filter(is_active=True))
    run = CollectionRun.objects.create(
        kind=CollectionRun.Kind.MINUTES, trigger=trigger, assets_count=len(assets)
    )
    timings: dict[str, float] = {}
    errors = []

    def step(name: str, started: float):
        timings[name] = round(time.monotonic() - started, 2)

    started = time.monotonic()
    for asset in assets:
        try:
            run.upserted_count += collect_minutes(asset, since=start, to=end, client=client)
            for unit in MODELS:
                aggregate_minutes(asset, unit, start, end)
                delete_orphan_aggregates(asset, unit, start, end)
        except Exception as exc:  # 한 종목 실패가 다른 종목을 멈추지 않게 한다
            logger.exception("%s 분봉 처리 실패", asset.symbol)
            errors.append(f"{asset.symbol}: {exc.__class__.__name__}: {exc}")
    step("collect_aggregate_s", started)

    checks: dict = {}
    deleted = 0
    started = time.monotonic()
    try:
        checks = run_minute_checks(start.date(), (end - timedelta(days=1)).date(), run=run)
    except Exception as exc:
        logger.exception("분봉 검사 실패")
        errors.append(f"checks: {exc.__class__.__name__}: {exc}")
    step("checks_s", started)

    started = time.monotonic()
    try:
        deleted = delete_expired_minutes(now, keep_days)
    except Exception as exc:
        logger.exception("분봉 보관 정리 실패")
        errors.append(f"retention: {exc.__class__.__name__}: {exc}")
    step("retention_s", started)

    if not errors:
        run.status = CollectionRun.Status.SUCCESS
    elif len(errors) < len(assets):
        run.status = CollectionRun.Status.PARTIAL
    else:
        run.status = CollectionRun.Status.FAILED
    run.error_message = "\n".join(errors)
    run.detail = {
        "range": [start.date().isoformat(), (end - timedelta(days=1)).date().isoformat()],
        "timings": timings,
        "deleted_minutes": deleted,
        "keep_days": keep_days,
        "checks": checks,
    }
    run.finished_at = timezone.now()
    run.save()
    return run
