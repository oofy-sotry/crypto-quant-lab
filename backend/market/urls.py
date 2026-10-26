from django.urls import path

from market import views

urlpatterns = [
    path("assets/", views.AssetListView.as_view(), name="asset-list"),
    path("candles/", views.CandleListView.as_view(), name="candle-list"),
    path("minutes/", views.MinuteCandleListView.as_view(), name="minute-list"),
    path("minutes/status/", views.MinuteStatusView.as_view(), name="minute-status"),
    path("bars/", views.AggBarListView.as_view(), name="bar-list"),
    path("collection-runs/", views.CollectionRunListView.as_view(), name="collection-run-list"),
    path("integrity/summary/", views.IntegritySummaryView.as_view(), name="integrity-summary"),
    path("integrity/issues/", views.IntegrityIssueListView.as_view(), name="integrity-issue-list"),
    path("cron/collect/", views.CronCollectView.as_view(), name="cron-collect"),
    path("cron/minutes/", views.CronMinutesView.as_view(), name="cron-minutes"),
    path("reprocess/", views.ReprocessView.as_view(), name="reprocess"),
    path("reprocess/<int:pk>/", views.ReprocessDetailView.as_view(), name="reprocess-detail"),
]
