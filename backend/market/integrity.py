"""일봉·분봉 데이터 무결성 검사.

각 검사는 DB를 모르는 순수 함수로 두고(입력: 일봉 목록 → 출력: 발견 목록),
DB 저장은 run_integrity_checks가 맡는다. 그래서 검사 규칙을 DB 없이 테스트할 수 있다.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from market.models import IntegrityIssue

Type = IntegrityIssue.Type
Severity = IntegrityIssue.Severity


@dataclass(frozen=True)
class Finding:
    date: date
    type: str
    severity: str
    detail: dict = field(default_factory=dict)


def find_missing_dates(dates: Iterable[date], start: date, end: date) -> list[Finding]:
    """start~end(둘 다 포함) 중 일봉이 없는 날짜를 찾는다.

    코인은 365일 24시간 거래되므로 하루라도 빠지면 오류다.
    start는 상장일, end는 어제(오늘 봉은 아직 마감 전)로 넘긴다.
    """
    have = set(dates)
    findings = []
    day = start
    while day <= end:
        if day not in have:
            findings.append(Finding(day, Type.MISSING, Severity.ERROR))
        day += timedelta(days=1)
    return findings


def check_candle_values(candles: Iterable) -> list[Finding]:
    """일봉 한 개 안에서 지켜져야 할 규칙을 검사한다.

    candles의 각 항목은 date, open, high, low, close, volume 속성을 가지면 된다
    (DailyCandle 모델과 upbit.Candle 둘 다 해당).
    """
    findings = []
    for c in candles:
        prices = {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
        detail = {k: str(v) for k, v in prices.items()}  # JSON 저장용으로 문자열화
        if any(p <= 0 for p in prices.values()):
            findings.append(Finding(c.date, Type.NON_POSITIVE, Severity.ERROR, detail))
        # 저가는 시가·종가보다 높을 수 없고, 고가는 시가·종가보다 낮을 수 없다.
        if not (c.low <= min(c.open, c.close) and max(c.open, c.close) <= c.high):
            findings.append(Finding(c.date, Type.OHLC_INVALID, Severity.ERROR, detail))
        if c.volume == 0:
            # 거래가 실제로 없었을 수도 있어서 경고로만 남긴다.
            findings.append(Finding(c.date, Type.ZERO_VOLUME, Severity.WARNING))
    return findings


SPIKE_THRESHOLD = Decimal("0.3")  # 전일 종가 대비 ±30%


def find_spikes(candles: Iterable, threshold: Decimal = SPIKE_THRESHOLD) -> list[Finding]:
    """전일 종가 대비 등락률이 threshold를 넘는 날을 찾는다.

    candles는 날짜 오름차순이어야 한다. 실제로 일어날 수 있는 일이라 경고로 남긴다.
    """
    findings = []
    prev = None
    for c in candles:
        if prev is not None and prev.close > 0:
            change = c.close / prev.close - 1
            if abs(change) > threshold:
                detail = {"prev_date": prev.date.isoformat(), "change": f"{change:.4f}"}
                findings.append(Finding(c.date, Type.SPIKE, Severity.WARNING, detail))
        prev = c
    return findings


def find_stale(latest_final: date | None, today: date, max_lag_days: int = 2) -> list[Finding]:
    """마지막 확정 일봉이 너무 오래됐으면 수집이 멈춘 것으로 본다.

    정상이라면 마지막 확정 봉은 어제(today - 1)다. 그보다 max_lag_days 이상 밀리면 오류.
    """
    if latest_final is None:
        return []
    lag = (today - latest_final).days
    if lag < max_lag_days:
        return []
    return [Finding(latest_final, Type.STALE, Severity.ERROR, {"lag_days": lag})]


PRICE_FIELDS = ["open", "high", "low", "close"]
AMOUNT_FIELDS = ["volume", "value"]
# 업비트 일봉은 1분봉을 그대로 합친 값이라 1년치 대조에서 가격은 정확히 같고 거래대금만 상대 1e-16
# 수준(소수 8자리 반올림 누적) 차이가 났다. 그보다 훨씬 크지만 실제 누락 1분보다는 작은 값으로 둔다.
AMOUNT_REL_TOL = Decimal("0.000001")


def find_minute_mismatches(
    aggs: Iterable, candles: Iterable, rel_tol: Decimal = AMOUNT_REL_TOL
) -> list[Finding]:
    """분봉으로 만든 일봉(DailyAgg)과 업비트 일봉(DailyCandle)을 날짜별로 대조한다.

    가격이 하나라도 다르면 error(두 원본 중 하나가 틀렸다), 거래량·거래대금만 rel_tol을 넘게
    다르면 warning. 한쪽에만 있는 날은 건너뛴다(일봉 결측은 find_missing_dates, 분봉 빈 날은
    find_minute_gaps가 잡는다).
    """
    by_date = {c.date: c for c in candles}
    findings = []
    for agg in aggs:
        day = agg.bucket.astimezone(UTC).date()
        candle = by_date.get(day)
        if candle is None:
            continue
        diffs = {}
        for f in PRICE_FIELDS:
            if getattr(agg, f) != getattr(candle, f):
                diffs[f] = (getattr(agg, f), getattr(candle, f))
        price_differs = bool(diffs)
        for f in AMOUNT_FIELDS:
            minute, daily = getattr(agg, f), getattr(candle, f)
            if abs(minute - daily) > abs(daily) * rel_tol:
                diffs[f] = (minute, daily)
        if not diffs:
            continue
        severity = Severity.ERROR if price_differs else Severity.WARNING
        detail = {f: {"minute": str(m), "daily": str(c)} for f, (m, c) in diffs.items()}
        findings.append(Finding(day, Type.MINUTE_MISMATCH, severity, detail))
    return findings


Gap = tuple[datetime, datetime]  # [시작, 끝) 동안 분봉이 하나도 없음
# 1년치에서 점검일이 아닌 날의 최장 빈 구간은 DOGE 15분, 나머지는 8분 이하였고
# 30분 이상은 거래소 점검(전 종목 동시)뿐이었다.
MIN_GAP = timedelta(minutes=30)


def find_minute_gaps(
    gaps: Iterable[Gap], peer_gaps: list[list[Gap]], min_gap: timedelta = MIN_GAP
) -> list[Finding]:
    """한 종목의 빈 구간 중 min_gap 이상인 것을 그 구간이 걸친 UTC 날짜마다 warning으로 남긴다.

    거래가 없는 분은 업비트가 분봉을 주지 않아서 짧은 빈 구간은 정상이다. 긴 빈 구간은 거래소
    점검이거나 수집 누락이다. peer_gaps(다른 종목들의 빈 구간)가 모두 이 구간과 겹치면
    전 종목이 같이 빈 것이라 detail에 all_assets=True로 표시한다(거래소 점검 추정).
    한 날에 긴 빈 구간이 여럿이면 가장 긴 것을 남기고 개수를 함께 적는다.
    """
    by_day: dict[date, list[Gap]] = {}
    for start, end in gaps:
        if end - start < min_gap:
            continue
        day = start.astimezone(UTC).date()
        last_day = (end - timedelta(microseconds=1)).astimezone(UTC).date()
        while day <= last_day:  # 자정을 넘는 빈 구간은 양쪽 날 모두에 남긴다
            by_day.setdefault(day, []).append((start, end))
            day += timedelta(days=1)

    findings = []
    for day, day_gaps in sorted(by_day.items()):
        start, end = max(day_gaps, key=lambda g: g[1] - g[0])
        shared = bool(peer_gaps) and all(
            any(p_start < end and start < p_end for p_start, p_end in peer) for peer in peer_gaps
        )
        detail = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "minutes": int((end - start) / timedelta(minutes=1)),
            "count": len(day_gaps),
            "all_assets": shared,
        }
        findings.append(Finding(day, Type.MINUTE_GAP, Severity.WARNING, detail))
    return findings


DAILY_TYPES = [
    Type.MISSING,
    Type.OHLC_INVALID,
    Type.NON_POSITIVE,
    Type.ZERO_VOLUME,
    Type.SPIKE,
    Type.STALE,
]


def run_integrity_checks(asset, today: date, run=None) -> dict:
    """한 종목의 확정 일봉 전체를 검사하고 결과를 IntegrityIssue에 반영한다."""
    candles = list(asset.candles.filter(is_final=True).order_by("date"))
    if not candles:
        return {"created": 0, "reopened": 0, "resolved": 0}

    start = asset.listed_on or candles[0].date
    findings = [
        *find_missing_dates((c.date for c in candles), start=start, end=today - timedelta(days=1)),
        *check_candle_values(candles),
        *find_spikes(candles),
        *find_stale(candles[-1].date, today),
    ]
    return sync_issues(asset, findings, DAILY_TYPES, run=run)


def sync_issues(
    asset,
    findings: list[Finding],
    types: list[str],
    run=None,
    dates: tuple[date, date] | None = None,
) -> dict:
    """검사 결과를 IntegrityIssue에 반영한다.

    - 새로 발견: 생성
    - 이미 있음: 내용 갱신, 자동 해결됐던 이슈면 다시 연다(사람이 note를 남긴 건 유지)
    - 이번엔 발견 안 됨: 자동 해결 처리
    types(와 dates를 주면 그 기간)에 속한 기존 이슈만 대상으로 한다. 다른 검사가 만든 이슈나
    이번에 검사하지 않은 기간의 이슈를 "이번엔 발견 안 됨"으로 잘못 해결하지 않기 위해서다.
    같은 데이터로 여러 번 돌려도 결과가 같다(멱등).
    """
    issues = asset.issues.filter(type__in=types)
    if dates is not None:
        issues = issues.filter(date__range=dates)
    existing = {(i.date, i.type): i for i in issues}
    found_keys = set()
    summary = {"created": 0, "reopened": 0, "resolved": 0}
    now = timezone.now()

    for f in findings:
        key = (f.date, f.type)
        found_keys.add(key)
        issue = existing.get(key)
        if issue is None:
            IntegrityIssue.objects.create(
                asset=asset,
                date=f.date,
                type=f.type,
                severity=f.severity,
                detail=f.detail,
                detected_run=run,
            )
            summary["created"] += 1
            continue
        issue.severity, issue.detail = f.severity, f.detail
        if issue.resolved_at is not None and not issue.note:
            issue.resolved_at = None
            issue.detected_run = run
            summary["reopened"] += 1
        issue.save()

    for key, issue in existing.items():
        if key not in found_keys and issue.resolved_at is None:
            issue.resolved_at = now
            issue.save(update_fields=["resolved_at"])
            summary["resolved"] += 1

    return summary
