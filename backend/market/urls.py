from django.urls import path

from market import views

urlpatterns = [
    path("assets/", views.AssetListView.as_view(), name="asset-list"),
    path("candles/", views.CandleListView.as_view(), name="candle-list"),
    path("collection-runs/", views.CollectionRunListView.as_view(), name="collection-run-list"),
    path("integrity/summary/", views.IntegritySummaryView.as_view(), name="integrity-summary"),
    path("integrity/issues/", views.IntegrityIssueListView.as_view(), name="integrity-issue-list"),
]
