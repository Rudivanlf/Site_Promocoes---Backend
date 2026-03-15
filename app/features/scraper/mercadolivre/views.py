from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import jwt

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

        # envia notificação por e-mail para usuários autenticados via JWT
        try:
            auth_header = request.headers.get('Authorization')
            user_email = None
            user_name = None

            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                try:
                    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
                    user_email = payload.get('email')
                    user_name = payload.get('first_name') or payload.get('username') or user_email.split('@')[0]
                    print(f"DEBUG: Usuário identificado via JWT: {user_email}")
                except Exception as e:
                    print(f"DEBUG: Falha ao decodificar token JWT: {e}")

            if user_email:
                print(f"DEBUG: Tentando enviar e-mail de busca para {user_email}...")
                EmailFeature.enviar_notificacao_busca(usuario_email=user_email, usuario_nome=user_name, query=query, total_resultados=len(produtos))

                if detalhes and produtos:
                    primeiro = produtos[0]
                    produto_nome = primeiro.get('title') or primeiro.get('name') or primeiro.get('titulo') or primeiro.get('name', '')
                    produto_link = primeiro.get('link') or primeiro.get('permalink') or ''
                    EmailFeature.enviar_acesso_produto(usuario_email=user_email, usuario_nome=user_name, produto_nome=produto_nome, produto_link=produto_link)
        except Exception as e:
            print(f"ERRO ao processar e-mail na busca: {e}")
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
