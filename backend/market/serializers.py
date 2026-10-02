from rest_framework import serializers

from market.models import Asset, CollectionRun, DailyCandle, IntegrityIssue


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
