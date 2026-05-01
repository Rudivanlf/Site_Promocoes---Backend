import logging
import re

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .base import ProviderQuotaExceeded
import json

from .serializers import (
    AgentRequestSerializer,
    AgentResponseSerializer,
    RecommendRequestSerializer,
)
from .services import AgentService, PROVIDERS

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def chat(request):
    """
    Send a chat message to an AI provider.

    Request body:
        {
            "provider": "gemini",           // optional if a default is configured
            "messages": [
                {"role": "user", "content": "Hello!"}
            ],
            "system_prompt": "...",         // optional
            "temperature": 0.7,             // optional
            "max_tokens": 2048              // optional
        }

    Response:
        {
            "content": "...",
            "provider": "gemini",
            "model": "gemini-1.5-flash",
            "input_tokens": 10,
            "output_tokens": 42
        }
    """
    serializer = AgentRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    data = serializer.validated_data

    last_user_message = None
    last_product_request = None
    for msg in reversed(data.get("messages") or []):
        if msg.get("role") == "user" and msg.get("content"):
            if last_user_message is None:
                last_user_message = msg.get("content")
            if last_product_request is None and _should_recommend(msg.get("content", "")):
                last_product_request = msg.get("content")
        if last_user_message and last_product_request:
            break

    should_recommend = False
    if last_user_message:
        should_recommend = _should_recommend(last_user_message)
        if not should_recommend and _is_criteria_message(last_user_message) and last_product_request:
            should_recommend = True

    if data.get("auto_recommend", True) and last_user_message and should_recommend:
        base_request = last_product_request or last_user_message
        query = _extract_query(base_request) or base_request
        if last_product_request and last_product_request != last_user_message:
            pedido = f"{base_request}. Criterios adicionais: {last_user_message}"
        else:
            pedido = last_user_message
        sources = data.get("sources") or ["mercadolivre", "amazon", "kabum"]
        pagina = data.get("pagina", 1)
        limite_por_fonte = data.get("limite_por_fonte", 10)
        max_resultados = data.get("max_resultados", 5)

        try:
            parsed, produtos_normalizados, erros_fontes, response = _run_recommendation(
                query=query,
                pedido=pedido,
                sources=sources,
                pagina=pagina,
                limite_por_fonte=limite_por_fonte,
                max_resultados=max_resultados,
                provider_name=data.get("provider"),
                model=data.get("model", ""),
                temperature=data.get("temperature", 0.2),
                max_tokens=data.get("max_tokens", 2048),
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except ProviderQuotaExceeded as e:
            logger.warning("Quota exceeded: provider=%s retry_after=%s", e.provider, e.retry_after)
            body = {
                "error": "Provider quota exceeded",
                "provider": e.provider,
                "message": e.message,
            }
            headers = {}
            if e.retry_after is not None:
                headers["Retry-After"] = str(int(e.retry_after))
            return Response(body, status=429, headers=headers)
        except Exception:
            logger.exception("Unexpected error calling provider")
            return Response({"error": "Falha ao processar a resposta do provedor."}, status=502)

        payload = AgentResponseSerializer(response).data
        payload["content"] = _render_recommendation_text(parsed, max_resultados)
        payload["recommendations"] = parsed
        payload["produtos"] = produtos_normalizados
        payload["query"] = query
        payload["pedido"] = pedido
        payload["sources"] = sources
        payload["erros_fontes"] = erros_fontes
        return Response(payload, status=200)

    # Resolve provider: use request value or fall back to first configured provider
    provider_name = data.get("provider")
    if not provider_name:
        from django.conf import settings
        configured = [
            name
            for name, cfg in getattr(settings, "AGENT_PROVIDERS", {}).items()
            if cfg.get("api_key")
        ]
        if not configured:
            return Response(
                {"error": "No provider configured. Set AGENT_PROVIDERS in settings or pass 'provider' in the request."},
                status=400,
            )
        provider_name = configured[0]

    try:
        response = AgentService.chat(
            provider_name=provider_name,
            messages=data["messages"],
            system_prompt=data["system_prompt"],
            model=data["model"],
            temperature=data["temperature"],
            max_tokens=data["max_tokens"],
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except ProviderQuotaExceeded as e:
        logger.warning("Quota exceeded: provider=%s retry_after=%s", e.provider, e.retry_after)
        body = {
            "error": "Provider quota exceeded",
            "provider": e.provider,
            "message": e.message,
        }
        headers = {}
        if e.retry_after is not None:
            headers["Retry-After"] = str(int(e.retry_after))
        return Response(body, status=429, headers=headers)
    except Exception:
        logger.exception("Unexpected error calling provider")
        return Response({"error": "Falha ao processar a resposta do provedor."}, status=502)

    return Response(AgentResponseSerializer(response).data, status=200)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_providers(request):
    """
    List all registered providers and whether they are configured.

    Response:
        {
            "providers": [
                {"provider": "gemini", "default_model": "gemini-1.5-flash", "configured": true}
            ]
        }
    """
    from django.conf import settings
    cfg = getattr(settings, "AGENT_PROVIDERS", {})
    return Response({
        "providers": [
            {
                "provider": name,
                "default_model": cls.DEFAULT_MODEL,
                "configured": bool(cfg.get(name, {}).get("api_key")),
            }
            for name, cls in PROVIDERS.items()
        ]
    })


def _should_recommend(text: str) -> bool:
    text_l = text.lower()
    keywords = [
        "quero",
        "procuro",
        "procurando",
        "preciso",
        "me recomenda",
        "me recomende",
        "me indica",
        "me indique",
        "me sugere",
        "me sugira",
        "comprar",
        "melhor",
        "custo beneficio",
        "ajuda a escolher",
        "qual voce indica",
    ]
    return any(k in text_l for k in keywords)


def _is_criteria_message(text: str) -> bool:
    text_l = text.lower()
    hints = [
        "orcamento",
        "orçamento",
        "ate",
        "até",
        "r$",
        "marca",
        "prefero",
        "prefiro",
        "uso",
        "para trabalho",
        "para jogar",
        "para estudo",
        "com ",
        "sem ",
        "nao quero",
        "não quero",
        "priorize",
        "mais barato",
        "mais caro",
        "custo beneficio",
    ]
    return any(h in text_l for h in hints)


def _extract_query(text: str) -> str:
    s = text.strip()
    if len(s) > 80:
        for sep in [".", ",", " para ", " com ", " que "]:
            if sep in s:
                s = s.split(sep)[0]
                break

    prefixes = [
        r"quero\s+",
        r"procuro\s+",
        r"procurando\s+",
        r"preciso\s+de\s+",
        r"me\s+recomenda\s+",
        r"me\s+recomende\s+",
        r"me\s+indica\s+",
        r"me\s+indique\s+",
        r"me\s+sugere\s+",
        r"me\s+sugira\s+",
        r"busco\s+",
        r"buscando\s+",
        r"ajuda\s+com\s+",
        r"ajuda\s+a\s+escolher\s+",
    ]
    for p in prefixes:
        s = re.sub(rf"^{p}", "", s, flags=re.IGNORECASE)

    return s.strip()


def _normalize_product(prod: dict, source: str) -> dict:
    title = prod.get("titulo") or prod.get("title") or prod.get("name") or ""
    price = prod.get("preco") or prod.get("price") or None
    link = prod.get("link") or prod.get("permalink") or ""
    rating = prod.get("nota") or prod.get("rating") or None
    reviews = prod.get("quantidade_avaliacoes") or prod.get("reviews") or None

    return {
        "source": source,
        "title": title,
        "price": price,
        "link": link,
        "image": prod.get("imagem") or prod.get("image") or "",
        "rating": rating,
        "reviews": reviews,
        "raw": prod,
    }


def _tokenize_query(text: str) -> list[str]:
    stop = {
        "um", "uma", "o", "a", "os", "as", "de", "do", "da", "dos", "das",
        "para", "pra", "com", "sem", "e", "ou", "por", "no", "na", "nos",
        "nas", "em", "ate", "até", "melhor", "custo", "beneficio", "benefício",
        "barato", "caro", "bom", "boa", "top",
    }
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if len(t) > 2 and t not in stop]


def _score_product(title: str, keywords: list[str]) -> int:
    if not title:
        return 0
    title_l = title.lower()
    return sum(1 for k in keywords if k in title_l)


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "")
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _to_int(value) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9]", "", value)
        try:
            return int(cleaned) if cleaned else 0
        except ValueError:
            return 0
    return 0


