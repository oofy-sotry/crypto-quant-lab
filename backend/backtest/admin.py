from django.contrib import admin

from backtest.models import BacktestRun


@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ["id", "asset", "strategy", "period", "total_return", "created_at"]
    list_filter = ["asset"]
    # 결과 JSON(자산 곡선 수천 점)은 목록에서 빼고 상세 화면에서만 본다.
    readonly_fields = ["params", "params_hash", "data_version", "metrics", "benchmark"]
    exclude = ["equity_curve"]

    @admin.display(description="전략")
    def strategy(self, obj):
        return obj.params.get("strategy")

    @admin.display(description="기간")
    def period(self, obj):
        return f"{obj.params.get('start')} ~ {obj.params.get('end')}"

    @admin.display(description="총수익률")
    def total_return(self, obj):
        return f"{obj.metrics.get('total_return', 0):.1%}"
