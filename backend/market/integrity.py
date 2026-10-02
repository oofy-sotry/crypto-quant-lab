"""일봉 데이터 무결성 검사.

각 검사는 DB를 모르는 순수 함수로 두고(입력: 일봉 목록 → 출력: 발견 목록),
DB 저장은 run_integrity_checks가 맡는다. 그래서 검사 규칙을 DB 없이 테스트할 수 있다.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
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


def run_integrity_checks(asset, today: date, run=None) -> dict:
    """한 종목의 확정 일봉 전체를 검사하고 결과를 IntegrityIssue에 반영한다.

    - 새로 발견: 생성
    - 이미 있음: 내용 갱신, 자동 해결됐던 이슈면 다시 연다(사람이 note를 남긴 건 유지)
    - 이번엔 발견 안 됨: 자동 해결 처리
    같은 데이터로 여러 번 돌려도 결과가 같다(멱등).
    """
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

    existing = {(i.date, i.type): i for i in asset.issues.all()}
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
