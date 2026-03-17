import threading
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse, JsonResponse
from app.features.busca_inteligente.tasks import buscar_promocoes_para_favoritos


def _home(request):
    return HttpResponse("<h1>Site de promoções</h1><p>Tudo funcionando!</p>")


def cron_verificar_precos(request):
    """
    Gatilho para o GitHub Actions. 
    Inicia a busca em uma thread separada para responder rápido ao cliente.
    """
    threading.Thread(target=buscar_promocoes_para_favoritos).start()
    return JsonResponse({
        "status": "iniciado",
        "mensagem": "Busca de promoções iniciada em segundo plano."
    })


urlpatterns = [
    path("", _home, name="home"),
    path("admin/", admin.site.urls),
    path("api/cron/verificar-precos/", cron_verificar_precos),

    # usuários 
    path("api/usuarios/", include("app.features.usuarios.urls")),

    # compatibilidade com frontends que esperam /api/auth/
    path("api/auth/", include("app.features.usuarios.urls")),

    path("api/favoritos/", include("app.features.favoritos.urls")),
    path("api/scraper/mercadolivre/", include("app.features.scraper.mercadolivre.urls")),
]
