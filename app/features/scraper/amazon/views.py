from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .services import buscar_produtos
from app.features.email.email import EmailFeature


class BuscarProdutosAmazonView(APIView):
    def get(self, request):
        query = request.query_params.get("q", "").strip()

        if not query:
            return Response(
                {"erro": "O parâmetro 'q' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pagina = int(request.query_params.get("pagina", 1))
            if pagina < 1:
                pagina = 1
        except ValueError:
            pagina = 1

        detalhes = request.query_params.get("detalhes", "false").lower() in (
            "1",
            "true",
            "y",
            "yes",
        )

        try:
            produtos = buscar_produtos(query=query, pagina=pagina, detalhes=detalhes)
        except ConnectionError as exc:
            return Response(
                {
                    "erro": str(exc),
                    "source_unavailable": True,
                    "source": "amazon",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            user = getattr(request, "user", None)
            if getattr(user, "is_authenticated", False) and getattr(user, "email", None):
                EmailFeature.enviar_notificacao_busca(
                    usuario=user,
                    query=query,
                    total_resultados=len(produtos),
                )

                if detalhes and produtos:
                    primeiro = produtos[0]
                    produto_nome = (
                        primeiro.get("title")
                        or primeiro.get("name")
                        or primeiro.get("titulo")
                        or ""
                    )
                    produto_link = primeiro.get("link") or primeiro.get("permalink") or ""
                    EmailFeature.enviar_acesso_produto(
                        usuario=user,
                        produto_nome=produto_nome,
                        produto_link=produto_link,
                    )
        except Exception:
            pass

        return Response(
            {
                "query": query,
                "pagina": pagina,
                "total": len(produtos),
                "produtos": produtos,
            },
            status=status.HTTP_200_OK,
        )
