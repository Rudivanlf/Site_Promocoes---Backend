from django.conf import settings
from config.gmail_oauth import send_email_oauth
from ..mongo import db
import random
import string
from datetime import datetime, timedelta


class EmailFeature:
    @staticmethod
    def gerar_codigo(tamanho=6):
        return ''.join(random.choices(string.digits, k=tamanho))

    def enviar_codigo(usuario_email, usuario_nome=None, tipo='login', ip_address=None):
        """
        Gera e envia um código de verificação para o e-mail informado.

        O projeto usa MongoDB para usuários; aqui guardamos o código na
        coleção `acessos` do Mongo em vez de usar modelos Django.
        """
        # marca códigos anteriores como verificados (inativos)
        db.acessos.update_many(
            {"email": usuario_email, "tipo": tipo, "verificado": False},
            {"$set": {"verificado": True}},
        )

        codigo_gerado = EmailFeature.gerar_codigo()

        acesso_doc = {
            "email": usuario_email,
            "codigo": codigo_gerado,
            "tipo": tipo,
            "verificado": False,
            "ip_address": ip_address,
            "criado_em": datetime.now(),
            "expira_em": datetime.now() + timedelta(minutes=10),
        }

        db.acessos.insert_one(acesso_doc)

        assunto = 'Seu Código de Verificação'
        nome_display = usuario_nome or usuario_email.split('@')[0]
        mensagem = f'''
Olá {nome_display}

Para sua segurança, use o código de verificação abaixo para confirmar o seu e-mail:

Código: {codigo_gerado}

Esse código irá expirar em 10 minutos.

Caso você não tenha feito essa solicitação, por favor ignore este e-mail.

'''

        try:
            send_email_oauth(
                to_email=usuario_email,
                subject=assunto,
                message_text=mensagem,
            )
            return acesso_doc
        except Exception as e:
            print(f'Erro ao enviar email: {e}')
            return acesso_doc

    @staticmethod
    def enviar_promocao(usuario=None, titulo_promocao=None, link_promocao=None, empresa_nome=None, usuario_email=None, usuario_nome=None):
        """
        Envia um e-mail de promoção.

        Aceita tanto um objeto `usuario` com atributos `email`/`first_name`/`username`,
        quanto os parâmetros `usuario_email` e `usuario_nome` (usado pelas tarefas).
        """
        # determina email e nome do destinatário
        to_email = usuario_email
        name = usuario_nome

        if to_email is None and usuario is not None:
            # chamado com objeto user
            to_email = getattr(usuario, 'email', None) if not isinstance(usuario, str) else usuario
            if name is None:
                name = getattr(usuario, 'first_name', None) or getattr(usuario, 'username', None) if not isinstance(usuario, str) else None

        if not to_email:
            return

        name = name or 'Cliente'
        empresa_text = f' - {empresa_nome}' if empresa_nome else ''
        assunto = f'Promoção: {titulo_promocao}{empresa_text}'
        mensagem = f'''
Olá {name},

Temos uma nova promoção para você: {titulo_promocao}

Aproveite agora:
{link_promocao}

Se preferir, acesse nosso site para ver mais ofertas.

'''

        try:
            send_email_oauth(
                to_email=to_email,
                subject=assunto,
                message_text=mensagem
            )
        except Exception as e:
            print(f'Erro ao enviar email de promoção: {e}')

    @staticmethod
    def enviar_notificacao_busca(usuario=None, query=None, total_resultados: int | None = None, usuario_email=None, usuario_nome=None):
        """Envia um e-mail curto informando que a busca foi realizada com sucesso."""
        to_email = usuario_email
        name = usuario_nome
        if to_email is None and usuario is not None:
            to_email = getattr(usuario, 'email', None) if not isinstance(usuario, str) else usuario
            if name is None:
                name = getattr(usuario, 'first_name', None) or getattr(usuario, 'username', None) if not isinstance(usuario, str) else None

        if not to_email:
            return

        name = name or 'Cliente'
        assunto = f'Busca concluída: {query}' if query else 'Busca concluída'
        resultados_text = f'Encontramos {total_resultados} resultados.' if total_resultados is not None else ''
        mensagem = f'''
Olá {name},

Sua busca por "{query}" foi concluída com sucesso.
{resultados_text}

Obrigado por usar nosso serviço.

'''
        try:
            send_email_oauth(to_email=to_email, subject=assunto, message_text=mensagem)
        except Exception as e:
            print(f'Erro ao enviar notificação de busca: {e}')

    @staticmethod
    def enviar_confirmacao_favorito(usuario=None, produto_nome=None, produto_link=None, usuario_email=None, usuario_nome=None):
        """Novo: Envia um e-mail confirmando que o produto foi favoritado."""
        to_email = usuario_email
        name = usuario_nome
        if to_email is None and usuario is not None:
            to_email = getattr(usuario, 'email', None) if not isinstance(usuario, str) else usuario
            if name is None:
                name = getattr(usuario, 'first_name', None) or getattr(usuario, 'username', None) if not isinstance(usuario, str) else None

        if not to_email:
            return

        name = name or 'Cliente'
        assunto = f'Novo favorito: {produto_nome}'
        mensagem = f'''
Olá {name},

Você acabou de adicionar um novo produto aos seus favoritos: {produto_nome}

Você receberá um e-mail se este produto tiver uma queda de preço!

Acompanhe por aqui:
{produto_link}

Obrigado por usar nosso serviço.

'''
        try:
            send_email_oauth(to_email=to_email, subject=assunto, message_text=mensagem)
        except Exception as e:
            print(f'Erro ao enviar confirmação de favorito: {e}')

    @staticmethod
    def enviar_acesso_produto(usuario=None, produto_nome=None, produto_link=None, usuario_email=None, usuario_nome=None):
        """Envia um e-mail quando o usuário acessa/abre os detalhes de um produto."""
        to_email = usuario_email
        name = usuario_nome
        if to_email is None and usuario is not None:
            to_email = getattr(usuario, 'email', None) if not isinstance(usuario, str) else usuario
            if name is None:
                name = getattr(usuario, 'first_name', None) or getattr(usuario, 'username', None) if not isinstance(usuario, str) else None

        if not to_email:
            return

        name = name or 'Cliente'
        assunto = f'Você acessou: {produto_nome}' if produto_nome else 'Acesso ao produto'
        mensagem = f'''
Olá {name},

Notamos que você acessou o produto: {produto_nome}

Link: {produto_link}

Se precisar, salve nos favoritos para acompanhar variações de preço.

'''
        try:
            send_email_oauth(to_email=to_email, subject=assunto, message_text=mensagem)
        except Exception as e:
            print(f'Erro ao enviar notificação de acesso a produto: {e}')
