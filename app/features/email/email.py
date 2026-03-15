from django.conf import settings
from .models import AcessoUsuario
from config.gmail_oauth import send_email_oauth


class EmailFeature:
    @staticmethod
    def enviar_codigo(usuario, tipo='login', ip_address=None):
        AcessoUsuario.objects.filter(
            usuario=usuario,
            tipo=tipo,
            verificado=False
        ).update(verificado=True)

        codigo_gerado = AcessoUsuario.gerar_codigo()

        codigo_object = AcessoUsuario.objects.create(
            usuario=usuario,
            codigo=codigo_gerado,
            tipo=tipo,
            ip_address=ip_address,
        )

        assunto = 'Seu Código de Verificação'
        nome_display = usuario.first_name or usuario.username or 'Nome'
        mensagem = f'''
    Olá {nome_display}

    Para sua segurança, use o código de verificação abaixo para confirmar o seu e-mail:

    Código: {codigo_gerado}

    Esse código irá expirar em 10 minutos.

    Caso você não tenha feito essa solicitação, por favor ignore este e-mail.

    Abraços da equipe Easely.
    '''

        try:
            send_email_oauth(
                to_email=usuario.email,
                subject=assunto,
                message_text=mensagem
            )
            return codigo_object

        except Exception as e:
            print(f'Erro ao enviar email: {e}')

        return codigo_object

    @staticmethod
    def enviar_promocao(usuario, titulo_promocao, link_promocao, empresa_nome=None):
        nome_display = getattr(usuario, 'first_name', None) or getattr(usuario, 'username', None) or 'Cliente'
        empresa_text = f' - {empresa_nome}' if empresa_nome else ''
        assunto = f'Promoção: {titulo_promocao}{empresa_text}'
        mensagem = f'''
Olá {nome_display},

Temos uma nova promoção para você: {titulo_promocao}

Aproveite agora:
{link_promocao}

Se preferir, acesse nosso site para ver mais ofertas.

---
Atenciosamente,
Equipe
'''

        try:
            send_email_oauth(
                to_email=usuario.email,
                subject=assunto,
                message_text=mensagem
            )
        except Exception as e:
            print(f'Erro ao enviar email de promoção: {e}')