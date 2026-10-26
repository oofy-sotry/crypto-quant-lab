import hmac
from datetime import UTC, date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Max, Min, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from config.querylog import recent_slow_queries
from market.aggregates import MODELS
from market.dashboard import revalidate_dashboard
from market.minute_pipeline import run_minute_pipeline
from market.models import (
    Asset,
    CollectionRun,
    DailyAgg,
    DailyCandle,
    HourlyBar,
    IntegrityIssue,
    MinuteCandle,
    ReprocessRun,
)
from market.ops import day_detail, day_matrix
from market.reprocess import run_reprocess
from market.serializers import (
    AggBarSerializer,
    AssetSerializer,
    BarQuerySerializer,
    CandleQuerySerializer,
    CandleSerializer,
    CollectionRunSerializer,
    DayDetailSerializer,
    DayMatrixSerializer,
    IntegrityIssueSerializer,
    IntegritySummarySerializer,
    MinuteCandleSerializer,
    MinuteQuerySerializer,
    MinuteStatusSerializer,
    ReprocessRequestSerializer,
    ReprocessRunSerializer,
    SlowQuerySerializer,
)
from market.services import collect_candles
from market.upbit import current_trading_day


def bearer_matches(request, secret: str) -> bool:
    """Authorization 헤더가 `Bearer <secret>`인지. secret이 비어 있으면 항상 거부한다.

    설정이 빠졌을 때 "빈 값끼리 일치"로 통과하는 구멍을 막는다.
    """
    if not secret:
        return False
    expected = f"Bearer {secret}".encode()
    # compare_digest는 영문이 아닌 글자가 섞인 str에 TypeError(500)를 내므로 bytes로 비교한다.
    received = request.headers.get("Authorization", "").encode()
    # 비교 시간으로 비밀값을 한 글자씩 추측하지 못하게 상수 시간 비교를 쓴다.
    return hmac.compare_digest(received, expected)


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


class TimeSeriesPagination(CursorPagination):
    """keyset 페이지네이션: "마지막으로 본 시각보다 뒤" 조건으로 다음 페이지를 읽는다.

    페이지 번호 방식은 페이지마다 COUNT(*)(BTC 분봉 52만 행, 약 135ms)를 하고, 깊은 페이지일수록
    OFFSET만큼 인덱스를 읽고 버린다. keyset은 COUNT가 없고 어느 페이지든 인덱스에서 바로 찾는다.
    대신 전체 개수와 임의 페이지 이동이 없다(시계열을 앞에서부터 차례로 읽는 용도라 괜찮다).
    정렬 컬럼은 종목 안에서 유일해야 한다(unique(asset, ts)·unique(asset, bucket)).
    """

    page_size = 500
    page_size_query_param = "page_size"
    max_page_size = 5000

    def decode_cursor(self, request):
        # DRF가 만든 커서는 항상 +00:00이 붙는다. 직접 만든 커서에 시간대가 없으면
        # 서버 시간대(Asia/Seoul)로 해석되므로 from·to와 같게 UTC로 맞춘다.
        cursor = super().decode_cursor(request)
        if cursor and cursor.position:
            try:
                position = parse_datetime(cursor.position)
            except ValueError:  # 형식은 맞는데 없는 날짜 → 아래 paginate_queryset에서 404
                position = None
            if position and is_naive(position):
                cursor = cursor._replace(position=position.replace(tzinfo=UTC).isoformat())
        return cursor

    def paginate_queryset(self, queryset, request, view=None):
        # 커서 안 위치 값이 시각 형식이 아니면(직접 고친 커서) DRF는 500을 낸다 → 404로 바꾼다.
        try:
            return super().paginate_queryset(queryset, request, view)
        except DjangoValidationError as exc:
            raise NotFound(self.invalid_cursor_message) from exc


class MinutePagination(TimeSeriesPagination):
    ordering = "ts"


class BarPagination(TimeSeriesPagination):
    ordering = "bucket"


