from django.contrib import admin
from django.utils import timezone

from market.models import Asset, CollectionRun, DailyCandle, IntegrityIssue


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ["symbol", "name", "listed_on", "is_active"]


@admin.register(DailyCandle)
class DailyCandleAdmin(admin.ModelAdmin):
    list_display = ["asset", "date", "open", "high", "low", "close", "is_final"]
    list_filter = ["asset", "is_final"]
    date_hierarchy = "date"


@admin.register(CollectionRun)
class CollectionRunAdmin(admin.ModelAdmin):
    list_display = ["started_at", "trigger", "status", "assets_count", "upserted_count"]
    list_filter = ["trigger", "status"]


@admin.register(IntegrityIssue)
class IntegrityIssueAdmin(admin.ModelAdmin):
    list_display = ["asset", "date", "type", "severity", "resolved_at", "note"]
    list_filter = ["asset", "type", "severity"]
    actions = ["acknowledge_source_gap"]

    @admin.action(description="원본 데이터에도 없음을 확인 — 해결 처리")
    def acknowledge_source_gap(self, request, queryset):
        updated = queryset.update(
            resolved_at=timezone.now(), note="업비트 원본에도 없는 데이터 (확인됨)"
        )
        self.message_user(request, f"{updated}건을 해결 처리했습니다.")
