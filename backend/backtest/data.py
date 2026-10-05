"""백테스트 입력 데이터 준비: DB의 확정 일봉 → pandas 종가 Series."""

from datetime import date, timedelta

import pandas as pd

from market.models import Asset, IntegrityIssue


class DataNotReady(Exception):
    """요청 기간의 데이터가 백테스트에 쓰기에 부족하거나 오류가 있을 때."""


def load_close(asset: Asset, start: date, end: date, warmup_days: int = 0) -> pd.Series:
    """start - warmup_days - 1 ~ end 의 확정 종가를 float Series로 돌려준다.

    -1일은 시작일 수익률(전날 종가 대비)을 계산하기 위한 하루다.
    무결성 error가 해결되지 않았거나 데이터가 모자라면 DataNotReady.
    """
    first_needed = start - timedelta(days=warmup_days + 1)

    # 수집 지연(stale)은 빼고 본다. "새 데이터가 안 들어온다"는 뜻이지 있는 데이터가 틀린 게 아니고,
    # end가 마지막 확정 봉보다 늦으면 아래에서 따로 거부한다.
    open_errors = (
        IntegrityIssue.objects.filter(
            asset=asset,
            severity=IntegrityIssue.Severity.ERROR,
            resolved_at__isnull=True,
            date__range=(first_needed, end),
        )
        .exclude(type=IntegrityIssue.Type.STALE)
        .order_by("date")
    )
    if open_errors.exists():
        dates = ", ".join(str(d) for d in open_errors.values_list("date", flat=True)[:5])
        raise DataNotReady(f"기간 안에 해결되지 않은 데이터 오류가 있습니다: {dates}")

    rows = list(
        asset.candles.filter(is_final=True, date__range=(first_needed, end))
        .order_by("date")
        .values_list("date", "close")
    )
    if not rows:
        raise DataNotReady(f"{first_needed} ~ {end} 기간에 확정된 일봉이 없습니다.")
    if rows[0][0] > first_needed:
        raise DataNotReady(
            f"데이터가 {rows[0][0]}부터 있는데, 이동평균 워밍업을 포함하면 {first_needed}부터"
            " 필요합니다. 시작일을 늦춰 주세요."
        )
    if rows[-1][0] < end:
        raise DataNotReady(f"{end}까지 확정된 일봉이 없습니다(마지막: {rows[-1][0]}).")

    index = pd.DatetimeIndex([d for d, _ in rows])
    # 저장은 Decimal(정확도), 계산은 float(속도). 수익률 계산에는 float 정밀도로 충분하다.
    return pd.Series([float(c) for _, c in rows], index=index, name="close")
