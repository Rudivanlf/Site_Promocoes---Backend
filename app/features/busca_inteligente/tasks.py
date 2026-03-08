import logging
from typing import List, Dict

from ..favoritos.services import FavoritoService
from ..scraper.mercadolivre.services import buscar_produtos_basic


logger = logging.getLogger(__name__)


def buscar_promocoes_para_favoritos() -> None:
    """Percorre todos os favoritos cadastrados e faz uma nova busca usando o
    scraper do MercadoLivre.

    O resultado desta busca pode ser usado para atualizar preços, guardar
    histórico ou disparar alertas. Se/quando você quiser trocar o scraper por
    um "agente de IA" basta alterar a chamada em vez de usar
    `buscar_produtos_basic`.
    """

    fav_service = FavoritoService()
    # obtém todos os documentos da coleção (sem mascarar nada)
    cursor = fav_service.collection.find({})

    total = 0
    atualizados = 0

    for doc in cursor:
        total += 1
        produto_nome = doc.get("produto_nome")
        produto_link = doc.get("produto_link")
        consulta: str = produto_nome or produto_link
        if not consulta:
            continue

        logger.debug("processando favorito %s", consulta)
        # usa o scraper para fazer a consulta no MercadoLivre
        try:
            resultados: List[Dict] = buscar_produtos_basic(consulta)
        except Exception as exc:  # pragma: no cover
            logger.error("erro na busca do produto %s: %s", consulta, exc)
            continue

        if not resultados:
            continue

        # como exemplo simples, consideramos o primeiro item como o mais
        # relevante e comparamos o preço
        primeiro = resultados[0]
        novo_preco = primeiro.get("preco")
        if novo_preco is None:
            continue

        try:
            novo_valor = float(novo_preco.replace(".", "").replace(",", "."))
        except ValueError:
            continue

        preco_atual = doc.get("produto_preco", 0.0)
        if novo_valor < preco_atual:
            atualizados += 1
            # atualiza o favorito para o novo preço; aqui você poderia criar
            # um registro no histórico ou notificar o usuário por e‑mail,
            # websocket, etc.
            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"produto_preco": novo_valor}},
            )
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
