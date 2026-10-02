from django.db.models import Count, Max, Min, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from market.models import Asset, CollectionRun, DailyCandle, IntegrityIssue
from market.serializers import (
    AssetSerializer,
    CandleQuerySerializer,
    CandleSerializer,
    CollectionRunSerializer,
    IntegrityIssueSerializer,
)


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
