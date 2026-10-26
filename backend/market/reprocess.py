"""재처리: 기간을 정해 원본을 다시 받거나 다시 계산한다.

바뀐 것만 반영한 뒤 정합성 검사를 다시 돌리고, 결과를 ReprocessRun에 남긴다.
"""

import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from market.aggregates import MODELS, delete_orphan_aggregates, upsert_aggregates
from market.integrity import run_integrity_checks, run_minute_checks
from market.minutes import upsert_minute_candles
from market.models import DailyAgg, DailyCandle, MinuteCandle, ReprocessRun
from market.services import upsert_candles
from market.upbit import UpbitClient, current_trading_day

logger = logging.getLogger(__name__)

VALUE_FIELDS = ["open", "high", "low", "close", "volume", "value"]
DELETE_CHUNK = 5000  # IN 목록 하나에 넣는 키 수 (쿼리 파라미터 상한 65,535보다 충분히 작게)


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


@dataclass
class Result:
    """대상 하나를 재처리한 결과. rows_*·changed는 대상의 주 테이블 기준."""

    rows_before: int
    rows_after: int
    changed: int
    diff: dict


def utc_range(start: date, end: date) -> tuple[datetime, datetime]:
    """UTC 날짜 start~end(포함) → [start 0시, end 다음 날 0시)."""
    return (
        datetime.combine(start, time(), tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), time(), tzinfo=UTC),
    )


def summarize(changes: dict[str, Iterable], day_of: Callable) -> dict:
    """{"inserted": 키들, "updated": ..., "deleted": ...} → 개수와 날짜별 개수."""
    summary: dict = {}
    dates: dict[str, Counter] = defaultdict(Counter)
    for kind, keys in changes.items():
        keys = list(keys)
        summary[kind] = len(keys)
        for key in keys:
            dates[day_of(key).isoformat()][kind] += 1
    summary["dates"] = {day: dict(counts) for day, counts in sorted(dates.items())}
    return summary


def bucket_day(bucket: datetime) -> date:
    return bucket.astimezone(UTC).date()


def reprocess_aggregates(asset, start: date, end: date, client=None) -> Result:
    """기간의 시간봉·일봉 집계를 지금 있는 분봉으로 다시 만들고, 분봉 검사를 다시 돌린다.

    바뀐 구간만 갱신하고, 분봉이 사라진 구간의 집계는 지운다 → 기간 안 집계가 "지금 분봉으로
    만든 결과"로 교체된다. client는 다른 대상과 호출 형태를 맞추려고 받기만 한다(업비트 호출 없음).
    """
    range_start, range_end = utc_range(start, end)

    def count_daily():
        return DailyAgg.objects.filter(
            asset=asset, bucket__gte=range_start, bucket__lt=range_end
        ).count()

    before = count_daily()
    diff = {}
    for unit, model in MODELS.items():
        upserted = upsert_aggregates(asset, unit, range_start, range_end)
        deleted = delete_orphan_aggregates(asset, unit, range_start, range_end)
        diff[model._meta.model_name] = summarize(
            {
                "inserted": [b for b, inserted in upserted if inserted],
                "updated": [b for b, inserted in upserted if not inserted],
                "deleted": deleted,
            },
            bucket_day,
        )
    diff["checks"] = run_minute_checks(start, end, targets=[asset]).get(asset.symbol, {})
    daily = diff["dailyagg"]
    changed = daily["inserted"] + daily["updated"] + daily["deleted"]
    return Result(before, count_daily(), changed, diff)


# 원본에 없어서 지울 행이 기간 안 기존 행의 이 비율을 넘으면 원본 응답이 덜 온 것으로 보고 멈춘다.
# 업비트가 과거 봉을 대량으로 없애는 일은 사실상 없고,
# 빈 응답·잘린 페이지를 그대로 믿으면 기간 전체가 삭제된다.
MAX_DELETE_RATIO = 0.1


class SourceLooksIncomplete(Exception):
    """원본 응답이 비었거나 너무 많은 행을 지우게 돼서 반영을 거부함(트랜잭션 전체 롤백)."""


def guard_deletions(existing: dict, fresh: dict, deleted: list) -> None:
    if existing and not fresh:
        raise SourceLooksIncomplete(f"원본이 비어 있습니다(기존 {len(existing):,}행).")
    if existing and len(deleted) / len(existing) > MAX_DELETE_RATIO:
        raise SourceLooksIncomplete(
            f"기존 {len(existing):,}행 중 {len(deleted):,}행을 지우게 됩니다"
            f"({MAX_DELETE_RATIO:.0%} 초과). 원본 응답을 확인하세요."
        )


def compare(existing: dict, fresh: dict) -> dict[str, list]:
    """키 → 값 튜플 두 벌을 비교해 추가·변경·삭제할 키를 돌려준다.

    Decimal은 자릿수 표기가 달라도(100 vs 100.00000000) 같은 값이면 같다고 본다.
    """
    return {
        "inserted": sorted(fresh.keys() - existing.keys()),
        "updated": sorted(k for k in fresh.keys() & existing.keys() if fresh[k] != existing[k]),
        "deleted": sorted(existing.keys() - fresh.keys()),
    }


