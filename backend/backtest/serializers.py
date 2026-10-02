from rest_framework import serializers

from backtest.services import DEFAULT_FEE
from backtest.strategies import STRATEGIES
from market.models import Asset


class BacktestRequestSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    strategy = serializers.ChoiceField(choices=sorted(STRATEGIES))
    start = serializers.DateField()
    end = serializers.DateField()
    short = serializers.IntegerField(required=False, min_value=1, max_value=200)
    long = serializers.IntegerField(required=False, min_value=2, max_value=400)
    # 0~1% 범위로 제한. 비현실적인 값으로 결과가 왜곡되는 걸 막는다.
    fee = serializers.FloatField(required=False, default=DEFAULT_FEE, min_value=0, max_value=0.01)

    def validate_symbol(self, value):
        if not Asset.objects.filter(symbol=value).exists():
            raise serializers.ValidationError("지원하지 않는 종목입니다.")
        return value

    def validate(self, attrs):
        if attrs["start"] >= attrs["end"]:
            raise serializers.ValidationError("start는 end보다 앞이어야 합니다.")
        if attrs["strategy"] == "ma_cross":
            short, long = attrs.get("short"), attrs.get("long")
            if short is None or long is None:
                raise serializers.ValidationError("ma_cross에는 short와 long이 필요합니다.")
            if short >= long:
                raise serializers.ValidationError("short는 long보다 작아야 합니다.")
        return attrs


class MetricsSerializer(serializers.Serializer):
    total_return = serializers.FloatField()
    cagr = serializers.FloatField()
    max_drawdown = serializers.FloatField()
    sharpe = serializers.FloatField()
    trades = serializers.IntegerField()
    win_rate = serializers.FloatField()
    exposure = serializers.FloatField()
    days = serializers.IntegerField()


class EquityPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    equity = serializers.FloatField()
    benchmark = serializers.FloatField()
    drawdown = serializers.FloatField()


class BacktestResultSerializer(serializers.Serializer):
    """응답 형식 문서화용 (실제 응답은 services.serialize_run이 만든다)."""

    id = serializers.IntegerField()
    params = serializers.DictField()
    data_version = serializers.CharField()
    metrics = MetricsSerializer()
    benchmark = MetricsSerializer()
    equity_curve = EquityPointSerializer(many=True)
    created_at = serializers.DateTimeField()
