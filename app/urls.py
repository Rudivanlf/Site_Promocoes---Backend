import os
import threading
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse, JsonResponse
from app.features.busca_inteligente.tasks import buscar_promocoes_para_favoritos


_cron_state_lock = threading.Lock()
_cron_running = False


def _home(request):
    return HttpResponse("<h1>Site de promoções</h1><p>Tudo funcionando!</p>")


def _run_cron_job() -> None:
    global _cron_running
    try:
        buscar_promocoes_para_favoritos()
    finally:
        with _cron_state_lock:
            _cron_running = False


def cron_verificar_precos(request):
    """
    Gatilho para o GitHub Actions. 
    Inicia a busca em uma thread separada para responder rápido ao cliente.
    """
    global _cron_running

    token_recebido = request.META.get("HTTP_X_CRON_TOKEN")
    token_esperado = os.environ.get("CRON_TOKEN")

    if not token_esperado or token_recebido != token_esperado:
        return JsonResponse({"error": "Acesso negado. Token inválido."}, status=403)

    # Verifica se já existe uma tarefa a correr
    with _cron_state_lock:
        if _cron_running:
            return JsonResponse({
                "status": "ignorado",
                "mensagem": "Já existe uma verificação de promoções em andamento."
            })
        _cron_running = True

    # Chama o _run_cron_job em vez de buscar_promocoes_para_favoritos
    threading.Thread(target=_run_cron_job).start()
    
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
    path("api/scraper/", include("app.features.historico_precos.urls")),
]
