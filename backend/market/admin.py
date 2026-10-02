from django.contrib import admin

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
    list_display = ["asset", "date", "type", "severity", "resolved_at"]
    list_filter = ["asset", "type", "severity"]
