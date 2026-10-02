"""업비트 공개 시세 API 클라이언트 (API 키 불필요).

문서: https://docs.upbit.com/kr/reference/list-candles-days
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upbit.com/v1"
MAX_COUNT = 200  # 업비트가 한 번에 돌려주는 최대 캔들 수
# 재시도할 응답 코드: 요청 수 제한(429)과 일시적인 서버 오류(5xx)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Candle:
    date: date  # KST 거래일
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    value: Decimal


def current_trading_day(now: datetime | None = None) -> date:
    """지금 진행 중인(아직 마감 안 된) 업비트 일봉의 날짜.

    업비트 일봉은 UTC 00:00(= KST 09:00)에 바뀐다. KST 달력 날짜를 쓰면
    KST 00:00~09:00 사이에는 아직 진행 중인 전날 봉을 마감된 것으로 착각한다.
    """
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).date()


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
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 10,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        min_interval: float = 0.15,
        # 테스트에서 실제로 기다리지 않도록 시계와 sleep을 주입할 수 있게 둔다
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.min_interval = min_interval
        self.sleep = sleep
        self.clock = clock
        self._last_request_at: float | None = None

    def _throttle(self):
        """직전 요청과 min_interval 이상 간격을 둔다 (업비트 시세 API는 초당 10회 제한)."""
        if self._last_request_at is not None:
            wait = self.min_interval - (self.clock() - self._last_request_at)
            if wait > 0:
                self.sleep(wait)
        self._last_request_at = self.clock()

    def _get(self, path: str, params: dict) -> requests.Response:
        """GET 요청. 429·5xx·네트워크 오류는 지수 백오프(0.5→1→2→4초…)로 재시도한다."""
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self.session.get(
                    f"{BASE_URL}{path}", params=params, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.max_retries:
                    raise
                logger.warning(
                    "업비트 요청 실패(%s), 재시도 %d", exc.__class__.__name__, attempt + 1
                )
            else:
                if response.status_code not in RETRYABLE_STATUS or attempt == self.max_retries:
                    response.raise_for_status()
                    return response
                logger.warning("업비트 응답 %d, 재시도 %d", response.status_code, attempt + 1)
            self.sleep(self.backoff_base * 2**attempt)
        raise AssertionError("unreachable")

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

        response = self._get("/candles/days", params)
        # float로 읽으면 오차가 생길 수 있어 처음부터 Decimal로 파싱한다.
        rows = json.loads(response.text, parse_float=Decimal)
        return [parse_candle(row) for row in rows]

    def iter_daily_candles(self, market: str, since: date | None = None):
        """최신 일봉부터 과거로 거슬러 올라가며 하나씩 돌려준다.

        200개씩 페이지를 넘기고, 응답이 200개보다 적으면(상장일에 도달) 멈춘다.
        since를 주면 그 날짜까지만 가져온다(since 포함).
        """
        to = None
        while True:
            page = self.fetch_daily_candles(market, MAX_COUNT, to)
            for candle in page:
                if since is not None and candle.date < since:
                    return
                yield candle
            if len(page) < MAX_COUNT:
                return
            to = page[-1].date  # 가장 오래된 날짜 이전부터 다음 페이지 (to는 해당 날짜 제외)
