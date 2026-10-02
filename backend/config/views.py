from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response


def _check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _check_cache():
    cache.set("health:ping", "pong", timeout=5)
    if cache.get("health:ping") != "pong":
        raise RuntimeError("cache round-trip failed")


@api_view(["GET"])
# 모니터링용이라 횟수 제한을 걸지 않는다. throttle은 Redis를 쓰므로,
# 걸어 두면 Redis 장애 때 health가 503 대신 500으로 죽어 장애 원인을 알려주지 못한다.
@throttle_classes([])
def health(request):
    checks = {}
    for name, check in (("database", _check_database), ("cache", _check_cache)):
        try:
            check()
            checks[name] = "ok"
        except Exception as exc:
            checks[name] = f"error: {exc.__class__.__name__}"

    healthy = all(status == "ok" for status in checks.values())
    return Response(
        {"status": "ok" if healthy else "error", "checks": checks},
        status=200 if healthy else 503,
    )