RANGE_PARAMETERS = [
    OpenApiParameter("symbol", str, required=True, description="예: KRW-BTC"),
    OpenApiParameter("from", str, description="시작 시각 ISO 8601 (포함, 시간대 없으면 UTC)"),
    OpenApiParameter("to", str, description="끝 시각 ISO 8601 (포함 안 함)"),
]


def time_range(queryset, field: str, params: dict):
    """검증된 from·to로 [start, end) 범위를 건다."""
    if "start" in params:
        queryset = queryset.filter(**{f"{field}__gte": params["start"]})
    if "end" in params:
        queryset = queryset.filter(**{f"{field}__lt": params["end"]})
    return queryset


@extend_schema(parameters=RANGE_PARAMETERS)
class MinuteCandleListView(generics.ListAPIView):
    """분봉 목록 (시각 오름차순, UTC)."""

    serializer_class = MinuteCandleSerializer
    pagination_class = MinutePagination

    def get_queryset(self):
        query = MinuteQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        asset = get_object_or_404(Asset, symbol=query.validated_data["symbol"])
        minutes = MinuteCandle.objects.filter(asset=asset)
        return time_range(minutes, "ts", query.validated_data)


@extend_schema(
    parameters=[
        *RANGE_PARAMETERS,
        OpenApiParameter("unit", str, required=True, enum=list(MODELS)),
    ]
)
class AggBarListView(generics.ListAPIView):
    """분봉으로 만든 집계 봉 목록 (구간 시작 오름차순, UTC). unit=hour 시간봉, unit=day 일봉."""

    serializer_class = AggBarSerializer
    pagination_class = BarPagination

    def get_queryset(self):
        query = BarQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        asset = get_object_or_404(Asset, symbol=params["symbol"])
        bars = MODELS[params["unit"]].objects.filter(asset=asset)
        return time_range(bars, "bucket", params)


def latest(model, field: str) -> Subquery:
    """종목마다 field의 가장 늦은 값.

    GROUP BY asset_id + Max(field)는 테이블 전체(분봉 260만 행)를 읽는다. PostgreSQL은 그룹마다
    인덱스를 건너뛰며 읽지 못해서다. 종목별 ORDER BY field DESC LIMIT 1 서브쿼리로 바꾸면
    unique(asset_id, field) 인덱스를 종목마다 끝에서 한 칸만 읽는다. 세 테이블을 한 쿼리로 묶는다
    (로컬 1년치: 쿼리 4개 DB 약 470ms → 1개 0.2ms).
    """
    rows = model.objects.filter(asset=OuterRef("pk")).order_by(f"-{field}").values(field)
    return Subquery(rows[:1])


class MinuteStatusView(APIView):
    """종목별 최신 상태: 마지막 분봉·마지막 시간봉·마지막 일 집계 시각(UTC)."""

    @extend_schema(responses=MinuteStatusSerializer(many=True))
    def get(self, request):
        assets = Asset.objects.annotate(
            last_minute=latest(MinuteCandle, "ts"),
            last_hour=latest(HourlyBar, "bucket"),
            last_day=latest(DailyAgg, "bucket"),
        )
        return Response(MinuteStatusSerializer(assets, many=True).data)


@extend_schema(
    parameters=[
        OpenApiParameter("kind", str, enum=CollectionRun.Kind.values, description="없으면 전부"),
    ]
)
class CollectionRunListView(generics.ListAPIView):
    """수집 실행 기록 (최신순). kind=daily 일봉 수집, kind=minutes 분봉 파이프라인."""

    serializer_class = CollectionRunSerializer

    def get_queryset(self):
        runs = CollectionRun.objects.all()
        kind = self.request.query_params.get("kind")
        if kind in CollectionRun.Kind.values:
            runs = runs.filter(kind=kind)
        return runs


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
        # 일봉 수집 기준(이 요약의 일봉 범위와 같은 대상). 분봉은 ?kind=minutes로 따로 본다.
        last_run = CollectionRun.objects.filter(kind=CollectionRun.Kind.DAILY).first()
        return Response(
            {
                "assets": assets,
                "last_run": CollectionRunSerializer(last_run).data if last_run else None,
            }
        )


