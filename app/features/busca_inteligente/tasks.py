import logging
import os
import time
import random
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..favoritos.services import FavoritoService
from ..historico_precos.price_history import record_price
from ..email.email import EmailFeature
from app.shared.clients.mercadolivre import resilient_get

logger = logging.getLogger(__name__)

MAX_PRODUTOS_POR_CICLO = int(os.getenv("ML_MAX_PRODUCTS_PER_CYCLE", "30"))
INTERVALO_SUCESSO_MIN = int(os.getenv("ML_SUCCESS_RECHECK_MINUTES", "120"))
INTERVALO_FALHA_MIN = int(os.getenv("ML_FAILURE_RECHECK_MINUTES", "240"))
JITTER_MIN = int(os.getenv("ML_RECHECK_JITTER_MINUTES", "25"))

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

    headers_minimal = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "text/html",
    }
    res = resilient_get(
        link,
        headers=headers_minimal,
        timeout=10,
        allow_redirects=True,
        stream=False,
    )
    if res is None:
        return link

    final_url = res.url
    if final_url and final_url != link and "mercadolivre.com" in final_url:
        print(f"DEBUG CRON: Link expandido de {link[:60]} para {final_url[:60]}", flush=True)
        return final_url

    return link


def _normalizar_chave_produto(link: str) -> str:
    try:
        partes = urlsplit((link or "").strip())
        netloc = partes.netloc.lower().replace("www.", "")
        caminho = partes.path.rstrip("/")
        return urlunsplit((partes.scheme.lower() or "https", netloc, caminho, "", ""))
    except Exception:
        return (link or "").split("#")[0].split("?")[0].strip()


def _to_utc_datetime(valor) -> datetime | None:
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            return valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(timezone.utc)
    return None


def _calcular_proxima_verificacao(sucesso: bool) -> datetime:
    base = INTERVALO_SUCESSO_MIN if sucesso else INTERVALO_FALHA_MIN
    jitter = random.randint(0, max(0, JITTER_MIN))
    return datetime.now(timezone.utc) + timedelta(minutes=base + jitter)

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

        res = resilient_get(
            link_limpo,
            headers=HEADERS_PROD,
            timeout=15,
            allow_redirects=True,
        )
        if res is None:
            return None

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

def buscar_promocoes_para_favoritos() -> tuple[int, int]:
    print("DEBUG CRON: Iniciando tarefa de busca de promoções...", flush=True)

    fav_service = FavoritoService()
    cursor = fav_service.collection.find({})
    agora = datetime.now(timezone.utc)

    agrupados = {}
    total = 0
    atualizados = 0

    # 1. FASE RÁPIDA: Apenas lê o banco e agrupa (SEM REQUESTS, SEM SLEEP)
    for doc in cursor:
        total += 1
        produto_link = doc.get("produto_link")

        if not produto_link:
            continue
        
        # NOTE QUE TIREI O REQUEST E O SLEEP DAQUI
        
        chave = _normalizar_chave_produto(produto_link)
        if not chave:
            continue

        if chave not in agrupados:
            agrupados[chave] = {
                "link": produto_link,
                "docs": [],
                "proxima_verificacao": None,
            }
        agrupados[chave]["docs"].append(doc)

        proxima_str = doc.get("proxima_verificacao_em")
        proxima = _to_utc_datetime(proxima_str) if proxima_str else None
        atual = agrupados[chave]["proxima_verificacao"]
        
        if proxima and (atual is None or proxima > atual):
            agrupados[chave]["proxima_verificacao"] = proxima

    # 2. FASE DE FILTRO: Escolhe quem vai ser processado neste ciclo
    candidatos = []
    for item in agrupados.values():
        proxima = item.get("proxima_verificacao")
        if proxima and proxima > agora:
            continue
        candidatos.append(item)

    if len(candidatos) > MAX_PRODUTOS_POR_CICLO:
        random.shuffle(candidatos)
        candidatos = candidatos[:MAX_PRODUTOS_POR_CICLO]

    logger.info(
        "Favoritos: total=%s, produtos_unicos=%s, candidatos=%s, limite_ciclo=%s",
        total, len(agrupados), len(candidatos), MAX_PRODUTOS_POR_CICLO
    )

    # 3. FASE LENTA: Processa APENAS o lote limitado (AQUI ENTRA O SLEEP E O REQUEST)
    for item in candidatos:
        link_base = item["link"]
        docs = item["docs"]
        
        # --- PAUSA AQUI ---
        # Dorme um tempo aleatório para enganar o WAF entre um produto e outro
        time.sleep(random.uniform(2.0, 5.0))
        
        # Faz UMA ÚNICA requisição para o link que serve para todos os usuários com esse favorito
        novo_valor = extrair_preco_pelo_link_direto(link_base)

        if novo_valor is None:
            proxima_falha = _calcular_proxima_verificacao(sucesso=False)
            for doc in docs:
                fav_service.collection.update_one(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "ultima_verificacao_em": agora,
                            "proxima_verificacao_em": proxima_falha,
                            "ultima_verificacao_status": "falha",
                        },
                        "$inc": {"falhas_consecutivas": 1},
                    },
                )
            continue

        proxima_sucesso = _calcular_proxima_verificacao(sucesso=True)

        for doc in docs:
            produto_nome = doc.get("produto_nome")
            produto_link = doc.get("produto_link")
            preco_atual = doc.get("produto_preco", 0.0)

            fav_service.collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "ultima_verificacao_em": agora,
                        "proxima_verificacao_em": proxima_sucesso,
                        "ultima_verificacao_status": "ok",
                    },
                    "$unset": {"falhas_consecutivas": ""},
                },
            )

            if novo_valor < (preco_atual - 0.01):
                destinatario_email = doc.get("usuario_email")
                if not destinatario_email:
                    continue

                atualizados += 1
                fav_service.collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"produto_preco": novo_valor}},
                )
                record_price(
                    link=produto_link,
                    name=produto_nome,
                    image=doc.get("produto_imagem", ""),
                    price=novo_valor,
                )

                try:
                    EmailFeature.enviar_promocao(
                        usuario_email=destinatario_email,
                        usuario_nome=destinatario_email.split("@")[0],
                        titulo_promocao=f"O preco de {produto_nome} caiu!",
                        link_promocao=produto_link,
                        empresa_nome="Mercado Livre",
                    )
                except Exception:
                    pass

            elif novo_valor > (preco_atual + 0.01):
                fav_service.collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"produto_preco": novo_valor}},
                )
                record_price(
                    link=produto_link,
                    name=produto_nome,
                    image=doc.get("produto_imagem", ""),
                    price=novo_valor,
                )

    return total, atualizados