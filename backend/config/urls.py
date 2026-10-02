from django.contrib import admin
from django.urls import include, path

from config import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", views.health, name="health"),
    path("api/", include("market.urls")),
]
