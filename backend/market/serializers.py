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
from market.reprocess import retention_error
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
            "kind",
            "trigger",
            "status",
            "started_at",
            "finished_at",
            "assets_count",
            "upserted_count",
            "error_message",
            "detail",
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
        if error := retention_error(attrs["target"], start, today):
            raise serializers.ValidationError(error)
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


class DayCellSerializer(serializers.Serializer):
    """운영 콘솔 매트릭스의 칸 하나 (종목, UTC 날짜)."""

    date = serializers.DateField()
    status = serializers.ChoiceField(
        choices=["error", "no_minutes", "not_aggregated", "warning", "ok"],
        help_text="error > no_minutes > not_aggregated > warning > ok 순으로 가장 심한 것",
    )
    minute_count = serializers.IntegerField()
    aggregated_minutes = serializers.IntegerField(
        allow_null=True, help_text="일 집계가 만들어질 때의 분봉 수(없으면 null)"
    )
    daily_final = serializers.BooleanField(help_text="업비트 확정 일봉이 있는지")
    open_errors = serializers.IntegerField()
    open_warnings = serializers.IntegerField()
    reprocess_runs = serializers.IntegerField(help_text="이 날을 포함한 재처리 수(dry-run 포함)")


class DayRowSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    cells = DayCellSerializer(many=True)


class DayMatrixSerializer(serializers.Serializer):
    """GET /api/ops/days/ 응답."""

    start = serializers.DateField()
    end = serializers.DateField()
    rows = DayRowSerializer(many=True)


class GapSerializer(serializers.Serializer):
    start = serializers.DateTimeField(default_timezone=UTC)
    end = serializers.DateTimeField(default_timezone=UTC)
    minutes = serializers.IntegerField()


class HourCountSerializer(serializers.Serializer):
    hour = serializers.DateTimeField(default_timezone=UTC)
    minute_count = serializers.IntegerField()


class DayValuesSerializer(serializers.Serializer):
    """일봉 값 한 벌. Decimal은 정밀도를 지키려고 문자열로 낸다(다른 API와 같게)."""

    open = serializers.CharField()
    high = serializers.CharField()
    low = serializers.CharField()
    close = serializers.CharField()
    volume = serializers.CharField()
    value = serializers.CharField()
    minute_count = serializers.IntegerField(required=False)  # 분봉 집계에만
    is_final = serializers.BooleanField(required=False)  # 업비트 일봉에만


class DayDetailSerializer(serializers.Serializer):
    """GET /api/ops/days/{symbol}/{date}/ 응답."""

    symbol = serializers.CharField()
    date = serializers.DateField()
    minute_count = serializers.IntegerField()
    gaps = GapSerializer(many=True, help_text="10분 이상 빈 구간")
    hourly = HourCountSerializer(many=True, help_text="시간대별 집계 분봉 수(없는 시간은 0)")
    daily_agg = DayValuesSerializer(allow_null=True, help_text="분봉으로 만든 일봉")
    daily_candle = DayValuesSerializer(allow_null=True, help_text="업비트 일봉")
    issues = IntegrityIssueSerializer(many=True)
    reprocess_runs = ReprocessRunSerializer(many=True)


class SlowQuerySerializer(serializers.Serializer):
    """GET /api/ops/slow-queries/ 항목 하나."""

    at = serializers.DateTimeField()
    path = serializers.CharField()
    ms = serializers.FloatField()
    sql = serializers.CharField(help_text="파라미터 값 없이 SQL 모양만")
