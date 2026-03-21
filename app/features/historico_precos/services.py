
from app.features.historico_precos.price_history import record_price

def buscar_produtos(query: str, pagina: int = 1, detalhes: bool = False) -> list[dict]:
    produtos = buscar_produtos_basic(query, pagina)

    if detalhes:
        pass  # lógica existente

    # Grava histórico usando link como chave
    for p in produtos:
        link = p.get("link")
        preco_raw = p.get("preco")
        if link and preco_raw:
            try:
                record_price(
                    link=link,
                    name=p.get("titulo", ""),
                    image=p.get("imagem", ""),
                    price=float(preco_raw),
                )
            except Exception:
                pass  # nunca quebra o scraper

    return produtos