OPS_MAX_DAYS = 90


class OpsDayMatrixView(APIView):
    """운영 콘솔: 활성 종목 × 최근 N일(마감된 UTC 날) 상태 표.

    칸 상태는 error(미해결 오류) > no_minutes(분봉 없음) > not_aggregated(집계가 분봉과 다름)
    > warning > ok 순으로 가장 심한 것 하나.
    """

    @extend_schema(
        operation_id="ops_days_matrix",
        parameters=[
            OpenApiParameter(
                "days",
                int,
                description="최근 며칠(기본 30, 최대 90, 분봉 보관 기간이 있으면 그 일수)",
            )
        ],
        responses=DayMatrixSerializer,
    )
    def get(self, request):
        # 보관 기간보다 오래된 날은 분봉이 지워져 있어 "분봉 없음(수집 안 됨)"으로 잘못 보인다.
        # 운영(30일 보관)에서는 보관 기간까지만 보여 준다. 끝날이 어제라 오늘-30일 = 보관되는 첫날.
        retention = settings.MINUTE_RETENTION_DAYS
        max_days = min(retention, OPS_MAX_DAYS) if retention > 0 else OPS_MAX_DAYS
        try:
            days = int(request.query_params.get("days", 30))
        except ValueError:
            days = 0
        if not 1 <= days <= max_days:
            return Response({"detail": f"days는 1~{max_days}"}, status=400)
        end = current_trading_day() - timedelta(days=1)
        matrix = day_matrix(end - timedelta(days=days - 1), end)
        return Response(DayMatrixSerializer(matrix).data)


class OpsDayDetailView(APIView):
    """운영 콘솔: 한 종목·하루 상세(분봉 수·빈 구간·시간대별 집계·일봉 대조·이슈·재처리 이력)."""

    @extend_schema(operation_id="ops_day_detail", responses=DayDetailSerializer)
    def get(self, request, symbol: str, day: str):
        asset = get_object_or_404(Asset, symbol=symbol)
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            return Response({"detail": "날짜는 YYYY-MM-DD"}, status=400)
        return Response(DayDetailSerializer(day_detail(asset, parsed)).data)


class OpsSlowQueriesView(APIView):
    """최근 느린 쿼리(SLOW_QUERY_MS 이상, 최신순 최대 50건, 7일 보관). Cron 배치는 제외."""

    @extend_schema(responses=SlowQuerySerializer(many=True))
    def get(self, request):
        return Response(SlowQuerySerializer(recent_slow_queries(), many=True).data)


class CronView(APIView):
    """Vercel Cron 전용 엔드포인트 공통: 비밀값 확인 → run() → 결과 기록(CollectionRun)을 응답.

    `Authorization: Bearer <CRON_SECRET>` 헤더가 맞아야 실행된다.
    `?sentry_test=1`이면 실행 대신 일부러 예외를 내서 Sentry 연동을 확인한다.
    """

    # 사용자 인증·Redis throttle과 무관하게 비밀값 하나로만 판단한다.
    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    def run(self) -> CollectionRun:
        raise NotImplementedError

    def after_success(self, run: CollectionRun) -> None:
        """전부 실패가 아닐 때 실행 뒤에 할 일."""

    # Vercel Cron 전용 내부 엔드포인트라 공개 API 문서(Swagger)에는 싣지 않는다.
    @extend_schema(exclude=True)
    def get(self, request):
        if not bearer_matches(request, settings.CRON_SECRET):
            return Response({"detail": "인증 실패"}, status=401)

        if request.query_params.get("sentry_test") == "1":
            raise RuntimeError("Sentry 연동 확인용 의도적 오류")

        run = self.run()
        # 전 종목 실패면 Vercel Cron 기록에도 실패로 남도록 500을 돌려준다.
        # 일부 실패(partial)는 다음 날 재수집으로 메워지므로 200으로 둔다.
        failed = run.status == CollectionRun.Status.FAILED
        if not failed:
            self.after_success(run)
        return Response(CollectionRunSerializer(run).data, status=500 if failed else 200)


