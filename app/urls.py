from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse


def _home(request):
    return HttpResponse("<h1>Site de promoções</h1><p>Tudo funcionando!</p>")


urlpatterns = [
    path("", _home, name="home"),
    path("admin/", admin.site.urls),

    # usuários (inclui login, registro, CRUD etc.)
    path("api/usuarios/", include("app.features.usuarios.urls")),

    # alias para compatibilidade com frontends que esperam /api/auth/
    path("api/auth/", include("app.features.usuarios.urls")),

    path("api/favoritos/", include("app.features.favoritos.urls")),
    path("api/scraper/mercadolivre/", include("app.features.scraper.mercadolivre.urls")),
]
