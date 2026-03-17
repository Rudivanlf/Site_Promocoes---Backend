import logging
import re
import requests
import traceback
from bs4 import BeautifulSoup
from typing import List, Dict

from ..favoritos.services import FavoritoService
from ..email.email import EmailFeature
from ..usuarios.services import UsuarioService

logger = logging.getLogger(__name__)

# --- FUNÇÕES UTILITÁRIAS PARA O SCRAPER DE FAVORITOS ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def _extrair_preco_from_text(text: str) -> str | None:
    if not text:
        return None
    s = text.strip()
    s = s.replace("R$", "").replace("\xa0", "").replace(" ", "")
    m = re.search(r"[\d\.,]+", s)
    if not m:
        return None
    num = m.group(0)
    if "," in num:
        if "." in num:
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", ".")
    else:
        num = num.replace(".", "")

    if "." in num:
        integer, frac = num.rsplit(".", 1)
        if len(frac) == 1:
            frac = frac + "0"
        elif len(frac) == 0:
            frac = "00"
        num = f"{integer}.{frac}"
    else:
        num = f"{num}.00"
    return num
# ---------------------------------------------------------


def expandir_link_encurtado(link: str) -> str:
    if not ("click" in link and "mercadolivre.com" in link):
        return link  
    
    try:
        HEADERS_MINIMAL = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "text/html",
        }
        res = requests.get(link, headers=HEADERS_MINIMAL, timeout=10, allow_redirects=True, stream=False)
        final_url = res.url
        
        if final_url and final_url != link and "mercadolivre.com" in final_url:
            print(f"DEBUG CRON: Link expandido de {link[:60]} para {final_url[:60]}", flush=True)
            return final_url
    except Exception as e:
        print(f"DEBUG CRON: Erro ao expandir link {link[:60]}: {type(e).__name__}", flush=True)
    
    return link

def extrair_preco_pelo_link_direto(link: str) -> float | None:
    try:
        link_limpo = link.split('#')[0].strip()
        if not link_limpo:
            return None
        
        if "click" in link_limpo and "mercadolivre.com" in link_limpo:
            link_expandido = expandir_link_encurtado(link_limpo)
            if link_expandido != link_limpo:
                if "/gz/account-verification" not in link_expandido and "/login" not in link_expandido:
                    link_limpo = link_expandido
                else:
                    return None
        
        HEADERS_PROD = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }

        res = requests.get(link_limpo, headers=HEADERS_PROD, timeout=15, allow_redirects=True)

        if res.status_code != 200 or "captcha" in res.text.lower() or len(res.text) < 100:
            return None

        soup = BeautifulSoup(res.text, "lxml")
        
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            script_text = script.text
            if '"offers"' in script_text and '"price"' in script_text:
                price_match = re.search(r'"price":\s*([0-9]+\.?[0-9]*)', script_text)
                if price_match:
                    return float(price_match.group(1))

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
            if not el: 
                continue
            
            if el.name == "meta":
                val = el.get("content")
                if val:
                    try:
                        return float(val)
                    except ValueError:
                        continue
            else:
                txt = el.get_text(strip=True)
                parent = el.find_parent(class_="andes-money-amount")
                cents = parent.select_one(".andes-money-amount__cents") if parent else None
                if cents:
                    txt = f"{txt},{cents.get_text(strip=True)}"
                
                norm = _extrair_preco_from_text(txt)
                if norm:
                    try:
                        return float(norm)
                    except ValueError:
                        continue

        full = soup.get_text(" ", strip=True)
        m = re.search(r"R\$\s*([\d\.,]+)", full)
        if m:
            norm = _extrair_preco_from_text(m.group(0))
            if norm:
                try:
                    return float(norm)
                except ValueError:
                    pass

    except Exception:
        pass
    
    return None

def buscar_promocoes_para_favoritos() -> None:
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
        
        novo_valor = extrair_preco_pelo_link_direto(produto_link)

        if novo_valor is None:
            continue

        if novo_valor < (preco_atual - 0.01):
            destinatario_email = doc.get("usuario_email")
            if not destinatario_email:
                continue

            atualizados += 1
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
            except Exception:
                pass
        
        elif novo_valor > (preco_atual + 0.01):
            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"produto_preco": novo_valor}},
            )

    return total, atualizados
