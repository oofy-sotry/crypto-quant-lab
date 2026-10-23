"""1분봉 수집·저장. 일봉(services.py)과 달리 행 수가 수백만 건이라 배치 단위로 흘려보낸다."""

from collections.abc import Iterable

from market.models import Asset, MinuteCandle
from market.upbit import MinuteBar

UPDATE_FIELDS = ["open", "high", "low", "close", "volume", "value"]
# 한 INSERT 문에 담는 행 수. 배치 크기별 적재 속도를 재서 정한다(docs/performance.md).
BATCH_SIZE = 2000


def upsert_minute_candles(
    asset: Asset, bars: Iterable[MinuteBar], batch_size: int = BATCH_SIZE
) -> int:
    """분봉을 저장한다. 같은 (asset, ts)가 있으면 덮어쓴다(멱등).

    PostgreSQL에서는 INSERT ... ON CONFLICT (asset_id, ts) DO UPDATE 한 문장에
    batch_size행씩 들어간다.
    """
    rows = [
        MinuteCandle(
            asset=asset,
            ts=b.ts,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
            value=b.value,
        )
        for b in bars
    ]
    if not rows:
        return 0
    MinuteCandle.objects.bulk_create(
        rows,
        batch_size=batch_size,
        update_conflicts=True,
        unique_fields=["asset", "ts"],
        update_fields=UPDATE_FIELDS,
    )
    return len(rows)
