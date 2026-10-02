"""업비트 공개 시세 API 클라이언트 (API 키 불필요).

문서: https://docs.upbit.com/kr/reference/list-candles-days
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import requests

BASE_URL = "https://api.upbit.com/v1"
MAX_COUNT = 200  # 업비트가 한 번에 돌려주는 최대 캔들 수


@dataclass(frozen=True)
class Candle:
    date: date  # KST 거래일
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    value: Decimal


def parse_candle(raw: dict) -> Candle:
    """업비트 일봉 응답 한 건을 Candle로 바꾼다.

    숫자 필드는 응답 JSON을 parse_float=Decimal로 읽었다고 가정한다.
    """
    return Candle(
        date=datetime.fromisoformat(raw["candle_date_time_kst"]).date(),
        open=Decimal(raw["opening_price"]),
        high=Decimal(raw["high_price"]),
        low=Decimal(raw["low_price"]),
        close=Decimal(raw["trade_price"]),
        volume=Decimal(raw["candle_acc_trade_volume"]),
        value=Decimal(raw["candle_acc_trade_price"]),
    )


class UpbitClient:
    def __init__(self, session: requests.Session | None = None, timeout: float = 10):
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch_daily_candles(
        self, market: str, count: int = MAX_COUNT, to: date | None = None
    ) -> list[Candle]:
        """일봉을 최신순으로 최대 count개 가져온다.

        to를 주면 그 날짜 '이전' 일봉만 가져온다(해당 날짜는 제외).
        업비트 일봉은 UTC 00:00(= KST 09:00)에 시작하므로 날짜의 UTC 자정을 넘긴다.
        """
        params = {"market": market, "count": count}
        if to is not None:
            params["to"] = f"{to.isoformat()}T00:00:00Z"

        response = self.session.get(f"{BASE_URL}/candles/days", params=params, timeout=self.timeout)
        response.raise_for_status()
        # float로 읽으면 오차가 생길 수 있어 처음부터 Decimal로 파싱한다.
        rows = json.loads(response.text, parse_float=Decimal)
        return [parse_candle(row) for row in rows]
