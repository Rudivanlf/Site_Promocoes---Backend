import json
import re
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from curl_cffi import requests


from app.shared.clients.mercadolivre import DEFAULT_HEADERS, resilient_get

logger = logging.getLogger(__name__)


HEADERS = DEFAULT_HEADERS

ML_SEARCH_URL = "https://lista.mercadolivre.com.br/{query}"

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None


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

    s = text.strip().replace("R$", "").replace("U$", "")
    s = s.replace("\xa0", " ").replace("\u202f", " ")
    s = re.sub(r"[^\d\.,]", "", s)
    if not s:
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        integer, sep, fraction = s.rpartition(",")
        if len(fraction) in (1, 2):
            s = f"{integer.replace('.', '')}.{fraction}"
        else:
            s = s.replace(",", "")
    elif "." in s:
        integer, sep, fraction = s.rpartition(".")
        if len(fraction) in (1, 2):
            s = f"{integer.replace('.', '')}.{fraction}"
        else:
            s = s.replace(".", "")

    s = s.strip(".")
    if not s:
        return None

    if "." not in s:
        s = f"{s}.00"
    else:
        integer, fraction = s.rsplit(".", 1)
        if len(fraction) == 0:
            fraction = "00"
        elif len(fraction) == 1:
            fraction = f"{fraction}0"
        else:
            fraction = fraction[:2]
        s = f"{integer}.{fraction}"

    return s


def _extrair_imagem(container) -> str | None:
    img = container.select_one("img.poly-component__picture")
    if not img:
        img = container.select_one("img[src]")
    if img:
        return img.get("data-src") or img.get("src")
    return None


def _normalizar_link(href: str | None) -> str | None:
    if not href:
        return None

    href = href.strip()
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        return urljoin("https://www.mercadolivre.com.br", href)
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("mercadolivre"):
        return f"https://{href}"

    return href


def _extrair_link(container) -> str | None:
    link = container.select_one("a.poly-card__portada")
    if not link:
        link = container.select_one("a[href*='mercadolivre']")
    if not link:
        link = container.select_one("a[href]")
    return _normalizar_link(link.get("href") if link else None)


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


def _extrair_produtos_json_ld(soup: BeautifulSoup) -> list[dict]:
    produtos: list[dict] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        payload = script.string or script.get_text(strip=True)
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue

        candidates: list[dict] = []
        if isinstance(data, dict) and isinstance(data.get("itemListElement"), list):
            candidates = data.get("itemListElement", [])
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and isinstance(item.get("itemListElement"), list):
                    candidates = item.get("itemListElement", [])
                    break

        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
            if not isinstance(item, dict):
                continue

            titulo = item.get("name")
            if not titulo:
                continue

            link = item.get("url")
            imagem = item.get("image")
            if isinstance(imagem, list):
                imagem = imagem[0] if imagem else None

            preco = None
            offers = item.get("offers") or {}
            raw_price = offers.get("price")
            if raw_price is not None:
                preco = _extrair_preco_from_text(str(raw_price))

            produtos.append({
                "titulo": titulo,
                "preco": preco,
                "preco_original": None,
                "desconto": None,
                "imagem": imagem,
                "link": _normalizar_link(link) if link else None,
                "nota": None,
                "quantidade_avaliacoes": None,
            })

    return produtos


def _find_results_list(data) -> list[dict] | None:
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return results
        for value in data.values():
            found = _find_results_list(value)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_results_list(item)
            if found is not None:
                return found
    return None


def _extrair_produtos_preloaded_state(soup: BeautifulSoup) -> list[dict]:
    scripts = [
        soup.find("script", attrs={"id": "__PRELOADED_STATE__"}),
        soup.find("script", attrs={"id": "__INITIAL_STATE__"}),
    ]
    for script in scripts:
        if not script:
            continue
        payload = script.string or script.get_text(strip=True)
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue

        results = _find_results_list(data)
        if not results:
            continue

        produtos = []
        seen_links = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            titulo = item.get("title") or item.get("name")
            link = item.get("permalink") or item.get("url")
            if not titulo or not link:
                continue
            if "mercadolivre" not in link:
                continue
            if link in seen_links:
                continue
            seen_links.add(link)

            preco_val = item.get("price") or item.get("price_value") or item.get("priceValue")
            preco = _extrair_preco_from_text(str(preco_val)) if preco_val is not None else None
            original = item.get("original_price")
            preco_original = _extrair_preco_from_text(str(original)) if original is not None else None

            produtos.append({
                "titulo": titulo,
                "preco": preco,
                "preco_original": preco_original,
                "desconto": None,
                "imagem": item.get("thumbnail") or item.get("picture_url") or item.get("image"),
                "link": _normalizar_link(link),
                "nota": None,
                "quantidade_avaliacoes": None,
            })

        if produtos:
            return produtos

    return []


def _is_js_challenge(html: str) -> bool:
    if not html:
        return False
    lower = html.lower()
    markers = [
        "micro-landing-container",
        "continue-button",
        "_bmstate",
        "_bmc=",
        "this page requires javascript",
    ]
    return any(marker in lower for marker in markers)


def _fetch_html_playwright(url: str) -> str | None:
    if not url or sync_playwright is None:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
            )
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3500)
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None


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
    resultados = soup.select("li.ui-search-layout__item, li.ui-search-layout__stack-item")
    if not resultados:
        # Fallback para estrutura alternativa
        resultados = soup.select("div.ui-search-result__wrapper, div.ui-search-result__content-wrapper")

    if not resultados:
        lower = (response.text or "").lower()
        if any(marker in lower for marker in ["captcha", "account-verification", "/login", "access denied"]):
            raise ConnectionError("Mercado Livre bloqueou a consulta (captcha/login).")

        if _is_js_challenge(response.text):
            html = _fetch_html_playwright(url)
            if html:
                soup = BeautifulSoup(html, "lxml")
                resultados = soup.select("li.ui-search-layout__item, li.ui-search-layout__stack-item")
                if not resultados:
                    resultados = soup.select("div.ui-search-result__wrapper, div.ui-search-result__content-wrapper")
                if not resultados:
                    produtos_json = _extrair_produtos_json_ld(soup)
                    if produtos_json:
                        return produtos_json
                    produtos_preloaded = _extrair_produtos_preloaded_state(soup)
                    if produtos_preloaded:
                        return produtos_preloaded

        produtos_json = _extrair_produtos_json_ld(soup)
        if produtos_json:
            return produtos_json

        produtos_preloaded = _extrair_produtos_preloaded_state(soup)
        if produtos_preloaded:
            return produtos_preloaded

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
