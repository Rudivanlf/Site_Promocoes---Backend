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

def expandir_link_encurtado(link: str) -> str:
    if not ("click" in link and "mercadolivre.com" in link):
        return link  
    
    try:
        HEADERS_MINIMAL = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "text/html",
        }
        
        # Tentar GET com allow_redirects=True (HEAD pode não funcionar com redirects)
        res = requests.get(link, headers=HEADERS_MINIMAL, timeout=10, allow_redirects=True, stream=False)
        final_url = res.url
        
        if final_url and final_url != link and "mercadolivre.com" in final_url:
            print(f"DEBUG CRON: Link expandido de {link[:60]} para {final_url[:60]}", flush=True)
            return final_url
        elif final_url:
            print(f"DEBUG CRON: Link não foi expandido (mesmo após redirecionamento): {final_url[:60]}", flush=True)
    except requests.Timeout:
        print(f"DEBUG CRON: Timeout ao expandir link {link[:60]}", flush=True)
    except Exception as e:
        print(f"DEBUG CRON: Erro ao expandir link {link[:60]}: {type(e).__name__}: {str(e)[:50]}", flush=True)
    
    return link

def extrair_preco_pelo_link_direto(link: str) -> float | None:
    try:
        # Normalizar link: remover fragmentos e parâmetros de rastreamento desnecessários
        # Os fragmentos (#...) não são enviados ao servidor, mas melhor garantir
        link_limpo = link.split('#')[0].strip()
        
        if not link_limpo:
            print(f"DEBUG CRON: Link vazio após limpeza: {link}", flush=True)
            return None
        
        # Se é um link encurtado, tentar expandir primeiro
        if "click" in link_limpo and "mercadolivre.com" in link_limpo:
            print(f"DEBUG CRON: Detectado link encurtado, tentando expandir...", flush=True)
            link_expandido = expandir_link_encurtado(link_limpo)
            # Validar se a URL expandida é legítima (não para páginas de login/verificação)
            if link_expandido != link_limpo:
                if "/gz/account-verification" not in link_expandido and "/login" not in link_expandido:
                    link_limpo = link_expandido
                else:
                    print(f"DEBUG CRON: Link expandiu para página de autenticação - ignorando", flush=True)
                    return None
        
        # User-Agent mobile costuma ser menos bloqueado em data centers
        # e o Mercado Livre serve um HTML mais enxuto (fácil de ler)
        HEADERS_PROD = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }

        res = requests.get(link_limpo, headers=HEADERS_PROD, timeout=15, allow_redirects=True)
        
        # LOG OBRIGATÓRIO PARA O RENDER - Identificar se o código novo rodou
        print(f"DEBUG CRON: [RENDER] Link: {link_limpo[:60]} | HTTP Status: {res.status_code}", flush=True)

        if res.status_code != 200:
            if res.status_code == 403:
                print("DEBUG CRON: [RENDER] BLOQUEIO 403 (Forbidden) detectado.", flush=True)
            elif res.status_code >= 400:
                print(f"DEBUG CRON: [RENDER] HTTP {res.status_code} para {link_limpo[:60]}", flush=True)
            return None

        if "captcha" in res.text.lower():
            print(f"DEBUG CRON: [RENDER] CAPTCHA detectado no link {link_limpo[:60]}", flush=True)
            return None
        
        # Validação: garantir que recebemos HTML válido
        if len(res.text) < 100:
            print(f"DEBUG CRON: Resposta HTML muito curta ({len(res.text)} bytes) - possível redirecionamento incorreto", flush=True)
            return None

        soup = BeautifulSoup(res.text, "lxml")
        
        # Estratégia 1: JSON-LD (A mais robusta)
        scripts = soup.find_all("script", type="application/ld+json")
        print(f"DEBUG CRON: Encontrados {len(scripts)} scripts JSON-LD", flush=True)
        
        for i, script in enumerate(scripts):
            script_text = script.text
            if '"offers"' in script_text and '"price"' in script_text:
                price_match = re.search(r'"price":\s*([0-9]+\.?[0-9]*)', script_text)
                if price_match:
                    preco_extraído = float(price_match.group(1))
                    print(f"DEBUG CRON: Preço extraído do JSON-LD (script {i}): {preco_extraído}", flush=True)
                    return preco_extraído

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
            if not el: 
                continue
            
            if el.name == "meta":
                val = el.get("content")
                if val:
                    try:
                        preco_extraído = float(val)
                        print(f"DEBUG CRON: Preço extraído do meta '{sel}': {preco_extraído}", flush=True)
                        return preco_extraído
                    except ValueError:
                        continue
            else:
                txt = el.get_text(strip=True)
                # Tenta pegar centavos no mesmo container
                parent = el.find_parent(class_="andes-money-amount")
                cents = parent.select_one(".andes-money-amount__cents") if parent else None
                if cents:
                    txt = f"{txt},{cents.get_text(strip=True)}"
                
                norm = _extrair_preco_from_text(txt)
                if norm:
                    try:
                        preco_extraído = float(norm)
                        print(f"DEBUG CRON: Preço extraído do CSS '{sel}': {preco_extraído}", flush=True)
                        return preco_extraído
                    except ValueError:
                        continue

        # 3. Fallback Regex no texto visível 
        full = soup.get_text(" ", strip=True)
        m = re.search(r"R\$\s*([\d\.,]+)", full)
        if m:
            norm = _extrair_preco_from_text(m.group(0))
            if norm:
                try:
                    preco_extraído = float(norm)
                    print(f"DEBUG CRON: Preço extraído do regex fallback: {preco_extraído}", flush=True)
                    return preco_extraído
                except ValueError:
                    pass
        
        # Se é um link encurtado (click1.mercadolivre), precisamos de um tratamento especial
        if "click1.mercadolivre.com" in link_limpo or "click.mercadolivre.com" in link_limpo:
            print(f"DEBUG CRON: [ALERTA] Link encurtado detectado - não conseguiu extrair preço", flush=True)
            print(f"DEBUG CRON: [ALERTA] URL original: {link_limpo[:100]}", flush=True)

    except Exception as e:
        print(f"DEBUG CRON: Erro ao acessar link direto {link}: {str(e)}", flush=True)
    
    print(f"DEBUG CRON: Falha total na extração de preço para {link_limpo[:60]}", flush=True)
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
        produto_id = doc.get("produto_id")
        preco_atual = doc.get("produto_preco", 0.0)

        if not produto_link:
            continue

        print(f"DEBUG CRON: Processando: {produto_nome[:30]}...", flush=True)
        
        # Tenta extrair o preco usando a logica
        novo_valor = extrair_preco_pelo_link_direto(produto_link)

        # ⚠️ IMPORTANTE: Sem fallback! 
        # Se o link original falha, o sistema não tenta alternativas para evitar falsos positivos.
        # Isso é seguro pois significa que produtos com links quebrados não enviarão emails indevidos.
        
        if novo_valor is None:
            print(f"DEBUG CRON: Preco nao encontrado para {produto_link[:80]}", flush=True)
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
                    titulo_promocao=f"O preco de {produto_nome} caiu!",
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
