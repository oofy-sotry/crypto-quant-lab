"""일봉 데이터 무결성 검사.

각 검사는 DB를 모르는 순수 함수로 두고(입력: 일봉 목록 → 출력: 발견 목록),
DB 저장은 run_integrity_checks가 맡는다. 그래서 검사 규칙을 DB 없이 테스트할 수 있다.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

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