def _build_recommend_prompt(pedido: str, products: list[dict], max_resultados: int) -> list[dict]:
    product_lines = []
    for idx, p in enumerate(products, start=1):
        product_lines.append(
            f"{idx}. {p.get('title','')} | preco: {p.get('price')} | nota: {p.get('rating')} | reviews: {p.get('reviews')} | fonte: {p.get('source')} | link: {p.get('link')}"
        )

    prompt = (
        "Voce e um assistente que recomenda produtos com base no pedido do usuario. "
        "Use somente a lista fornecida. "
        "Priorize produtos que casam com o termo principal e evite acessorios quando o usuario pede o produto principal. "
        "Se faltar informacao, infira criterios razoaveis e explique rapidamente. "
        "Responda APENAS JSON valido no formato: "
        "{\"top\": [ {\"rank\": 1, \"title\": \"...\", \"reason\": \"...\", \"score\": 0-100, \"link\": \"...\", \"price\": ..., \"source\": \"...\" } ], "
        "\"rejected\": [ {\"title\": \"...\", \"reason\": \"...\" } ], "
        "\"notes\": \"...\" }. "
        f"Retorne no maximo {max_resultados} itens em top."
    )

    user_content = (
        f"Pedido do usuario:\n{pedido}\n\n"
        f"Produtos:\n" + "\n".join(product_lines)
    )

    return [
        {"role": "user", "content": user_content},
    ], prompt


