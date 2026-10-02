from django.urls import path

from backtest import views

urlpatterns = [
    path("backtests/", views.BacktestCreateView.as_view(), name="backtest-create"),
    path("backtests/<int:pk>/", views.BacktestDetailView.as_view(), name="backtest-detail"),
]
