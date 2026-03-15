# favoritos/views.py

"""
Views para o módulo de favoritos.
Todos os endpoints exigem autenticação JWT via header Authorization: Bearer {token}.
"""

from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .services import FavoritoService
from ..utils import parse_request_body, autenticar_jwt


@method_decorator(csrf_exempt, name="dispatch")
class FavoritoView(View):
    """
    GET    /api/favoritos/ — Lista favoritos do usuário autenticado
    POST   /api/favoritos/ — Adiciona um produto aos favoritos
    DELETE /api/favoritos/ — Remove um produto dos favoritos pelo link
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = FavoritoService()

    # ------------------------------------------------------------------
    # GET — listar favoritos
    # ------------------------------------------------------------------

    def get(self, request):
        payload, erro = autenticar_jwt(request)
        if erro:
            return erro

        try:
            favoritos = self.service.listar_favoritos(payload["id"])
            return JsonResponse(favoritos, safe=False)
        except Exception as e:
            return JsonResponse(
                {"error": f"Erro ao buscar favoritos: {str(e)}"}, status=500
            )

    # ------------------------------------------------------------------
    # POST — adicionar favorito
    # ------------------------------------------------------------------

    def post(self, request):
        payload, erro = autenticar_jwt(request)
        if erro:
            return erro

        data, parse_error = parse_request_body(request)
        if parse_error:
            return JsonResponse({"error": parse_error}, status=400)

        # Validações obrigatórias
        if not data.get("link"):
            return JsonResponse({"error": "Campo 'link' é obrigatório"}, status=400)
        if not data.get("name"):
            return JsonResponse({"error": "Campo 'name' é obrigatório"}, status=400)
        if data.get("price") is None:
            return JsonResponse({"error": "Campo 'price' é obrigatório"}, status=400)
        try:
            float(data["price"])
        except (ValueError, TypeError):
            return JsonResponse({"error": "Campo 'price' deve ser um número"}, status=400)

        try:
            favorito = self.service.adicionar(
                usuario_id=payload["id"],
                usuario_email=payload.get("email", ""),
                data=data,
            )
            return JsonResponse(favorito, status=201)
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)
        except Exception as e:
            return JsonResponse(
                {"error": f"Erro ao adicionar favorito: {str(e)}"}, status=500
            )

    # ------------------------------------------------------------------
    # DELETE — remover favorito
    # ------------------------------------------------------------------

    def delete(self, request):
        payload, erro = autenticar_jwt(request)
        if erro:
            return erro

        data, parse_error = parse_request_body(request)
        if parse_error:
            return JsonResponse({"error": parse_error}, status=400)

        link = data.get("link")
        if not link:
            return JsonResponse({"error": "Campo 'link' é obrigatório"}, status=400)

        try:
            removido = self.service.remover(
                usuario_id=payload["id"],
                produto_link=link,
            )
            if not removido:
                return JsonResponse({"error": "Favorito não encontrado"}, status=404)
            return JsonResponse({}, status=204)
        except Exception as e:
            return JsonResponse(
                {"error": f"Erro ao remover favorito: {str(e)}"}, status=500
            )
