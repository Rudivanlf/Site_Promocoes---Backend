import logging
import json
import re
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi import requests

from app.shared.clients.mercadolivre import DEFAULT_HEADERS, resilient_get

logger = logging.getLogger(__name__)

KABUM_BASE_URL = "https://www.kabum.com.br"
KABUM_SEARCH_URL = f"{KABUM_BASE_URL}/busca/{{query}}"


def _price_to_str(value) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _normalizar_preco(str(value))


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


def _extrair_titulo(item) -> str | None:
    for sel in [
        "span.nameCard",
        "h2 span",
        "h2",
        "a[name='link-produto'] span",
    ]:
        el = item.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return None


def _extrair_link(item) -> str | None:
    for sel in [
        "a[name='link-produto']",
        "a.productLink",
        "a[href*='/produto/']",
        "a[href]",
    ]:
        el = item.select_one(sel)
        if not el:
            continue
        href = el.get("href")
        if not href:
            continue
        if href.startswith("http"):
            return href
        return f"{KABUM_BASE_URL}{href}"
    return None


def _extrair_imagem(item) -> str | None:
    for sel in [
        "img.imageCard",
        "img[src]",
    ]:
        img = item.select_one(sel)
        if not img:
            continue
        return img.get("src") or img.get("data-src")
    return None


def _extrair_avaliacao(item) -> dict:
    nota = None
    quantidade = None

    for sel in [
        "span.reviewScoreCard",
        "span.rating",
        "span[aria-label*='de 5']",
    ]:
        el = item.select_one(sel)
        if el and el.get_text(strip=True):
            nota = el.get_text(strip=True)
            break

    for sel in [
        "span.reviewCountCard",
        "span.ratingCount",
        "span[aria-label*='avali']",
    ]:
        el = item.select_one(sel)
        if el and el.get_text(strip=True):
            quantidade = el.get_text(strip=True)
            break

    return {"nota": nota, "quantidade_avaliacoes": quantidade}


def _extrair_desconto(item) -> str | None:
    for sel in [
        "span.offerPercentage",
        "span.discountPercentage",
        "span[data-testid='product-discount']",
    ]:
        el = item.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

    texto = item.get_text(" ", strip=True)
    m = re.search(r"\b\d{1,2}%\s*OFF\b", texto, flags=re.IGNORECASE)
    if m:
        return m.group(0)

    return None


def _extrair_precos(item) -> dict:
    preco = None
    preco_original = None

    selectors_preco = [
        "span.priceCard",
        "span.finalPrice",
        "span[data-testid='price']",
    ]
    for sel in selectors_preco:
        el = item.select_one(sel)
        if el and el.get_text(strip=True):
            preco = _normalizar_preco(el.get_text(strip=True))
            if preco:
                break

    selectors_original = [
        "span.oldPriceCard",
        "span.oldPrice",
        "span[data-testid='old-price']",
    ]
    for sel in selectors_original:
        el = item.select_one(sel)
        if el and el.get_text(strip=True):
            preco_original = _normalizar_preco(el.get_text(strip=True))
            if preco_original:
                break

    if not preco:
        # Fallback por valores monetarios no texto do card.
        texto = item.get_text(" ", strip=True)
        valores = re.findall(r"R\$\s*[\d\.]+(?:,[\d]{1,2})?", texto)
        normalizados = [_normalizar_preco(v) for v in valores]
        normalizados = [v for v in normalizados if v]
        if len(normalizados) == 1:
            preco = normalizados[0]
        elif len(normalizados) >= 2:
            preco_original = normalizados[0]
            preco = normalizados[1]

    return {"preco": preco, "preco_original": preco_original}


