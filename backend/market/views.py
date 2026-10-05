import hmac

from django.conf import settings
from django.db.models import Count, Max, Min, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from market.dashboard import revalidate_dashboard
from market.models import Asset, CollectionRun, DailyCandle, IntegrityIssue
from market.serializers import (
    AssetSerializer,
    CandleQuerySerializer,
    CandleSerializer,
    CollectionRunSerializer,
    IntegrityIssueSerializer,
    IntegritySummarySerializer,
)
from market.services import collect_candles


class AssetListView(generics.ListAPIView):
    """수집 대상 종목 목록."""

    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    pagination_class = None  # 종목은 몇 개뿐이라 나누지 않는다


class CandlePagination(PageNumberPagination):
    # 차트는 수년치(수천 개)를 한 번에 그리므로 기본 100개보다 크게 둔다.
    page_size = 500
    page_size_query_param = "page_size"
    max_page_size = 5000


@extend_schema(
    parameters=[
        OpenApiParameter("symbol", str, required=True, description="예: KRW-BTC"),
        OpenApiParameter("from", str, description="시작일 YYYY-MM-DD (포함)"),
        OpenApiParameter("to", str, description="종료일 YYYY-MM-DD (포함)"),
    ]
)
class CandleListView(generics.ListAPIView):
    """일봉 목록 (날짜 오름차순)."""

    serializer_class = CandleSerializer
    pagination_class = CandlePagination

    def get_queryset(self):
        query = CandleQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        asset = get_object_or_404(Asset, symbol=params["symbol"])

        candles = DailyCandle.objects.filter(asset=asset)
        if "start" in params:
            candles = candles.filter(date__gte=params["start"])
        if "end" in params:
            candles = candles.filter(date__lte=params["end"])
        return candles.order_by("date")


class CollectionRunListView(generics.ListAPIView):
    """수집 실행 기록 (최신순)."""

    queryset = CollectionRun.objects.all()
    serializer_class = CollectionRunSerializer


@extend_schema(
    parameters=[
        OpenApiParameter("symbol", str),
        OpenApiParameter("type", str, enum=IntegrityIssue.Type.values),
        OpenApiParameter("severity", str, enum=IntegrityIssue.Severity.values),
        OpenApiParameter("resolved", bool, description="true: 해결된 것만, false: 열린 것만"),
    ]
)
class IntegrityIssueListView(generics.ListAPIView):
    """무결성 이슈 목록 (최신 날짜순)."""

    serializer_class = IntegrityIssueSerializer

    def get_queryset(self):
        params = self.request.query_params
        issues = IntegrityIssue.objects.select_related("asset")
        if params.get("symbol"):
            issues = issues.filter(asset__symbol=params["symbol"])
        if params.get("type"):
            issues = issues.filter(type=params["type"])
        if params.get("severity"):
            issues = issues.filter(severity=params["severity"])
        if params.get("resolved") in ("true", "false"):
            issues = issues.filter(resolved_at__isnull=params["resolved"] == "false")
        return issues


class IntegritySummaryView(APIView):
    """종목별 데이터 상태 요약 + 마지막 수집 실행."""

    @extend_schema(responses=IntegritySummarySerializer)
    def get(self, request):
        open_issue = Q(issues__resolved_at__isnull=True)
        # 한 쿼리에 이슈 수를 세고, 일봉 범위는 별도 집계로 가져온다
        # (두 관계를 한 쿼리에서 JOIN하면 행이 곱해져 개수가 부풀려진다).
        issue_counts = Asset.objects.annotate(
            open_errors=Count("issues", filter=open_issue & Q(issues__severity="error")),
            open_warnings=Count("issues", filter=open_issue & Q(issues__severity="warning")),
        ).in_bulk()
        candle_ranges = Asset.objects.annotate(
            candle_count=Count("candles"),
            first_date=Min("candles__date"),
            last_final_date=Max("candles__date", filter=Q(candles__is_final=True)),
        ).order_by("symbol")  # 집계(GROUP BY) 쿼리에는 Meta.ordering이 적용되지 않는다

        assets = [
            {
                "symbol": a.symbol,
                "name": a.name,
                "candle_count": a.candle_count,
                "first_date": a.first_date,
                "last_final_date": a.last_final_date,
                "open_errors": issue_counts[a.id].open_errors,
                "open_warnings": issue_counts[a.id].open_warnings,
            }
            for a in candle_ranges
        ]
        last_run = CollectionRun.objects.first()
        return Response(
            {
                "assets": assets,
                "last_run": CollectionRunSerializer(last_run).data if last_run else None,
            }
        )


class CronCollectView(APIView):
    """Vercel Cron이 매일 호출하는 수집 엔드포인트. 최근 7일을 다시 받아 저장한다.

    `Authorization: Bearer <CRON_SECRET>` 헤더가 맞아야 실행된다.
    `?sentry_test=1`이면 수집 대신 일부러 예외를 내서 Sentry 연동을 확인한다.
    """

    # 사용자 인증·Redis throttle과 무관하게 비밀값 하나로만 판단한다.
    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    # Vercel Cron 전용 내부 엔드포인트라 공개 API 문서(Swagger)에는 싣지 않는다.
    @extend_schema(exclude=True)
    def get(self, request):
        expected = f"Bearer {settings.CRON_SECRET}".encode()
        # compare_digest는 영문이 아닌 글자가 섞인 str에 TypeError(500)를 내므로 bytes로 비교한다.
        received = request.headers.get("Authorization", "").encode()
        # 비교 시간으로 비밀값을 한 글자씩 추측하지 못하게 상수 시간 비교를 쓴다.
        if not settings.CRON_SECRET or not hmac.compare_digest(received, expected):
            return Response({"detail": "인증 실패"}, status=401)

        if request.query_params.get("sentry_test") == "1":
            raise RuntimeError("Sentry 연동 확인용 의도적 오류")

        run = collect_candles(CollectionRun.Trigger.CRON)
        # 전 종목 실패면 Vercel Cron 기록에도 실패로 남도록 500을 돌려준다.
        # 일부 실패(partial)는 다음 날 7일 재수집으로 메워지므로 200으로 둔다.
        failed = run.status == CollectionRun.Status.FAILED
        if not failed:
            # 새 데이터가 들어왔으니 대시보드가 이전 캐시를 보여 주지 않게 바로 갱신시킨다.
            revalidate_dashboard()
        return Response(CollectionRunSerializer(run).data, status=500 if failed else 200)
