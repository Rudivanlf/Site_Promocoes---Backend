import logging
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict

from ..favoritos.services import FavoritoService
from ..scraper.mercadolivre.services import _extrair_preco_from_text, HEADERS
from ..email.email import EmailFeature
from ..usuarios.services import UsuarioService

logger = logging.getLogger(__name__)

def extrair_preco_pelo_link_direto(link: str) -> float | None:
    try:
        # Resolve links de redirecionamento
        response = requests.get(link, headers=HEADERS, timeout=15, allow_redirects=True)
        response.raise_for_status()
        
        # O link final apos redirecionamentos
        url_final = response.url
        soup = BeautifulSoup(response.text, "lxml")
        
        # 1. Tentar seletores de preco da pagina de PRODUTO 
        # O preco principal geralmente esta em .ui-pdp-price__second-line ou .ui-pdp-price__price
        selectors = [
            ".ui-pdp-price__second-line .andes-money-amount__fraction",
            ".ui-pdp-price__price .andes-money-amount__fraction",
            ".ui-pdp-price .andes-money-amount__fraction",
            "meta[property=\"product:price:amount\"]", # Fallback meta tag
        ]
        
        for sel in selectors:
            el = soup.select_one(sel)
            if not el: continue
            
            if el.name == "meta":
                val = el.get("content")
                if val: return float(val)
                continue

            frac = el.get_text(strip=True)
            if not frac: continue
            
            # Busca centavos (opcional)
            cents = None
            cents_el = None
            # Tenta achar centavos no mesmo container pai
            parent = el.find_parent(class_="andes-money-amount")
            if parent:
                cents_el = parent.select_one(".andes-money-amount__cents")
            
            if not cents_el:
                cents_el = soup.select_one(".ui-pdp-price__second-line .andes-money-amount__cents")
            
            if cents_el:
                cents = cents_el.get_text(strip=True)
            
            texto = frac
            if cents:
                texto = f"{texto},{cents}"
            
            norm = _extrair_preco_from_text(texto)
            if norm:
                return float(norm)

        # 2. Fallback: Se for uma pagina de busca disfarçada ou outro layout
        # Tenta pegar qualquer preco que pareça o principal
        price_meta = soup.select_one("meta[itemprop=\"price\"]")
        if price_meta and price_meta.get("content"):
            try:
                return float(price_meta.get("content"))
            except: pass

        # 3. Fallback Regex no texto visivel (igual ao services.py)
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
