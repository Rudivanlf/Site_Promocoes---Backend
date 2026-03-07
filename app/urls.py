from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/usuarios/", include("app.features.usuarios.urls")),
    path("api/favoritos/", include("app.features.favoritos.urls")),
    path("api/scraper/mercadolivre/", include("app.features.scraper.mercadolivre.urls")),
]
