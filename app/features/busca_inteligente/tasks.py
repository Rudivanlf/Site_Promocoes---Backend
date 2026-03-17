import logging
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict

from ..favoritos.services import FavoritoService
from ..scraper.mercadolivre.services import buscar_produtos, _extrair_preco_from_text, HEADERS
from ..email.email import EmailFeature
from ..usuarios.services import UsuarioService

logger = logging.getLogger(__name__)

def extrair_preco_pelo_link_direto(link: str) -> float | None:
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
                frac = el.get_text(strip=True)
                cents = None
                for sc in cents_selectors:
                    ec = soup.select_one(sc)
                    if ec and ec.get_text(strip=True):
                        cents = ec.get_text(strip=True)
                        break
                
                texto = frac
                if cents:
                    texto = f"{texto},{cents}"
                
                norm = _extrair_preco_from_text(texto)
                if norm:
                    return float(norm)

        # Fallback Regex 
        full = soup.get_text(" ", strip=True)
        m = re.search(r"R\$\s*[\d\.,]+\s*(?:,\s*[\d]{1,2})?", full)
        if m:
            norm = _extrair_preco_from_text(m.group(0))
            if norm:
                return float(norm)

    except Exception as e:
        print(f"DEBUG CRON: Erro ao acessar link direto {link}: {e}", flush=True)
    return None

def buscar_promocoes_para_favoritos() -> None:
    """Percorre os favoritos e usa a logica de extracao direta do services.py"""
    print("DEBUG CRON: Iniciando tarefa de busca de promo��es...", flush=True)

    fav_service = FavoritoService()
    cursor = fav_service.collection.find({})

    total = 0
    atualizados = 0

    for doc in cursor:
        total += 1
        produto_nome = doc.get("produto_nome")
        produto_link = doc.get("produto_link")
        preco_atual = doc.get("produto_preco", 0.0)

        if not produto_link:
            continue

        print(f"DEBUG CRON: Processando: {produto_nome[:30]}...", flush=True)
        
        novo_valor = extrair_preco_pelo_link_direto(produto_link)

        if novo_valor is None:
            print(f"DEBUG CRON: Preco nao encontrado para {produto_link}", flush=True)
            continue

        print(f"DEBUG CRON: Precos -> Banco: {preco_atual} | ML: {novo_valor}", flush=True)

        if novo_valor < (preco_atual - 0.01):
            destinatario_email = doc.get("usuario_email")
            if not destinatario_email:
                continue

            print(f"DEBUG CRON: QUEDA DETECTADA! Enviando e-mail...", flush=True)
            atualizados += 1
            
            # Atualiza no MongoDB
            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"produto_preco": novo_valor}},
            )
            
            try:
                EmailFeature.enviar_promocao(
                    usuario_email=destinatario_email,
                    usuario_nome=destinatario_email.split("@")[0],
                    titulo_promocao=f"O preco de {produto_nome} caiu!",
                    link_promocao=produto_link,
                    empresa_nome="Mercado Livre"
                )
            except Exception as e:
                print(f"DEBUG CRON: ERRO e-mail: {e}", flush=True)

    print(f"DEBUG CRON: Finalizado. {total} lidos, {atualizados} e-mails enviados.", flush=True)
    return total, atualizados
