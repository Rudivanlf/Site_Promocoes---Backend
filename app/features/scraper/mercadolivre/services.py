import re
import logging
from bs4 import BeautifulSoup
import requests
from curl_cffi import requests


from app.shared.clients.mercadolivre import DEFAULT_HEADERS, resilient_get

logger = logging.getLogger(__name__)


HEADERS = DEFAULT_HEADERS

ML_SEARCH_URL = "https://lista.mercadolivre.com.br/{query}"


def _extrair_preco(container) -> dict:
    preco = None
    preco_original = None

    # Primeiro, tentar extrair pelos blocos conhecidos
    blocos_preco = container.select(".andes-money-amount")
    for bloco in blocos_preco:
        classes = bloco.get("class", []) or []
        frac = bloco.select_one(".andes-money-amount__fraction")
        cents = bloco.select_one(".andes-money-amount__cents")
        texto = None
        if frac:
            texto = frac.get_text(strip=True)
            if cents:
                texto = f"{texto},{cents.get_text(strip=True)}"

        if "andes-money-amount--previous" in classes:
            if texto:
                preco_original = _extrair_preco_from_text(texto)
        else:
            if preco is None and texto:
                preco = _extrair_preco_from_text(texto)

    # Se não encontrou, tentar procurar padrões no texto completo do item
    if not preco or not preco_original:
        full_text = container.get_text(" ", strip=True)
        matches = re.findall(r"(R?\$?\s*[\d\.\,]+)(?:\s*([A-Za-z%]+))?", full_text)
        candidates: list[tuple[str, float, bool, str]] = []
        units_blacklist = {"GB", "TB", "MB", "mAh", "cm", "mm", "kg", "g", "hz", "Hz", "GB)", "TB)", "GB,", "TB,"}
        for m in matches:
            raw, following = m[0], m[1] or ""
            norm = _extrair_preco_from_text(raw)
            if not norm:
                continue
            try:
                val = float(norm.replace(".", "") if norm.count(".")>1 else norm)
            except Exception:
                val = float(norm)
            has_rs = "R$" in raw
            if following.strip() and following.strip() in units_blacklist:
                continue
            candidates.append((norm, val, has_rs, following.strip()))

        rs_candidates = [c for c in candidates if c[2]]
        use_candidates = rs_candidates if rs_candidates else candidates

        use_candidates.sort(key=lambda x: x[1], reverse=True)
        values = []
        seen_vals = set()
        for norm, val, _, _ in use_candidates:
            if val in seen_vals:
                continue
            seen_vals.add(val)
            values.append((norm, val))

        if values:
            if preco is None and preco_original is None:
                if len(values) == 1:
                    preco = values[0][0]
                else:
                    preco_original = values[0][0]
                    preco = values[1][0]
            elif preco is None and preco_original is not None:
                try:
                    original_val = float(preco_original.replace(",", "."))
                except Exception:
                    original_val = None
                lower = [v for v in values if original_val is None or v[1] < original_val]
                if lower:
                    preco = lower[0][0]
                else:
                    preco = values[-1][0]
            elif preco is not None and preco_original is None:
                try:
                    preco_val = float(preco.replace(",", "."))
                except Exception:
                    preco_val = None
                higher = [v for v in values if preco_val is None or v[1] > preco_val]
                if higher:
                    preco_original = higher[0][0]

    return {"preco": preco, "preco_original": preco_original}


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


def _extrair_imagem(container) -> str | None:
    img = container.select_one("img.poly-component__picture")
    if not img:
        img = container.select_one("img[src]")
    if img:
        return img.get("data-src") or img.get("src")
    return None


def _extrair_link(container) -> str | None:
    link = container.select_one("a.poly-card__portada")
    if not link:
        link = container.select_one("a[href*='mercadolivre']")
    if not link:
        link = container.select_one("a[href]")
    return link.get("href") if link else None


def _extrair_titulo(container) -> str | None:
    for selector in [
        ".poly-component__title",
        "h2.ui-search-item__title",
        ".ui-search-item__title",
    ]:
        el = container.select_one(selector)
        if el:
            return el.get_text(strip=True)
    return None


def _extrair_desconto(container) -> str | None:
    el = container.select_one(".poly-price__discount")
    if not el:
        el = container.select_one(".andes-badge__content")
    return el.get_text(strip=True) if el else None


def _extrair_avaliacao(container) -> dict:
    nota = None
    quantidade = None

    rating = container.select_one(".poly-reviews__rating")
    total = container.select_one(".poly-reviews__total")

    if rating:
        nota = rating.get_text(strip=True)
    if total:
        quantidade = total.get_text(strip=True).strip("()")

    return {"nota": nota, "quantidade_avaliacoes": quantidade}


def buscar_produtos_basic(query: str, pagina: int = 1) -> list[dict]:
    # Formata a URL para o site visual do Mercado Livre
    query_formatada = query.strip().replace(" ", "-")
    url = ML_SEARCH_URL.format(query=query_formatada)

    # Lógica de paginação do HTML do ML (saltos de 48 itens)
    if pagina > 1:
        offset = (pagina - 1) * 48 + 1
        url = f"{url}_Desde_{offset}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        # Usamos curl_cffi para mascarar a requisição e passar pelo WAF do site HTML
        response = requests.get(
            url, 
            headers=headers, 
            impersonate="chrome110", 
            timeout=15
        )
        # Se a resposta for um erro (como 403 ou 503), ele vai levantar uma exceção
        response.raise_for_status()
    except Exception as exc:
        raise ConnectionError(f"Erro ao acessar o Mercado Livre: {exc}") from exc

    # Parseia o HTML com BeautifulSoup
    soup = BeautifulSoup(response.text, "lxml")

    # Seletor principal dos resultados (o ML altera isso de vez em quando)
    resultados = soup.select("li.ui-search-layout__item")
    if not resultados:
        # Fallback para estrutura alternativa
        resultados = soup.select("div.ui-search-result__wrapper")

    produtos = []
    for item in resultados:
        titulo = _extrair_titulo(item)
        if not titulo:
            continue  # Ignora anúncios ou itens sem título

        precos = _extrair_preco(item)
        avaliacao = _extrair_avaliacao(item)

        produtos.append({
            "titulo": titulo,
            "preco": precos["preco"],
            "preco_original": precos["preco_original"],
            "desconto": _extrair_desconto(item),
            "imagem": _extrair_imagem(item),
            "link": _extrair_link(item),
            "nota": avaliacao["nota"],
            "quantidade_avaliacoes": avaliacao["quantidade_avaliacoes"],
        })

    return produtos

def buscar_produtos(query: str, pagina: int = 1, detalhes: bool = False) -> list[dict]:
    basic = buscar_produtos_basic(query, pagina)
    if not detalhes:
        return basic

    for p in basic:
        link = p.get("link")
        if not link:
            continue
        try:
            rp = resilient_get(
                link,
                headers=HEADERS,
                timeout=8,
                max_retries=0,
                wait_for_circuit=False,
            )
            if rp is None or rp.status_code >= 400:
                continue
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
            found = None
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
                        p["preco"] = norm
                        found = True
                        break
            if not found:
                full = soup.get_text(" ", strip=True)
                import re

                m = re.search(r"R\$\s*[\d\.,]+\s*(?:,\s*[\d]{1,2})?", full)
                if m:
                    norm = _extrair_preco_from_text(m.group(0))
                    if norm:
                        p["preco"] = norm
        except Exception:
            # falha ao buscar detalhes de um produto não interrompe os demais
            continue

    return basic