def reprocess_minutes(asset, start: date, end: date, client=None) -> Result:
    """기간의 분봉을 업비트에서 다시 받아 DB와 비교하고, 다른 것만 추가·변경·삭제한 뒤 재집계한다.

    업비트에 없는데 DB에 있는 분봉은 지운다(원본 기준으로 교체). 그래서 dry-run으로 먼저 확인한다.
    """
    client = client or UpbitClient()
    range_start, range_end = utc_range(start, end)
    in_range = MinuteCandle.objects.filter(asset=asset, ts__gte=range_start, ts__lt=range_end)

    fresh_bars = {
        bar.ts: bar
        for bar in client.iter_minute_candles(asset.symbol, since=range_start, to=range_end)
    }
    fresh = {ts: tuple(getattr(bar, f) for f in VALUE_FIELDS) for ts, bar in fresh_bars.items()}
    existing = {row[0]: row[1:] for row in in_range.values_list("ts", *VALUE_FIELDS)}
    changes = compare(existing, fresh)
    guard_deletions(existing, fresh, changes["deleted"])

    upsert_minute_candles(
        asset, [fresh_bars[ts] for ts in changes["inserted"] + changes["updated"]]
    )
    for i in range(0, len(changes["deleted"]), DELETE_CHUNK):
        in_range.filter(ts__in=changes["deleted"][i : i + DELETE_CHUNK]).delete()

    aggregates = reprocess_aggregates(asset, start, end)
    diff = {"minutecandle": summarize(changes, bucket_day), **aggregates.diff}
    changed = sum(len(keys) for keys in changes.values())
    return Result(len(existing), in_range.count(), changed, diff)


def reprocess_daily(asset, start: date, end: date, client=None) -> Result:
    """기간의 일봉을 업비트에서 다시 받아 다른 것만 반영하고, 일봉 무결성 검사를 다시 돌린다.

    값이 같은 일봉은 건드리지 않아 collected_at이 그대로다. 백테스트 캐시 키의 데이터 버전이
    Max(collected_at) + 행 수이므로, 실제로 바뀐(추가·변경·삭제) 일봉이 있을 때만 캐시가 무효화된다.
    """
    client = client or UpbitClient()
    today = current_trading_day()
    in_range = DailyCandle.objects.filter(asset=asset, date__range=(start, end))

    fresh_candles = {
        c.date: c for c in client.iter_daily_candles(asset.symbol, since=start) if c.date <= end
    }
    fresh = {
        day: (*(getattr(c, f) for f in VALUE_FIELDS), day < today)
        for day, c in fresh_candles.items()
    }
    existing = {row[0]: row[1:] for row in in_range.values_list("date", *VALUE_FIELDS, "is_final")}
    changes = compare(existing, fresh)
    guard_deletions(existing, fresh, changes["deleted"])

    upsert_candles(
        asset, [fresh_candles[d] for d in changes["inserted"] + changes["updated"]], today=today
    )
    in_range.filter(date__in=changes["deleted"]).delete()

    diff = {
        "dailycandle": summarize(changes, lambda day: day),
        "checks": run_integrity_checks(asset, today=today),
    }
    changed = sum(len(keys) for keys in changes.values())
    return Result(len(existing), in_range.count(), changed, diff)


def retention_error(target: str, start: date, today: date) -> str | None:
    """분봉 보관 기간(MINUTE_RETENTION_DAYS) 밖 날의 분봉·집계 재처리를 막는 오류 문구(없으면 None).

    그 날은 분봉이 이미 지워져 있다. 집계 재처리는 "분봉이 없는 구간"으로 보고 남아 있던 집계 봉을
    지우고, 분봉 재처리는 다시 받은 분봉이 다음 Cron에 또 지워진다. 일봉 재처리는 상관없다.
    """
    keep = settings.MINUTE_RETENTION_DAYS
    if keep <= 0 or target == ReprocessRun.Target.DAILY:
        return None
    oldest = today - timedelta(days=keep)  # 분봉 Cron이 이 날 0시(UTC) 전 분봉을 지운다
    if start < oldest:
        return f"{target} 재처리는 분봉 보관 기간({keep}일) 안, {oldest}부터만 가능합니다."
    return None


TARGETS = {
    ReprocessRun.Target.MINUTES: reprocess_minutes,
    ReprocessRun.Target.AGGREGATES: reprocess_aggregates,
    ReprocessRun.Target.DAILY: reprocess_daily,
}


class Rejected(Exception):
    """같은 종목·기간(하루라도 겹침)의 재처리가 이미 실행 중."""


def run_reprocess(
    asset,
    target: str,
    start: date,
    end: date,
    *,
    dry_run: bool,
    reason: str,
    requested_by: str,
    client=None,
) -> ReprocessRun:
    """재처리를 실행하고 이력(ReprocessRun)을 남긴다.

    - 이력 행은 트랜잭션 밖에서 만들고 갱신한다. 안에서 만들면 롤백 때 이력도 사라진다.
    - 트랜잭션 하나 안에서: 락 → 원본 비교·반영 → 재집계 → 재검증. 중간에 실패하면 전부 롤백.
    - dry-run은 똑같이 다 실행한 뒤 마지막에 롤백한다. 실제 실행과 같은 코드로 계산하므로
      "미리 본 차이"와 "실제로 바뀔 차이"가 어긋나지 않는다.
    """
    run = ReprocessRun.objects.create(
        asset=asset,
        target=target,
        start_date=start,
        end_date=end,
        dry_run=dry_run,
        reason=reason,
        requested_by=requested_by,
    )
    try:
        with transaction.atomic():
            if not lock_days(asset, start, end):
                raise Rejected
            result = TARGETS[target](asset, start, end, client=client)
            if dry_run:
                transaction.set_rollback(True)
    except Rejected:
        run.status = ReprocessRun.Status.REJECTED
    except Exception as exc:
        logger.exception("재처리 실패: %s", run)
        run.status = ReprocessRun.Status.FAILED
        run.error_message = f"{exc.__class__.__name__}: {exc}"
    else:
        run.status = ReprocessRun.Status.SUCCESS
        run.rows_before = result.rows_before
        run.rows_after = result.rows_after
        run.changed_rows = result.changed
        run.diff = result.diff
    run.finished_at = timezone.now()
    run.save()
    return run
