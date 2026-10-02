from django.db import models

from market.models import Asset


class BacktestRun(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="backtests")
    # 요청 파라미터(정규화된 형태)와 그 해시. 같은 요청은 같은 해시가 된다.
    params = models.JSONField()
    params_hash = models.CharField(max_length=64)
    # 계산에 쓴 데이터의 버전(종목의 마지막 수집 시각). 데이터가 바뀌면 결과도 새로 계산한다.
    data_version = models.CharField(max_length=40)
    metrics = models.JSONField()  # 전략 지표
    benchmark = models.JSONField()  # 같은 기간 Buy&Hold 지표
    equity_curve = models.JSONField()  # [{date, equity, benchmark, drawdown}, ...]
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # 같은 파라미터 + 같은 데이터면 결과도 같으므로 한 번만 저장한다.
            models.UniqueConstraint(fields=["params_hash", "data_version"], name="uniq_backtest"),
        ]

    def __str__(self):
        return f"{self.asset} {self.params.get('strategy')} {self.created_at:%Y-%m-%d %H:%M}"
