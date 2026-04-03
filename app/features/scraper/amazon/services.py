import logging
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from curl_cffi import requests

from app.shared.clients.mercadolivre import DEFAULT_HEADERS, resilient_get

logger = logging.getLogger(__name__)

AMAZON_BASE_URL = "https://www.amazon.com.br"
AMAZON_SEARCH_URL = f"{AMAZON_BASE_URL}/s?k={{query}}"


def _normalizar_preco(text: str | None) -> str | None:
    if not text:
        return None

    s = text.strip().replace("R$", "").replace("\xa0", "")
    s = re.sub(r"\s+", "", s)

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

    if "." not in num:
        num = f"{num}.00"
    else:
        inteiro, frac = num.rsplit(".", 1)
        if len(frac) == 1:
            frac = f"{frac}0"
        elif len(frac) == 0:
            frac = "00"
        num = f"{inteiro}.{frac}"

    return num


def _extrair_preco_card(item) -> dict:
    preco = None
    preco_original = None

    bloco = item.select_one("span.a-price:not(.a-text-price)")
    if bloco:
        whole = bloco.select_one("span.a-price-whole")
        frac = bloco.select_one("span.a-price-fraction")
        if whole:
            whole_txt = whole.get_text(strip=True).replace(".", "")
            frac_txt = frac.get_text(strip=True) if frac else "00"
            preco = _normalizar_preco(f"{whole_txt},{frac_txt}")

    if not preco:
        preco_offscreen = item.select_one("span.a-price span.a-offscreen")
        if preco_offscreen:
            preco = _normalizar_preco(preco_offscreen.get_text(strip=True))

    preco_anterior = item.select_one("span.a-price.a-text-price span.a-offscreen")
    if preco_anterior:
        preco_original = _normalizar_preco(preco_anterior.get_text(strip=True))

    return {"preco": preco, "preco_original": preco_original}


def _extrair_titulo(item) -> str | None:
    el = item.select_one("h2 a span")
    if el:
        return el.get_text(strip=True)

    el = item.select_one("h2 span")
    return el.get_text(strip=True) if el else None


def _extrair_link(item) -> str | None:
    el = item.select_one("h2 a.a-link-normal")
    if not el:
        el = item.select_one("a.a-link-normal[href]")
    if not el:
        return None

    href = el.get("href")
    if not href:
        return None

    if href.startswith("http"):
        return href

    return f"{AMAZON_BASE_URL}{href}"


def _extrair_imagem(item) -> str | None:
    img = item.select_one("img.s-image")
    if not img:
        img = item.select_one("img[src]")
    if not img:
        return None
    return img.get("src") or img.get("data-src")


def _extrair_avaliacao(item) -> dict:
    nota = None
    quantidade = None

    nota_el = item.select_one("span.a-icon-alt")
    qtd_el = item.select_one("span.a-size-base.s-underline-text")
    if not qtd_el:
        qtd_el = item.select_one("a[aria-label*='avalia'] span.a-size-base")

    if nota_el:
        nota = nota_el.get_text(strip=True)
    if qtd_el:
        quantidade = qtd_el.get_text(strip=True)

    return {"nota": nota, "quantidade_avaliacoes": quantidade}


def _extrair_desconto(item) -> str | None:
    for sel in [
        "span.a-badge-label-inner",
        "span.s-coupon-unclipped",
        "span.a-letter-space",
    ]:
        el = item.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

    return None


def buscar_produtos_basic(query: str, pagina: int = 1) -> list[dict]:
    query_formatada = quote_plus(query.strip())
    if not query_formatada:
        return []

    url = AMAZON_SEARCH_URL.format(query=query_formatada)
    if pagina > 1:
        url = f"{url}&page={pagina}"

    try:
        response = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            impersonate="chrome120",
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        raise ConnectionError(f"Erro ao acessar a Amazon: {exc}") from exc

    soup = BeautifulSoup(response.text, "lxml")
    resultados = soup.select("div.s-result-item[data-component-type='s-search-result']")

    produtos = []
    for item in resultados:
        titulo = _extrair_titulo(item)
        if not titulo:
            continue

        precos = _extrair_preco_card(item)
        avaliacao = _extrair_avaliacao(item)

        produtos.append(
            {
                "titulo": titulo,
                "preco": precos["preco"],
                "preco_original": precos["preco_original"],
                "desconto": _extrair_desconto(item),
                "imagem": _extrair_imagem(item),
                "link": _extrair_link(item),
                "nota": avaliacao["nota"],
                "quantidade_avaliacoes": avaliacao["quantidade_avaliacoes"],
            }
        )

    return produtos


def buscar_produtos(query: str, pagina: int = 1, detalhes: bool = False) -> list[dict]:
    produtos = buscar_produtos_basic(query=query, pagina=pagina)
    if not detalhes:
        return produtos

    for produto in produtos:
        link = produto.get("link")
        if not link:
            continue

        try:
            response = resilient_get(
                link,
                headers=DEFAULT_HEADERS,
                timeout=8,
                max_retries=1,
                wait_for_circuit=False,
            )
            if response is None or response.status_code >= 400:
                continue

            soup = BeautifulSoup(response.text, "lxml")
            for sel in [
                "span.a-price.aok-align-center span.a-offscreen",
                "span.a-price span.a-offscreen",
                "#corePriceDisplay_desktop_feature_div span.a-offscreen",
            ]:
                el = soup.select_one(sel)
                if not el or not el.get_text(strip=True):
                    continue
                normalizado = _normalizar_preco(el.get_text(strip=True))
                if normalizado:
                    produto["preco"] = normalizado
                    break
        except Exception:
            # Falha de detalhes em um produto nao interrompe a lista inteira.
            continue

    return produtos