def _render_recommendation_text(parsed: dict, max_resultados: int) -> str:
    if isinstance(parsed, dict) and isinstance(parsed.get("top"), list):
        lines = [
            "Encontrei boas opcoes para voce. Aqui vai um top rapido com o por que de cada escolha:",
        ]
        for idx, item in enumerate(parsed.get("top", [])[:max_resultados], start=1):
            title = item.get("title", "")
            reason = item.get("reason", "")
            price = item.get("price", "")
            link = item.get("link", "")
            lines.append(f"{idx}) {title} | preco: {price} | {reason}")
            if link:
                lines.append(f"Link: {link}")

        notes = parsed.get("notes")
        if notes:
            lines.append(f"Notas: {notes}")

        lines.append("Se quiser, me diga seu orcamento, marca preferida ou uso principal para refinar.")
        return "\n".join(lines)

    return (
        "Encontrei alguns produtos, mas nao consegui ordenar direito ainda. "
        "Me diga seu orcamento, marca preferida e o uso principal que eu refaço o ranking."
    )


def _parse_json_response(content: str) -> dict:
    try:
        return json.loads(content)
    except Exception:
        return {"raw": content}


def _fallback_rank(products: list[dict], max_resultados: int) -> dict:
    ranked = sorted(
        products,
        key=lambda p: (
            p.get("match_score", 0),
            _to_float(p.get("rating")),
            _to_int(p.get("reviews")),
        ),
        reverse=True,
    )

    top = []
    for idx, p in enumerate(ranked[:max_resultados], start=1):
        top.append(
            {
                "rank": idx,
                "title": p.get("title", ""),
                "reason": "Melhor match com o pedido e boas avaliacoes.",
                "score": min(100, 60 + (p.get("match_score", 0) * 10)),
                "link": p.get("link", ""),
                "price": p.get("price"),
                "source": p.get("source", ""),
            }
        )

    return {
        "top": top,
        "rejected": [],
        "notes": "Ranking gerado por criterio automatico quando a IA nao retornou JSON valido.",
    }


def _resolve_provider_name(provider_name: str | None) -> str:
    if provider_name:
        return provider_name

    from django.conf import settings

    configured = [
        name
        for name, cfg in getattr(settings, "AGENT_PROVIDERS", {}).items()
        if cfg.get("api_key")
    ]
    if not configured:
        raise ValueError(
            "No provider configured. Set AGENT_PROVIDERS in settings or pass 'provider' in the request."
        )
    return configured[0]


