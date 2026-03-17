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
    """
    print("DEBUG CRON: Iniciando tarefa de busca de promoções...", flush=True)

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

        if not produto_link:
            print(f"DEBUG CRON: Favorito {doc.get('_id')} ignorado por falta de link.", flush=True)
            continue

        print(f"DEBUG CRON: Processando favorito: {produto_link}", flush=True)
        
        # usa o scraper para fazer a consulta no MercadoLivre usando o link direto
        try:
            resultados: List[Dict] = buscar_produtos_basic(produto_link)
        except Exception as exc:
            print(f"DEBUG CRON: Erro no scraper para {produto_link}: {exc}", flush=True)
            continue

        if not resultados:
            print(f"DEBUG CRON: Nenhum preço encontrado para {produto_link}", flush=True)
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
        
        # 1. Determina o destinatário ANTES de testar a queda de preço
        destinatario_email = doc.get("usuario_email")
        destinatario_nome = destinatario_email.split('@')[0] if destinatario_email else "Cliente"

        # LOGS DE DEBUG FORÇADOS
        print(f"DEBUG CRON: Produto '{produto_nome}' | No Banco: {preco_atual} | No ML: {novo_valor}", flush=True)

        # Se o preço caiu, atualiza e envia e-mail
        if novo_valor < preco_atual:
            if not destinatario_email:
                print(f"DEBUG CRON: QUEDA DETECTADA, mas favorito sem e-mail!", flush=True)
                continue

            print(f"DEBUG CRON: QUEDA DETECTADA! Enviando e-mail para {destinatario_email}", flush=True)
            atualizados += 1
            
            # 1. Atualiza no MongoDB
            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"produto_preco": novo_valor}},
            )
            
            try:
                EmailFeature.enviar_promocao(
                    usuario_email=destinatario_email,
                    usuario_nome=destinatario_nome,
                    titulo_promocao=f"O preço de '{produto_nome}' caiu!",
                    link_promocao=produto_link,
                    empresa_nome="Mercado Livre"
                )
                print(f"DEBUG CRON: E-mail enviado com sucesso para {destinatario_email}", flush=True)
            except Exception as e:
                print(f"DEBUG CRON: ERRO ao enviar e-mail: {e}", flush=True)

            logger.info(
                "produto %s teve preço reduzido de %s para %s",
                produto_nome,
                preco_atual,
                novo_valor,
            )

            logger.info(
                "produto %s teve preço reduzido de %s para %s",
                produto_nome,
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
