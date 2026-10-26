"""1분봉 수집·저장. 일봉(services.py)과 달리 행 수가 수백만 건이라 배치 단위로 흘려보낸다."""

from collections.abc import Callable, Iterable
from datetime import datetime

from django.utils import timezone

from market.models import Asset, MinuteCandle
from market.upbit import MinuteBar, UpbitClient

UPDATE_FIELDS = ["open", "high", "low", "close", "volume", "value"]
# 한 INSERT 문에 담는 행 수. 500/2000/5000을 재서 2000이 가장 빨랐다(docs/ROADMAP.md D2,
# bench_minute_upsert 커맨드).
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


def collect_minutes(
    asset: Asset,
    since: datetime,
    to: datetime | None = None,
    client: UpbitClient | None = None,
    batch_size: int = BATCH_SIZE,
    on_batch: Callable[[int, datetime], None] | None = None,
) -> int:
    """since 이후(포함) 분봉을 업비트에서 받아 batch_size행 모일 때마다 저장한다.

    to를 안 주면 현재 분의 시작 시각까지(진행 중인 분은 값이 바뀌므로 제외).
    배치마다 바로 저장하므로 긴 백필이 중간에 끊겨도 저장한 만큼은 남는다. 이어 받으려면 to에
    마지막으로 저장된 가장 오래된 시각을 넘기면 되고, 겹쳐 받아도 upsert라 중복이 생기지 않는다.
    on_batch(누적 저장 행 수, 그 배치의 가장 오래된 시각)로 진행 상황을 알린다.
    """
    client = client or UpbitClient()
    to = to or timezone.now().replace(second=0, microsecond=0)
    saved = 0
    buffer: list[MinuteBar] = []

    def flush():
        nonlocal saved
        saved += upsert_minute_candles(asset, buffer, batch_size=batch_size)
        if on_batch:
            on_batch(saved, buffer[-1].ts)
        buffer.clear()

    for bar in client.iter_minute_candles(asset.symbol, since=since, to=to):
        buffer.append(bar)
        if len(buffer) >= batch_size:
            flush()
    if buffer:
        flush()
    return saved
