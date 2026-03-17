import logging
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict

from ..favoritos.services import FavoritoService
from ..scraper.mercadolivre.services import buscar_produtos
from ..email.email import EmailFeature
from ..usuarios.services import UsuarioService

logger = logging.getLogger(__name__)

# Copiado de services.py para garantir consistência
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def _extrair_preco_direto(link: str) -> float | None:
    """Extrai o preço diretamente da página do produto (mesma lógica do services.py)"""
    try:
        rp = requests.get(link, headers=HEADERS, timeout=15)
        rp.raise_for_status()
        soup = BeautifulSoup(rp.text, "lxml")
        
        selectors = [
            ".ui-pdp-price__second-line .andes-money-amount__fraction",
            ".ui-pdp-price__price .andes-money-amount__fraction",
            ".price-tag-fraction",
            ".andes-money-amount__fraction",
        ]
        cents_selectors = [
            ".ui-pdp-price__second-line .andes-money-amount__cents",
            ".andes-money-amount__cents",
        ]

        for sel in selectors:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                frac = el.get_text(strip=True).replace(".", "").replace(",", "")
                cents = "00"
                for sc in cents_selectors:
                    ec = soup.select_one(sc)
                    if ec and ec.get_text(strip=True):
                        cents = ec.get_text(strip=True).zfill(2)
                        break
                return float(f"{frac}.{cents}")

        # Fallback Regex
        full_text = soup.get_text(" ", strip=True)
        m = re.search(r"R\$\s*([\d\.,]+)", full_text)
        if m:
            clean_price = m.group(1).replace(".", "").replace(",", ".")
            return float(clean_price)
            
    except Exception as e:
        print(f"DEBUG CRON: Erro ao extrair preço de {link}: {e}", flush=True)
    return None

def buscar_promocoes_para_favoritos() -> None:
    """Percorre todos os favoritos cadastrados e faz uma nova busca usando o
    scraper do MercadoLivre.
    """
    print("DEBUG CRON: Iniciando tarefa de busca de promoções...", flush=True)

    fav_service = FavoritoService()
    # obtém todos os documentos da coleção
    cursor = fav_service.collection.find({})

    total = 0
    atualizados = 0

    for doc in cursor:
        total += 1
        produto_nome = doc.get("produto_nome")
        produto_link = doc.get("produto_link")

        if not produto_link:
            continue

        print(f"DEBUG CRON: Processando favorito: {produto_link}", flush=True)
        
        # 1. Tenta extrair o preço diretamente do link (mais preciso)
        novo_valor = _extrair_preco_direto(produto_link)
        
        # 2. Se falhar, tenta a busca por nome como fallback
        if novo_valor is None:
            print(f"DEBUG CRON: Link direto falhou, tentando busca por nome para '{produto_nome}'", flush=True)
            try:
                resultados = buscar_produtos(produto_nome, detalhes=True)
                if resultados:
                    # Tenta encontrar o produto exato pelo link nos resultados, ou pega o primeiro
                    match = next((p for p in resultados if p.get("link") == produto_link), resultados[0])
                    preco_str = match.get("preco")
                    if preco_str:
                        novo_valor = float(preco_str)
            except Exception as exc:
                print(f"DEBUG CRON: Erro no fallback para {produto_nome}: {exc}", flush=True)

        if novo_valor is None:
            print(f"DEBUG CRON: Nenhum preço encontrado para {produto_link}", flush=True)
            continue

        preco_atual = doc.get("produto_preco", 0.0)
        
        # LOGS DE DEBUG
        print(f"DEBUG CRON: Produto '{produto_nome}' | No Banco: {preco_atual} | No ML: {novo_valor}", flush=True)

        # Se o preço caiu (com margem de segurança de 0.01)
        if novo_valor < (preco_atual - 0.01):
            destinatario_email = doc.get("usuario_email")
            if not destinatario_email:
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
                    usuario_nome=destinatario_email.split('@')[0],
                    titulo_promocao=f"O preço de '{produto_nome}' caiu!",
                    link_promocao=produto_link,
                    empresa_nome="Mercado Livre"
                )
                print(f"DEBUG CRON: E-mail enviado com sucesso.", flush=True)
            except Exception as e:
                print(f"DEBUG CRON: ERRO ao enviar e-mail: {e}", flush=True)

    print(f"DEBUG CRON: Tarefa finalizada. {total} verificados, {atualizados} atualizados.", flush=True)
    return total, atualizados



# quando quiser integrar com um "agente de IA" real, mova essa lógica para
# um cliente separado e substitua a chamada a buscar_produtos_basic pela
# invocação do modelo/serviço apropriado.
