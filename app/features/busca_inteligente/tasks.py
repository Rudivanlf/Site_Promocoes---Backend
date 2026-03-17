import logging
import re
import requests
import traceback
from bs4 import BeautifulSoup
from typing import List, Dict

from ..favoritos.services import FavoritoService
from ..scraper.mercadolivre.services import _extrair_preco_from_text, HEADERS
from ..email.email import EmailFeature
from ..usuarios.services import UsuarioService

logger = logging.getLogger(__name__)

def extrair_preco_pelo_link_direto(link: str) -> float | None:
    try:
        # User-Agent mobile costuma ser menos bloqueado em data centers
        # e o Mercado Livre serve um HTML mais enxuto (fácil de ler)
        HEADERS_PROD = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }

        res = requests.get(link, headers=HEADERS_PROD, timeout=15, allow_redirects=True)
        
        # LOG OBRIGATÓRIO PARA O RENDER - Identificar se o código novo rodou
        print(f"DEBUG CRON: [RENDER] Link: {link[:40]} | HTTP Status: {res.status_code}", flush=True)

        if res.status_code != 200:
            if res.status_code == 403:
                print("DEBUG CRON: [RENDER] BLOQUEIO 403 (Forbidden) detectado.", flush=True)
            return None

        if "captcha" in res.text.lower():
            print(f"DEBUG CRON: [RENDER] CAPTCHA detectado no link {link[:40]}", flush=True)
            return None

        soup = BeautifulSoup(res.text, "lxml")
        
        # Estratégia 1: JSON-LD (A mais robusta)
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if '"offers"' in script.text and '"price"' in script.text:
                price_match = re.search(r'"price":\s*"?([\d\.]+)"?', script.text)
                if price_match:
                    return float(price_match.group(1))

        # Estratégia 2: Seletores de Detalhes (PDP) revisados
        selectors = [
            ".ui-pdp-price__second-line .andes-money-amount__fraction",
            ".ui-pdp-container__row--price .andes-money-amount__fraction",
            ".ui-pdp-price__price .andes-money-amount__fraction",
            ".ui-render-price-part .andes-money-amount__fraction",
            "meta[itemprop='price']",
            "meta[property='product:price:amount']"
        ]
        
        for sel in selectors:
            el = soup.select_one(sel)
            if not el: continue
            
            if el.name == "meta":
                val = el.get("content")
                if val: 
                    return float(val)
            else:
                txt = el.get_text(strip=True)
                # Tenta pegar centavos no mesmo container
                parent = el.find_parent(class_="andes-money-amount")
                cents = parent.select_one(".andes-money-amount__cents") if parent else None
                if cents:
                    txt = f"{txt},{cents.get_text(strip=True)}"
                
                norm = _extrair_preco_from_text(txt)
                if norm:
                    return float(norm)

        # 3. Fallback Regex no texto visivel 
        full = soup.get_text(" ", strip=True)
        m = re.search(r"R\$\s*([\d\.,]+)", full)
        if m:
            norm = _extrair_preco_from_text(m.group(0))
            if norm:
                return float(norm)

    except Exception as e:
        print(f"DEBUG CRON: Erro ao acessar link direto {link}: {e}", flush=True)
    return None

def buscar_promocoes_para_favoritos() -> None:
    """Percorre os favoritos e usa a logica de extracao direta do services.py"""
    print("DEBUG CRON: Iniciando tarefa de busca de promoções...", flush=True)

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
        
        # Tenta extrair o preco usando a logica
        novo_valor = extrair_preco_pelo_link_direto(produto_link)

        if novo_valor is None:
            print(f"DEBUG CRON: Preco nao encontrado para {produto_link}", flush=True)
            continue

        print(f"DEBUG CRON: Precos -> Banco: {preco_atual} | ML: {novo_valor}", flush=True)

        # Queda de preco detectada (margem de 1 centavo para evitar floats)
        if novo_valor < (preco_atual - 0.01):
            destinatario_email = doc.get("usuario_email")
            if not destinatario_email:
                continue

            print(f"DEBUG CRON: QUEDA DETECTADA! Enviando e-mail...", flush=True)
            atualizados += 1
            
            # Atualiza no MongoDB primeiro para nao enviar duplicado se falhar o email
            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"produto_preco": novo_valor}},
            )
            
            try:
                EmailFeature.enviar_promocao(
                    usuario_email=destinatario_email,
                    usuario_nome=destinatario_email.split("@")[0],
                    titulo_promocao=f"O pre�o de {produto_nome} caiu!",
                    link_promocao=produto_link,
                    empresa_nome="Mercado Livre"
                )
            except Exception as e:
                print(f"DEBUG CRON: ERRO e-mail: {e}", flush=True)
        
        # Se o preço subiu, atualizamos no banco também para manter o histórico correto
        elif novo_valor > (preco_atual + 0.01):
            print(f"DEBUG CRON: Preço subiu para {novo_valor}. Atualizando banco.", flush=True)
            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"produto_preco": novo_valor}},
            )

    print(f"DEBUG CRON: Finalizado. {total} lidos, {atualizados} e-mails enviados.", flush=True)
    return total, atualizados
