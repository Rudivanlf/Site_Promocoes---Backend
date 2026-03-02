from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/scraper/mercadolivre/", include("app.features.scraper.mercadolivre.urls")),
]
