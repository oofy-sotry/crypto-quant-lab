import logging
from collections.abc import Iterable
from datetime import date, timedelta

from django.db import connection
from django.utils import timezone

from market.integrity import run_integrity_checks
from market.models import Asset, CollectionRun, DailyCandle
from market.upbit import Candle, UpbitClient, current_trading_day

logger = logging.getLogger(__name__)

UPDATE_FIELDS = ["open", "high", "low", "close", "volume", "value", "is_final", "collected_at"]
# 정기 수집 때 다시 받는 최근 일수. 미완성 봉 확정과 업비트 쪽 정정 값을 반영하기 위함.
RECENT_DAYS = 7


def upsert_candles(asset: Asset, candles: Iterable[Candle], today: date | None = None) -> int:
    """일봉을 저장한다. 같은 (asset, date)가 있으면 덮어쓰고 없으면 새로 넣는다.

    unique(asset, date) 제약을 이용한 upsert라서 여러 번 실행해도 행이 중복되지 않는다(멱등).
    today(진행 중인 일봉 날짜) 이전 날짜만 마감된 봉(is_final=True)으로 표시한다.
    """
    today = today or current_trading_day()
    rows = [
        DailyCandle(
            asset=asset,
            date=c.date,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
            value=c.value,
            is_final=c.date < today,
        )
        for c in candles
    ]
    if not rows:
        return 0

    # MySQL의 ON DUPLICATE KEY UPDATE는 충돌 컬럼을 지정하지 않고 걸린 unique 제약을 쓴다.
    # PostgreSQL/SQLite는 ON CONFLICT (asset, date)처럼 지정해야 한다.
    unique_fields = None
    if connection.features.supports_update_conflicts_with_target:
        unique_fields = ["asset", "date"]

    DailyCandle.objects.bulk_create(
        rows,
        batch_size=500,
        update_conflicts=True,
        unique_fields=unique_fields,
        update_fields=UPDATE_FIELDS,
    )
    return len(rows)


def collect_candles(
    trigger: str, days: int | None = RECENT_DAYS, client: UpbitClient | None = None
) -> CollectionRun:
    """활성 종목의 일봉을 수집해 저장하고, 무결성 검사를 돌린 뒤 결과를 CollectionRun에 남긴다.

    days=None이면 상장일부터 전체 기간을 가져오고(백필) Asset.listed_on도 채운다.
    한 종목이 실패해도 나머지는 계속 수집하고 상태를 partial로 기록한다.
    """
    client = client or UpbitClient()
    today = current_trading_day()
    since = None if days is None else today - timedelta(days=days - 1)
    assets = list(Asset.objects.filter(is_active=True))
    run = CollectionRun.objects.create(trigger=trigger, assets_count=len(assets))

    errors = []
    for asset in assets:
        try:
            candles = list(client.iter_daily_candles(asset.symbol, since=since))
            run.upserted_count += upsert_candles(asset, candles, today=today)
            if days is None and candles:
                asset.listed_on = min(c.date for c in candles)
                asset.save(update_fields=["listed_on"])
            run_integrity_checks(asset, today=today, run=run)
        except Exception as exc:  # 한 종목 실패가 전체 수집을 멈추지 않게 한다
            logger.exception("%s 수집 실패", asset.symbol)
            errors.append(f"{asset.symbol}: {exc.__class__.__name__}: {exc}")

    if not errors:
        run.status = CollectionRun.Status.SUCCESS
    elif len(errors) < len(assets):
        run.status = CollectionRun.Status.PARTIAL
    else:
        run.status = CollectionRun.Status.FAILED
    run.error_message = "\n".join(errors)
    run.finished_at = timezone.now()
    run.save()
    return run
