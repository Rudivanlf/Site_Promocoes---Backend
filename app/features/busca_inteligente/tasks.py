import logging
from typing import List, Dict
import logging

from ..favoritos.services import FavoritoService
from ..scraper.mercadolivre.services import buscar_produtos_basic
from ..email.email import EmailFeature
from ..usuarios.services import UsuarioService

logger = logging.getLogger(__name__)

def buscar_promocoes_para_favoritos() -> None:
    """Percorre todos os favoritos cadastrados e faz uma nova busca usando o
    scraper do MercadoLivre.

    O resultado desta busca pode ser usado para atualizar preços, guardar
    histórico ou disparar alertas.
    """

    fav_service = FavoritoService()
    user_service = UsuarioService()
    # obtém todos os documentos da coleção (sem mascarar nada)
    cursor = fav_service.collection.find({})

    total = 0
    atualizados = 0

    for doc in cursor:
        total += 1
        produto_nome = doc.get("produto_nome")
        produto_link = doc.get("produto_link")
        usuario_id = doc.get("usuario_id")
        
        consulta: str = produto_nome or produto_link
        if not consulta:
            continue

        logger.debug("processando favorito %s", consulta)
        # usa o scraper para fazer a consulta no MercadoLivre
        try:
            resultados: List[Dict] = buscar_produtos_basic(consulta)
        except Exception as exc:
            logger.error("erro na busca do produto %s: %s", consulta, exc)
            continue

        if not resultados:
            continue

        primeiro = resultados[0]
        novo_preco = primeiro.get("preco")
        if novo_preco is None:
            continue

        try:
            novo_valor = float(novo_preco.replace(".", "").replace(",", "."))
        except ValueError:
            continue

        preco_atual = doc.get("produto_preco", 0.0)
        
        # Se o preço caiu, atualiza e envia e-mail
        if novo_valor < preco_atual:
            atualizados += 1
            
            # 1. Atualiza no MongoDB
            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"produto_preco": novo_valor}},
            )
            
            # 2. Busca dados do usuário para enviar o e-mail
            if usuario_id:
                user_data = user_service.buscar_por_id(usuario_id)
                if user_data and user_data.get("email"):
                    try:
                        EmailFeature.enviar_promocao(
                            usuario_email=user_data["email"],
                            usuario_nome=user_data.get("nome", "Cliente"),
                            titulo_promocao=f"O preço de '{produto_nome}' caiu!",
                            link_promocao=produto_link,
                            empresa_nome="Mercado Livre"
                        )
                        logger.info("E-mail de promoção enviado para %s", user_data["email"])
                    except Exception as e:
                        logger.error("Falha ao enviar e-mail de alerta: %s", e)

            logger.info(
                "produto %s teve preço reduzido de %s para %s",
                consulta,
                preco_atual,
                novo_valor,
            )

    logger.info(
        "busca concluída: %d favoritos verificados, %d atualizados",
        total,
        atualizados,
    )
    # retornar uma tupla para permitir relatórios na chamada, se desejado
    return total, atualizados


# quando quiser integrar com um "agente de IA" real, mova essa lógica para
# um cliente separado e substitua a chamada a buscar_produtos_basic pela
# invocação do modelo/serviço apropriado.