def _collect_products(query: str, sources: list[str], pagina: int, limite_por_fonte: int) -> tuple[list[dict], list[dict]]:
    produtos_normalizados = []
    erros_fontes = []
    keywords = _tokenize_query(query)

    if "mercadolivre" in sources:
        try:
            from app.features.scraper.mercadolivre.services import buscar_produtos as buscar_ml

            produtos = buscar_ml(query=query, pagina=pagina, detalhes=False)
            for p in produtos[:limite_por_fonte]:
                produtos_normalizados.append(_normalize_product(p, "mercadolivre"))
        except Exception as exc:
            erros_fontes.append({"source": "mercadolivre", "error": str(exc)})

    if "amazon" in sources:
        try:
            from app.features.scraper.amazon.services import buscar_produtos as buscar_amazon

            produtos = buscar_amazon(query=query, pagina=pagina, detalhes=False)
            for p in produtos[:limite_por_fonte]:
                produtos_normalizados.append(_normalize_product(p, "amazon"))
        except Exception as exc:
            erros_fontes.append({"source": "amazon", "error": str(exc)})

    if "kabum" in sources:
        try:
            from app.features.scraper.kabum.services import buscar_produtos as buscar_kabum

            produtos = buscar_kabum(query=query, pagina=pagina, detalhes=False)
            for p in produtos[:limite_por_fonte]:
                produtos_normalizados.append(_normalize_product(p, "kabum"))
        except Exception as exc:
            erros_fontes.append({"source": "kabum", "error": str(exc)})

    if keywords:
        scored = []
        for p in produtos_normalizados:
            score = _score_product(p.get("title", ""), keywords)
            if score > 0:
                p["match_score"] = score
                scored.append(p)
        produtos_normalizados = scored or produtos_normalizados

        produtos_normalizados.sort(
            key=lambda p: (
                p.get("match_score", 0),
                _to_float(p.get("rating")),
                _to_int(p.get("reviews")),
            ),
            reverse=True,
        )

    produtos_normalizados = produtos_normalizados[:5]

    return produtos_normalizados, erros_fontes


def _run_recommendation(
    *,
    query: str,
    pedido: str,
    sources: list[str],
    pagina: int,
    limite_por_fonte: int,
    max_resultados: int,
    provider_name: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
) -> tuple[dict, list[dict], list[dict], object]:
    if not query:
        raise ValueError("Campo 'query' e obrigatorio.")
    if not pedido:
        raise ValueError("Campo 'pedido' e obrigatorio.")

    produtos_normalizados, erros_fontes = _collect_products(
        query=query,
        sources=sources,
        pagina=pagina,
        limite_por_fonte=limite_por_fonte,
    )

    if not produtos_normalizados:
        raise ValueError("Nenhum produto encontrado nas fontes solicitadas.")

    messages, system_prompt = _build_recommend_prompt(pedido, produtos_normalizados, max_resultados)
    provider_name = _resolve_provider_name(provider_name)

    response = AgentService.chat(
        provider_name=provider_name,
        messages=messages,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=min(max_tokens, 1024),
    )

    parsed = _parse_json_response(response.content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("top"), list) or not parsed.get("top"):
        parsed = _fallback_rank(produtos_normalizados, max_resultados)
    return parsed, produtos_normalizados, erros_fontes, response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def recommend(request):
    serializer = RecommendRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    data = serializer.validated_data
    query = data["query"].strip()
    pedido = data["pedido"].strip()
    sources = data.get("sources") or ["mercadolivre", "amazon", "kabum"]
    pagina = data.get("pagina", 1)
    limite_por_fonte = data.get("limite_por_fonte", 10)
    max_resultados = data.get("max_resultados", 5)

    try:
        parsed, produtos_normalizados, erros_fontes, response = _run_recommendation(
            query=query,
            pedido=pedido,
            sources=sources,
            pagina=pagina,
            limite_por_fonte=limite_por_fonte,
            max_resultados=max_resultados,
            provider_name=data.get("provider"),
            model=data.get("model", ""),
            temperature=data.get("temperature", 0.2),
            max_tokens=data.get("max_tokens", 2048),
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)
    except ProviderQuotaExceeded as exc:
        logger.warning("Quota exceeded: provider=%s retry_after=%s", exc.provider, exc.retry_after)
        body = {
            "error": "Provider quota exceeded",
            "provider": exc.provider,
            "message": exc.message,
        }
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(int(exc.retry_after))
        return Response(body, status=429, headers=headers)
    except Exception:
        logger.exception("Unexpected error calling provider")
        return Response({"error": "Falha ao processar a resposta do provedor."}, status=502)

    return Response(
        {
            "query": query,
            "pedido": pedido,
            "sources": sources,
            "total_produtos": len(produtos_normalizados),
            "produtos": produtos_normalizados,
            "resultado": parsed,
            "provider": response.provider,
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "erros_fontes": erros_fontes,
        },
        status=200,
    )