def _extrair_produtos_next_data(soup: BeautifulSoup) -> list[dict]:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script or not script.string:
        return []

    try:
        next_data = json.loads(script.string)
        raw_data = next_data.get("props", {}).get("pageProps", {}).get("data")
        if not raw_data:
            return []
        if isinstance(raw_data, str):
            page_data = json.loads(raw_data)
        elif isinstance(raw_data, dict):
            page_data = raw_data
        else:
            return []
    except Exception:
        return []

    items = page_data.get("catalogServer", {}).get("data") or []
    if not isinstance(items, list):
        return []

    produtos = []
    for item in items:
        if not isinstance(item, dict):
            continue

        titulo = (item.get("name") or "").strip()
        if not titulo:
            continue

        offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        preco = (
            _price_to_str(offer.get("priceWithDiscount"))
            or _price_to_str(item.get("priceWithDiscount"))
            or _price_to_str(offer.get("price"))
            or _price_to_str(item.get("price"))
        )
        preco_original = _price_to_str(item.get("oldPrice")) or _price_to_str(item.get("price"))

        desconto_pct = offer.get("discountPercentage")
        if desconto_pct is None:
            desconto_pct = item.get("discountPercentage")
        desconto = f"{desconto_pct}% OFF" if desconto_pct not in (None, "", 0, "0") else None

        code = item.get("code")
        friendly = item.get("friendlyName")
        link = item.get("externalUrl")
        if not link and code and friendly:
            link = f"{KABUM_BASE_URL}/produto/{code}/{friendly}"
        elif not link and code:
            link = f"{KABUM_BASE_URL}/produto/{code}"

        imagem = item.get("image") or item.get("thumbnail")
        if not imagem:
            imagens = item.get("images")
            if isinstance(imagens, list) and imagens:
                imagem = imagens[0]

        nota = str(item.get("rating")) if item.get("rating") not in (None, "") else None
        quantidade = item.get("ratingCount")
        quantidade_avaliacoes = str(quantidade) if quantidade not in (None, "") else None

        produtos.append(
            {
                "titulo": titulo,
                "preco": preco,
                "preco_original": preco_original,
                "desconto": desconto,
                "imagem": imagem,
                "link": link,
                "nota": nota,
                "quantidade_avaliacoes": quantidade_avaliacoes,
            }
        )

    return produtos


def _selecionar_cards_resultado(soup: BeautifulSoup) -> list:
    selectors = [
        "article.productCard",
        "div.productCard",
        "div[data-testid='product-card']",
        "a[href*='/produto/']",
    ]
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            return cards
    return []


def buscar_produtos_basic(query: str, pagina: int = 1) -> list[dict]:
    query_limpa = query.strip()
    if not query_limpa:
        return []

    # A Kabum responde diferente dependendo da forma do termo na URL.
    # Tentamos variantes deterministicas para cobrir buscas com espacos.
    query_encoded = quote(query_limpa, safe="")
    query_slug = re.sub(r"\s+", "-", query_limpa)
    query_plus = query_limpa.replace(" ", "+")

    candidatos = []
    for q in [query_encoded, query_slug, query_plus]:
        if not q:
            continue
        if q not in candidatos:
            candidatos.append(q)

    ultimo_erro = None
    for query_url in candidatos:
        url = KABUM_SEARCH_URL.format(query=query_url)
        if pagina > 1:
            url = f"{url}?page_number={pagina}"

        try:
            response = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                impersonate="chrome120",
                timeout=15,
            )
            response.raise_for_status()
        except Exception as exc:
            ultimo_erro = exc
            continue

        soup = BeautifulSoup(response.text, "lxml")

        # Fonte principal: payload estruturado do Next.js, mais estavel que seletores de DOM.
        produtos_next = _extrair_produtos_next_data(soup)
        if produtos_next:
            return produtos_next

        cards = _selecionar_cards_resultado(soup)
        produtos = []
        for item in cards:
            titulo = _extrair_titulo(item)
            link = _extrair_link(item)
            if not titulo or not link:
                continue

            precos = _extrair_precos(item)
            avaliacao = _extrair_avaliacao(item)

            produtos.append(
                {
                    "titulo": titulo,
                    "preco": precos["preco"],
                    "preco_original": precos["preco_original"],
                    "desconto": _extrair_desconto(item),
                    "imagem": _extrair_imagem(item),
                    "link": link,
                    "nota": avaliacao["nota"],
                    "quantidade_avaliacoes": avaliacao["quantidade_avaliacoes"],
                }
            )

        if produtos:
            return produtos

    if ultimo_erro:
        raise ConnectionError(f"Erro ao acessar a Kabum: {ultimo_erro}") from ultimo_erro

    return []


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
                "h4.finalPrice",
                "span.finalPrice",
                "span[data-testid='price']",
            ]:
                el = soup.select_one(sel)
                if not el or not el.get_text(strip=True):
                    continue
                normalizado = _normalizar_preco(el.get_text(strip=True))
                if normalizado:
                    produto["preco"] = normalizado
                    break
        except Exception:
            continue

    return produtos
