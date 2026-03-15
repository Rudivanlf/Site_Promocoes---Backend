from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .services import buscar_produtos
from app.features.email.email import EmailFeature
from django.conf import settings


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

       # envia notificação por e-mail para usuários autenticados
        try:
            user = getattr(request, 'user', None)
            if getattr(user, 'is_authenticated', False) and getattr(user, 'email', None):
                # notificação de busca
                EmailFeature.enviar_notificacao_busca(usuario=user, query=query, total_resultados=len(produtos))

                # se o cliente pediu detalhes, notifica que abriu o produto (usa primeiro resultado como exemplo)
                if detalhes and produtos:
                    primeiro = produtos[0]
                    produto_nome = primeiro.get('title') or primeiro.get('name') or primeiro.get('titulo') or primeiro.get('name', '')
                    produto_link = primeiro.get('link') or primeiro.get('permalink') or ''
                    EmailFeature.enviar_acesso_produto(usuario=user, produto_nome=produto_nome, produto_link=produto_link)
        except Exception:
            # não queremos que falha no envio de e-mail quebre a resposta da busca
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
