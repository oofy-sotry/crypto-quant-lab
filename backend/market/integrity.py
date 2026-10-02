"""일봉 데이터 무결성 검사.

각 검사는 DB를 모르는 순수 함수로 두고(입력: 일봉 목록 → 출력: 발견 목록),
DB 저장은 run_integrity_checks가 맡는다. 그래서 검사 규칙을 DB 없이 테스트할 수 있다.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

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
