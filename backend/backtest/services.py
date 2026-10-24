"""백테스트 실행: 캐시 → DB → 계산 순서로 결과를 찾는다."""

import hashlib
import json
from datetime import date

import pandas as pd
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, Max

from backtest.data import load_close
from backtest.engine import simulate
from backtest.metrics import compute_metrics
from backtest.models import BacktestRun
from backtest.strategies import STRATEGIES, buy_and_hold
from market.models import Asset

DEFAULT_FEE = 0.0005  # 업비트 KRW 마켓 수수료 0.05%
CACHE_TIMEOUT = 60 * 60 * 24  # 데이터 버전이 키에 들어가 있어 오래 둬도 안전하다


def normalize_params(
    symbol: str,
    strategy: str,
    start: date,
    end: date,
    fee: float = DEFAULT_FEE,
    short: int | None = None,
    long: int | None = None,
) -> dict:
    """같은 의미의 요청이 항상 같은 dict(→ 같은 해시)가 되도록 정리한다."""
    if strategy not in STRATEGIES:
        raise ValueError(f"알 수 없는 전략입니다: {strategy}")
    if strategy == "buy_and_hold":
        short = long = None  # 이 전략에는 의미 없는 값이 해시를 바꾸지 않게 한다
    return {
        "symbol": symbol,
        "strategy": strategy,
        "short": short,
        "long": long,
        "fee": float(fee),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def data_version(asset: Asset) -> str:
    """종목 일봉의 버전: 마지막 수집·갱신 시각 + 행 수. 일봉이 바뀌면 이 값도 바뀐다.

    수집 시각만 쓰면 일봉이 삭제되기만 했을 때(재처리가 원본에 없는 날을 지움) 남은 행의
    시각이 그대로라 버전이 안 바뀌어 옛 백테스트 결과가 캐시에서 나간다. 그래서 행 수를 붙인다.
    길이: 시각 32자 + ":" + 행 수 → BacktestRun.data_version(40자) 안에 들어간다.
    """
    v = asset.candles.aggregate(latest=Max("collected_at"), count=Count("id"))
    return f"{v['latest'].isoformat()}:{v['count']}" if v["latest"] else "empty"


def compute_backtest(asset: Asset, params: dict) -> dict:
    start = date.fromisoformat(params["start"])
    end = date.fromisoformat(params["end"])
    warmup = params["long"] or 0
    close = load_close(asset, start, end, warmup_days=warmup)

    if params["strategy"] == "ma_cross":
        signal = STRATEGIES["ma_cross"](close, params["short"], params["long"])
    else:
        signal = STRATEGIES[params["strategy"]](close)

    start_ts = pd.Timestamp(start)
    strategy_frame = simulate(close, signal, start_ts, fee=params["fee"])
    benchmark_frame = simulate(close, buy_and_hold(close), start_ts, fee=params["fee"])

    equity = strategy_frame["equity"]
    drawdown = equity / equity.cummax().clip(lower=1.0) - 1
    curve = [
        {
            "date": day.date().isoformat(),
            "equity": round(float(equity[day]), 6),
            "benchmark": round(float(benchmark_frame["equity"][day]), 6),
            "drawdown": round(float(drawdown[day]), 6),
        }
        for day in equity.index
    ]
    return {
        "metrics": compute_metrics(strategy_frame),
        "benchmark": compute_metrics(benchmark_frame),
        "equity_curve": curve,
    }


def serialize_run(run: BacktestRun) -> dict:
    return {
        "id": run.id,
        "params": run.params,
        "data_version": run.data_version,
        "metrics": run.metrics,
        "benchmark": run.benchmark,
        "equity_curve": run.equity_curve,
        "created_at": run.created_at.isoformat(),
    }


def run_backtest(params: dict) -> tuple[dict, bool]:
    """백테스트 결과와 '이미 있던 결과인지(cached)'를 돌려준다.

    1) Redis 캐시  2) DB(BacktestRun)  3) 새로 계산 후 저장
    """
    asset = Asset.objects.get(symbol=params["symbol"])
    p_hash = params_hash(params)
    version = data_version(asset)
    key = f"bt:{p_hash}:{version}"

    payload = cache.get(key)
    if payload is not None:
        return payload, True

    run = BacktestRun.objects.filter(params_hash=p_hash, data_version=version).first()
    cached = run is not None
    if run is None:
        result = compute_backtest(asset, params)
        try:
            with transaction.atomic():
                run = BacktestRun.objects.create(
                    asset=asset, params=params, params_hash=p_hash, data_version=version, **result
                )
        except IntegrityError:
            # 같은 요청이 동시에 들어와 다른 쪽이 먼저 저장한 경우
            run = BacktestRun.objects.get(params_hash=p_hash, data_version=version)
            cached = True

    payload = serialize_run(run)
    cache.set(key, payload, CACHE_TIMEOUT)
    return payload, cached
