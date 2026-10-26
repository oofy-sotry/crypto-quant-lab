from datetime import UTC, timedelta

from rest_framework import serializers

from market.aggregates import MODELS
from market.models import (
    Asset,
    CollectionRun,
    DailyCandle,
    HourlyBar,
    IntegrityIssue,
    MinuteCandle,
    ReprocessRun,
)
from market.upbit import current_trading_day


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = ["symbol", "name", "listed_on", "is_active"]


class CandleSerializer(serializers.ModelSerializer):
    # Decimal은 문자열로 내보낸다(DRF 기본값). JSON 숫자(float)로 바꾸면 정밀도가 깨질 수 있다.
    class Meta:
        model = DailyCandle
        fields = ["date", "open", "high", "low", "close", "volume", "value", "is_final"]


class CandleQuerySerializer(serializers.Serializer):
    """GET /api/candles/ 쿼리 파라미터 검증."""

    # 쿼리 파라미터 이름(from, to) → 필드 이름. from은 파이썬 예약어라 필드 이름으로 못 쓴다.
    PARAM_NAMES = {"symbol": "symbol", "from": "start", "to": "end"}

    symbol = serializers.CharField()
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)

    def to_internal_value(self, data):
        data = {field: data[param] for param, field in self.PARAM_NAMES.items() if data.get(param)}
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs.get("start") and attrs.get("end") and attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("from은 to보다 늦을 수 없습니다.")
        return attrs


class MinuteCandleSerializer(serializers.ModelSerializer):
    # 분봉은 UTC로 저장하고 UTC로 내보낸다(일봉 경계 UTC 00:00과 맞춰 읽기 쉽게).
    ts = serializers.DateTimeField(default_timezone=UTC)

    class Meta:
        model = MinuteCandle
        fields = ["ts", "open", "high", "low", "close", "volume", "value"]


class MinuteQuerySerializer(CandleQuerySerializer):
    """GET /api/minutes/ 쿼리 파라미터 검증. from·to는 시각(시간대 없으면 UTC), to는 미포함."""

    start = serializers.DateTimeField(required=False, default_timezone=UTC)
    end = serializers.DateTimeField(required=False, default_timezone=UTC)


class AggBarSerializer(serializers.ModelSerializer):
    bucket = serializers.DateTimeField(default_timezone=UTC)

    class Meta:
        model = HourlyBar  # 필드는 AggBar 공통이라 DailyAgg에도 그대로 쓴다
        fields = [
            "bucket",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "value",
            "vwap",
            "volatility",
            "minute_count",
        ]


class BarQuerySerializer(MinuteQuerySerializer):
    """GET /api/bars/ 쿼리 파라미터 검증. unit은 hour(시간봉) 또는 day(분봉으로 만든 일봉)."""

    PARAM_NAMES = {**MinuteQuerySerializer.PARAM_NAMES, "unit": "unit"}

    unit = serializers.ChoiceField(choices=list(MODELS))


class MinuteStatusSerializer(serializers.Serializer):
    """GET /api/minutes/status/ 종목 하나의 최신 상태."""

    symbol = serializers.CharField()
    last_minute = serializers.DateTimeField(allow_null=True, default_timezone=UTC)
    last_hour = serializers.DateTimeField(allow_null=True, default_timezone=UTC)
    last_day = serializers.DateTimeField(allow_null=True, default_timezone=UTC)


class CollectionRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollectionRun
        fields = [
            "id",
            "trigger",
            "status",
            "started_at",
            "finished_at",
            "assets_count",
            "upserted_count",
            "error_message",
        ]


class IntegrityIssueSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="asset.symbol")

    class Meta:
        model = IntegrityIssue
        fields = [
            "id",
            "symbol",
            "date",
            "type",
            "severity",
            "detail",
            "detected_at",
            "resolved_at",
            "note",
        ]


class AssetSummarySerializer(serializers.Serializer):
    symbol = serializers.CharField()
    name = serializers.CharField()
    candle_count = serializers.IntegerField()
    first_date = serializers.DateField(allow_null=True)
    last_final_date = serializers.DateField(allow_null=True)
    open_errors = serializers.IntegerField()
    open_warnings = serializers.IntegerField()


class IntegritySummarySerializer(serializers.Serializer):
    """GET /api/integrity/summary/ 응답 형식."""

    assets = AssetSummarySerializer(many=True)
    last_run = CollectionRunSerializer(allow_null=True)


class ReprocessRequestSerializer(serializers.Serializer):
    """POST /api/reprocess/ 본문 검증."""

    # 서버리스 함수 제한(300초) 안에 끝나도록 대상별 기간 상한을 둔다.
    # 분봉 31일 ≈ 업비트 요청 220여 번. 더 긴 기간은 management command(reprocess)로 실행한다.
    MAX_DAYS = {
        ReprocessRun.Target.MINUTES: 31,
        ReprocessRun.Target.AGGREGATES: 31,
        ReprocessRun.Target.DAILY: 366,
    }

    symbol = serializers.SlugRelatedField(
        slug_field="symbol", queryset=Asset.objects.all(), source="asset"
    )
    target = serializers.ChoiceField(choices=ReprocessRun.Target.choices)
    start = serializers.DateField()
    end = serializers.DateField()
    reason = serializers.CharField(max_length=200)
    requested_by = serializers.CharField(max_length=100)
    # 실수로 데이터를 바꾸지 않도록 기본은 미리보기. 반영하려면 false를 명시한다.
    dry_run = serializers.BooleanField(default=True)

    def validate(self, attrs):
        start, end = attrs["start"], attrs["end"]
        if start > end:
            raise serializers.ValidationError("start는 end보다 늦을 수 없습니다.")
        today = current_trading_day()
        if end >= today:
            raise serializers.ValidationError(
                f"end는 마감된 날({today - timedelta(days=1)})까지만 가능합니다."
            )
        max_days = self.MAX_DAYS[attrs["target"]]
        if (end - start).days + 1 > max_days:
            raise serializers.ValidationError(
                f"{attrs['target']}는 한 번에 {max_days}일까지 가능합니다."
                " 더 긴 기간은 reprocess 커맨드로 실행하세요."
            )
        return attrs


class ReprocessRunSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="asset.symbol")

    class Meta:
        model = ReprocessRun
        fields = [
            "id",
            "symbol",
            "target",
            "start_date",
            "end_date",
            "dry_run",
            "reason",
            "requested_by",
            "status",
            "rows_before",
            "rows_after",
            "changed_rows",
            "diff",
            "started_at",
            "finished_at",
            "error_message",
        ]
