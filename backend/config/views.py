import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from config.querylog import recent_slow_queries


def _check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _check_cache():
    cache.set("health:ping", "pong", timeout=5)
    if cache.get("health:ping") != "pong":
        raise RuntimeError("cache round-trip failed")


@extend_schema(
    responses=inline_serializer(
        "Health",
        {
            "status": serializers.CharField(),
            "checks": serializers.DictField(),
            "latency_ms": serializers.DictField(),
            "queries": serializers.DictField(),
        },
    )
)
@api_view(["GET"])
# 모니터링용이라 횟수 제한을 걸지 않는다. throttle은 Redis를 쓰므로,
# 걸어 두면 Redis 장애 때 health가 503 대신 500으로 죽어 장애 원인을 알려주지 못한다.
@throttle_classes([])
def health(request):
    checks, latency_ms = {}, {}
    for name, check in (("database", _check_database), ("cache", _check_cache)):
        started = time.perf_counter()
        try:
            check()
            checks[name] = "ok"
        except Exception as exc:
            checks[name] = f"error: {exc.__class__.__name__}"
        # 연결 수립 시간까지 포함한 소요 시간. 의존 서비스가 느려지는 것도 감지할 수 있다.
        latency_ms[name] = round((time.perf_counter() - started) * 1000)

    healthy = all(status == "ok" for status in checks.values())
    return Response(
        {
            "status": "ok" if healthy else "error",
            "checks": checks,
            "latency_ms": latency_ms,
            "queries": _query_metrics(checks["cache"] == "ok"),
        },
        status=200 if healthy else 503,
    )


def _query_metrics(cache_ok: bool) -> dict:
    """느린 쿼리 기준과 최근 24시간 건수. 느린 쿼리 목록은 Redis에 있어 Redis가 죽으면 None."""
    slow_24h = None
    if cache_ok:
        since = timezone.now() - timedelta(hours=24)
        slow_24h = sum(1 for q in recent_slow_queries() if datetime.fromisoformat(q["at"]) >= since)
    # 목록은 최근 50건까지만 보관하므로 그보다 많으면 50으로 잘린다.
    return {"slow_threshold_ms": settings.SLOW_QUERY_MS, "slow_24h": slow_24h}


# DRF 뷰가 아닌 일반 Django 뷰로 둔다. throttle(Redis)을 거치지 않아 첫 화면 이동이 가볍다.
def root(request):
    if not settings.DASHBOARD_URL:
        raise Http404
    # 대시보드 주소가 바뀔 수 있으니 브라우저가 기억하는 301 대신 302.
    return redirect(settings.DASHBOARD_URL)
