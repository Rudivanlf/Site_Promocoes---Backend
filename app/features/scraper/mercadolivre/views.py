from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .services import buscar_produtos


class BuscarProdutosMercadoLivreView(APIView):

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

        detalhes = request.query_params.get("detalhes", "false").lower() in ("1", "true", "y", "yes")

        try:
            produtos = buscar_produtos(query=query, pagina=pagina, detalhes=detalhes)
        except ConnectionError as exc:
            return Response(
                {"erro": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "query": query,
                "pagina": pagina,
                "total": len(produtos),
                "produtos": produtos,
            },
            status=status.HTTP_200_OK,
        )
