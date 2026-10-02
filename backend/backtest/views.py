from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from backtest.data import DataNotReady
from backtest.models import BacktestRun
from backtest.serializers import BacktestRequestSerializer, BacktestResultSerializer
from backtest.services import normalize_params, run_backtest, serialize_run


class BacktestCreateView(APIView):
    """백테스트 실행. 같은 요청·같은 데이터면 저장된 결과를 돌려준다."""

    throttle_scope = "backtest"

    @extend_schema(
        request=BacktestRequestSerializer,
        responses={
            201: OpenApiResponse(BacktestResultSerializer, description="새로 계산함"),
            200: OpenApiResponse(BacktestResultSerializer, description="캐시 또는 DB에 있던 결과"),
            400: OpenApiResponse(description="요청 값 오류"),
            422: OpenApiResponse(description="기간 내 데이터 오류·부족으로 계산 불가"),
        },
    )
    def post(self, request):
        serializer = BacktestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = normalize_params(**serializer.validated_data)
        try:
            payload, cached = run_backtest(params)
        except DataNotReady as exc:
            # 요청 형식은 맞지만 데이터 상태 때문에 처리할 수 없다 → 422
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(payload, status=status.HTTP_200_OK if cached else status.HTTP_201_CREATED)


class BacktestDetailView(APIView):
    """저장된 백테스트 결과 조회."""

    @extend_schema(responses=BacktestResultSerializer)
    def get(self, request, pk):
        return Response(serialize_run(get_object_or_404(BacktestRun, pk=pk)))