class CronCollectView(CronView):
    """매일 일봉 수집. 최근 7일을 다시 받아 저장하고 무결성 검사를 돌린다."""

    def run(self):
        return collect_candles(CollectionRun.Trigger.CRON)

    def after_success(self, run):
        # 새 데이터가 들어왔으니 대시보드가 이전 캐시를 보여 주지 않게 바로 갱신시킨다.
        revalidate_dashboard()


class CronMinutesView(CronView):
    """매일 분봉 파이프라인. 최근 2일 분봉 수집 → 집계 → 분봉 검사 → 보관 기간 지난 분봉 삭제.

    일봉 Cron과 따로 둬서 한쪽 실패·지연이 다른 쪽에 번지지 않고 실행 시간도 따로 남는다.
    """

    def run(self):
        return run_minute_pipeline(CollectionRun.Trigger.CRON)


@extend_schema(
    methods=["GET"],
    parameters=[
        OpenApiParameter("symbol", str),
        OpenApiParameter("date", str, description="이 날(YYYY-MM-DD)을 포함한 재처리만"),
    ],
)
class ReprocessView(generics.ListAPIView):
    """GET: 재처리 이력 목록(최신순, 공개). POST: 재처리 실행.

    POST는 `Authorization: Bearer <ADMIN_API_TOKEN>` 헤더가 맞아야 실행된다. 기본은 dry-run
    (바뀔 내용만 계산하고 롤백), `"dry_run": false`면 반영. 같은 종목·기간(하루라도 겹침)이
    실행 중이면 409, 실행 중 오류면 500(전부 롤백됨). 결과(거부·실패 포함)는 항상 이력으로 남는다.
    """

    # 사용자 세션이 아니라 관리자 토큰 하나로만 판단한다(세션 인증이 없으니 CSRF도 해당 없음).
    authentication_classes = []
    permission_classes = []
    serializer_class = ReprocessRunSerializer

    def get_queryset(self):
        runs = ReprocessRun.objects.select_related("asset")
        params = self.request.query_params
        if params.get("symbol"):
            runs = runs.filter(asset__symbol=params["symbol"])
        if params.get("date"):
            try:
                day = date.fromisoformat(params["date"])
            except ValueError as exc:
                raise ValidationError({"date": "YYYY-MM-DD"}) from exc
            runs = runs.filter(start_date__lte=day, end_date__gte=day)
        return runs

    STATUS_CODES = {
        ReprocessRun.Status.SUCCESS: 201,
        ReprocessRun.Status.REJECTED: 409,
        ReprocessRun.Status.FAILED: 500,
    }

    @extend_schema(
        request=ReprocessRequestSerializer,
        responses={
            201: ReprocessRunSerializer,
            400: OpenApiResponse(description="입력 오류(기간·상한·필수 값)"),
            401: OpenApiResponse(description="관리자 토큰 불일치"),
            409: ReprocessRunSerializer,
            500: ReprocessRunSerializer,
        },
    )
    def post(self, request):
        if not bearer_matches(request, settings.ADMIN_API_TOKEN):
            return Response({"detail": "인증 실패"}, status=401)
        serializer = ReprocessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        run = run_reprocess(
            data["asset"],
            data["target"],
            data["start"],
            data["end"],
            dry_run=data["dry_run"],
            reason=data["reason"],
            requested_by=data["requested_by"],
        )
        return Response(ReprocessRunSerializer(run).data, status=self.STATUS_CODES[run.status])


class ReprocessDetailView(generics.RetrieveAPIView):
    """재처리 이력 하나. 운영 콘솔에서 누가 왜 무엇을 바꿨는지 보여 주려고 공개로 둔다."""

    queryset = ReprocessRun.objects.select_related("asset")
    serializer_class = ReprocessRunSerializer
