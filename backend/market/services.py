from collections.abc import Iterable
from datetime import date

from django.db import connection
from django.utils import timezone

from market.models import Asset, DailyCandle
from market.upbit import Candle

UPDATE_FIELDS = ["open", "high", "low", "close", "volume", "value", "is_final", "collected_at"]


def upsert_candles(asset: Asset, candles: Iterable[Candle], today: date | None = None) -> int:
    """일봉을 저장한다. 같은 (asset, date)가 있으면 덮어쓰고 없으면 새로 넣는다.

    unique(asset, date) 제약을 이용한 upsert라서 여러 번 실행해도 행이 중복되지 않는다(멱등).
    today(KST) 이전 날짜만 마감된 봉(is_final=True)으로 표시한다.
    """
    today = today or timezone.localdate()  # settings.TIME_ZONE = Asia/Seoul
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
