import json
import statistics
import time
from base64 import b64encode
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

from django.core.management.base import BaseCommand
from django.db import connection
from rest_framework.test import APIRequestFactory

from market.integrity import MIN_GAP, find_gaps_in_db
from market.models import Asset, MinuteCandle
from market.views import (
    AggBarListView,
    IntegrityIssueListView,
    MinuteCandleListView,
    MinuteStatusView,
)

SYMBOL = "KRW-BTC"
# 로컬 1년치 분봉(2025-10-23 ~ 2026-10-22 UTC)에 맞춰 고정한 범위(실행마다 같은 쿼리가 되도록).
LAST_DAY = date(2026, 10, 22)


def utc(day: date) -> str:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC).isoformat()


def api(view, path: str, **query):
    """뷰를 throttle 없이 직접 호출한다(반복 측정이 요청 제한에 걸리지 않게)."""
    request = APIRequestFactory().get(path, query, SERVER_NAME="localhost")
    view_fn = view.as_view(throttle_classes=[])
    return lambda: view_fn(request).render()


# 예전 페이지 번호 방식의 page=500(500개씩)과 같은 위치. 전후 비교를 같은 행들로 한다.
DEEP_OFFSET = 249_500


def cursor_at(offset: int) -> dict:
    """offset번째 행부터 읽는 커서 쿼리. DRF CursorPagination과 같은 형식(p=마지막으로 본 값)."""
    asset = Asset.objects.get(symbol=SYMBOL)
    rows = MinuteCandle.objects.filter(asset=asset).order_by("ts").values_list("ts", flat=True)
    before = list(rows[offset - 1 : offset])
    if not before:  # 데이터가 적으면(테스트 DB) 첫 페이지
        return {}
    return {"cursor": b64encode(urlencode({"p": before[0]}).encode()).decode()}


def gaps(days: int):
    asset = Asset.objects.get(symbol=SYMBOL)
    end = datetime.combine(LAST_DAY + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return lambda: find_gaps_in_db(asset, end - timedelta(days=days), end, MIN_GAP)


def scenarios() -> dict:
    month_ago = utc(LAST_DAY - timedelta(days=29))
    return {
        # 1. 종목·기간 분봉 조회 (페이지네이션): 첫 페이지 / 깊은 페이지(1년 중 절반쯤)
        "minutes_first_page": api(MinuteCandleListView, "/api/minutes/", symbol=SYMBOL),
        "minutes_deep_page": api(
            MinuteCandleListView, "/api/minutes/", symbol=SYMBOL, **cursor_at(DEEP_OFFSET)
        ),
        "minutes_month": api(
            MinuteCandleListView, "/api/minutes/", symbol=SYMBOL, **{"from": month_ago}
        ),
        # 2. 기간별 시간 집계 조회
        "bars_hour_month": api(
            AggBarListView, "/api/bars/", symbol=SYMBOL, unit="hour", **{"from": month_ago}
        ),
        "bars_hour_year": api(AggBarListView, "/api/bars/", symbol=SYMBOL, unit="hour"),
        # 3. 종목별 최신 상태 요약
        "minute_status": api(MinuteStatusView, "/api/minutes/status/"),
        # 4. 결측 구간 탐지 (재처리 상한 31일, 1년 전체)
        "gaps_31d": gaps(31),
        "gaps_year": gaps(365),
        # 5. 미해결 이슈 목록
        "open_issues": api(IntegrityIssueListView, "/api/integrity/issues/", resolved="false"),
    }


class Recorder:
    """실행되는 SQL과 파라미터를 그대로 모은다(나중에 같은 문장을 EXPLAIN하려고)."""

    def __init__(self):
        self.statements = []

    def __call__(self, execute, sql, params, many, context):
        self.statements.append((sql, params))
        return execute(sql, params, many, context)


def explain(sql: str, params) -> dict:
    # TIMING OFF: 노드마다 시계를 읽는 비용이 빠져 Execution Time이 실제 실행 시간에 가깝다
    # (켜면 행이 많은 쿼리에서 1.5배 이상 부풀었다). 노드별 시간은 쓰지 않는다.
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, FORMAT JSON) {sql}", params)
        return cursor.fetchone()[0][0]


def scan_nodes(plan: dict) -> list[str]:
    """실행 계획에서 테이블을 읽는 노드만 "노드 종류(인덱스)" 형태로 뽑는다."""
    nodes = []
    if "Scan" in plan["Node Type"]:
        target = plan.get("Index Name") or plan.get("Relation Name", "")
        nodes.append(f"{plan['Node Type']}({target})")
    for child in plan.get("Plans", []):
        nodes.extend(scan_nodes(child))
    return nodes


def measure_statement(sql: str, params, repeat: int) -> dict:
    explain(sql, params)  # 워밍업
    runs = [explain(sql, params) for _ in range(repeat)]
    median = statistics.median_low([r["Execution Time"] for r in runs])
    run = next(r for r in runs if r["Execution Time"] == median)
    top = run["Plan"]
    return {
        "sql": sql[:200],
        "exec_ms": round(median, 3),
        "planning_ms": round(run["Planning Time"], 3),
        "shared_hit": top.get("Shared Hit Blocks", 0),
        "shared_read": top.get("Shared Read Blocks", 0),
        "rows": top.get("Actual Rows"),
        "scans": scan_nodes(top),
    }


class Command(BaseCommand):
    help = (
        "D5 튜닝 시나리오를 실제 코드 경로(API 뷰·검사 함수)로 실행해 걸린 시간을 재고, "
        "실행된 SQL마다 EXPLAIN (ANALYZE, BUFFERS)를 워밍업 1회 + N회 중앙값으로 기록한다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--only", nargs="+", help="시나리오 이름 일부만 실행")
        parser.add_argument("--repeat", type=int, default=5)
        parser.add_argument("--out", help="결과를 JSON 파일로 저장")
        parser.add_argument("--label", default="", help="결과에 붙일 이름(예: before, after)")

    def handle(self, *args, **options):
        repeat = options["repeat"]
        results = {}
        for name, run in scenarios().items():
            if options["only"] and name not in options["only"]:
                continue
            recorder = Recorder()
            with connection.execute_wrapper(recorder):
                run()  # 워밍업 + 실행 SQL 수집
            wall = []
            for _ in range(repeat):
                start = time.perf_counter()
                run()
                wall.append((time.perf_counter() - start) * 1000)
            statements = [measure_statement(sql, p, repeat) for sql, p in recorder.statements]
            results[name] = {
                "wall_ms": round(statistics.median(wall), 2),
                "queries": len(statements),
                "statements": statements,
            }
            self.stdout.write(f"{name}: {results[name]['wall_ms']}ms, 쿼리 {len(statements)}개")
            for s in statements:
                self.stdout.write(
                    f"  {s['exec_ms']:>9.3f}ms  hit {s['shared_hit']:>6} read {s['shared_read']:>5}"
                    f"  {', '.join(s['scans']) or '-'}"
                )

        if options["out"]:
            payload = {
                "label": options["label"],
                "measured_at": datetime.now(UTC).isoformat(),
                "repeat": repeat,
                "cache": "warm (워밍업 1회 후 측정)",
                "results": results,
            }
            with open(options["out"], "w") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
